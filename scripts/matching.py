"""Matching units between consecutive elections, the population-replacement filter and sectors.

Units are built per locality (place and number keys are locality-specific), so the result per
region equals matching per region. Region membership is applied afterwards by locality code.
"""
import numpy as np
import pandas as pd

from common import PLACE_PAIRS

TOL_PLACE = 0.08     # place-level / number-level bzb tolerance, and tolerance of the rest unit
TOL_BALLOT = 0.05    # ballot-level tolerance inside a kept place
TOL_REPL = 0.15      # population-replacement threshold T (default)
HAREDI_MIN = 0.60
ARAB_MIN_MIXED = 0.50
DRUZE_MIXED_MAX = 0.40


def _ratio_ok(bzb_a, bzb_b, tol, g=1.0):
    """|ratio / g - 1| <= tol with ratio = bzb_b / bzb_a (g = 1 is the plain rule)."""
    bzb_a = np.asarray(bzb_a, dtype=float)
    bzb_b = np.asarray(bzb_b, dtype=float)
    g = np.asarray(g, dtype=float)
    ok = bzb_a > 0
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = np.where(ok, bzb_b / np.where(ok, bzb_a, 1.0), np.nan)
    return ok & (np.abs(ratio / g - 1) <= tol)


def _growth_map(both, bzb_a='bzb_a', bzb_b='bzb_b'):
    """Per locality: median bzb ratio (k26/k25) over its shared places or groups; 1.0 with fewer than 3."""
    if len(both) == 0:
        return {}
    r = both[bzb_b].values / both[bzb_a].values
    d = pd.DataFrame({'code': both['code'].values, 'r': r})
    d = d[np.isfinite(d['r'])]
    med = d.groupby('code')['r'].median()
    cnt = d.groupby('code')['r'].size()
    return {int(c): float(med[c]) if cnt[c] >= 3 else 1.0 for c in med.index}


def _gvec(codes, gmap):
    return np.array([gmap.get(int(c), 1.0) for c in codes], dtype=float)


def _key_set(df, cols):
    return set(map(tuple, df[cols].values.tolist()))


