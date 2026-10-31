"""Loading of raw ballot-box CSVs, CBS locality file, party mapping and category counts.

All functions are pure loaders; nothing here writes to data/raw or config.
"""
import json
import os
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.abspath(os.path.join(HERE, '..'))
RAW = os.path.join(BASE, 'data', 'raw')
CONFIG = os.path.join(BASE, 'config', 'parties.json')
OUT = os.path.join(BASE, 'out')

ELECTIONS = [19, 20, 21, 22, 23, 24, 25]
PAIRS = ['19-20', '20-21', '21-22', '22-23', '23-24', '24-25', '20-25']
PLACE_PAIRS = {'22-23', '23-24', '24-25', '25-26'}   # both elections have ריכוז (25-26: live stage)

DOUBLE_ENV_CODE = 9999          # k22-25 double envelopes (spec)
DOUBLE_ENV_NAME = 'מעטפות חיצוניות'  # name of the envelope pseudo-locality in every year
OTHER = 'אחרים'
DNV = 'לא הצביעו'


def load_config():
    with open(CONFIG, encoding='utf-8') as f:
        return json.load(f)


def load_cbs():
    """CBS locality table indexed by int code. Columns: name, district, dat, form."""
    with open(os.path.join(RAW, 'bycode2023.json'), encoding='utf-8') as f:
        recs = json.load(f)['result']['records']
    cb = pd.DataFrame(recs)
    out = pd.DataFrame({
        'code': cb['סמל יישוב'].astype(int),
        'name': cb['שם יישוב'].astype(str).str.strip(),
        'district': cb['שם מחוז'].astype(str).str.strip(),
        'dat': pd.to_numeric(cb['דת יישוב'], errors='coerce'),
        'form': pd.to_numeric(cb['צורת יישוב שוטפת - ארעי'], errors='coerce'),
    })
    if out['code'].duplicated().any():
        raise ValueError('CBS file has duplicate locality codes')
    return out.set_index('code')


def druze_codes(cfg, cbs):
    """Map the Druze / Druze-mixed locality names in the config to CBS codes (exact name match)."""
    name_to_code = {n: c for c, n in cbs['name'].items()}
    res = {}
    for key in ('druze_localities', 'druze_mixed_localities'):
        codes = set()
        for nm in cfg[key]:
            if nm not in name_to_code:
                raise ValueError(f'{key}: name not found in CBS file: {nm!r}')
            codes.add(int(name_to_code[nm]))
        res[key] = codes
    return res['druze_localities'], res['druze_mixed_localities']


@dataclass
class Election:
    year: int
    df: pd.DataFrame            # modelled ballot boxes (double envelopes removed)
    cats: list                  # display names of categories, last two are אחרים, לא הצביעו
    fam: dict                   # display name -> colour family
    cat_cols: list              # column names in df holding category counts (same order as cats)
    haredi_codes: list
    arab_codes: list
    dbl_rows: pd.DataFrame      # excluded double-envelope rows, one per excluded box
    raw_rows: int = 0
    party_cols_unlisted: list = field(default_factory=list)


