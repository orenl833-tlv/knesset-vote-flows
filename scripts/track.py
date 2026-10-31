"""Track how the national 2022-2026 flows move as the count goes on, so we know when they have settled.

Appends every national link of this run to out/live/history.csv, then prints, for today's 12 largest
cross-list flows, the change in rate since the previous run and since the run one hour earlier.
"""
import csv, datetime as dt, json, os

ROOT = os.path.join(os.path.dirname(__file__), '..')
WEB = os.path.join(ROOT, 'out/live/web')
HIST = os.path.join(ROOT, 'out/live/history.csv')


def main():
    live = json.load(open(os.path.join(WEB, 'live.json')))
    nat = json.load(open(os.path.join(WEB, 'data/national.json')))['pairs']['25-26']
    t = live['updated_utc']
    rows = [[t, live.get('counted_share_national'), nat['from'][i][0], nat['to'][j][0], v, r]
            for i, j, v, r, lo, hi in nat['links']]
    fresh = not os.path.exists(HIST)
    with open(HIST, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if fresh:
            w.writerow(['updated_utc', 'counted_share', 'from', 'to', 'votes', 'rate'])
        w.writerows(rows)
    hist = list(csv.DictReader(open(HIST, encoding='utf-8')))
    times = sorted({h['updated_utc'] for h in hist})
    when = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    prev = times[-2] if len(times) > 1 else None
    hour = max((x for x in times if when(x) <= when(t) - dt.timedelta(hours=1)), default=None)
    rate = lambda tt: {(h['from'], h['to']): float(h['rate']) for h in hist if h['updated_utc'] == tt}
    now, p, hr = rate(t), rate(prev) if prev else {}, rate(hour) if hour else {}
    cross = sorted([r for r in rows if r[2] != r[3] and not (r[2] == 'לא הצביעו' and r[3] == 'לא הצביעו')], key=lambda r: -r[4])[:12]
    print(f'stability, counted share {live.get("counted_share_national")}: change in rate (points) since previous run / since an hour ago')
    for r in cross:
        k = (r[2], r[3])
        d1 = f'{now[k] - p[k]:+.1f}' if k in p else 'new'
        d2 = f'{now[k] - hr[k]:+.1f}' if k in hr else '—'
        print(f'  {r[2]} -> {r[3]}: {now[k]:.1f}%  ({d1} / {d2})')


if __name__ == '__main__':
    main()