def build_units(a, b, pair):
    """Build matching units for pair 'a-b' (a, b are Election objects).

    Returns (units, drops, A, B):
      units : one row per unit: uid, code, place, method, a_<cat...>, a_bzb, a_val, a_mtz, a_hv,
              a_rv and the same for b.
      drops : rows (code, kind) with one row per dropped candidate (kind = bzb-rule reason).
      A, B  : ballot frames with a 'uid' column (NaN when the box is in no unit).
    """
    A = a.df.copy()
    B = b.df.copy()
    A['ai'] = A.index
    B['bi'] = B.index
    A['uid'] = np.nan
    B['uid'] = np.nan
    # partial counts (live stage): B may carry a 'counted' flag. Without it every ballot counts.
    B['_cnt'] = B['counted'].values.astype(bool) if 'counted' in B.columns else True
    growth = bool(getattr(b, 'growth_adj', False))     # 25-26 growth-adjusted tolerance (live only)
    drops = []
    metas = []
    counter = [0]

    def new_ids(n):
        ids = np.arange(counter[0], counter[0] + n, dtype=float)
        counter[0] += n
        return ids

    # the place method needs ריכוז in both elections; a live file without it uses the number method
    if pair in PLACE_PAIRS and not getattr(b, 'no_place', False):
        # ---- place level (locality, ריכוז) ----------------------------------------------
        pa = A.groupby(['code', 'place'])['bzb'].sum().rename('bzb_a')
        pb = B.groupby(['code', 'place'])['bzb'].sum().rename('bzb_b')
        pm = pd.concat([pa, pb], axis=1).reset_index()
        one = pm[pm['bzb_a'].isna() | pm['bzb_b'].isna()]
        drops.append(one[['code']].assign(kind='place_unmatched'))
        both = pm.dropna(subset=['bzb_a', 'bzb_b'])
        gmap = _growth_map(both) if growth else {}
        keep = _ratio_ok(both['bzb_a'], both['bzb_b'], TOL_PLACE, _gvec(both['code'], gmap))
        drops.append(both[~keep][['code']].assign(kind='place_bzb'))
        kept = both[keep][['code', 'place']]
        kp = _key_set(kept, ['code', 'place'])
        A_k = A[np.array([k in kp for k in zip(A['code'], A['place'])], dtype=bool)]
        B_k = B[np.array([k in kp for k in zip(B['code'], B['place'])], dtype=bool)]
        # a place is 'full' when all its k26 ballots are counted (only then does its rest form a unit)
        full_keys = set(B.groupby(['code', 'place'])['_cnt'].all().loc[lambda x: x].index)

        # ballot-level units: counted k26 ballot with the same place and ballot number, bzb ratio within TOL_BALLOT
        B_kc = B_k[B_k['_cnt'].values.astype(bool)]
        mm = A_k[['ai', 'code', 'place', 'bnum', 'bzb']].merge(
            B_kc[['bi', 'code', 'place', 'bnum', 'bzb']],
            on=['code', 'place', 'bnum'], suffixes=('_a', '_b'))
        good = mm[_ratio_ok(mm['bzb_a'], mm['bzb_b'], TOL_BALLOT, _gvec(mm['code'], gmap))].reset_index(drop=True)
        ids = new_ids(len(good))
        A.loc[good['ai'].values.astype(int), 'uid'] = ids
        B.loc[good['bi'].values.astype(int), 'uid'] = ids
        metas.append(pd.DataFrame({'uid': ids, 'code': good['code'].values,
                                   'place': good['place'].values, 'method': 'place_ballot'}))

        # rest of each kept place: all leftover boxes of the place, one unit if bzb ratio ok
        used_a = set(good['ai'].astype(int))
        used_b = set(good['bi'].astype(int))
        rest_a = A_k[~A_k['ai'].isin(used_a)]
        rest_b = B_k[~B_k['bi'].isin(used_b)]
        fa_ = np.array([k in full_keys for k in zip(rest_a['code'], rest_a['place'])], dtype=bool)
        fb_ = np.array([k in full_keys for k in zip(rest_b['code'], rest_b['place'])], dtype=bool)
        rest_a = rest_a[fa_]
        rest_b = rest_b[fb_]
        ra = rest_a.groupby(['code', 'place'])['bzb'].sum().rename('bzb_a')
        rb = rest_b.groupby(['code', 'place'])['bzb'].sum().rename('bzb_b')
        rm = pd.concat([ra, rb], axis=1).reset_index()
        drops.append(rm[rm['bzb_a'].isna() | rm['bzb_b'].isna()][['code']].assign(kind='rest_unmatched'))
        rboth = rm.dropna(subset=['bzb_a', 'bzb_b'])
        rkeep = _ratio_ok(rboth['bzb_a'], rboth['bzb_b'], TOL_PLACE, _gvec(rboth['code'], gmap))
        drops.append(rboth[~rkeep][['code']].assign(kind='rest_bzb'))
        rk = rboth[rkeep][['code', 'place']].reset_index(drop=True)
        rids = new_ids(len(rk))
        rid = {k: u for k, u in zip(zip(rk['code'], rk['place']), rids)}
        sel_a = rest_a[np.array([k in rid for k in zip(rest_a['code'], rest_a['place'])], dtype=bool)]
        sel_b = rest_b[np.array([k in rid for k in zip(rest_b['code'], rest_b['place'])], dtype=bool)]
        A.loc[sel_a['ai'].values.astype(int), 'uid'] = [rid[k] for k in zip(sel_a['code'], sel_a['place'])]
        B.loc[sel_b['bi'].values.astype(int), 'uid'] = [rid[k] for k in zip(sel_b['code'], sel_b['place'])]
        metas.append(pd.DataFrame({'uid': rids, 'code': rk['code'].values,
                                   'place': rk['place'].values, 'method': 'place_rest'}))
    else:
        # ---- number level (locality, floor(ballot number)) ------------------------------
        ga = A.groupby(['code', 'floor'])['bzb'].sum().rename('bzb_a')
        gb = B.groupby(['code', 'floor'])['bzb'].sum().rename('bzb_b')
        gm = pd.concat([ga, gb], axis=1).reset_index()
        drops.append(gm[gm['bzb_a'].isna() | gm['bzb_b'].isna()][['code']].assign(kind='num_unmatched'))
        gboth = gm.dropna(subset=['bzb_a', 'bzb_b'])
        gmap_n = _growth_map(gboth) if growth else {}
        keep = _ratio_ok(gboth['bzb_a'], gboth['bzb_b'], TOL_PLACE, _gvec(gboth['code'], gmap_n))
        if 'counted' in B.columns:
            # partial counts: a unit forms only when all k26 ballots of the group are counted
            gfull = set(B.groupby(['code', 'floor'])['_cnt'].all().loc[lambda x: x].index)
            full = np.array([k in gfull for k in zip(gboth['code'], gboth['floor'])], dtype=bool)
            drops.append(gboth[keep & ~full][['code']].assign(kind='num_partial'))
            keep = keep & full
        drops.append(gboth[~keep][['code']].assign(kind='num_bzb'))
        gk = gboth[keep][['code', 'floor']].reset_index(drop=True)
        ids = new_ids(len(gk))
        gid = {k: u for k, u in zip(zip(gk['code'], gk['floor']), ids)}
        A['uid'] = [gid.get(k, np.nan) for k in zip(A['code'], A['floor'])]
        B['uid'] = [gid.get(k, np.nan) for k in zip(B['code'], B['floor'])]
        metas.append(pd.DataFrame({'uid': ids, 'code': gk['code'].values,
                                   'place': '', 'method': 'number'}))

    # ---- city residual unit: per locality, all boxes not in a matched unit (both sides) -------
    # a locality takes part in the residual only if all its k26 ballots are counted
    la = A[A['uid'].isna()]
    lb = B[B['uid'].isna()]
    if 'counted' in B.columns:
        loc_full = set(B.groupby('code')['_cnt'].all().loc[lambda x: x].index)
        la = la[la['code'].isin(loc_full)]
        lb = lb[lb['code'].isin(loc_full)]
    ra = la.groupby('code')['bzb'].sum().rename('bzb_a')
    rb = lb.groupby('code')['bzb'].sum().rename('bzb_b')
    rr = pd.concat([ra, rb], axis=1).reset_index()
    drops.append(rr[rr['bzb_a'].isna() | rr['bzb_b'].isna()][['code']].assign(kind='res_unmatched'))
    rr2 = rr.dropna(subset=['bzb_a', 'bzb_b'])
    if growth:
        # residual ratio against the locality total ratio (k26 total / k25 total, all ballots)
        ta = A.groupby('code')['bzb'].sum()
        tb = B.groupby('code')['bzb'].sum()
        loc_ratio = np.array([tb.get(c, np.nan) / ta.get(c, np.nan) for c in rr2['code']], dtype=float)
        loc_ratio = np.where(np.isfinite(loc_ratio) & (loc_ratio > 0), loc_ratio, 1.0)
        rok = _ratio_ok(rr2['bzb_a'], rr2['bzb_b'], TOL_PLACE, loc_ratio)
    else:
        rok = _ratio_ok(rr2['bzb_a'], rr2['bzb_b'], TOL_PLACE)
    drops.append(rr2[~rok][['code']].assign(kind='res_bzb'))
    rkeep = rr2[rok][['code']].reset_index(drop=True)
    rids = new_ids(len(rkeep))
    rmap = dict(zip(rkeep['code'], rids))
    sel_a = la.index[la['code'].isin(list(rmap))]
    sel_b = lb.index[lb['code'].isin(list(rmap))]
    A.loc[sel_a, 'uid'] = la.loc[sel_a, 'code'].map(rmap).values
    B.loc[sel_b, 'uid'] = lb.loc[sel_b, 'code'].map(rmap).values
    metas.append(pd.DataFrame({'uid': rids, 'code': rkeep['code'].values, 'place': '', 'method': 'residual'}))

    meta = pd.concat(metas, ignore_index=True)
    base = ['bzb', 'val', 'mtz', 'hv', 'rv']
    cols_a = a.cat_cols + base
    cols_b = b.cat_cols + base
    Ua = A[A['uid'].notna()].groupby('uid')[cols_a].sum()
    Ub = B[B['uid'].notna()].groupby('uid')[cols_b].sum()
    Ua.columns = [f'a_{c}' for c in cols_a]
    Ub.columns = [f'b_{c}' for c in cols_b]
    units = Ua.join(Ub, how='inner').reset_index()
    units = units.merge(meta, on='uid', how='inner')
    if len(units) != len(meta):
        raise RuntimeError(f'{pair}: unit count mismatch {len(units)} vs {len(meta)}')
    # the number of units per side must match the number of metas
    drops = pd.concat(drops, ignore_index=True) if drops else pd.DataFrame(columns=['code', 'kind'])
    drops = drops.assign(n=1)
    return units.sort_values('uid').reset_index(drop=True), drops, A, B


