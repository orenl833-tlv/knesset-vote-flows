"""Election night, Knesset 26: pair 25-26 with partial counting (see design/SPEC_LIVE.md).

    python3 -I scripts/live_update.py [--k26 PATH] [--boot B] [--workers 4]

Writes only under out/live/ (fits, web, live.json, summary.txt). Reads out/web/data for the existing areas.
Fails loudly (SystemExit with a message) on unexpected input.
"""
import os
import sys
import time
import json
import argparse
import shutil
import datetime as dt
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np
import pandas as pd

import common
from common import OUT, PAIRS, OTHER, DNV, Election, load_config, load_cbs, druze_codes, load_all
from pipeline import Context
from matching import sector_ballots
import stage2 as S2
import stage3 as S3

BASE = common.BASE
LIVE = os.path.join(OUT, 'live')
LIVE_WEB = os.path.join(LIVE, 'web')
LIVE_DATA = os.path.join(LIVE_WEB, 'data')
LIVE_FITS = os.path.join(LIVE, 'fits', '25-26')
SRC_WEB = os.path.join(OUT, 'web')
PAIR, YA, YB = '25-26', 25, 26
T_REPL = 0.15
THIN = S2.THIN
DEFAULT_K26 = os.path.join(BASE, 'live', 'k26', 'latest.csv')
DEFAULT_SES = os.path.join(BASE, 'config', 'ses_clusters_2021.csv')
REQ = ['סמל ישוב', 'שם ישוב', 'קלפי', 'בזב', 'מצביעים', 'פסולים', 'כשרים']     # ריכוז is optional (number method)
ALIASES = {'סמל יישוב': 'סמל ישוב', 'שם יישוב': 'שם ישוב', 'מספר קלפי': 'קלפי',
           'בעלי זכות בחירה': 'בזב', 'קולות כשרים': 'כשרים', 'קולות פסולים': 'פסולים',
           'סה"כ מצביעים': 'מצביעים', 'מקום קלפי': 'ריכוז'}


def norm_header(h):
    """Header text without BOM, NBSP, quotes, extra spaces."""
    for junk in ('\ufeff', '"', '\u05f4', '\u05f3', "'", '\u200f', '\u200e'):
        h = h.replace(junk, '')
    h = h.replace('\xa0', ' ')
    return ' '.join(h.split())


_ALIAS_N = {norm_header(k): v for k, v in ALIASES.items()}


def normalise_headers(cols):
    """Canonical column names and the mapping used (original -> canonical) for printing."""
    out, used = [], []
    for c in cols:
        n = norm_header(c)
        canon = _ALIAS_N.get(n, n)
        if canon != c:
            used.append((c, canon))
        out.append(canon)
    return out, used
META = {'סמל ועדה', 'ברזל', 'שם ישוב', 'סמל ישוב', 'קלפי', 'ריכוז', 'שופט', 'חיצוניות', 'קלפי אחרת', 'בזב', 'מצביעים', 'פסולים', 'כשרים'}
COUNTS = ['בזב', 'מצביעים', 'פסולים', 'כשרים']
LOG = []


def say(msg):
    LOG.append(msg)
    print(msg, flush=True)


def fail(msg):
    raise SystemExit(f'live_update: {msg}')


