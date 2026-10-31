"""Stage 2: fits, bootstrap, aggregates, sanity, sensitivity and web JSON.

Run:  python3 -I scripts/stage2.py [--boot N]
"""
import os
import sys
import time
import json
import zlib
import argparse
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np
import pandas as pd

import common
from common import OUT, PAIRS, ELECTIONS, OTHER, DNV, load_config, load_cbs, druze_codes, load_all
from pipeline import Context, build_pair
from model import fit_inputs
from solver import fista
from stage1 import MARK2

THIN = 12          # region fits with fewer units use the type-pooled fit
GEN_MIN = 15       # general:<id> fits need at least this many general units
NOINT = 10         # no bootstrap below this many units
SEED = 20260101
SECTOR_NAMES = {'haredi': 'חרדים', 'arab': 'ערבים', 'druze': 'דרוזים', 'general': 'כללי'}
TSENS = [0.10, 0.15, 0.20]
WEB = os.path.join(OUT, 'web')

_MAP_CACHE = {}


def map_matrix(cats, names):
    """nA x k matrix that maps totals over display categories `cats` to fit categories `names`."""
    key = (tuple(cats), tuple(names))
    if key in _MAP_CACHE:
        return _MAP_CACHE[key]
    kept = [n for n in names if n not in (OTHER, DNV)]
    ci = {c: i for i, c in enumerate(cats)}
    M = np.zeros((len(cats), len(names)))
    for j, n in enumerate(names):
        if n == OTHER:
            for i, c in enumerate(cats):
                if c not in kept and c != DNV:
                    M[i, j] = 1.0
        else:
            M[ci[n], j] = 1.0
    _MAP_CACHE[key] = M
    return M


def fit_worker(task):
    """One fit: point estimate, then B warm-started bootstrap replicates (resampling units)."""
    fid, X, Y, w, B, seed = task
    P, info = fista(X, Y, w)
    n = len(w)
    k, m = P.shape
    if B == 0 or n < NOINT:
        return dict(fid=fid, P=P, conv=info['converged'], iters=info['iters'], Pb=None, n=n, nonconv_reps=0)
    rng = np.random.default_rng(seed)
    Pb = np.empty((B, k, m))
    nc = 0
    for b in range(B):
        idx = rng.integers(0, n, n)
        Pb[b], inf = fista(X[idx], Y[idx], w[idx], P0=P)
        nc += int(not inf['converged'])
    return dict(fid=fid, P=P, conv=info['converged'], iters=info['iters'], Pb=Pb, n=n, nonconv_reps=nc)


def make_totals(ctx):
    """Per election: region totals, region general totals, sector totals (own-election classification)."""
    tot = {}
    for y in ELECTIONS:
        f = ctx.frames[y]
        cc = ctx.elections[y].cat_cols
        reg = f.groupby('region')[cc].sum().reindex(ctx.region_list).fillna(0.0)
        gen = f[f['sector'] == 'general'].groupby('region')[cc].sum().reindex(ctx.region_list).fillna(0.0)
        sec = f.groupby('sector')[cc].sum()
        secb = f.groupby('sector')['bzb'].sum()
        tot[y] = dict(reg=reg, gen=gen, sec=sec, secb=secb,
                      reg_bzb=f.groupby('region')['bzb'].sum().reindex(ctx.region_list).fillna(0.0),
                      nat=f[cc].sum().values.astype(float), nat_bzb=float(f['bzb'].sum()))
    ctx.tot = tot


def vec(df, key):
    return df.loc[key].values.astype(float)


def stack_of(res, B):
    if res['Pb'] is None:
        return np.repeat(res['P'][None], 1 + B, axis=0)
    return np.concatenate([res['P'][None], res['Pb']], axis=0)


def fid_of(src):
    """Fit id that a region's votes come from. src: 'region:R' | ('type', t) | ('national', 'all') | ('none', r)."""
    if isinstance(src, str):
        return src
    if src[0] == 'type':
        return f'type:{src[1]}'
    if src[0] == 'national':
        return 'national:all'
    return None