def add_shares(units):
    """h and r per side (Haredi / Arab party votes over valid votes). NaN when there are no valid votes."""
    u = units
    for s in ('a', 'b'):
        v = u[f'{s}_val'].values.astype(float)
        ok = v > 0
        with np.errstate(divide='ignore', invalid='ignore'):
            u[f'h_{s}'] = np.where(ok, u[f'{s}_hv'].values / np.where(ok, v, 1.0), np.nan)
            u[f'r_{s}'] = np.where(ok, u[f'{s}_rv'].values / np.where(ok, v, 1.0), np.nan)
    return u


def replacement_mask(units, T=TOL_REPL):
    """True for units kept by the population-replacement filter (|h_b-h_a|<=T and |r_b-r_a|<=T).

    A unit with an undefined share (no valid votes on one side) is not dropped by the comparison;
    its count is reported separately by the caller.
    """
    dh = np.abs(units['h_b'].values - units['h_a'].values)
    dr = np.abs(units['r_b'].values - units['r_a'].values)
    with np.errstate(invalid='ignore'):
        drop = (dh > T) | (dr > T)
    return ~drop


def sector_units(units, dat_by_code, druze_set, mixed_set):
    """Sector of each unit for one pair, using both elections' shares (spec order)."""
    code = units['code'].values
    dat = np.asarray(dat_by_code.reindex(code).values, dtype=float)
    is_druze = np.isin(code, list(druze_set))
    is_mixed = np.isin(code, list(mixed_set))
    h_a, h_b = units['h_a'].values, units['h_b'].values
    r_a, r_b = units['r_a'].values, units['r_b'].values
    with np.errstate(invalid='ignore'):
        hi_a, hi_b = h_a >= HAREDI_MIN, h_b >= HAREDI_MIN
        ra_hi, rb_hi = r_a >= ARAB_MIN_MIXED, r_b >= ARAB_MIN_MIXED
        r_lo_both = (r_a < DRUZE_MIXED_MAX) & (r_b < DRUZE_MIXED_MAX)
    sec = np.full(len(units), 'general', dtype=object)
    sec[hi_a ^ hi_b] = 'transitional'
    sec[hi_a & hi_b] = 'haredi'
    mixed4 = (dat == 4.0) & ra_hi & rb_hi & ~is_druze & ~is_mixed
    sec[mixed4] = 'arab'
    sec[np.isin(dat, [2.0, 3.0]) & ~is_druze] = 'arab'
    sec[is_mixed] = np.where(r_lo_both[is_mixed], 'druze', 'arab')
    sec[is_druze] = 'druze'
    return sec


def sector_ballots(df, dat_by_code, druze_set, mixed_set):
    """Ballot-level sector using only the ballot's own election shares (scaling of sector totals)."""
    code = df['code'].values
    dat = np.asarray(dat_by_code.reindex(code).values, dtype=float)
    is_druze = np.isin(code, list(druze_set))
    is_mixed = np.isin(code, list(mixed_set))
    val = df['val'].values.astype(float)
    ok = val > 0
    with np.errstate(divide='ignore', invalid='ignore'):
        h = np.where(ok, df['hv'].values / np.where(ok, val, 1.0), np.nan)
        r = np.where(ok, df['rv'].values / np.where(ok, val, 1.0), np.nan)
    sec = np.full(len(df), 'general', dtype=object)
    with np.errstate(invalid='ignore'):
        sec[h >= HAREDI_MIN] = 'haredi'
        sec[(dat == 4.0) & (r >= ARAB_MIN_MIXED)] = 'arab'
        sec[np.isin(dat, [2.0, 3.0]) & ~is_druze] = 'arab'
        sec[is_mixed] = np.where(r[is_mixed] < DRUZE_MIXED_MAX, 'druze', 'arab')
        sec[is_druze] = 'druze'
    return sec
