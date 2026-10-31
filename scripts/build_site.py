"""Assemble the publishable site in out/site from out/web, the page source and the config files."""
import json, os, re, shutil, subprocess, sys

ROOT = os.path.join(os.path.dirname(__file__), '..')
MIN_SES_ELECTORATE = 20000
WEB, SITE = os.path.join(ROOT, 'out/web'), os.path.join(ROOT, 'out/site')


ALIASES = {'סמל יישוב': 'סמל ישוב', 'שם יישוב': 'שם ישוב', 'מספר קלפי': 'קלפי', 'בעלי זכות בחירה': 'בזב',
           'קולות כשרים': 'כשרים', 'קולות פסולים': 'פסולים', 'סה"כ מצביעים': 'מצביעים', 'מקום קלפי': 'ריכוז'}


def raw_shares(files=None, only_counted=False):
    """Party shares of the valid vote per election, straight from the ballot files, for the country and each locality.

    The national figure includes the double-envelope rows, as the official results do; localities cannot.
    files maps an election to a CSV path (default: every data/raw/k<N>.csv). With only_counted, ballots without
    valid votes are left out, so a partial count gives the shares and turnout of what has been counted.
    """
    import pandas as pd
    cfg = json.load(open(os.path.join(ROOT, 'config/parties.json')))['elections']
    meta = {'סמל ועדה', 'ברזל', 'שם ישוב', 'סמל ישוב', 'קלפי', 'מספר קלפי', 'ריכוז', 'שופט', 'חיצוניות', 'קלפי אחרת', 'בזב', 'מצביעים', 'פסולים', 'כשרים'}
    out = {}
    files = files or {k: os.path.join(ROOT, f'data/raw/k{k}.csv') for k in cfg}
    for k, path in files.items():
        if not os.path.exists(path):
            continue  # the election-night file is handled by build_site_live
        e = cfg[k]
        df = pd.read_csv(path, encoding='utf-8-sig')
        df.columns = [ALIASES.get(c.strip().replace('\u00a0', ' '), c.strip()) for c in df.columns]
        df = df.loc[:, ~df.columns.str.startswith('Unnamed')]
        party = [c for c in df.columns if c not in meta]
        df[party + ['בזב', 'כשרים']] = df[party + ['בזב', 'כשרים']].apply(pd.to_numeric, errors='coerce').fillna(0)
        # a configured list missing from the file (not running, or not yet in it) simply has no share
        named = {c: n for c, (n, _) in e['parties'].items() if c in df.columns}
        df['אחרים'] = df[[c for c in party if c not in named]].sum(axis=1)
        df = df.rename(columns=named)
        cols = list(named.values()) + ['אחרים']
        if only_counted:
            df = df[df['כשרים'] > 0]
        envelope = df['בזב'] == 0
        def shares(rows, eligible):
            valid = rows['כשרים'].sum()
            sh = {n: round(rows[n].sum() / valid * 100, 2) for n in cols if valid}
            sh['לא הצביעו'] = round((eligible - valid) / eligible * 100, 2) if eligible else None
            return sh
        out.setdefault('national', {})[k] = shares(df, df['בזב'].sum())
        for code, rows in df[~envelope].groupby('סמל ישוב'):
            # turnout for a locality leaves out its residents who voted in double envelopes
            out.setdefault(str(int(code)), {})[k] = shares(rows, rows['בזב'].sum())
    return out


# "general" was unclear to readers: it means Jewish ballots that are not Haredi
RENAME = [('יהודי (חרדי + כללי)', 'יהודי (כולל חרדים)'), ('מגזר כללי', 'יהודי לא-חרדי'), ('כללי', 'יהודי לא-חרדי')]


def rename(text):
    for a, b in RENAME:
        if a in text:
            return text.replace(a, b)
    return text


def pending26():
    """The 2026 lists for the placeholder column shown before results: [name, colour family], right to left as on the seat bar."""
    parties = json.load(open(os.path.join(ROOT, 'config/parties.json')))['elections']['26']['parties']
    blocs = json.load(open(os.path.join(ROOT, 'config/blocs26.json')))
    codes = [c for b in ('bibi', 'mid', 'joint', 'raam', 'anti') for c in blocs.get(b, []) if c in parties]
    return [parties[c] for c in codes] + [['אחרים', 'other'], ['לא הצביעו', 'dnv']]