def run_pair(ctx, pair, T, B, pool=None, fallback=False):
    """All fits for one pair and the aggregated vote stacks. Stacks have shape (1+B, nA, nB).

    fallback=False (stage 2): thin regions use their type pool. fallback=True (live): a thin region uses its type
    pool if that has >= 12 units, else one national pool of all units ('national:all'), else no source ('none');
    general and jewish pooled fits with < 12 units fall back to national pools of their family.
    """
    t_start = time.time()
    bp = build_pair(ctx, pair, T)
    ya, yb = bp['ya'], bp['yb']
    a, b = ctx.elections[ya], ctx.elections[yb]
    u = bp['units']
    kept = u[u['reason'] == ''].copy()
    rtype = ctx.region_meta['type'].to_dict()
    regs = ctx.region_list
    by_reg = {r: g for r, g in kept.groupby('region')}
    empty = kept.iloc[0:0]

    specs = {}          # fid -> units
    kinds = {}
    region_src = {}     # r -> fid  |  ('type', t)  |  ('national', 'all')  |  ('none', r)
    thin = []
    n_type = kept['region'].map(rtype).value_counts().to_dict() if fallback else {}
    for r in regs:
        ur = by_reg.get(r, empty)
        if len(ur) >= THIN:
            fid = f'region:{r}'
            specs[fid] = ur
            kinds[fid] = ('region', r)
            region_src[r] = fid
        else:
            thin.append(r)
            if not fallback or n_type.get(rtype[r], 0) >= THIN:
                region_src[r] = ('type', rtype[r])
            elif len(kept) >= THIN:
                region_src[r] = ('national', 'all')
            else:
                region_src[r] = ('none', r)
    gen_src = {}
    for r in regs:
        ug = by_reg.get(r, empty)
        ug = ug[ug['sector'] == 'general'] if len(ug) else ug
        if len(ug) >= GEN_MIN:
            fid = f'general:{r}'
            specs[fid] = ug
            kinds[fid] = ('general', r)
            gen_src[r] = fid
    pooled_regions = [r for r in regs if r not in gen_src]
    gp = kept[(kept['sector'] == 'general') & kept['region'].isin(pooled_regions)]
    if len(gp):
        specs['general:pooled'] = gp
        kinds['general:pooled'] = ('gpool', pooled_regions)
    for s in ('haredi', 'arab', 'druze'):
        us = kept[kept['sector'] == s]
        if len(us):
            specs[f'sector:{s}'] = us
            kinds[f'sector:{s}'] = ('sector', s)
    # jewish fits (stage 3): units of sector general or haredi; own fit if >= GEN_MIN units
    jw_own = set()
    for r in regs:
        uj = by_reg.get(r, empty)
        uj = uj[uj['sector'].isin(['general', 'haredi'])] if len(uj) else uj
        if len(uj) >= GEN_MIN:
            fid = f'jewish:{r}'
            specs[fid] = uj
            kinds[fid] = ('jewish', r)
            jw_own.add(r)
    jp_regions = [r for r in regs if r not in jw_own]
    jp = kept[kept['sector'].isin(['general', 'haredi']) & kept['region'].isin(jp_regions)]
    if len(jp):
        specs['jewish:pooled'] = jp
        kinds['jewish:pooled'] = ('jpool', jp_regions)
    for t in sorted({rtype[r] for r in thin}):
        ut = kept[kept['region'].map(rtype) == t]
        if len(ut):
            specs[f'type:{t}'] = ut
            kinds[f'type:{t}'] = ('type', t)
    if fallback:
        if len(kept):
            specs['national:all'] = kept
            kinds['national:all'] = ('national', 'all')
        gk = kept[kept['sector'] == 'general']
        if len(gk):
            specs['general:national'] = gk
            kinds['general:national'] = ('gnational', None)
        jk = kept[kept['sector'].isin(['general', 'haredi'])]
        if len(jk):
            specs['jewish:national'] = jk
            kinds['jewish:national'] = ('jnational', None)

    tasks = []
    names = {}
    for fid, us in specs.items():
        X, Y, w, nx, ny, ka, kb = fit_inputs(us, a, b)
        names[fid] = (nx, ny)
        tasks.append((fid, X, Y, w, B, zlib.crc32(f'{pair}|{fid}'.encode()) ^ SEED))
    t_fit = time.time()
    raw = pool.map(fit_worker, tasks) if pool is not None else [fit_worker(t) for t in tasks]
    res = {r['fid']: dict(r, names_x=names[r['fid']][0], names_y=names[r['fid']][1]) for r in raw}
    t_fit = time.time() - t_fit

    ia = {c: i for i, c in enumerate(a.cats)}
    ib = {c: i for i, c in enumerate(b.cats)}
    nA, nB = len(a.cats), len(b.cats)
    Bd = 1 + B

    def add(full, fid, ta):
        r_ = res[fid]
        tx = ta @ map_matrix(a.cats, r_['names_x'])
        S = stack_of(r_, B) * tx[None, :, None]
        ix = np.array([ia[n] for n in r_['names_x']])
        iy = np.array([ib[n] for n in r_['names_y']])
        full[:, ix[:, None], iy[None, :]] += S

    T_a, T_b = ctx.tot[ya], ctx.tot[yb]
    nat = np.zeros((Bd, nA, nB))
    region_full = {}
    null_regions = set()
    for r in regs:
        src = region_src[r]
        fid = fid_of(src)
        if fid is None or fid not in res:
            null_regions.add(r)
            continue
        full = np.zeros((Bd, nA, nB))
        ta = vec(T_a['reg'], r)
        add(full, fid, ta)
        region_full[r] = (full, isinstance(src, str))
        nat += full

    gen = np.zeros((Bd, nA, nB))
    gen_regions_pooled = [r for r in regs if r not in gen_src]
    for r, fid in gen_src.items():
        add(gen, fid, vec(T_a['gen'], r))
    gpool_fid = 'general:pooled'
    if fallback and 'general:pooled' in res and res['general:pooled']['n'] < THIN and 'general:national' in res:
        gpool_fid = 'general:national'
    if gpool_fid in res and gen_regions_pooled:
        add(gen, gpool_fid, T_a['gen'].loc[gen_regions_pooled].values.sum(axis=0).astype(float))

    sec_full = {}
    for s in ('haredi', 'arab', 'druze'):
        if f'sector:{s}' in res:
            full = np.zeros((Bd, nA, nB))
            add(full, f'sector:{s}', vec(T_a['sec'], s))
            sec_full[s] = full
    return dict(pair=pair, T=T, ya=ya, yb=yb, bp=bp, kept=kept, res=res, kinds=kinds, region_src=region_src,
                thin=thin, gen_src=gen_src, gen_pooled=gen_regions_pooled, region_full=region_full,
                null_regions=null_regions, nat=nat, gen=gen, sec_full=sec_full, a=a, b=b,
                t_fit=t_fit, t_total=time.time() - t_start)


