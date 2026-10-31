"""Stage 3: socioeconomic clusters x sector (see design/SPEC_SES.md).

Reuses stage 2 fits (now including jewish:<region> / jewish:pooled), writes out/fits/<pair>/<fid>.npz,
regenerates out/web with the stage 2 code, and writes out/web/data/ses-<F>-<combo>.json and
out/web/ses_index.json. Checks are written to out/ses_summary.txt.

Run:  python3 -I scripts/stage3.py
"""
import os
import sys
import time
import json
import itertools
from collections import defaultdict
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np
import pandas as pd

from common import OUT, PAIRS, ELECTIONS, load_config, load_cbs, druze_codes, load_all, OTHER, DNV
from pipeline import Context
import stage2 as S2

BOOT = 100
THIN = S2.THIN
GROUPS = {'g1': [1, 2, 3], 'g2': [4, 5], 'g3': [6, 7], 'g4': [8, 9, 10]}
GLABEL = {'g1': '1–3', 'g2': '4–5', 'g3': '6–7', 'g4': '8–10'}
FILTERS = ['all', 'jewish', 'general', 'arab']
FLABEL = {'all': 'כל המגזרים', 'jewish': 'יהודי (חרדי + כללי)', 'general': 'מגזר כללי', 'arab': 'מגזר ערבי'}
COMBOS = [''.join(c) for n in range(1, 5) for c in itertools.combinations(['g1', 'g2', 'g3', 'g4'], n)]
WEB = os.path.join(OUT, 'web')
FITS = os.path.join(OUT, 'fits')


def combo_groups(cid):
    return [cid[i:i + 2] for i in range(0, len(cid), 2)]


def load_ses(path=None):
    """Locality code -> SES group (g1..g4). Default: config/ses_clusters.csv (CBS 2019)."""
    if path is None:
        path = os.path.join(os.path.dirname(HERE), 'config', 'ses_clusters.csv')
    s = pd.read_csv(path, dtype={'code': str})
    s['code'] = s['code'].str.strip()
    if not s['code'].str.fullmatch(r'\d+').all():
        raise ValueError(f'{path}: non-numeric locality code')
    s['code'] = s['code'].astype(int)
    if s['code'].duplicated().any():
        raise ValueError(f'{path}: duplicate locality codes')
    if not s['cluster'].isin(range(1, 11)).all():
        raise ValueError(f'{path}: cluster outside 1-10')
    grp = {}
    for code, cl in zip(s['code'], s['cluster']):
        for g, cls in GROUPS.items():
            if cl in cls:
                grp[int(code)] = g
    assert len(grp) == len(s), 'ses cluster not in 1-10'
    return grp


def masks(frame, arab_elig):
    code = frame['code'].values
    sec = frame['sector'].values
    elig = np.isin(code, list(arab_elig))
    return {'all': np.ones(len(frame), bool),
            'general': sec == 'general',
            'jewish': np.isin(sec, ['general', 'haredi']),
            'arab': (sec == 'arab') & elig}


def save_fits(R, pair):
    d = os.path.join(FITS, pair)
    os.makedirs(d, exist_ok=True)
    for fid, r in R['res'].items():
        P = r['P']
        Pb = r['Pb'] if r['Pb'] is not None else np.zeros((0,) + P.shape)
        fn = os.path.join(d, fid.replace('/', '_') + '.npz')
        np.savez(fn, P=P, Pb=Pb, names_x=np.array(r['names_x'], dtype=str),
                 names_y=np.array(r['names_y'], dtype=str), n_units=r['n'], converged=r['conv'],
                 no_interval=r['Pb'] is None, kind=R['kinds'][fid][0])