# ----------------------------------------------------------------------------- input
def parse_k26(path, cfg):
    """Validate and parse the Knesset 26 file. Returns a dict of pieces (see main)."""
    if not os.path.isfile(path):
        fail(f'k26 file not found: {path}')
    try:
        df = pd.read_csv(path, dtype=str, encoding='utf-8-sig', keep_default_na=False)
    except UnicodeDecodeError as e:
        fail(f'k26 file is not UTF-8 ({path}): {e}')
    except pd.errors.EmptyDataError:
        fail(f'k26 file is empty: {path}')
    keep = [c for c in df.columns if c.strip() and not c.strip().startswith('Unnamed')]
    df = df[keep]
    cols, used = normalise_headers(list(df.columns))
    df.columns = cols
    for orig, canon in used:
        say(f'  header mapping: {orig!r} -> {canon!r}')
    if len(df) == 0:
        fail(f'k26 file has no rows: {path}')
    miss = [c for c in REQ if c not in df.columns]
    if miss:
        fail(f'k26 file lacks required columns {miss} (after alias mapping); found columns {list(df.columns)}')
    if len(set(df.columns)) != len(df.columns):
        fail(f'k26 file has duplicate column names after alias mapping: '
             f'{sorted({c for c in df.columns if list(df.columns).count(c) > 1})}')
    no_place = 'ריכוז' not in df.columns
    if no_place:
        say('  WARNING: no ריכוז (polling place) column in the k26 file: pair 25-26 uses the NUMBER method '
            '(floor of ballot number, bzb ratio within 8%); a unit forms only when all its k26 ballots are counted.')
        df['ריכוז'] = ''
    n_file_rows = len(df)
    raw_s = df.copy()                       # the file as text, for the dropped-rows log
    for c in ['שם ישוב'] + ([] if no_place else ['ריכוז']):
        df[c] = df[c].str.strip()
    kinds_of = {}                           # row position -> list of problem kinds

    def flag(mask, kind):
        for i in np.flatnonzero(np.asarray(mask, dtype=bool)):
            lst = kinds_of.setdefault(int(i), [])
            if kind not in lst:
                lst.append(kind)

    code_s = df['סמל ישוב'].str.strip()
    flag(~code_s.str.fullmatch(r'\d+').values, 'non-numeric values')
    df['code'] = pd.to_numeric(code_s, errors='coerce').fillna(-1).astype(np.int64)
    bn = pd.to_numeric(df['קלפי'].str.strip(), errors='coerce')
    flag(bn.isna().values, 'non-numeric values')
    df['bnum'] = bn.fillna(-1).astype(float).round(6)
    party_cols = [c for c in df.columns if c not in META and c not in ('code', 'bnum')]
    blank_cells = 0
    for c in COUNTS + party_cols:
        s_ = df[c].str.strip()
        blank_cells += int((s_ == '').sum())
        v = pd.to_numeric(s_.where(s_ != '', '0'), errors='coerce')
        flag(v.isna().values, 'non-numeric values')
        flag(((v < 0) | (np.floor(v) != v)).fillna(True).values, 'non-numeric values')
        df[c] = v.fillna(0).astype(np.int64)
    if blank_cells:
        say(f'  note: {blank_cells} empty numeric cells read as 0')
    if not no_place:
        flag((df['ריכוז'] == '').values, 'a ballot without ריכוז')
    env = ((df['code'] == 9999) | (df['בזב'] == 0) | (df['שם ישוב'] == common.DOUBLE_ENV_NAME)).values
    party_sum = df[party_cols].sum(axis=1).values
    val = df['כשרים'].values
    mtz = df['מצביעים'].values
    pas = df['פסולים'].values
    # consistency checks only on rows whose numbers were all read (a non-numeric cell is already a problem)
    numeric_bad = np.zeros(len(df), bool)
    numeric_bad[[i for i, ks in kinds_of.items() if 'non-numeric values' in ks]] = True
    ordn = (~env) & (~numeric_bad)
    flag(ordn & (val > 0) & (party_sum != val), 'party columns do not sum to כשרים')
    flag(ordn & (val > 0) & (mtz != pas + val), 'מצביעים ≠ פסולים + כשרים')
    flag(ordn & (val == 0) & ((mtz != 0) | (pas != 0) | (party_sum != 0)), 'votes on an uncounted row')
    dropped = np.zeros(len(df), bool)
    dropped[list(kinds_of)] = True
    n_drop = int(dropped.sum())
    n_counted_raw = int(((~env) & (val > 0)).sum())
    limit = 0.05 * n_counted_raw
    # dropped rows: log them (and their problems)
    by_kind = {}
    for i, ks in kinds_of.items():
        for k in ks:
            by_kind.setdefault(k, []).append(i)
    if n_drop:
        say(f'  WARNING: {n_drop} rows dropped for data problems (of {n_counted_raw} counted rows; a row can have several problems); '
            f'listed in {os.path.join(LIVE, "dropped_rows.csv")}')
        for k in sorted(by_kind):
            ex = [f'(locality {raw_s.at[i, "סמל ישוב"].strip()}, ballot {raw_s.at[i, "קלפי"].strip()})'
                  for i in by_kind[k][:5]]
            say(f'    {k}: {len(by_kind[k])} rows; examples {"; ".join(ex)}')
    os.makedirs(LIVE, exist_ok=True)
    recs = []
    for i in sorted(kinds_of):
        rv = raw_s.iloc[i]
        recs.append(dict(file_row=i + 2, problems=' | '.join(kinds_of[i]),
                         locality=str(rv['סמל ישוב']).strip(), ballot=str(rv['קלפי']).strip(),
                         place=('' if no_place else str(rv['ריכוז']).strip()),
                         raw_row=json.dumps({c: str(rv[c]) for c in raw_s.columns}, ensure_ascii=False)))
    pd.DataFrame(recs, columns=['file_row', 'problems', 'locality', 'ballot', 'place', 'raw_row']).to_csv(
        os.path.join(LIVE, 'dropped_rows.csv'), index=False, encoding='utf-8')
    if n_drop > limit:   # checked after the log is written, so a failed night still leaves the list
        fail(f'k26: {n_drop} rows have data problems, more than 5% of the {n_counted_raw} counted rows '
             f'(limit {limit:.0f}); not writing any output. Examples: ' + '; '.join(
                 f'file row {i + 2}: {", ".join(kinds_of[i])}' for i in list(kinds_of)[:5]))
    # a dropped row that has a place and a ballot number is re-entered as an uncounted ballot (zero votes,
    # its bzb kept), so its place is not treated as fully counted
    ph = dropped & (~env) & (df['code'].values >= 0) & (df['bnum'].values >= 0) & (df['בזב'].values > 0)
    if not no_place:
        ph = ph & (df['ריכוז'].values != '')
    ph_df = df[ph].copy()
    for c in party_cols + ['מצביעים', 'פסולים', 'כשרים']:
        ph_df[c] = 0
    keep_df = df[~dropped]
    df = pd.concat([keep_df, ph_df])
    env = np.concatenate([env[~dropped], np.zeros(int(ph.sum()), bool)])
    ordinary = df[~env].copy()
    if len(ordinary) == 0:
        fail('k26: no ordinary ballots after removing envelope rows and dropped rows')
    counted = ordinary['כשרים'] > 0
    ordinary['counted'] = counted.values
    # parties
    ycfg = cfg['elections']['26']['parties']
    names = []
    listed = {}
    for code, (name, fam) in ycfg.items():
        listed.setdefault(name, []).append(code)
        if name not in names:
            names.append(name)
    if len(set(names)) != len(names):
        fail('config 26: duplicate display names')
    absent_cfg = [c for c in ycfg if c not in party_cols]
    unlisted = [c for c in party_cols if c not in ycfg]
    warnings = []
    if absent_cfg:
        warnings.append(f'configured party codes absent from the file (treated as 0): {absent_cfg}')
    if unlisted:
        warnings.append(f'file party columns not in config 26 (folded into {OTHER}): {unlisted}')
    hcodes = cfg['sector_parties']['haredi']['26']
    acodes = cfg['sector_parties']['arab']['26']
    for c in hcodes + acodes:
        if c not in party_cols:
            warnings.append(f'sector code {c!r} absent from the file (treated as 0 votes)')
    fam = {OTHER: 'other', DNV: 'dnv'}
    for code, (name, f) in ycfg.items():
        fam[name] = f
    cats = names + [OTHER, DNV]
    cat_cols = [f'c{i}' for i in range(len(cats))]
    for i, name in enumerate(names):
        codes = [c for c in listed[name] if c in party_cols]
        ordinary[cat_cols[i]] = ordinary[codes].sum(axis=1) if codes else 0
    ordinary[cat_cols[len(names)]] = ordinary[unlisted].sum(axis=1) if unlisted else 0   # OTHER
    ordinary[cat_cols[-1]] = ordinary['בזב'] - ordinary['כשרים']
    ordinary['hv'] = ordinary[[c for c in hcodes if c in party_cols]].sum(axis=1) if any(c in party_cols for c in hcodes) else 0
    ordinary['rv'] = ordinary[[c for c in acodes if c in party_cols]].sum(axis=1) if any(c in party_cols for c in acodes) else 0
    ordinary['val'] = ordinary['כשרים']
    ordinary['mtz'] = ordinary['מצביעים']
    ordinary['pas'] = ordinary['פסולים']
    ordinary['bzb'] = ordinary['בזב']
    ordinary['name'] = ordinary['שם ישוב']
    ordinary['place'] = ordinary['ריכוז'] if not no_place else ''
    ordinary['floor'] = np.floor(ordinary['bnum']).astype(int)
    # category check: categories add up to bzb on every row
    cat_sum = ordinary[cat_cols].sum(axis=1)
    if not (cat_sum == ordinary['bzb']).all():
        fail('k26: category totals do not add up to בזב (internal check)')
    ordinary = ordinary.reset_index(drop=True)
    e26_meta = dict(hcodes=hcodes, acodes=acodes, cats=cats, fam=fam, cat_cols=cat_cols, warnings=warnings,
                    no_place=no_place, header_map=used,
                    n_raw=n_file_rows, n_env=int(env.sum()), env_valid=int(df.loc[env, 'כשרים'].sum()),
                    env_rows=int(env.sum()), n_dropped=n_drop, n_placeholder=int(ph.sum()))
    return ordinary, e26_meta, df[env]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--k26', default=DEFAULT_K26)
    ap.add_argument('--boot', type=int, default=0)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--ses-clusters', default=DEFAULT_SES, help='SES cluster file for the 25-26 aggregates')
    ap.add_argument('--plain-tolerance', action='store_true',
                    help='use the plain +-8%% bzb tolerance (no growth adjustment) for 25-26')
    args = ap.parse_args()
    if args.boot < 0:
        fail('--boot must be >= 0')
    t_all = time.time()
    steps = []

    def step(name, t0):
        steps.append((name, time.time() - t0))
        say(f'  {time.time() - t0:8.2f} s  {name}')

    t0 = time.time()
    cfg = load_config()
    cbs = load_cbs()
    dz, mx = druze_codes(cfg, cbs)
    el = load_all(cfg)
    ctx = Context(cfg, el, cbs, dz, mx)
    S2.make_totals(ctx)
    if not os.path.isfile(args.ses_clusters):
        fail(f'SES cluster file not found: {args.ses_clusters}')
    grp = S3.load_ses(args.ses_clusters)
    base_ses = os.path.basename(args.ses_clusters)
    ses_source = 'CBS 2021' if '2021' in base_ses else ('CBS 2019' if '2019' in base_ses else f'custom: {base_ses}')
    say(f'  SES clusters: {args.ses_clusters} -> {ses_source}')
    arab_elig = set(int(c) for c in cbs.index if cbs.loc[c, 'dat'] in (2.0, 3.0) and int(c) not in dz)
    step('load stage-2 context (regions, k19-k25 totals), SES clusters', t0)

    t0 = time.time()
    rows, meta, env_rows = parse_k26(args.k26, cfg)
    for w_ in meta['warnings']:
        say(f'  warning: {w_}')
    n_ord = len(rows)
    full = rows.groupby(['code', 'place'])['counted'].all()
    full_keys = set(full[full].index)
    unmapped = sorted(set(int(c) for c in rows['code'].unique()) - set(ctx.loc_to_region))
    if unmapped:
        say(f'  warning: k26 localities not in any earlier election (excluded from areas): {unmapped}')
    rows['region'] = rows['code'].map(ctx.loc_to_region)
    mapped = rows[rows['region'].notna()].reset_index(drop=True)
    counted_map = mapped[mapped['counted']].copy()
    n_counted = int(mapped['counted'].sum())
    say(f'  k26 file: rows {meta["n_raw"]}, envelope rows {meta["n_env"]} (valid votes {meta["env_valid"]}), '
        f'ordinary ballots {n_ord}, counted {int(rows["counted"].sum())}, mapped {len(mapped)}')
    say(f'  places fully counted: {len(full_keys)} of {rows.groupby(["code","place"]).ngroups} in the file')
    if n_counted == 0:
        say('  no counted k26 ballots yet: nothing to model; no output written.')
        return
    cat_cols, cats, fam = meta['cat_cols'], meta['cats'], meta['fam']
    # all mapped k26 ballots, with the counted flag: matching uses the counted ones (bzb of all)
    E26 = Election(year=26, df=mapped, cats=cats, fam=fam, cat_cols=cat_cols,
                   haredi_codes=meta['hcodes'], arab_codes=meta['acodes'],
                   dbl_rows=env_rows, raw_rows=meta['n_raw'], party_cols_unlisted=[])
    E26.no_place = meta['no_place']
    E26.growth_adj = not args.plain_tolerance
    say(f'  bzb tolerance for 25-26: {"plain (+-8%)" if args.plain_tolerance else "growth-adjusted (median locality growth)"}')
    ctx.elections[YB] = E26
    counted_map['sector'] = sector_ballots(counted_map, ctx.dat, dz, mx)
    frame26 = counted_map.reset_index(drop=True)
    ctx.frames[YB] = frame26
    ctx.tot[YB] = totals_from_frame(frame26, cat_cols, ctx.region_list)
    step('read and validate k26 file, partial-count rules, frames', t0)

    t0 = time.time()
    pool = Pool(args.workers)
    R = S2.run_pair(ctx, PAIR, T_REPL, args.boot, pool, fallback=True)
    step(f'matching, filters, all fit families for 25-26 (B = {args.boot}, {args.workers} workers)', t0)

    t0 = time.time()
    save_fits_live(R)
    step('write fits to out/live/fits/25-26', t0)
    t0 = time.time()
    san = live_sanity(R, ctx, E26, R['res'])
    os.makedirs(LIVE, exist_ok=True)
    san.to_csv(os.path.join(LIVE, 'sanity.csv'), index=False, encoding='utf-8')
    step(f'live sanity: {san["fit"].nunique() if len(san) else 0} fits with >= {THIN} units -> out/live/sanity.csv', t0)

    # ---- fallback chain and null rules
    t0 = time.time()
    res = R['res']
    areas = S2.build_areas(R, ctx, cfg)
    entries = {}
    null_reason = {}
    lvl = {}   # region -> level of its region-family source
    for r in ctx.region_list:
        src = R['region_src'][r]
        fid = S2.fid_of(src)
        if fid is None or fid not in res:
            lvl[r] = None
        else:
            lvl[r] = {'region': 'own', 'type': 'type', 'national': 'national'}[
                'region' if isinstance(src, str) else src[0]]
    nat_null = any(lvl[r] is None for r in ctx.region_list)
    if nat_null:
        null_reason['national'] = 'a region has no source (national pool < 12 units)'
    entries['national'] = None if nat_null else areas['national']
    gen_pool = S3.pool_fid(res, 'general', True)
    gen_ok = gen_pool is not None and res[gen_pool]['n'] >= THIN
    for s_ in ('haredi', 'arab', 'druze', 'general'):
        key = f'sector:{s_}'
        if s_ == 'general':
            ok = gen_ok
        else:
            ok = (key in res) and res[key]['n'] >= THIN
        entries[key] = areas.get(key) if ok else None
        if not ok:
            null_reason[key] = 'sector fit missing or fewer than 12 units' if s_ != 'general' else \
                'general pool fewer than 12 units (national general pool too)'
    for r in ctx.region_meta.index[ctx.region_meta['kind'] == 'large']:
        if r not in areas or areas[r] is None:
            null_reason[r] = 'thin region (no own region fit)'
            entries[r] = None
        else:
            entries[r] = areas[r]
    ses_out = S3.ses_pair(R, ctx, grp, arab_elig, args.boot, fallback=True)[0]
    ses_entries = {}
    for (F, cid), v in ses_out.items():
        sid = f'ses-{F}-{cid}'
        if v is None:
            ses_entries[sid] = None
            continue
        bad_ = [f for f in v['fids'] if f.startswith('MISSING') or f not in res or res[f]['n'] < THIN]
        if bad_:
            ses_entries[sid] = None
            null_reason[sid] = f'uses unavailable fit {sorted(bad_)[:2]}'
        else:
            ses_entries[sid] = v['entry']
    if null_reason:
        say(f'  null areas: {len(null_reason)}; sample: ' + '; '.join(
            f'{k}: {v}' for k, v in list(null_reason.items())[:4]))
    step('fallback chain, national, sector, city and SES areas', t0)

    # ---- fallback levels per area (regions used, by level)
    def gen_level(r):
        if f'general:{r}' in res:
            return 'own'
        p = S3.pool_fid(res, 'general', True)
        return {'general:pooled': 'type', 'general:national': 'national'}.get(p)

    def jew_level(r):
        if f'jewish:{r}' in res:
            return 'own'
        p = S3.pool_fid(res, 'jewish', True)
        return {'jewish:pooled': 'type', 'jewish:national': 'national'}.get(p)

    def count_levels(regions, fn):
        c = {'own': 0, 'type': 0, 'national': 0}
        for r in regions:
            v = fn(r)
            if v in c:
                c[v] += 1
        return c

    def levels_for(aid):
        if aid == 'national':
            return count_levels(ctx.region_list, lambda r: lvl[r])
        if aid == 'sector:general':
            return count_levels(ctx.region_list, gen_level)
        if aid.startswith('sector:'):
            return {'own': 0, 'type': 0, 'national': 0}      # sector fits are national by design
        _, F, cid = aid.split('-', 2)
        groups = {cid[i:i + 2] for i in range(0, len(cid), 2)}
        codes = [c for c in grp if grp[c] in groups and (F != 'arab' or c in arab_elig)]
        regs = sorted({ctx.loc_to_region[c] for c in codes if c in ctx.loc_to_region})
        fn = {'all': lambda r: lvl[r], 'arab': lambda r: lvl[r],
              'general': gen_level, 'jewish': jew_level}[F]
        return count_levels(regs, fn)

    # ---- counted fields and the 25-26 entries
    t0 = time.time()
    f25 = ctx.frames[YA]
    all_ids = list(entries.keys()) + list(ses_entries.keys())

    def spec_of(aid):
        if aid == 'national':
            return ('all',)
        if aid.startswith('sector:'):
            return ('sector', aid.split(':', 1)[1])
        if aid.startswith('ses-'):
            _, F, cid = aid.split('-', 2)
            return ('ses', F, {cid[i:i + 2] for i in range(0, len(cid), 2)})
        return ('codes', {int(aid)})

    def member(frame, spec, total=False):
        codes = frame['code'].values
        n = len(frame)
        if spec[0] == 'all':
            return np.ones(n, bool)
        if spec[0] == 'sector':
            return np.ones(n, bool) if total else frame['sector'].values == spec[1]
        if spec[0] == 'codes':
            return np.isin(codes, list(spec[1]))
        F, groups = spec[1], spec[2]
        ok = np.array([grp.get(int(c)) in groups for c in codes], bool)
        if total:
            if F == 'arab':
                ok &= np.isin(codes, list(arab_elig))
            return ok
        return ok & S3.masks(frame, arab_elig)[F]

    out_counted = {}
    for aid in all_ids:
        sp = spec_of(aid)
        out_counted[aid] = dict(counted_ballots=int(member(frame26, sp).sum()),
                                total_ballots=int(member(mapped, sp, total=True).sum()))
    step('counted and total ballots per area', t0)

    # ---- write web
    t0 = time.time()
    os.makedirs(LIVE_DATA, exist_ok=True)
    ids = sorted(f[:-5] for f in os.listdir(os.path.join(SRC_WEB, 'data')) if f.endswith('.json'))
    missing = [i for i in ids if i not in entries and i not in ses_entries]
    extra = [i for i in list(entries) + list(ses_entries) if i not in ids]
    if missing or extra:
        fail(f'area id mismatch with out/web/data: missing {missing[:5]} extra {extra[:5]}')
    for aid in ids:
        with open(os.path.join(SRC_WEB, 'data', aid + '.json'), encoding='utf-8') as f:
            rec = json.load(f)
        ent = entries[aid] if aid in entries else ses_entries[aid]
        if ent is not None:
            ent = dict(ent)
            ent['to_counted'] = ent.pop('to_actual')
            ent['counted_share'] = round(ent['coverage'] / 100.0, 4) if ent['coverage'] is not None else None
            ent['counted_ballots'] = out_counted[aid]['counted_ballots']
            ent['total_ballots'] = out_counted[aid]['total_ballots']
            if aid.startswith('ses-'):
                ent['ses_source'] = ses_source
            if aid == 'national' or aid.startswith('sector:') or aid.startswith('ses-'):
                lv = levels_for(aid)
                ent['fallback_levels'] = lv
                ent['fallback_regions'] = lv['type'] + lv['national']
        rec['pairs'][PAIR] = ent
        with open(os.path.join(LIVE_DATA, aid + '.json'), 'w', encoding='utf-8') as f:
            json.dump(rec, f, ensure_ascii=False)
    for name in ('index.json', 'ses_index.json', 'map.json'):
        shutil.copyfile(os.path.join(SRC_WEB, name), os.path.join(LIVE_WEB, name))
    nat_cov = areas['national']['coverage']
    live = dict(updated_utc=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                k26_file=os.path.abspath(args.k26), counted_ballots=n_counted,
                total_ballots=len(mapped),
                counted_share_national=round(nat_cov / 100.0, 4) if nat_cov is not None else None,
                boot=args.boot)
    with open(os.path.join(LIVE_WEB, 'live.json'), 'w', encoding='utf-8') as f:
        json.dump(live, f, ensure_ascii=False, indent=1)
    step(f'write {len(ids)} area files, index copies and live.json', t0)

    ses_shares = ses_group_shares(ctx, grp)
    summary(R, entries, ses_entries, areas, null_reason, args, t_all, steps, out_counted, meta, levels_for('national'),
            ses_shares, ses_source)
    pool.close()