def sanity_rows(R, ctx):
    """Modelled later totals (sum of votes per later category) vs actual later totals of each fit's area."""
    a, b = R['a'], R['b']
    T_a, T_b = ctx.tot[R['ya']], ctx.tot[R['yb']]
    rows = []
    for fid, r_ in R['res'].items():
        kind = R['kinds'][fid]
        if kind[0] in ('jewish', 'jpool'):
            continue          # jewish fits are used by stage 3 only; sanity.csv stays as in stage 2
        if kind[0] == 'region':
            areas = [(vec(T_a['reg'], kind[1]), vec(T_b['reg'], kind[1]), f'region {kind[1]}')]
        elif kind[0] == 'general':
            areas = [(vec(T_a['gen'], kind[1]), vec(T_b['gen'], kind[1]), f'general {kind[1]}')]
        elif kind[0] == 'gpool':
            rs = kind[1]
            areas = [(T_a['gen'].loc[rs].values.sum(0).astype(float), T_b['gen'].loc[rs].values.sum(0).astype(float),
                      f'general pooled ({len(rs)} regions)')]
        elif kind[0] == 'sector':
            areas = [(vec(T_a['sec'], kind[1]), vec(T_b['sec'], kind[1]), f'sector {kind[1]}')]
        else:
            rs = [r for r in ctx.region_list if ctx.region_meta.loc[r, 'type'] == kind[1]]
            areas = [(vec(T_a['reg'], r), vec(T_b['reg'], r), f'type {kind[1]} ({len(rs)} regions)') for r in rs]
        Mx = map_matrix(a.cats, r_['names_x'])
        My = map_matrix(b.cats, r_['names_y'])
        model = np.zeros(len(r_['names_y']))
        actual = np.zeros(len(r_['names_y']))
        bzb_area = 0.0
        for ta, tb, _ in areas:
            model += (r_['P'] * (ta @ Mx)[:, None]).sum(axis=0)
            ya_ = tb @ My
            actual += ya_
            bzb_area += tb.sum()
        share = actual / bzb_area if bzb_area else np.zeros_like(actual)
        qual = share >= 0.03
        with np.errstate(divide='ignore', invalid='ignore'):
            dev = np.where(actual > 0, 100.0 * np.abs(model - actual) / actual, np.nan)
        mx = np.nanmax(dev[qual]) if qual.any() and np.isfinite(dev[qual]).any() else np.nan
        desc = '; '.join(d for _, _, d in areas)
        for j, nm in enumerate(r_['names_y']):
            rows.append(dict(fit=fid, pair=R['pair'], n_units=r_['n'], area=desc, category=nm,
                             model=round(model[j], 2), actual=round(actual[j], 2), share=round(share[j], 4),
                             qualifies=bool(qual[j]), pct_dev=round(dev[j], 3) if dev[j] == dev[j] else None,
                             max_abs_pct_dev=round(mx, 3) if mx == mx else None))
    return rows