def ses_pair(R, ctx, grp, arab_elig, B, fallback=False):
    """Per-locality vote matrices by filter, aggregated per group and combo for one pair."""
    ya, yb = R['ya'], R['yb']
    a, b = ctx.elections[ya], ctx.elections[yb]
    res = R['res']
    nA, nB = len(a.cats), len(b.cats)
    Bd = 1 + B
    units = R['bp']['units']
    kept_u = set(units.loc[units['reason'] == '', 'uid'].dropna().tolist())
    core_u = set(units.loc[(units['reason'] == '') & (units['method'] != 'residual'), 'uid'].dropna().tolist())
    fa = ctx.frames[ya].assign(uid=R['bp']['A']['uid'].values)
    fb = ctx.frames[yb]
    cc_a, cc_b = a.cat_cols, b.cat_cols
    ma, mb = masks(fa, arab_elig), masks(fb, arab_elig)
    kept_m = fa['uid'].isin(kept_u).values
    core_m = fa['uid'].isin(core_u).values

    def sums(frame, m, cols):
        sub = frame.loc[m, ['code'] + cols + ['bzb']]
        return sub.groupby('code').sum()

    tot_a, tot_b, num_a, num_c = {}, {}, {}, {}
    for F in FILTERS:
        tot_a[F] = sums(fa, ma[F], cc_a)
        tot_b[F] = sums(fb, mb[F], cc_b)
        num_a[F] = sums(fa, ma[F] & kept_m, cc_a)
        num_c[F] = sums(fa, ma[F] & core_m, cc_a)
    # unit-level counts per filter (kept units and replacement drops)
    uc = {}
    for F in FILTERS:
        if F == 'all':
            um = np.ones(len(units), bool)
        elif F == 'general':
            um = (units['sector'] == 'general').values
        elif F == 'jewish':
            um = units['sector'].isin(['general', 'haredi']).values
        else:
            um = ((units['sector'] == 'arab') & units['code'].isin(list(arab_elig))).values
        kept_units = um & (units['reason'] == '').values
        drop_units = um & (units['reason'] == 'replacement').values
        uc[F] = (pd.Series(units['code'].values[kept_units]).value_counts(),
                 pd.Series(units['code'].values[drop_units]).value_counts())

    G = {F: {g: np.zeros((Bd, nA, nB)) for g in GROUPS} for F in FILTERS}
    toact = {F: {g: np.zeros(nB) for g in GROUPS} for F in FILTERS}
    den = {F: {g: 0.0 for g in GROUPS} for F in FILTERS}
    num = {F: {g: 0.0 for g in GROUPS} for F in FILTERS}
    numc = {F: {g: 0.0 for g in GROUPS} for F in FILTERS}
    used = {F: {g: set() for g in GROUPS} for F in FILTERS}
    cnt = {F: {g: 0 for g in GROUPS} for F in FILTERS}
    ia = {c: i for i, c in enumerate(a.cats)}
    ib = {c: i for i, c in enumerate(b.cats)}
    for F in FILTERS:
        for code in tot_a[F].index:
            if code not in grp:
                continue
            g = grp[code]
            tA = tot_a[F].loc[code, cc_a].values.astype(float)
            bz = float(tot_a[F].loc[code, 'bzb'])
            if bz <= 0:
                continue
            r_id = ctx.loc_to_region[code]
            if F in ('all', 'arab'):
                fid = S2.fid_of(R['region_src'][r_id])
            elif F == 'general':
                fid = f'general:{r_id}' if f'general:{r_id}' in res else pool_fid(res, 'general', fallback)
            else:
                fid = f'jewish:{r_id}' if f'jewish:{r_id}' in res else pool_fid(res, 'jewish', fallback)
            if fid is None or fid not in res:
                if not fallback:
                    raise RuntimeError(f'{R["pair"]} {F} locality {code}: fit {fid} missing')
                used[F][g].add(f'MISSING:{r_id}')     # the combo that uses it is null (live stage)
                continue
            r_ = res[fid]
            tx = tA @ S2.map_matrix(a.cats, r_['names_x'])
            Sx = S2.stack_of(r_, B) * tx[None, :, None]
            ix = np.array([ia[n] for n in r_['names_x']])
            iy = np.array([ib[n] for n in r_['names_y']])
            G[F][g][:, ix[:, None], iy[None, :]] += Sx
            if code in tot_b[F].index:
                toact[F][g] += tot_b[F].loc[code, cc_b].values.astype(float)
            den[F][g] += bz
            if code in num_a[F].index:
                num[F][g] += float(num_a[F].loc[code, 'bzb'])
            if code in num_c[F].index:
                numc[F][g] += float(num_c[F].loc[code, 'bzb'])
            used[F][g].add(fid)
            cnt[F][g] += 1
    # combos
    out = {}
    for F in FILTERS:
        for cid in COMBOS:
            gs = combo_groups(cid)
            n_loc = sum(cnt[F][g] for g in gs)
            if n_loc == 0:
                out[(F, cid)] = None
                continue
            full = sum(G[F][g] for g in gs)
            act = sum(toact[F][g] for g in gs)
            dn = sum(den[F][g] for g in gs)
            cov = sum(num[F][g] for g in gs) / dn if dn else None
            covc = sum(numc[F][g] for g in gs) / dn if dn else None
            fids = set().union(*[used[F][g] for g in gs])
            no_int = any(res[f]['Pb'] is None for f in fids)
            n_units = sum(int(uc[F][0].get(c, 0)) for c in grp if grp[c] in gs)
            dropped = sum(int(uc[F][1].get(c, 0)) for c in grp if grp[c] in gs)
            entry = S2.area_entry(full, a, b, np.zeros(nA), act, n_units, cov, covc, dropped, no_int)
            out[(F, cid)] = dict(entry=entry, full=full, fids=fids,
                                 G={g: G[F][g] for g in gs} if F == 'all' else None)
    single = {(F, g): dict(full=G[F][g], n=cnt[F][g]) for F in FILTERS for g in GROUPS}
    return out, single, G, fa, fb, ma, mb


