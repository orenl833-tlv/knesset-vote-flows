"""Shared pipeline: context (regions, sectors, ballot classes) and candidate units for one pair.

Used by stage1 (diagnostics) and stage2 (fits). Unit drop reasons, in order:
  'zero_valid'   : no valid votes on one side (amendment d)
  'replacement'  : population-replacement filter with threshold T
  ''             : kept
"""
import numpy as np
import pandas as pd

from common import ELECTIONS
from regions import build_regions
from matching import build_units, add_shares, replacement_mask, sector_units, sector_ballots, TOL_REPL


class Context:
    def __init__(self, cfg, elections, cbs, druze_set, mixed_set):
        self.cfg = cfg
        self.elections = elections
        self.cbs = cbs
        self.druze = druze_set
        self.mixed = mixed_set
        self.dat = cbs['dat']
        self.loc_to_region, self.region_meta, self.gaps = build_regions(elections, cbs, druze_set)
        self.region_meta = self.region_meta.set_index('region')
        self.region_list = list(self.region_meta.index)
        # ballot-level frames with region and own-election sector (for totals)
        self.frames = {}
        for y in ELECTIONS:
            d = elections[y].df
            sec = sector_ballots(d, self.dat, druze_set, mixed_set)
            f = d.assign(region=d['code'].map(self.loc_to_region), sector=sec)
            self.frames[y] = f


def build_pair(ctx, pair, T=TOL_REPL):
    """Candidate units for pair 'a-b' with region, sector, and drop reason. Returns dict."""
    ya, yb = (int(p) for p in pair.split('-'))
    a, b = ctx.elections[ya], ctx.elections[yb]
    units, drops, A, B = build_units(a, b, pair)
    units = add_shares(units)
    units['region'] = units['code'].map(ctx.loc_to_region)
    sec = np.asarray(sector_units(units, ctx.dat, ctx.druze, ctx.mixed), dtype=object)
    res = (units['method'] == 'residual').values
    sec = np.where(res & np.isin(sec, ['haredi', 'transitional']), 'general', sec)
    units['sector'] = sec
    zero = ((units['a_val'] == 0) | (units['b_val'] == 0)).values
    keep = replacement_mask(units, T)
    units['reason'] = np.where(zero, 'zero_valid', np.where(~keep, 'replacement', ''))
    drops = drops.copy()
    drops['region'] = drops['code'].map(ctx.loc_to_region)
    return dict(pair=pair, ya=ya, yb=yb, units=units, drops=drops, T=T, A=A, B=B)