def totals_from_frame(frame, cat_cols, region_list):
    cc = cat_cols
    reg = frame.groupby('region')[cc].sum().reindex(region_list).fillna(0.0)
    gen = frame[frame['sector'] == 'general'].groupby('region')[cc].sum().reindex(region_list).fillna(0.0)
    sec = frame.groupby('sector')[cc].sum()
    secb = frame.groupby('sector')['bzb'].sum()
    return dict(reg=reg, gen=gen, sec=sec, secb=secb,
                reg_bzb=frame.groupby('region')['bzb'].sum().reindex(region_list).fillna(0.0),
                nat=frame[cc].sum().values.astype(float), nat_bzb=float(frame['bzb'].sum()))


def live_sanity(R, ctx, E26, res):
    """Per fit with >= 12 units: modelled later totals (rescaled to the counted k26 total of the same area) vs
    the actual counted k26 totals, for categories with >= 3% share. Same columns as out/sanity.csv."""
    a, b = ctx.elections[YA], E26
    f25, f26 = ctx.frames[YA], ctx.frames[YB]
    kinds = R['kinds']
    rtype = ctx.region_meta['type'].to_dict()
    regs = ctx.region_list
    jew = lambda f: f['sector'].isin(['general', 'haredi']).values
    gen = lambda f: (f['sector'] == 'general').values

    def sums(frame, mask, cols):
        return frame.loc[mask, cols].sum().values.astype(float) if mask.any() else np.zeros(len(cols))

    def area_pair(filt, r_list):
        """(k25 vector, counted k26 vector) for the rows of filt in regions r_list (None = all regions)."""
        out = []
        for rr in (r_list if r_list is not None else [None]):
            m25 = filt(f25) & (True if rr is None else (f25['region'] == rr).values)
            m26 = filt(f26) & (True if rr is None else (f26['region'] == rr).values)
            out.append((sums(f25, m25, a.cat_cols), sums(f26, m26, b.cat_cols)))
        return out

    everything = lambda f: np.ones(len(f), bool)
    rows = []
    for fid, r_ in res.items():
        if r_['n'] < THIN:
            continue
        kind = kinds[fid]
        if kind[0] == 'region':
            areas = area_pair(everything, [kind[1]])
            desc = f'region {kind[1]}'
        elif kind[0] == 'general':
            areas = area_pair(gen, [kind[1]])
            desc = f'general {kind[1]}'
        elif kind[0] == 'gpool':
            areas = area_pair(gen, [r for r in kind[1]])
            desc = f'general pooled ({len(kind[1])} regions)'
        elif kind[0] == 'gnational':
            areas = area_pair(gen, None)
            desc = 'general national'
        elif kind[0] == 'sector':
            areas = [(sums(f25, (f25['sector'] == kind[1]).values, a.cat_cols),
                      sums(f26, (f26['sector'] == kind[1]).values, b.cat_cols))]
            desc = f'sector {kind[1]}'
        elif kind[0] == 'type':
            rs = [r for r in regs if rtype[r] == kind[1]]
            areas = area_pair(everything, rs)
            desc = f'type {kind[1]} ({len(rs)} regions)'
        elif kind[0] == 'national':
            areas = area_pair(everything, None)
            desc = 'national'
        elif kind[0] == 'jewish':
            areas = area_pair(jew, [kind[1]])
            desc = f'jewish {kind[1]}'
        elif kind[0] == 'jpool':
            areas = area_pair(jew, list(kind[1]))
            desc = f'jewish pooled ({len(kind[1])} regions)'
        elif kind[0] == 'jnational':
            areas = area_pair(jew, None)
            desc = 'jewish national'
        else:
            continue
        Mx = S2.map_matrix(a.cats, r_['names_x'])
        My = S2.map_matrix(b.cats, r_['names_y'])
        model = np.zeros(len(r_['names_y']))
        actual = np.zeros(len(r_['names_y']))
        for ta, tb in areas:
            model += (r_['P'] * (ta @ Mx)[:, None]).sum(axis=0)
            actual += tb @ My
        if model.sum() > 0 and actual.sum() > 0:
            model = model * (actual.sum() / model.sum())
        share = actual / actual.sum() if actual.sum() > 0 else np.zeros_like(actual)
        qual = share >= 0.03
        with np.errstate(divide='ignore', invalid='ignore'):
            dev = np.where(actual > 0, 100.0 * np.abs(model - actual) / actual, np.nan)
        mx_dev = np.nanmax(dev[qual]) if (qual & np.isfinite(dev)).any() else np.nan
        for j, nm in enumerate(r_['names_y']):
            rows.append(dict(fit=fid, pair=PAIR, n_units=r_['n'], area=desc, category=nm,
                             model=round(model[j], 2), actual=round(actual[j], 2), share=round(share[j], 4),
                             qualifies=bool(qual[j]), pct_dev=round(dev[j], 3) if dev[j] == dev[j] else None,
                             max_abs_pct_dev=round(mx_dev, 3) if mx_dev == mx_dev else None))
    return pd.DataFrame(rows)


