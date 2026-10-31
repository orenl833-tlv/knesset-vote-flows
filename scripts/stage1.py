"""Stage 1: data preparation, regions, matching units (7 pairs), filters, sectors, diagnostics,
FISTA solver check and the Holon validation fit.

Run:  python3 -I scripts/stage1.py
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import numpy as np
import pandas as pd

import common
from common import OUT, PAIRS, ELECTIONS, load_config, load_cbs, druze_codes, load_all
from pipeline import Context, build_pair
from model import fit_inputs
from solver import fista

HOLON = 6600
VALIDATION = {
    '23-24': [('כחול לבן', 'יש עתיד', 50), ('כחול לבן', 'כחול לבן', 24), ('הליכוד', 'הליכוד', 76),
              ('ש"ס', 'ש"ס', 85), ('ישראל ביתנו', 'ישראל ביתנו', 80)],
    '24-25': [('הליכוד', 'הליכוד', 85), ('הליכוד', 'הציונות הדתית', 13), ('יש עתיד', 'יש עתיד', 82),
              ('כחול לבן', 'המחנה הממלכתי', 72), ('ש"ס', 'ש"ס', 97)],
}
SECTORS = ['druze', 'arab', 'haredi', 'general', 'transitional']
DROP_LEVEL = ['place_unmatched', 'place_bzb', 'num_unmatched', 'num_bzb']
DROP_REST = ['rest_unmatched', 'rest_bzb']
DROP_RES = ['res_unmatched', 'res_bzb']
MARK2 = '=== STAGE 2 ==='


def stage1_lines(ctx, elections, pair_builds, holon, runtimes, t_all, ballot_sector):
    """Build stage-1 summary text lines."""
    lines = []
    w = lines.append
    w('Stage 1 diagnostics summary')
    w('=' * 60)
    w('')
    w('1. National coverage per pair (share of all modelled boxes): before residual rule -> after')
    for pair in PAIRS:
        bp = pair_builds[pair]
        u = bp['units']
        kept = u[u['reason'] == '']
        nores = kept[kept['method'] != 'residual']
        ya, yb = bp['ya'], bp['yb']
        nat_a = int(elections[ya].df['bzb'].sum())
        nat_b = int(elections[yb].df['bzb'].sum())
        ca0, cb0 = nores['a_bzb'].sum() / nat_a, nores['b_bzb'].sum() / nat_b
        ca, cb = kept['a_bzb'].sum() / nat_a, kept['b_bzb'].sum() / nat_b
        w(f'  {pair}: before residual a {100*ca0:.2f}% b {100*cb0:.2f}% | after a {100*ca:.2f}% b {100*cb:.2f}% | '
          f'units kept {len(kept)} (residual {int((kept["method"]=="residual").sum())}, '
          f'candidates {len(u)}; dropped zero-valid {int((u["reason"]=="zero_valid").sum())}, '
          f'replacement {int((u["reason"]=="replacement").sum())})')
    w('')
    w('2. Double-envelope rows excluded from all modelling (valid votes per election)')
    for y in ELECTIONS:
        dr = elections[y].dbl_rows
        label = '9999 (double envelopes)' if y >= 22 else 'code 875 (19-20) / 99999 (21), named "מעטפות חיצוניות"'
        w(f'  k{y}: {len(dr)} rows, {label}: bzb {int(dr.bzb.sum())}, valid votes {int(dr.val.sum())}')
        if y <= 21:
            w(f'      = {100*dr.val.sum()/elections[y].df["val"].sum():.2f}% of modelled valid votes; cannot be matched (bzb 0).')
    w('')
    w('3. Ten large localities with the lowest coverage per pair (ranked by min(cov a, cov b), kept units)')
    for pair in PAIRS:
        big = ctx_diag(pair_builds[pair], ctx)
        big = big[big['kind'] == 'large'].copy()
        big['min_cov'] = big[['cov_a', 'cov_b']].min(axis=1)
        low = big.sort_values('min_cov').head(10)
        w(f'  {pair}:')
        for _, r in low.iterrows():
            w(f'    {r["region"]:>6}  {r["name"]:<22} cov_a {100*r["cov_a"]:6.2f}%  cov_b {100*r["cov_b"]:6.2f}%  '
              f'units {int(r["n_units"]):4d}  boxes_k25 {int(r["k25_boxes"])}')
    w('')
    w('4. Sector unit counts per pair (kept units; transitional units used in no sector fit)')
    for pair in PAIRS:
        kept = pair_builds[pair]['units']
        kept = kept[kept['reason'] == '']
        s = kept['sector'].value_counts().to_dict()
        w(f'  {pair}: ' + ', '.join(f'{k} {s.get(k, 0)}' for k in SECTORS) + f'  (total {len(kept)})')
    w('')
    w('5. Ballot-level sector totals per election (classified on the election\'s own shares)')
    for y in ELECTIONS:
        t = ballot_sector[y]
        w(f'  k{y}: ' + ', '.join(f'{s} valid {int(t.loc[s, "val"])} / bzb {int(t.loc[s, "bzb"])}' for s in t.index))
    w('')
    w('6. Localities in the elections missing from the CBS file (excluding envelope pseudo-localities)')
    for c in ctx.gaps['missing_cbs']:
        if c in (9999, 99999):
            continue
        yrs = [f'k{y}:{int((elections[y].df["code"] == c).sum())}' for y in ELECTIONS
               if (elections[y].df['code'] == c).any()]
        w(f'  code {c} "{ctx.gaps["names"].get(c, "")}": boxes {" ".join(yrs)} -> region {ctx.loc_to_region.get(c)}')
    w('  Code 875 is in CBS as "כפר עבודה"; in k19-k20 the 875 rows are the envelope pseudo-locality and are excluded by name.')
    w('  Localities in CBS with an empty religion code (flagged; assigned to their district cluster rules: unknown -> misc):')
    for c in ctx.gaps['nan_dat']:
        n25 = int((elections[25].df['code'] == c).sum())
        if n25 or any((elections[y].df['code'] == c).any() for y in ELECTIONS):
            w(f'    code {c} "{ctx.cbs.loc[c, "name"]}" ({ctx.cbs.loc[c, "district"]}), k25 boxes {n25} -> region {ctx.loc_to_region.get(c)}')
    w('  Large localities with fewer than 25 k25 boxes keep their own region (see note in stage 2 summary).')
    w('')
    w('7. Holon (6600) validation, reference from spec (rates in %)')
    for _, r in holon.iterrows():
        w(f'  {r["pair"]}  {r["flow"]:<40} ref {r["ref_pct"]:>3}  ours {r["ours_pct"]}  diff {r["diff_pp"]} pp  {r["note"]}')
    for pair in ('23-24', '24-25'):
        r = holon[holon['pair'] == pair].iloc[0]
        w(f'  {pair}: units {int(r["n_units"])}, categories X {int(r["cats_x"])} / Y {int(r["cats_y"])}, '
          f'FISTA iterations {int(r["iters"])}, converged {bool(r["converged"])}')
    w('')
    w('8. Runtime per step (stage 1)')
    for name, sec in runtimes:
        w(f'  {sec:8.2f} s  {name}')
    w(f'  {time.time() - t_all:8.2f} s  total stage 1')
    w('')
    return lines


_DIAG = {}


def ctx_diag(bp, ctx):
    return _DIAG[bp['pair']]


def diag_rows(bp, ctx):
    u = bp['units']
    kept = u[u['reason'] == '']
    rows = []
    ya, yb = bp['ya'], bp['yb']
    rb_a = ctx.region_bzb[ya]
    rb_b = ctx.region_bzb[yb]
    for rid in ctx.region_list:
        ub = u[u['region'] == rid]
        uk = kept[kept['region'] == rid]
        d = bp['drops'][bp['drops']['region'] == rid]
        ra = float(rb_a.get(rid, 0))
        rbb = float(rb_b.get(rid, 0))
        ba = float(uk['a_bzb'].sum())
        bb = float(uk['b_bzb'].sum())
        nores = uk[uk['method'] != 'residual']
        row = dict(
            pair=bp['pair'], region=rid, kind=ctx.region_meta.loc[rid, 'kind'],
            type=ctx.region_meta.loc[rid, 'type'], name=ctx.region_meta.loc[rid, 'name'],
            k25_boxes=int(ctx.region_meta.loc[rid, 'k25_boxes']),
            n_units_candidates=len(ub), n_units=len(uk), n_residual=int((uk['method'] == 'residual').sum()),
            dropped_zero_valid=int((ub['reason'] == 'zero_valid').sum()),
            dropped_replacement=int((ub['reason'] == 'replacement').sum()),
            dropped_bzb_level=int(d['kind'].isin(DROP_LEVEL).sum()),
            dropped_bzb_rest=int(d['kind'].isin(DROP_REST).sum()),
            dropped_bzb_residual=int(d['kind'].isin(DROP_RES).sum()),
            bzb_a_region=int(ra), bzb_b_region=int(rbb), bzb_a_units=int(ba), bzb_b_units=int(bb),
            cov_a=ba / ra if ra else np.nan, cov_b=bb / rbb if rbb else np.nan,
            cov_a_noresidual=float(nores['a_bzb'].sum()) / ra if ra else np.nan,
            cov_b_noresidual=float(nores['b_bzb'].sum()) / rbb if rbb else np.nan,
        )
        for s in SECTORS:
            row[f'sec_{s}'] = int((uk['sector'] == s).sum())
        rows.append(row)
    return rows


def run_holon(elections, bp):
    uh = bp['units']
    uh = uh[(uh['reason'] == '') & (uh['code'] == HOLON)]
    ya, yb = bp['ya'], bp['yb']
    X, Y, w, nx, ny, _, _ = fit_inputs(uh, elections[ya], elections[yb])
    P, info = fista(X, Y, w)
    out = []
    for fa, ta, ref in VALIDATION[bp['pair']]:
        if fa not in nx or ta not in ny:
            rate, note = np.nan, 'category not in fit (folded)'
        else:
            rate = 100.0 * P[nx.index(fa), ny.index(ta)]
            note = ''
        out.append(dict(pair=bp['pair'], flow=f'{fa} -> {ta}', ref_pct=ref,
                        ours_pct=round(rate, 1) if rate == rate else None,
                        diff_pp=round(rate - ref, 1) if rate == rate else None, note=note,
                        n_units=len(uh), iters=info['iters'], converged=info['converged'],
                        cats_x=len(nx), cats_y=len(ny)))
    return out


def main():
    t_all = time.time()
    runtimes = []

    def step(name, t0):
        runtimes.append((name, time.time() - t0))

    t0 = time.time()
    cfg = load_config()
    cbs = load_cbs()
    druze_set, mixed_set = druze_codes(cfg, cbs)
    elections = load_all(cfg)
    step('load: config, CBS, six ballot-box CSVs (k19-k25)', t0)

    t0 = time.time()
    ctx = Context(cfg, elections, cbs, druze_set, mixed_set)
    ctx.region_bzb = {y: ctx.frames[y].groupby('region')['bzb'].sum() for y in ELECTIONS}
    step('regions, clusters and misc merge', t0)

    t0 = time.time()
    pair_builds = {}
    diag = []
    for pair in PAIRS:
        t1 = time.time()
        bp = build_pair(ctx, pair)
        pair_builds[pair] = bp
        rows = diag_rows(bp, ctx)
        diag += rows
        step(f'matching, residual, filters, sectors {pair}', t1)
    _DIAG.update({p: pd.DataFrame([r for r in diag if r['pair'] == p]) for p in PAIRS})
    step('matching total (7 pairs)', t0)

    t0 = time.time()
    dg = pd.DataFrame(diag)
    common.ensure_out()
    dg.to_csv(os.path.join(OUT, 'diagnostics_units.csv'), index=False, encoding='utf-8', float_format='%.6f')
    step('write diagnostics_units.csv', t0)

    t0 = time.time()
    holon = pd.DataFrame([r for pair in ('23-24', '24-25') for r in run_holon(elections, pair_builds[pair])])
    step('Holon validation fits (23-24, 24-25)', t0)

    t0 = time.time()
    ballot_sector = {}
    for y in ELECTIONS:
        f = ctx.frames[y]
        ballot_sector[y] = f.groupby('sector')[['bzb', 'val']].sum()
    lines = stage1_lines(ctx, elections, pair_builds, holon, runtimes, t_all, ballot_sector)
    step('write summary', t0)
    lines.append(f'  {runtimes[-1][1]:8.2f} s  write summary (stage 1)')
    with open(os.path.join(OUT, 'diagnostics_summary.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    holon.to_csv(os.path.join(OUT, 'holon_validation_stage1.csv'), index=False, encoding='utf-8')
    print('\n'.join(lines))


if __name__ == '__main__':
    main()
