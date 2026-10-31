#!/usr/bin/env python3
"""Knesset seats from a per-ballot results file, by the Bader-Ofer method with surplus-vote agreements.

    python3 -I elections/live/seats.py                       # Knesset 26 from elections/live/k26/latest.csv
    python3 -I elections/live/seats.py --knesset 25 --file elections/data/raw/k25.csv   # check against 2022

Rules (Knesset Elections Law):
  * lists below the threshold (3.25% of valid votes) get nothing;
  * the general quota is the passing lists' votes divided by 120, and each list first gets floor(votes / quota);
  * remaining seats go one at a time to the unit with the largest votes / (seats + 1), where two passing lists
    with a surplus agreement form one unit;
  * a unit's seats are then split between its two lists the same way.
Double-envelope rows are counted, as in the official result.
"""
import argparse, csv, io, json, os

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
THRESHOLD = 0.0325   # electoral threshold, share of the valid votes
META = {'סמל ועדה', 'ברזל', 'שם ישוב', 'סמל ישוב', 'קלפי', 'מספר קלפי', 'ריכוז', 'שופט', 'חיצוניות', 'קלפי אחרת', 'בזב', 'מצביעים', 'פסולים', 'כשרים'}


def totals(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp1255'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    rows = csv.reader(io.StringIO(text))
    head = [h.strip() for h in next(rows)]
    sums = [0] * len(head)
    for r in rows:
        for i, v in enumerate(r[:len(head)]):
            try:
                sums[i] += int(float(v or 0))
            except ValueError:
                pass
    t = {h: s for h, s in zip(head, sums) if h and h not in META and not h.startswith('Unnamed')}
    return t, sums[head.index('כשרים')], sums[head.index('בזב')]


def dhondt(votes, seats, start):
    """Hand out `seats` one at a time by largest votes / (current + 1)."""
    have = dict(start)
    for _ in range(seats):
        best = max(votes, key=lambda k: (votes[k] / (have[k] + 1), votes[k]))
        have[best] += 1
    return have


def quota(votes, valid, threshold=THRESHOLD, total=120):
    """Votes per seat: the votes of the lists that pass the threshold, over the seats."""
    return sum(v for v in votes.values() if v >= threshold * valid) / total


def allocate(votes, valid, agreements, threshold=THRESHOLD, total=120):
    passing = {k: v for k, v in votes.items() if v >= threshold * valid}
    quota = sum(passing.values()) / total
    base = {k: int(v // quota) for k, v in passing.items()}
    # units: agreement pairs where both lists pass, otherwise the list alone
    unit_of = {k: k for k in passing}
    for a, b in agreements:
        if a in passing and b in passing:
            unit_of[a] = unit_of[b] = f'{a}+{b}'
    uvotes, ubase = {}, {}
    for k, u in unit_of.items():
        uvotes[u] = uvotes.get(u, 0) + passing[k]
        ubase[u] = ubase.get(u, 0) + base[k]
    useats = dhondt(uvotes, total - sum(base.values()), ubase)
    seats = {}
    for u, n in useats.items():
        members = [k for k in passing if unit_of[k] == u]
        if len(members) == 1:
            seats[members[0]] = n
        else:
            seats.update(dhondt({k: passing[k] for k in members}, n, {k: 0 for k in members}))
    return seats


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--knesset', default='26')
    p.add_argument('--file')
    p.add_argument('--out', help='write the result as JSON here')
    a = p.parse_args()
    cfg = json.load(open(os.path.join(ROOT, 'config/parties.json')))
    agreements = json.load(open(os.path.join(ROOT, 'config/surplus_agreements.json')))[a.knesset]
    path = a.file or os.path.join(ROOT, f'live/k{a.knesset}/latest.csv')
    votes, valid, eligible = totals(path)
    seats = allocate(votes, valid, agreements)
    names = cfg['elections'][a.knesset]['parties']
    rows = sorted(({'code': k, 'name': names.get(k, [k])[0], 'family': names.get(k, [None, 'other'])[1],
                    'votes': v, 'pct': round(v / valid * 100, 2), 'seats': seats.get(k, 0)} for k, v in votes.items()),
                  key=lambda r: -r['votes'])
    for r in rows[:20]:
        print(f"{r['name']:<22} {r['votes']:>9,} {r['pct']:>6.2f}% {r['seats']:>3}")
    print('valid', f'{valid:,}', 'turnout', f'{valid / eligible:.1%}' if eligible else '', 'seats', sum(seats.values()))
    if a.out:
        json.dump({'valid': valid, 'eligible': eligible, 'lists': rows}, open(a.out, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