def save_fits_live(R):
    os.makedirs(LIVE_FITS, exist_ok=True)
    for old in os.listdir(LIVE_FITS):          # remove fits of an earlier run (e.g. a fuller count)
        if old.endswith('.npz'):
            os.remove(os.path.join(LIVE_FITS, old))
    for fid, r_ in R['res'].items():
        P = r_['P']
        Pb = r_['Pb'] if r_['Pb'] is not None else np.zeros((0,) + P.shape)
        fn = os.path.join(LIVE_FITS, fid.replace('/', '_') + '.npz')
        np.savez(fn, P=P, Pb=Pb, names_x=np.array(r_['names_x'], dtype=str),
                 names_y=np.array(r_['names_y'], dtype=str), n_units=r_['n'], converged=r_['conv'],
                 no_interval=r_['Pb'] is None, kind=R['kinds'][fid][0])


def ses_group_shares(ctx, grp):
    """k25 bzb share of each SES group, and of localities missing from the SES file."""
    f25 = ctx.frames[YA]
    tot = float(f25['bzb'].sum())
    codes = f25['code'].values
    out = {}
    for g in ('g1', 'g2', 'g3', 'g4'):
        m = np.array([grp.get(int(c)) == g for c in codes], bool)
        out[g] = float(f25.loc[m, 'bzb'].sum()) / tot if tot else 0.0
    miss = np.array([int(c) not in grp for c in codes], bool)
    out['missing'] = float(f25.loc[miss, 'bzb'].sum()) / tot if tot else 0.0
    return out

