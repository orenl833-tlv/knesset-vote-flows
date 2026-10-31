"""Build simulated Knesset 26 night files from data/raw/k25.csv (for testing live_update.py).

Writes data/sim/k26_sim_<pct>.csv (UTF-8 with BOM). Party codes are relabelled to 2026 codes, noise is added,
and a seeded random <pct>% of the ordinary ballots are kept as counted; the rest get zero votes, keeping בזב.

Run:  python3 -I scripts/make_sim26.py [--pcts 30 100]
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, '..'))
SRC = os.path.join(BASE, 'data', 'raw', 'k25.csv')
DST_DIR = os.path.join(BASE, 'data', 'sim')

BASE_COLS = ['סמל ועדה', 'ברזל', 'שם ישוב', 'סמל ישוב', 'קלפי', 'ריכוז', 'שופט', 'בזב', 'מצביעים', 'פסולים', 'כשרים']
RENAME = {'מחל': 'מחל', 'פה': 'רק', 'כן': 'כן', 'ט': 'ט', 'שס': 'שס', 'ג': 'ג', 'ל': 'ל', 'עם': 'עם',
          'ום': 'ודם', 'ד': 'ודם', 'אמת': 'אמת', 'מרצ': 'אמת'}
OTHER_2026 = 'זז'
NOISE = [('מחל', 'ב', 0.05), ('רק', 'דרך', 0.03)]   # (from, to, share moved, rounded down)
SEED = 2026


def town_counted_mask(df, env, pct, seed):
    """Whole localities counted in a seeded random order (weight 1/sqrt(bzb)) until pct% of k25 bzb is counted."""
    code = df['סמל ישוב'].str.strip()
    bzb = df.loc[~env].groupby(code[~env])['בזב'].sum()
    rng = np.random.default_rng(seed)
    codes = bzb.index.values
    key = rng.exponential(1.0, size=len(codes)) * np.sqrt(bzb.values)   # small localities tend to come first
    order = codes[np.argsort(key)]
    target = pct / 100.0 * bzb.sum()
    chosen, acc = [], 0.0
    for c in order:
        if acc >= target:
            break
        chosen.append(c)
        acc += float(bzb.loc[c])
    keep = np.isin(code.values, chosen) & ~env.values
    return keep | env.values, len(chosen), acc / bzb.sum()


def build(pct, mode='ballot'):
    if not os.path.exists(SRC):
        sys.exit(f'make_sim26: source not found: {SRC}')
    df = pd.read_csv(SRC, dtype=str, encoding='utf-8-sig', keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    df = df[[c for c in df.columns if c and not c.startswith('Unnamed')]]
    missing = [c for c in BASE_COLS if c not in df.columns]
    if missing:
        sys.exit(f'make_sim26: k25 is missing columns {missing}')
    party_src = [c for c in df.columns if c not in BASE_COLS]
    for c in BASE_COLS[7:] + party_src:
        df[c] = pd.to_numeric(df[c], errors='raise').astype(np.int64)
    n = len(df)
    env = (df['סמל ישוב'].str.strip() == '9999') | (df['בזב'] == 0)
    # relabel and sum
    out = pd.DataFrame({c: df[c] for c in BASE_COLS})
    new = {}
    for c in party_src:
        code = RENAME.get(c, OTHER_2026)
        new[code] = new.get(code, 0) + df[c]
    # noise: move a share (rounded down) from one 2026 code to another, per ballot
    for src, dst, share in NOISE:
        if src in new:
            move = np.floor(share * new[src]).astype(np.int64)
            new[src] = new[src] - move
            new[dst] = new.get(dst, 0) + move
    for code in new:
        out[code] = new[code]
    party_cols = list(new.keys())
    if mode == 'growth':
        # every locality grows by its own factor in [1.00, 1.25] (bzb and votes; party sums kept consistent)
        rng_g = np.random.default_rng(SEED + 2000)
        codes_u = sorted(set(df.loc[~env, 'סמל ישוב'].str.strip()))
        fac = dict(zip(codes_u, rng_g.uniform(1.0, 1.25, size=len(codes_u))))
        f = df['סמל ישוב'].str.strip().map(fac).fillna(1.0).values
        ordn = ~env.values
        for c in ['בזב'] + [c for c in party_cols] + ['פסולים']:
            out.loc[ordn, c] = np.round(out.loc[ordn, c].values * f[ordn]).astype(np.int64)
        out.loc[ordn, 'כשרים'] = out.loc[ordn, party_cols].sum(axis=1).values
        out.loc[ordn, 'מצביעים'] = out.loc[ordn, 'פסולים'].values + out.loc[ordn, 'כשרים'].values
        keep = np.ones(n, bool)
        ordinary = np.flatnonzero(~env.values)
        print(f'  growth mode: {len(codes_u)} localities scaled by factors in [1.00, 1.25]')
    elif mode == 'town':
        keep, n_loc, share = town_counted_mask(df, env, pct, SEED + 1000 + pct)
        ordinary = np.flatnonzero(~env.values)
        print(f'  town mode: {n_loc} whole localities counted, {100*share:.2f}% of k25 bzb')
    else:
        # partial count: seeded random subset of ordinary (non-envelope) ballots
        rng = np.random.default_rng(SEED + pct)
        ordinary = np.flatnonzero(~env.values)
        k = int(round(len(ordinary) * pct / 100.0))
        keep = np.zeros(n, bool)
        keep[rng.choice(ordinary, size=k, replace=False)] = True
        keep |= env.values
    zero_cols = party_cols + ['כשרים', 'מצביעים', 'פסולים']
    out.loc[~keep, zero_cols] = 0
    os.makedirs(DST_DIR, exist_ok=True)
    name = {'ballot': f'k26_sim_{pct}.csv', 'town': f'k26_sim_town{pct}.csv', 'growth': f'k26_sim_growth{pct}.csv'}[mode]
    path = os.path.join(DST_DIR, name)
    out[BASE_COLS + party_cols].to_csv(path, index=False, encoding='utf-8-sig')
    counted = int(((out['כשרים'] > 0) & ~env.values).sum())
    print(f'{path}: rows {n}, ordinary {len(ordinary)}, counted {counted} ({100*counted/len(ordinary):.1f}%), '
          f'party columns {party_cols}')
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pcts', type=int, nargs='+', default=[30, 100])
    ap.add_argument('--mode', choices=['ballot', 'town', 'growth'], default='ballot')
    args = ap.parse_args()
    for pct in args.pcts:
        if not 0 < pct <= 100:
            sys.exit(f'make_sim26: pct must be in (0, 100], got {pct}')
        build(pct, args.mode)


if __name__ == '__main__':
    main()