def national_flows(stack_point, a, b, pct_row=True):
    P0 = stack_point
    rowtot = P0.sum(axis=1)
    out = []
    for i, fa in enumerate(a.cats):
        for j, tb_ in enumerate(b.cats):
            v = P0[i, j]
            if v >= 9.5:
                out.append((fa, tb_, v, 100.0 * v / rowtot[i] if rowtot[i] > 0 else np.nan))
    return out


def area_entry(full, a, b, actual_a, actual_b, n_units, coverage, coverage_core, dropped, no_int, fallback=None):
    """Web entry. from / to totals are the modelled row / column sums (point estimate)."""
    P0 = full[0]
    rowtot = P0.sum(axis=1)
    coltot = P0.sum(axis=0)
    if full.shape[0] > 1:
        lo = np.percentile(full[1:], 5, axis=0)
        hi = np.percentile(full[1:], 95, axis=0)
    else:
        lo = hi = None        # no bootstrap: intervals are null
    links = []
    for i in range(P0.shape[0]):
        for j in range(P0.shape[1]):
            v = P0[i, j]
            if round(v) < 10:
                continue
            rt = rowtot[i]
            if rt <= 0:
                continue
            if lo is None:
                links.append([i, j, int(round(v)), round(100 * v / rt, 1), None, None])
            else:
                links.append([i, j, int(round(v)), round(100 * v / rt, 1), round(100 * lo[i, j] / rt, 1),
                              round(100 * hi[i, j] / rt, 1)])
    e = dict(
        **{'from': [[n, a.fam.get(n, 'other'), int(round(t))] for n, t in zip(a.cats, rowtot)]},
        to=[[n, b.fam.get(n, 'other'), int(round(t))] for n, t in zip(b.cats, coltot)],
        to_actual=[[n, b.fam.get(n, 'other'), int(round(t))] for n, t in zip(b.cats, actual_b)],
        links=links, n_units=int(n_units),
        coverage=round(100 * coverage, 1) if coverage is not None else None,
        coverage_core=round(100 * coverage_core, 1) if coverage_core is not None else None,
        dropped_replacement=int(dropped), no_interval=bool(no_int))
    if fallback is not None:
        e['fallback_regions'] = int(fallback)
    return e