def summary(R, entries, ses_entries, areas, null_reason, args, t_all, steps, out_counted, meta, lv_nat,
            ses_shares=None, ses_source=''):
    L = []
    w = L.append
    w(f'Live summary, 25-26, k26 file {args.k26}, B = {args.boot}')
    w(f'  runtime steps (s): ' + ', '.join(f'{s:.1f}' for _, s in steps) + f'; total {time.time() - t_all:.1f}')
    nat = entries.get('national')
    diag = nat is None
    if diag:
        nat = areas['national']
        w('  national: null (a region has no source). DIAGNOSTIC ONLY, not published: national with the regions'
          ' that have a source:')
    fr, to, to_c = nat['from'], nat['to'], nat['to_actual']
    cov = nat['coverage']
    w(f'  national counted_share (k25 bzb covered by used units) {cov / 100:.4f}; units {nat["n_units"]}; '
      f'counted ballots {out_counted["national"]["counted_ballots"]} of {out_counted["national"]["total_ballots"]}; '
      f'fallback_levels {lv_nat}')
    w('  modelled vs counted 2026 shares (national, categories >= 3% of counted total; pp deviation):')
    tot_m = sum(x[2] for x in to)
    tot_c = sum(x[2] for x in to_c)
    for (n, f_, mdl), (_, _, act) in zip(to, to_c):
        if tot_c and act / tot_c >= 0.03:
            sm, sa = 100 * mdl / tot_m, 100 * act / tot_c
            w(f'    {n:<22} modelled {sm:6.2f}%  counted {sa:6.2f}%  dev {sm - sa:+6.2f} pp')
    links = [l for l in nat['links'] if fr[l[0]][0] != to[l[1]][0]]
    links.sort(key=lambda l: -l[2])
    w('  five largest cross-category national flows 25-26:')
    for l in links[:5]:
        w(f'    {fr[l[0]][0]} -> {to[l[1]][0]}: votes {l[2]}  rate {l[3]}%')
    for name_from, name_to in (('יש עתיד', 'ביחד'), ('הליכוד', 'הליכוד')):
        hit = [l for l in nat['links'] if fr[l[0]][0] == name_from and to[l[1]][0] == name_to]
        w(f'  {name_from} -> {name_to}: ' + (f'rate {hit[0][3]}%' if hit else 'not in links (votes < 10)'))
    cities = [r for r in areas if r.isdigit()]
    nn = sum(1 for r in cities if entries.get(r) is not None)
    w(f'  cities non-null: {nn} of {len(cities)} ({100 * nn / max(1, len(cities)):.1f}%)')
    w(f'  SES areas non-null: {sum(1 for v in ses_entries.values() if v is not None)} of {len(ses_entries)}')
    if ses_shares:
        w(f'  SES file for 25-26: {ses_source}; k25 bzb share by group: ' + ', '.join(
            f'{g} {100 * ses_shares[g]:.2f}%' for g in ('g1', 'g2', 'g3', 'g4')) +
          f'; not in the SES file {100 * ses_shares["missing"]:.2f}%')
    text = '\n'.join(L) + '\n'
    with open(os.path.join(LIVE, 'summary.txt'), 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)


if __name__ == '__main__':
    main()