# the published page, for links that open it on one headline
SITE_URL = 'https://claude.ai/artifact/BCTFfnxbxmSaC4kxwg3AgC'


def main():
    shutil.rmtree(SITE, ignore_errors=True)
    os.makedirs(os.path.join(SITE, 'data'))
    shutil.copy(os.path.join(ROOT, 'web/index.html'), SITE)
    for f in ('index.json', 'map.json', 'ses_index.json'):
        shutil.copy(os.path.join(WEB, f), SITE)
    idx = json.load(open(os.path.join(SITE, 'index.json')))
    for a in idx:
        # the sector list uses plural group names (חרדים, ערבים, דרוזים)
        a['name'] = 'יהודים לא-חרדים' if a['id'] == 'sector:general' else rename(a['name'])
    json.dump(idx, open(os.path.join(SITE, 'index.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    shutil.copy(os.path.join(ROOT, 'config/seats.json'), SITE)
    shutil.copy(os.path.join(ROOT, 'config/turnout_hourly.json'), os.path.join(SITE, 'turnout.json'))
    insights = json.load(open(os.path.join(ROOT, 'out/insights_auto.json')))
    insights.update(json.load(open(os.path.join(ROOT, 'config/insights_major.json'))))
    json.dump(insights, open(os.path.join(SITE, 'insights.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    clamped = dropped = 0
    exact = raw_shares()
    live = set()
    for name in os.listdir(os.path.join(WEB, 'data')):
        d = json.load(open(os.path.join(WEB, 'data', name)))
        for key, p in d['pairs'].items():
            if not p:
                continue
            if d['kind'] == 'ses' and sum(x[2] for x in p['from']) < MIN_SES_ELECTORATE:
                # too few eligible voters behind this combination to show a flow chart
                d['pairs'][key] = None; dropped += 1
                continue
            for l in p['links']:
                # a few bootstrap percentiles miss the point estimate by a rounding hair; widen to include it
                if l[4] is not None and l[5] is not None and not (l[4] <= l[3] <= l[5]):
                    l[4], l[5] = min(l[4], l[3]), max(l[5], l[3]); clamped += 1
        # a colon in a published path is awkward in URLs; the page maps sector:x to sector-x
        d['name'] = 'יהודים לא-חרדים' if d['id'] == 'sector:general' else rename(d['name'])
        if d['id'] in exact:
            d['shares'] = exact[d['id']]
        if d['kind'] == 'ses':
            # "1–3" reads backwards inside right-to-left text, so spell ranges out
            d['name'] = re.sub(r'(\d+)–(\d+)', r'\1 עד \2', d['name'])
            if d['id'].endswith('g1g2g3g4'):
                d['name'] = 'כל האשכולות · ' + d['name'].split(' · ', 1)[1]
        if d['kind'] == 'ses' and any(d['pairs'].values()):
            live.add(d['id'])
        json.dump(d, open(os.path.join(SITE, 'data', name.replace(':', '-')), 'w'), ensure_ascii=False, separators=(',', ':'))
    ses = json.load(open(os.path.join(SITE, 'ses_index.json')))
    ses['available'] = [i for i in ses['available'] if i in live]
    ses['filters'] = {f: rename(v) for f, v in ses['filters'].items()}
    ses['groups'] = {g: re.sub(r'(\d+)–(\d+)', r'\1 עד \2', v) for g, v in ses['groups'].items()}
    json.dump(ses, open(os.path.join(SITE, 'ses_index.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print('ses pairs hidden for small electorate:', dropped, '; ses areas available:', len(ses['available']))
    size = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(SITE) for f in fs)
    print('site files:', sum(len(fs) for _, _, fs in os.walk(SITE)), 'size', round(size / 1e6, 2), 'MB; intervals widened:', clamped)
    if not os.path.exists(os.path.join(SITE, 'site.json')):
        json.dump({'url': SITE_URL, 'pending26': pending26()}, open(os.path.join(SITE, 'site.json'), 'w'), ensure_ascii=False)
    # the headline cards read their numbers from the files just written
    subprocess.run([sys.executable, '-I', os.path.join(ROOT, 'scripts', 'headlines.py'), SITE], check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