def build_areas(R, ctx, cfg):
    """Web entries for national, sector and large-locality areas of one pair."""
    a, b = R['a'], R['b']
    kept, u = R['kept'], R['bp']['units']
    core = kept[kept['method'] != 'residual']
    T_a, T_b = ctx.tot[R['ya']], ctx.tot[R['yb']]
    nat_bzb_a = T_a['nat_bzb']
    out = {}
    src_fids = set(fid_of(R['region_src'][r]) for r in R['region_full'])
    nat_noint = any(R['res'][fid]['Pb'] is None for fid in src_fids)
    out['national'] = area_entry(
        R['nat'], a, b, T_a['nat'], T_b['nat'], len(kept),
        kept['a_bzb'].sum() / nat_bzb_a, core['a_bzb'].sum() / nat_bzb_a,
        (u['reason'] == 'replacement').sum(), nat_noint, len(R['thin']))
    for s in ('haredi', 'arab', 'druze', 'general'):
        key = f'sector:{s}'
        us = kept[kept['sector'] == s]
        uc = us[us['method'] != 'residual']
        dr = int(((u['sector'] == s) & (u['reason'] == 'replacement')).sum())
        den = T_a['secb'][s] if s in T_a['secb'].index else 0
        cov = us['a_bzb'].sum() / den if den else None
        cov_c = uc['a_bzb'].sum() / den if den else None
        act_a = T_a['sec'].loc[s].values.astype(float) if s in T_a['sec'].index else np.zeros(len(a.cats))
        act_b = T_b['sec'].loc[s].values.astype(float) if s in T_b['sec'].index else np.zeros(len(b.cats))
        if s == 'general':
            no_int = any(R['res'][f]['Pb'] is None for f in
                         [R['gen_src'][r] for r in R['gen_src']] + (['general:pooled'] if 'general:pooled' in R['res'] else []))
            out[key] = area_entry(R['gen'], a, b, act_a, act_b, len(us), cov, cov_c, dr, no_int, len(R['gen_pooled']))
        else:
            if s not in R['sec_full']:
                out[key] = None
                continue
            no_int = R['res'][key]['Pb'] is None
            out[key] = area_entry(R['sec_full'][s], a, b, act_a, act_b, len(us), cov, cov_c, dr, no_int, 0)
    for r in ctx.region_meta.index[ctx.region_meta['kind'] == 'large']:
        if r in R['region_full'] and R['region_full'][r][1]:
            full, own = R['region_full'][r]
            ur = kept[kept['region'] == r]
            uc = ur[ur['method'] != 'residual']
            dr = int(((u['region'] == r) & (u['reason'] == 'replacement')).sum())
            den = T_a['reg_bzb'][r]
            cov = ur['a_bzb'].sum() / den if den else None
            cov_c = uc['a_bzb'].sum() / den if den else None
            no_int = R['res'][R['region_src'][r]]['Pb'] is None
            out[r] = area_entry(full, a, b, vec(T_a['reg'], r), vec(T_b['reg'], r), len(ur), cov, cov_c, dr, no_int)
        else:
            out[r] = None
    return out