def pool_fid(res, family, fallback):
    """Pooled fit of a family ('general' or 'jewish'); national family pool if the pool is thin (fallback)."""
    pooled = f'{family}:pooled'
    if fallback and pooled in res and res[pooled]['n'] < THIN and f'{family}:national' in res:
        return f'{family}:national'
    return pooled if pooled in res else None


def fmt_pct(x):
    return f'{100 * x:.2f}%'


def main():
    global BOOT
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--boot', type=int, default=100)
    BOOT = ap.parse_args().boot
    t_all = time.time()
    steps = []

    def step(name, t0):
        steps.append((name, time.time() - t0))

    t0 = time.time()
    cfg = load_config()
    cbs = load_cbs()
    dz, mx = druze_codes(cfg, cbs)
    el = load_all(cfg)
    ctx = Context(cfg, el, cbs, dz, mx)
    S2.make_totals(ctx)
    grp = load_ses()
    arab_elig = set(int(c) for c in cbs.index if cbs.loc[c, 'dat'] in (2.0, 3.0) and int(c) not in dz)
    step('load, context, SES clusters', t0)

    os.makedirs(WEB, exist_ok=True)
    pool = Pool(4)
    all_areas, ses_out, checks, single_out = {}, {}, {}, {}
    fits_count = {}
    for pair in PAIRS:
        t1 = time.time()
        R = S2.run_pair(ctx, pair, 0.15, BOOT, pool)
        t_fit = time.time() - t1
        t2 = time.time()
        save_fits(R, pair)
        all_areas[pair] = S2.build_areas(R, ctx, cfg)
        t_save = time.time() - t2
        t3 = time.time()
        out, single, G, fa, fb, ma, mb = ses_pair(R, ctx, grp, arab_elig, BOOT)
        ses_out[pair] = out
        single_out[pair] = single
        # check 1 and 2 data (point estimates)
        nat_point = R['nat'][0]
        all_g = sum(G['all'][g][0] for g in GROUPS)
        full_all = out[('all', 'g1g2g3g4')]['full'][0]
        singles_sum_vs_combo = float(np.abs(all_g - full_all).max())
        checks[pair] = dict(
            d_votes=float(np.abs(nat_point - full_all).max()),
            d_to=float(np.abs(nat_point.sum(0) - full_all.sum(0)).max()),
            d_from=float(np.abs(nat_point.sum(1) - full_all.sum(1)).max()),
            d_total=float(np.abs(nat_point - full_all).sum()),
            nat_total=float(nat_point.sum()), ses_total=float(full_all.sum()),
            singles_vs_combo=singles_sum_vs_combo,
        )
        jw_own = sum(1 for f in R['res'] if f.startswith('jewish:') and f != 'jewish:pooled')
        fits_count[pair] = dict(own=jw_own, pooled=('jewish:pooled' in R['res']),
                                n_fits=len(R['res']))
        step(f'fits, storage, areas {pair}', t1)
        step(f'  per-locality matrices and SES aggregates {pair}', t3)
        print('done', pair, round(time.time() - t1, 1), flush=True)
    pool.close()

    t0 = time.time()
    index = S2.write_web(all_areas, ctx, PAIRS)
    step('write out/web (stage 2 areas, regenerated)', t0)

    t0 = time.time()
    ses_index_avail = []
    for F in FILTERS:
        for cid in COMBOS:
            pairs_out = {}
            for pair in PAIRS:
                ent = ses_out[pair][(F, cid)]
                pairs_out[pair] = ent['entry'] if ent is not None else None
            sid = f'ses-{F}-{cid}'
            name = 'אשכולות ' + ', '.join(GLABEL[g] for g in combo_groups(cid)) + ' · ' + FLABEL[F]
            if any(v is not None for v in pairs_out.values()):
                ses_index_avail.append(sid)
            rec = dict(id=sid, name=name, kind='ses', pairs=pairs_out)
            with open(os.path.join(WEB, 'data', f'{sid}.json'), 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False)
    sidx = dict(filters=FLABEL, groups={g: GLABEL[g] for g in GROUPS}, available=ses_index_avail)
    with open(os.path.join(WEB, 'ses_index.json'), 'w', encoding='utf-8') as f:
        json.dump(sidx, f, ensure_ascii=False)
    step('write ses JSON and ses_index.json', t0)

    # ---------- checks ----------
    t0 = time.time()
    L = []
    w = L.append
    w('Stage 3 (SES x sector) summary')
    w('=' * 60)
    w('CHECK 1: ses-all-g1g2g3g4 vs national (point estimates; max over cells, per pair)')
    for pair in PAIRS:
        c = checks[pair]
        w(f'  {pair}: max |votes| diff {c["d_votes"]:.1f}; max |to total| diff {c["d_to"]:.1f}; '
          f'max |from total| diff {c["d_from"]:.1f}; sum |diff| {c["d_total"]:.1f} of national total {c["nat_total"]:.0f} '
          f'({100 * c["d_total"] / c["nat_total"]:.3f}%); ses total {c["ses_total"]:.0f}')
    w('  Expected difference: votes of localities missing from ses_clusters.csv (see bzb share below).')
    w('')
    w('CHECK 2: sum of the four single-group areas (link by link) vs ses-all-g1g2g3g4')
    for pair in PAIRS:
        w(f'  {pair}: max abs diff {checks[pair]["singles_vs_combo"]:.3e} votes')
    w('')

    # check 3: bzb shares
    w('CHECK 3: bzb share of each group per election (denominator: all boxes of the election, excluding envelopes)')
    for y in ELECTIONS:
        f = ctx.frames[y]
        tot = float(f['bzb'].sum())
        parts = []
        for g in GROUPS:
            ids = [c for c, gg in grp.items() if gg == g]
            parts.append(f'{g} {100 * f.loc[f["code"].isin(ids), "bzb"].sum() / tot:.2f}%')
        miss = float(f.loc[~f['code'].isin(list(grp)), 'bzb'].sum())
        w(f'  k{y}: ' + ', '.join(parts) + f', missing from SES file {100 * miss / tot:.2f}%')
    w('  Per filter (denominator: all boxes of that filter in the election):')
    for y in ELECTIONS:
        f = ctx.frames[y]
        m = masks(f, arab_elig)
        for F in FILTERS:
            sub = f.loc[m[F]]
            tot = float(sub['bzb'].sum())
            if tot == 0:
                continue
            parts = []
            for g in GROUPS:
                ids = [c for c, gg in grp.items() if gg == g]
                parts.append(f'{g} {100 * sub.loc[sub["code"].isin(ids), "bzb"].sum() / tot:.2f}%')
            miss = float(sub.loc[~sub['code'].isin(list(grp)), 'bzb'].sum())
            w(f'  k{y} {F:<8}: ' + ', '.join(parts) + f', missing {100 * miss / tot:.2f}%')
    w('')
    w('CHECK 4: five largest cross-category flows, 24-25, per filter and single group (rate % of from-row, 90% interval)')
    for F in FILTERS:
        for g in GROUPS:
            with open(os.path.join(WEB, 'data', f'ses-{F}-{g}.json'), encoding='utf-8') as f:
                rec = json.load(f)
            e = rec['pairs']['24-25']
            if e is None:
                w(f'  {F}-{g}: null')
                continue
            fr, to = e['from'], e['to']
            cross = [l for l in e['links'] if fr[l[0]][0] != to[l[1]][0]]
            cross.sort(key=lambda l: -l[2])
            w(f'  {F}-{g}:')
            for l in cross[:5]:
                w(f'    {fr[l[0]][0]} -> {to[l[1]][0]}: votes {l[2]}  rate {l[3]}%  [{l[4]}, {l[5]}]')
    w('')
    w('CHECK 5a: jewish fit counts per pair (own fits for regions with >= 15 jewish units; pooled fit present)')
    for pair in PAIRS:
        fc = fits_count[pair]
        w(f'  {pair}: own jewish fits {fc["own"]}, jewish:pooled {"yes" if fc["pooled"] else "no"}, total fits {fc["n_fits"]}')
    w('')
    w('CHECK 5b: runtime per step')
    for name, sec_ in steps:
        w(f'  {sec_:8.2f} s  {name}')
    w(f'  {time.time() - t_all:8.2f} s  total stage 3 (before the reproduction check)')
    with open(os.path.join(OUT, 'ses_summary.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
