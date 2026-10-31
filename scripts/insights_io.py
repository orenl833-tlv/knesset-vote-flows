"""Prepare the per-city facts for wording (llm_facts.json) and validate the worded findings against them.

  python3 -I scripts/insights_io.py prepare
  python3 -I scripts/insights_io.py check out/insights_auto.json

The check fails any text that contains a number not present in that city's facts.
"""
import json, os, re, sys

OUT = os.path.join(os.path.dirname(__file__), '..', 'out')
MAJOR = {'3000', '5000', '4000', '9000'}


def prepare():
    facts = json.load(open(os.path.join(OUT, 'insight_facts.json')))
    out = {}
    for cid, v in facts.items():
        if cid in MAJOR or not v['facts']:
            continue
        out[cid] = {'city': v['name'], 'facts': [{
            'from_year': f['from_year'], 'to_year': f['to_year'], 'from_party': f['src'], 'to_party': f['dst'],
            'votes': f"{f['votes']:,}", 'rate_pct': round(f['rate']), 'interval_pct': [round(f['lo']), round(f['hi'])],
            'national_rate_pct': round(f['national_rate']) if f.get('national_rate') is not None else None,
            'kind': f['kind']} for f in v['facts']]}
    json.dump(out, open(os.path.join(OUT, 'llm_facts.json'), 'w'), ensure_ascii=False, indent=1)
    print(len(out), 'cities to word')


def allowed_numbers(city):
    nums = set()
    for f in city['facts']:
        nums.update([f['votes'], str(f['rate_pct']), *map(str, f['interval_pct'])])
        if f['national_rate_pct'] is not None:
            nums.add(str(f['national_rate_pct']))
        for y in (f['from_year'], f['to_year']):
            nums.update(re.findall(r'\d+', y))
    return nums


def check(path):
    facts = json.load(open(os.path.join(OUT, 'llm_facts.json')))
    texts = json.load(open(path))
    bad = 0
    for cid, items in texts.items():
        if cid not in facts:
            print('unknown city', cid); bad += 1; continue
        ok = allowed_numbers(facts[cid])
        for it in items:
            for n in re.findall(r'\d[\d,]*', it['title'] + ' ' + it['text']):
                if n.strip(',') not in ok:
                    print(cid, facts[cid]['city'], 'number not in facts:', n, '|', it['text']); bad += 1
    missing = set(facts) - set(texts)
    if missing:
        print('missing cities:', sorted(missing)); bad += len(missing)
    print('problems:', bad)
    return bad


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        prepare()
    else:
        sys.exit(1 if check(sys.argv[2]) else 0)