def write_web(all_areas, ctx, pairs):
    os.makedirs(os.path.join(WEB, 'data'), exist_ok=True)
    meta = [('national', 'כלל הארץ', 'national')]
    for s in ('haredi', 'arab', 'druze', 'general'):
        meta.append((f'sector:{s}', SECTOR_NAMES[s], 'sector'))
    large = ctx.region_meta[ctx.region_meta['kind'] == 'large']
    first = [r for r in ['3000', '5000', '4000', '9000'] if r in large.index]
    rest = sorted([r for r in large.index if r not in first], key=lambda r: large.loc[r, 'name'].strip())
    for r in first + rest:
        meta.append((r, large.loc[r, 'name'], 'city'))
    index = [dict(id=i, name=n, kind=k) for i, n, k in meta]
    with open(os.path.join(WEB, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False)
    for i, n, k in meta:
        pairs_out = {}
        for p in pairs:
            pairs_out[p] = all_areas[p].get(i)
        rec = dict(id=i, name=n, kind=k, pairs=pairs_out)
        with open(os.path.join(WEB, 'data', f'{i}.json'), 'w', encoding='utf-8') as f:
            json.dump(rec, f, ensure_ascii=False)
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--boot', type=int, default=100)
    args = ap.parse_args()
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
    make_totals(ctx)
    step('load and context', t0)

    pool = Pool(4)
    t0 = time.time()
    R = run_pair(ctx, '24-25', 0.15, 0, pool)
    t_point = time.time() - t0
    step('timing: full pair 24-25 WITHOUT bootstrap (fits and assembly)', t0)
    t0 = time.time()
    R2 = run_pair(ctx, '24-25', 0.15, 2, pool)
    t_b2 = time.time() - t0
    per_rep = max((t_b2 - t_point) / 2.0, 1e-3)
    est = len(PAIRS) * (t_point + 100 * per_rep)
    B = args.boot
    if est > 7200:
        B = 60
    timing_note = (f'timing: one pair point-only {t_point:.1f}s; per bootstrap replicate per pair {per_rep:.2f}s; '
                   f'extrapolated 7 pairs with B=100: {est/60:.1f} min -> '
                   + ('exceeds 2 h, reduced to B=60' if est > 7200 else f'within 2 h, using B={B}'))
    step('timing: bootstrap cost probe (2 replicates, one pair)', t0)

    t0 = time.time()
    results = {}
    for pair in PAIRS:
        results[pair] = run_pair(ctx, pair, 0.15, B, pool)
    step(f'fits with bootstrap B={B}, all 7 pairs (incl. aggregates)', t0)

    t0 = time.time()
    sanity = []
    all_areas = {}
    for pair in PAIRS:
        R = results[pair]
        sanity += sanity_rows(R, ctx)
        all_areas[pair] = build_areas(R, ctx, cfg)
    step('sanity and web areas', t0)

    t0 = time.time()
    index = write_web(all_areas, ctx, PAIRS)
    step('write web JSON', t0)

    t0 = time.time()
    san = pd.DataFrame(sanity)
    san.to_csv(os.path.join(OUT, 'sanity.csv'), index=False, encoding='utf-8')
    step('write sanity.csv', t0)

    t0 = time.time()
    sens_rows = []
    sens_nat = {}
    for T in TSENS:
        for pair in PAIRS:
            if T == 0.15:
                nat = results[pair]['nat'][0]
                a, b = results[pair]['a'], results[pair]['b']
            else:
                Rt = run_pair(ctx, pair, T, 0, pool)
                nat = Rt['nat'][0]
                a, b = Rt['a'], Rt['b']
            sens_nat[(pair, T)] = (nat, a, b)
    for pair in PAIRS:
        nat15, a, b = sens_nat[(pair, 0.15)]
        for T in TSENS:
            nat, a2, b2 = sens_nat[(pair, T)]
            fl = national_flows(nat, a2, b2)
            fl = [f for f in fl if f[0] != f[1]]
            fl.sort(key=lambda x: -x[2])
            fl = fl[:20]
            n15 = national_flows(nat15, a, b)
            d15 = {(x[0], x[1]): (x[2], x[3]) for x in n15}
            for rk, (fa, tb_, v, rate) in enumerate(fl, 1):
                v15, r15 = d15.get((fa, tb_), (np.nan, np.nan))
                sens_rows.append(dict(pair=pair, T=T, rank=rk, from_=fa, to=tb_, votes=round(v, 1),
                                      rate_pct=round(rate, 2), votes_T015=round(v15, 1),
                                      rate_pct_T015=round(r15, 2), delta_pp=round(rate - r15, 2)))
    sens = pd.DataFrame(sens_rows)
    sens.to_csv(os.path.join(OUT, 'sensitivity.csv'), index=False, encoding='utf-8')
    step('sensitivity (T=0.10, 0.20 point fits, 7 pairs)', t0)

    # ---- summary ----
    t0 = time.time()
    lines = [MARK2, '']
    w = lines.append
    w('Stage 2 summary (bootstrap B = %d; solver tol 1e-6, max 50000 iterations)' % B)
    w(timing_note)
    w('')
    w('A. Per pair: national coverage (after residual, after filter), units, non-converged main fits, fallback regions')
    total_nc = 0
    for pair in PAIRS:
        R = results[pair]
        nat = all_areas[pair]['national']
        nonconv = [fid for fid, r_ in R['res'].items() if not r_['conv']]
        total_nc += len(nonconv)
        nulls = [(r, ctx.region_meta.loc[r, 'name']) for r in ctx.region_meta.index[ctx.region_meta['kind'] == 'large']
                 if all_areas[pair].get(r) is None]
        w(f'  {pair}: coverage {nat["coverage"]}% (core, non-residual {nat["coverage_core"]}%)  units {nat["n_units"]}  non-converged main fits {len(nonconv)} '
          f'of {len(R["res"])}  fallback regions (thin, type pool) {nat["fallback_regions"]}  '
          f'large localities null {len(nulls)}')
        if nonconv:
            w(f'      non-converged: {", ".join(nonconv)}')
        w(f'      null large localities: {", ".join(n for _, n in nulls)}')
    w(f'  total non-converged main fits: {total_nc}')
    w('')
    w('B. Sanity: the 10 worst max abs % deviation among fits with >= 12 units')
    s12 = san[san['n_units'] >= THIN].dropna(subset=['max_abs_pct_dev'])
    worst = s12.drop_duplicates(['fit', 'pair']).sort_values('max_abs_pct_dev', ascending=False).head(10)
    for _, r in worst.iterrows():
        w(f'  {r["pair"]} {r["fit"]:<22} units {int(r["n_units"]):5d}  max abs % dev {r["max_abs_pct_dev"]:.2f}  ({r["area"]})')
    w('')
    w('C. Sensitivity: top-20 national cross-category flows at T=0.15; movement at T=0.10 and 0.20')
    for pair in PAIRS:
        top = sens[(sens['pair'] == pair) & (sens['T'] == 0.15)].head(20)
        rates = {T_: {(x[0], x[1]): x[3] for x in national_flows(sens_nat[(pair, T_)][0],
                      sens_nat[(pair, T_)][1], sens_nat[(pair, T_)][2])} for T_ in TSENS}
        mv, rows_ = [], []
        for _, r in top.iterrows():
            key = (r['from_'], r['to'])
            d10 = rates[0.10].get(key, np.nan) - r['rate_pct']
            d20 = rates[0.20].get(key, np.nan) - r['rate_pct']
            rows_.append((key, r['rate_pct'], d10, d20))
            mv += [abs(x) for x in (d10, d20) if x == x]
        w(f'  {pair}: T=0.15 top-20 flows, largest rate shift at T=0.10 or 0.20: {max(mv):.2f} pp; '
          f'median absolute shift {np.median(mv):.2f} pp')
    w('')
    w('D. Top 10 national cross-category flows, 24-25 and 20-25, with 90% intervals (rate %, from-row)')
    for pair in ('23-24', '24-25', '20-25'):
        ent = all_areas[pair]['national']
        fr, to = ent['from'], ent['to']
        cross = [l for l in ent['links'] if fr[l[0]][0] != to[l[1]][0]]
        cross.sort(key=lambda l: -l[2])
        w(f'  {pair}:')
        for l in cross[:10]:
            w(f'    {fr[l[0]][0]} -> {to[l[1]][0]}: votes {l[2]}  rate {l[3]}%  [{l[4]}, {l[5]}]')
    w('')
    w('E. Interval check: point estimate inside its 5-95% interval (rounded web values), all areas')
    for pair in PAIRS:
        n_links = viol = 0
        for area, ent in all_areas[pair].items():
            if not ent:
                continue
            for l in ent['links']:
                n_links += 1
                if not (l[4] - 0.05 <= l[3] <= l[5] + 0.05):
                    viol += 1
        w(f'  {pair}: links {n_links}, point outside interval {viol}')
    w('')
    w('F. Runtime per step (stage 2)')
    for name, sec_ in steps:
        w(f'  {sec_:8.2f} s  {name}')
    w(f'  {time.time() - t_all:8.2f} s  total stage 2')
    w('')
    pool.close()
    with open(os.path.join(OUT, 'diagnostics_summary.txt'), 'r', encoding='utf-8') as f:
        prev = f.read()
    if MARK2 in prev:
        prev = prev[:prev.index(MARK2)]
    with open(os.path.join(OUT, 'diagnostics_summary.txt'), 'w', encoding='utf-8') as f:
        f.write(prev + '\n'.join(lines) + '\n')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
