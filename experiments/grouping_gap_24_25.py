# Result (25 Oct 2026), Likud 2021 -> far right 2022: separate parties 11.3% national fit / 12.1% per region;
# Yamina+RZ as "right" 7.6% / 9.5%; Yamina+RZ+New Hope as "right" 0.0% / 7.3%. INES survey: ~12%.
# Run from elections/: python3 elections/experiments/grouping_gap_24_25.py (about 1 minute).
# Why does a grouped, single national fit see no Likud -> far-right move in 2021 -> 2022?
# Same matched units as our model; vary (a) party grouping and (b) one national fit vs one fit per region.
import os, sys, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'scripts'))
from common import load_config, load_cbs, druze_codes, load_all
from pipeline import Context, build_pair
from solver import fista

cfg = load_config(); cbs = load_cbs(); dz, mx = druze_codes(cfg, cbs)
el = load_all(cfg); ctx = Context(cfg, el, cbs, dz, mx)
P = build_pair(ctx, '24-25'); u = P['units']; u = u[u['reason'] == ''].copy()
a, b = el[24], el[25]
print('2021 cats', a.cats); print('2022 cats', b.cats)

def mat(side, E, groups):
    names, cols = [], []
    for c, nm in zip(E.cat_cols, E.cats):
        g = groups.get(nm, nm)
        if g not in names: names.append(g); cols.append(u[f'{side}_{c}'].values.astype(float).copy())
        else: cols[names.index(g)] += u[f'{side}_{c}'].values
    return np.column_stack(cols), names

def fold_small(M, names, keep_always):
    tot = M.sum(0); val = tot[[i for i, n in enumerate(names) if n != 'לא הצביעו']].sum()
    keep = [i for i, n in enumerate(names) if n in keep_always or n == 'לא הצביעו' or tot[i] / val >= 0.03]
    other = [i for i in range(len(names)) if i not in keep]
    cols = [M[:, i] for i in keep] + [M[:, other].sum(1)]
    return np.column_stack(cols), [names[i] for i in keep] + ['אחרים*']

def run(ga, gb, src, dst, label):
    Ma, na = mat('a', a, ga); Mb, nb = mat('b', b, gb)
    Ma, na = fold_small(Ma, na, {src}); Mb, nb = fold_small(Mb, nb, {dst})
    bza, bzb = u['a_bzb'].values.astype(float), u['b_bzb'].values.astype(float)
    X, Y = Ma / bza[:, None], Mb / bzb[:, None]
    w = 0.5 * (bza + bzb)
    res = (u['method'] == 'residual').values
    if res.any(): w[res] = np.minimum(w[res], w[~res].max())
    i, j = na.index(src), nb.index(dst)
    out = {}
    Pn, _ = fista(X, Y, w); out['national'] = Pn[i, j]
    num = den = 0.0
    regs = u['region'].values
    small = []
    for r in np.unique(regs):
        m = regs == r
        if m.sum() < 12: small.append(m); continue
        Pr, _ = fista(X[m], Y[m], w[m]); num += Pr[i, j] * Ma[m, i].sum(); den += Ma[m, i].sum()
    if small:
        m = np.any(small, axis=0); Pr, _ = fista(X[m], Y[m], w[m]); num += Pr[i, j] * Ma[m, i].sum(); den += Ma[m, i].sum()
    out['regional'] = num / den
    print(f'{label:<46} one national fit {100*out["national"]:5.1f}%   per region {100*out["regional"]:5.1f}%', flush=True)

LIK, RZ = 'הליכוד', 'הציונות הדתית'
run({}, {}, LIK, RZ, 'separate parties (as on the page)')
run({'ימינה': 'ימין', RZ: 'ימין'}, {RZ: 'ימין', 'הבית היהודי': 'ימין'}, LIK, 'ימין', 'Yamina+RZ grouped as "right"')
run({'ימינה': 'ימין', RZ: 'ימין', 'תקווה חדשה': 'ימין'}, {RZ: 'ימין', 'הבית היהודי': 'ימין'}, LIK, 'ימין', 'Yamina+RZ+New Hope grouped as "right"')
