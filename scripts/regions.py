"""Region definitions.

Large localities (k25 boxes >= 20) are their own regions. Other localities go to clusters keyed by
district x type. A cluster with < 25 k25 boxes merges into the national cluster of its type; then any
region (national cluster or unknown) with < 25 k25 boxes merges into `misc`.
Membership is fixed by locality code and identical for every pair.
"""
import pandas as pd

from common import ELECTIONS

LARGE_MIN_BOXES = 20      # k25 ballot boxes for a locality to be its own region
CLUSTER_MIN_BOXES = 25    # k25 boxes below which a cluster region merges (see above)
URBAN_FORM_MAX = 300      # form code below this is urban
MISC = 'misc'


def locality_type(code, cbs, druze_set):
    """Type of a locality by the CBS / druze rules. Returns (type, district); type 'unknown' if undetermined."""
    if code not in cbs.index:
        return 'unknown', None
    row = cbs.loc[code]
    if code in druze_set:
        return 'druze', row['district']
    dat = row['dat']
    if pd.isna(dat):
        return 'unknown', row['district']
    if dat in (2, 3):
        return 'arab', row['district']
    if dat in (1, 4):
        return ('jewish_urban' if row['form'] < URBAN_FORM_MAX else 'jewish_rural'), row['district']
    return 'unknown', row['district']


def build_regions(elections, cbs, druze_set):
    """Return (loc_to_region: dict code -> region id, meta: DataFrame, gaps: dict)."""
    boxes25 = elections[25].df.groupby('code').size()
    all_codes = set()
    names = {}
    for y in ELECTIONS:
        d = elections[y].df
        all_codes |= set(d['code'].unique())
        for c, n in d.groupby('code')['name'].first().items():
            names.setdefault(c, n)

    loc_to_region, meta = {}, []
    members = {}          # region id -> list of codes (cluster-type regions)
    rtype = {}            # region id -> type
    rdistrict = {}
    cluster_key = {}      # code -> (district, type) or ('unknown',)
    cluster_boxes = {}
    for code in sorted(all_codes):
        nb = int(boxes25.get(code, 0))
        if nb >= LARGE_MIN_BOXES:
            rid = str(code)
            loc_to_region[code] = rid
            name = cbs.loc[code, 'name'] if code in cbs.index else names[code]
            typ, district = locality_type(code, cbs, druze_set)
            if typ == 'unknown':
                typ = 'jewish_urban'   # large locality without CBS type: flagged in stage1 summary
            meta.append(dict(region=rid, name=name, kind='large', type=typ,
                             district=district or '', k25_boxes=nb, n_localities=1))
            continue
        typ, district = locality_type(code, cbs, druze_set)
        key = ('unknown',) if typ == 'unknown' else (district, typ)
        cluster_key[code] = key
        cluster_boxes[key] = cluster_boxes.get(key, 0) + nb

    # stage A: cluster < 25 boxes -> national cluster of its type (unknown is not a type)
    def rid_of_key(key):
        if key == ('unknown',):
            return 'unknown'
        district, typ = key
        if cluster_boxes[key] < CLUSTER_MIN_BOXES:
            return f'national|{typ}'
        return f'{district}|{typ}'

    region_boxes = {}
    key_rid = {k: rid_of_key(k) for k in cluster_boxes}
    for k, rid in key_rid.items():
        region_boxes[rid] = region_boxes.get(rid, 0) + cluster_boxes[k]
    # stage B: any region (national cluster or unknown) < 25 boxes -> misc
    small = {rid for rid, nb in region_boxes.items() if nb < CLUSTER_MIN_BOXES}
    final_rid = {}
    for k, rid in key_rid.items():
        final_rid[k] = MISC if rid in small else rid
    for code, k in cluster_key.items():
        loc_to_region[code] = final_rid[k]
        members.setdefault(final_rid[k], []).append(code)
    for rid, codes in members.items():
        boxes = sum(int(boxes25.get(c, 0)) for c in codes)
        if rid == MISC:
            typ, district, kind = 'jewish_urban', 'misc', 'misc'
        elif rid == 'unknown':
            typ, district, kind = 'unknown', '', 'unknown'
        elif rid.startswith('national|'):
            typ, district, kind = rid.split('|', 1)[1], 'national', 'national_cluster'
        else:
            district, typ = rid.split('|', 1)
            kind = 'cluster'
        meta.append(dict(region=rid, name=rid, kind=kind, type=typ, district=district,
                         k25_boxes=boxes, n_localities=len(codes)))
    meta = pd.DataFrame(meta)
    missing_cbs = [c for c in sorted(all_codes) if c not in cbs.index]
    nan_dat = [c for c in sorted(all_codes) if c in cbs.index and pd.isna(cbs.loc[c, 'dat'])]
    gaps = dict(missing_cbs=missing_cbs, nan_dat=nan_dat, names=names)
    return loc_to_region, meta, gaps
