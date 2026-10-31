"""Model inputs for one fit: category selection (3% rule, cap on categories), folding, X, Y, weights."""
import numpy as np

from common import OTHER, DNV, load_config

MIN_SHARE = 0.03
MIN_SHARE_ALWAYS = 0.005
# lists that skip the 3% rule (config always_kept), by display name; they still fold under the cap
_cfg = load_config()
ALWAYS = {_cfg['elections'][k]['parties'][c][0] for k, codes in _cfg.get('always_kept', {}).items() for c in codes}


def kept_parties(M, names, n_units, val_total):
    """Party display names kept as own categories for one side of a unit set.

    A party is kept if it has >= 3% of the valid votes of the units in this election, or is in ALWAYS and has
    >= 0.5% there (below that its column is mostly noise). Then, while
    k = kept + 2 (אחרים, לא הצביעו) exceeds max(4, floor(n/4)), the smallest kept party is folded.
    """
    names = list(names)
    totals = M.sum(axis=0)
    party = [i for i, nm in enumerate(names) if nm not in (OTHER, DNV)]
    kept = [i for i in party if totals[i] / val_total >= MIN_SHARE or (names[i] in ALWAYS and totals[i] / val_total >= MIN_SHARE_ALWAYS)]
    cap = max(4, n_units // 4)
    while len(kept) + 2 > cap and kept:
        kept.remove(min(kept, key=lambda i: totals[i]))
    return [names[i] for i in kept]


def fold(M, names, kept_names):
    """Fold categories onto kept party names + אחרים + לא הצביעו. Returns (counts matrix, names)."""
    names = list(names)
    idx = {n: i for i, n in enumerate(names)}
    cols = [M[:, idx[n]] for n in kept_names]
    other = M[:, idx[OTHER]].copy()
    for i, nm in enumerate(names):
        if nm not in kept_names and nm not in (OTHER, DNV):
            other = other + M[:, i]
    cols += [other, M[:, idx[DNV]]]
    return np.column_stack(cols), list(kept_names) + [OTHER, DNV]


def fit_inputs(units, a, b, kept_a=None, kept_b=None):
    """Build (X, Y, w, names_x, names_y, kept_a, kept_b) for a set of units from pair a->b.

    If kept_a / kept_b are given they are used as-is (bootstrap, sensitivity); otherwise selected here.
    """
    n = len(units)
    if n == 0:
        raise ValueError('no units')
    bzb_a = units['a_bzb'].values.astype(float)
    bzb_b = units['b_bzb'].values.astype(float)
    Ma = units[[f'a_{c}' for c in a.cat_cols]].values.astype(float)
    Mb = units[[f'b_{c}' for c in b.cat_cols]].values.astype(float)
    if kept_a is None:
        kept_a = kept_parties(Ma, a.cats, n, units['a_val'].sum())
    if kept_b is None:
        kept_b = kept_parties(Mb, b.cats, n, units['b_val'].sum())
    Mx, nx = fold(Ma, a.cats, kept_a)
    My, ny = fold(Mb, b.cats, kept_b)
    X = Mx / bzb_a[:, None]
    Y = My / bzb_b[:, None]
    w = 0.5 * (bzb_a + bzb_b)
    # residual units are capped at the largest weight of a non-residual unit in the same fit
    # (weight 1 if the fit has no non-residual unit); the cap carries into the bootstrap
    if 'method' in units.columns:
        res = (units['method'] == 'residual').values
        if res.any():
            if (~res).any():
                cap = w[~res].max()
            else:
                cap = 1.0
            w = w.copy()
            w[res] = np.minimum(w[res], cap)
    return X, Y, w, nx, ny, kept_a, kept_b