def _read_csv(year):
    path = os.path.join(RAW, f'k{year}.csv')
    df = pd.read_csv(path, dtype=str, encoding='utf-8', keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    df = df[[c for c in df.columns if c and not c.startswith('Unnamed')]]
    df['סמל ישוב'] = df['סמל ישוב'].str.strip()
    df['שם ישוב'] = df['שם ישוב'].str.strip()
    return df


def load_election(year, cfg=None):
    """Load one election. Returns Election with ballot-level numeric columns and category counts.

    Category counts per box: listed party codes -> display name, unlisted codes -> אחרים,
    לא הצביעו = בזב - כשרים (includes invalid ballots).
    """
    cfg = cfg or load_config()
    ycfg = cfg['elections'][str(year)]['parties']
    ballot_col = 'מספר קלפי' if year <= 21 else 'קלפי'
    raw = _read_csv(year)
    n_raw = len(raw)

    if year >= 22 and 'ריכוז' not in raw.columns:
        raise ValueError(f'k{year}: ריכוז missing')
    if year <= 21 and 'ריכוז' in raw.columns:
        raise ValueError(f'k{year}: unexpected ריכוז column')

    base_cols = ['שם ישוב', 'סמל ישוב', ballot_col, 'בזב', 'מצביעים', 'פסולים', 'כשרים']
    extra = ['ריכוז'] if year >= 22 else []
    meta_cols = set(base_cols + extra + ['ברזל', 'סמל ועדה', 'שופט', 'חיצוניות', 'קלפי אחרת'])
    party_cols = [c for c in raw.columns if c not in meta_cols]

    missing_cfg = [c for c in ycfg if c not in party_cols]
    if missing_cfg:
        raise ValueError(f'k{year}: configured codes not in CSV: {missing_cfg}')

    for c in ['בזב', 'מצביעים', 'פסולים', 'כשרים'] + party_cols:
        raw[c] = pd.to_numeric(raw[c], errors='raise').astype(np.int64)

    # consistency: party columns sum to valid votes
    if not (raw[party_cols].sum(axis=1) == raw['כשרים']).all():
        raise ValueError(f'k{year}: party columns do not sum to כשרים')

    raw['code'] = raw['סמל ישוב'].astype(int)
    raw['bnum'] = raw[ballot_col].astype(float).round(6)
    raw['place'] = raw['ריכוז'].str.strip() if year >= 22 else ''

    dbl = (raw['code'] == DOUBLE_ENV_CODE) | (raw['שם ישוב'] == DOUBLE_ENV_NAME)
    dbl_rows = raw.loc[dbl, ['code', 'שם ישוב', 'בזב', 'מצביעים', 'כשרים']].rename(
        columns={'שם ישוב': 'name', 'בזב': 'bzb', 'מצביעים': 'mtz', 'כשרים': 'val'})
    dbl_rows = dbl_rows.assign(year=year)
    main = raw.loc[~dbl].copy()

    # category display names and counts
    listed = {}
    fam = {OTHER: 'other', DNV: 'dnv'}
    for code, (name, family) in ycfg.items():
        listed.setdefault(name, []).append(code)
        fam[name] = family
    unlisted = [c for c in party_cols if c not in ycfg]
    cats = list(dict.fromkeys(name for name in (ycfg[c][0] for c in ycfg if c in party_cols)))
    cats = cats + [OTHER, DNV]
    cat_cols = [f'c{i}' for i in range(len(cats))]

    counts = {}
    for name, codes in listed.items():
        counts[name] = main[codes].sum(axis=1)
    counts[OTHER] = main[unlisted].sum(axis=1) if unlisted else 0 * main['כשרים']
    counts[DNV] = main['בזב'] - main['כשרים']
    for col, name in zip(cat_cols, cats):
        main[col] = counts[name]

    hcodes = cfg['sector_parties']['haredi'][str(year)]
    acodes = cfg['sector_parties']['arab'][str(year)]
    for c in hcodes + acodes:
        if c not in party_cols:
            raise ValueError(f'k{year}: sector code {c} not in CSV')
    main['hv'] = main[hcodes].sum(axis=1)
    main['rv'] = main[acodes].sum(axis=1)

    df = pd.DataFrame({
        'year': year,
        'code': main['code'].values,
        'name': main['שם ישוב'].values,
        'place': main['place'].values,
        'bnum': main['bnum'].values,
        'bzb': main['בזב'].values,
        'mtz': main['מצביעים'].values,
        'val': main['כשרים'].values,
        'hv': main['hv'].values,
        'rv': main['rv'].values,
    })
    for col in cat_cols:
        df[col] = main[col].values
    df['floor'] = np.floor(df['bnum']).astype(int)
    df = df.reset_index(drop=True)

    # sanity: categories add up to bzb
    cat_sum = df[cat_cols].sum(axis=1)
    if not (cat_sum == df['bzb']).all():
        raise ValueError(f'k{year}: category counts do not sum to bzb')

    return Election(year=year, df=df, cats=cats, fam=fam, cat_cols=cat_cols,
                    haredi_codes=hcodes, arab_codes=acodes, dbl_rows=dbl_rows,
                    raw_rows=n_raw, party_cols_unlisted=unlisted)


def load_all(cfg=None):
    cfg = cfg or load_config()
    return {y: load_election(y, cfg) for y in ELECTIONS}


def fam_of(name, fam):
    return fam.get(name, 'other')


def ensure_out():
    os.makedirs(OUT, exist_ok=True)


def add_scripts_to_path():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
