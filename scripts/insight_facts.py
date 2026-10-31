"""Pick 3-4 notable, well-identified flows per city from out/web/data and write out/insight_facts.json.

Only flows whose 90% interval is reasonably narrow are eligible, so a finding is never built on noise.
The facts carry every number a finding may quote; the wording step may not add numbers of its own.
"""
import json, os, sys
import pandas as pd

BASE = os.path.join(os.path.dirname(__file__), '..', 'out', 'web')
YEARS = {'19': '2013', '20': '2015', '21': 'אפריל 2019', '22': 'ספטמבר 2019', '23': '2020', '24': '2021', '25': '2022'}
PAIRS = ['19-20', '20-21', '21-22', '22-23', '23-24', '24-25', '20-25']
MAX_CI = 25.0          # widest acceptable 90% interval, in percentage points
MIN_SHARE = 0.01       # a flow must move at least 1% of the city's eligible voters
MIN_DIFF = 10.0        # city rate must differ from the national rate by this much to count as distinctive
# lists that ran together in the later election; their flow is the merger itself, not a finding
MERGERS = {
    ('20-21', 'יש עתיד', 'כחול לבן'), ('21-22', 'חד"ש-תע"ל', 'הרשימה המשותפת'), ('21-22', 'רע"מ-בל"ד', 'הרשימה המשותפת'),
    ('21-22', 'כולנו', 'הליכוד'), ('21-22', 'איחוד מפלגות הימין', 'ימינה'), ('21-22', 'גשר', 'העבודה-גשר'),
    ('22-23', 'המחנה הדמוקרטי', 'העבודה-גשר-מרצ'), ('24-25', 'תקווה חדשה', 'המחנה הממלכתי'),
}
MAX_DEV = 10.0         # skip a pair when the city's modelled totals miss its actual totals by more than this (%)
MIN_COVERAGE = 40.0    # skip a pair when less than this share of the electorate is in matched units


def pct(x):
    # coverage arrives either as a fraction or as a percentage
    return x * 100 if x <= 1 else x


def flows(pair):
    out = {}
    for i, j, v, rate, lo, hi in pair['links']:
        s, t = pair['from'][i], pair['to'][j]
        out[(s[0], t[0])] = dict(src=s[0], dst=t[0], src_fam=s[1], dst_fam=t[1], votes=v, rate=rate, lo=lo, hi=hi,
                                 src_total=s[2])
    return out


def candidates(city, national, sanity):
    first = next((p for p in city['pairs'].values() if p), None)
    if first is None:
        return []
    eligible = sum(x[2] for x in first['from'])
    cands = []
    for key in PAIRS:
        p, n = city['pairs'].get(key), national['pairs'].get(key)
        if not p or sanity.get((city['id'], key), 999) > MAX_DEV or pct(p.get('coverage_core', p['coverage'])) < MIN_COVERAGE:
            continue
        a, b = key.split('-')
        nat = flows(n) if n else {}
        for f in flows(p).values():
            if f['lo'] is None or f['hi'] - f['lo'] > MAX_CI or f['votes'] < MIN_SHARE * eligible:
                continue
            base = dict(pair=key, from_year=YEARS[a], to_year=YEARS[b], coverage_pct=round(pct(p.get('coverage_core', p['coverage'])), 0), **f)
            nf = nat.get((f['src'], f['dst']))
            if nf:
                base['national_rate'] = nf['rate']
            # the same colour family across elections is the same party under a new name or list
            stay = f['src'] == f['dst'] or f['src_fam'] == f['dst_fam']
            if f['src_fam'] == 'dnv' and f['dst_fam'] == 'dnv':
                continue
            if stay:
                # weak loyalty is a finding; strong loyalty is the default and is not
                if f['src_fam'] not in ('other', 'dnv') and nf and nf['rate'] - f['rate'] >= MIN_DIFF and f['hi'] < nf['rate']:
                    cands.append(dict(kind='low_retention', score=(nf['rate'] - f['rate']) * f['src_total'] / eligible, **base))
                continue
            if 'other' in (f['src_fam'], f['dst_fam']) or (key, f['src'], f['dst']) in MERGERS:
                continue
            kind = 'turnout' if 'dnv' in (f['src_fam'], f['dst_fam']) else 'switch'
            score = f['votes'] / eligible * 100
            if nf and abs(f['rate'] - nf['rate']) >= MIN_DIFF and not (f['lo'] <= nf['rate'] <= f['hi']):
                kind += '_distinct'
                score *= 1.5
            cands.append(dict(kind=kind, score=score, **base))
    return cands


def pick(cands, k=4):
    chosen, per_pair = [], {}
    for c in sorted(cands, key=lambda c: -c['score']):
        if per_pair.get(c['pair'], 0) >= 2:
            continue
        if any(c['src'] == x['src'] and c['dst'] == x['dst'] for x in chosen):
            continue
        # a flow that matches the national pattern says little about the city, so allow only one
        if not c['kind'].endswith('_distinct') and c['kind'] != 'low_retention' and \
                any(not x['kind'].endswith('_distinct') and x['kind'] != 'low_retention' for x in chosen):
            continue
        chosen.append(c)
        per_pair[c['pair']] = per_pair.get(c['pair'], 0) + 1
        if len(chosen) == k:
            break
    return sorted(chosen, key=lambda c: PAIRS.index(c['pair']))


def main():
    index = json.load(open(os.path.join(BASE, 'index.json')))
    national = json.load(open(os.path.join(BASE, 'data', 'national.json')))
    # the bootstrap interval misses specification error; the gap between modelled and actual totals shows it
    s = pd.read_csv(os.path.join(BASE, '..', 'sanity.csv'))
    s = s[s['qualifies'] & s['fit'].str.startswith('region:')]
    sanity = {(f.split(':', 1)[1], pair): v for (f, pair), v in s.groupby(['fit', 'pair'])['pct_dev'].apply(lambda x: x.abs().max()).items()}
    out = {}
    for a in index:
        if a['kind'] != 'city':
            continue
        city = json.load(open(os.path.join(BASE, 'data', f"{a['id']}.json")))
        facts = pick(candidates(city, national, sanity))
        for f in facts:
            f.pop('score'); f.pop('src_fam'); f.pop('dst_fam')
            f['votes'] = int(round(f['votes'], -1))
        out[a['id']] = dict(name=a['name'], facts=facts)
    path = os.path.join(BASE, '..', 'insight_facts.json')
    json.dump(out, open(path, 'w'), ensure_ascii=False, indent=1)
    print(len(out), 'cities;', sum(1 for v in out.values() if len(v['facts']) < 2), 'with fewer than 2 facts')


if __name__ == '__main__':
    main()
