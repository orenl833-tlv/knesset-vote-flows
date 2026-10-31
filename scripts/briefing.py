"""Morning briefing for the 2022 to 2026 transfer: the numbers to write the analysis from, in one Markdown file.

    python3 -I scripts/briefing.py [--pair 25-26] [--web out/live/web] [--out out/live/briefing.md]

Sections: count status; national flows; where each 2026 list's voters came from; how each 2022 list kept its
voters; sectors; socioeconomic groups (all ballots and Jewish non-Haredi); the 20 largest localities against the
national rate. Every rate comes with its 90% interval when the run had a bootstrap.
"""
import argparse, json, os

ROOT = os.path.join(os.path.dirname(__file__), '..')


def flows(p):
    out = []
    for i, j, v, r, lo, hi in p['links']:
        s, t = p['from'][i], p['to'][j]
        out.append(dict(src=s[0], dst=t[0], sf=s[1], tf=t[1], votes=v, rate=r, lo=lo, hi=hi, src_total=s[2]))
    return out


def ci(f):
    return f' [{f["lo"]:.0f}–{f["hi"]:.0f}]' if f['lo'] is not None else ''


def table(rows, head):
    lines = ['| ' + ' | '.join(head) + ' |', '|' + '---|' * len(head)]
    lines += ['| ' + ' | '.join(str(c) for c in r) + ' |' for r in rows]
    return '\n'.join(lines)


def cross(fl, n=12):
    keep = [f for f in fl if f['src'] != f['dst'] and not (f['sf'] == 'dnv' and f['tf'] == 'dnv')]
    return sorted(keep, key=lambda f: -f['votes'])[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pair', default='25-26')
    ap.add_argument('--web', default=os.path.join(ROOT, 'out/live/web'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'out/live/briefing.md'))
    a = ap.parse_args()
    def load(i):
        # out/live/web keeps sector:x names; the built site renames them to sector-x
        for name in (i, i.replace(':', '-')):
            path = os.path.join(a.web, 'data', name + '.json')
            if os.path.exists(path):
                return json.load(open(path))
        raise FileNotFoundError(i)
    nat = load('national')
    p = nat['pairs'][a.pair]
    fl = flows(p)
    natrate = {(f['src'], f['dst']): f['rate'] for f in fl}
    md = []
    live = os.path.join(a.web, 'live.json')
    if os.path.exists(live):
        L = json.load(open(live))
        md.append(f"# תדריך בוקר: מעבר הקולות {a.pair}\n\nעודכן {L['updated_utc']} (UTC). נספרו {L['counted_ballots']:,} מתוך {L['total_ballots']:,} קלפיות. "
                  f"כיסוי ארצי {L.get('counted_share_national', 0):.0%}. בוטסטרפ: {L.get('boot')}.\n")
    md.append('## הזרמים הארציים הגדולים בין רשימות\n')
    md.append(table([[f['src'], f['dst'], f"{f['votes']:,}", f"{f['rate']:.1f}%{ci(f)}"] for f in cross(fl, 15)],
                    ['מ-2022', 'אל 2026', 'קולות', 'שיעור']))
    md.append('\n## מאיפה הגיעו המצביעים של כל רשימה ב-2026\n')
    for dst in [t[0] for t in sorted(p['to'], key=lambda t: -t[2]) if t[1] not in ('dnv',)][:12]:
        inc = sorted([f for f in fl if f['dst'] == dst], key=lambda f: -f['votes'])
        tot = sum(f['votes'] for f in inc) or 1
        parts = ', '.join(f"{f['src']} {f['votes'] / tot:.0%}" for f in inc[:5])
        md.append(f'- **{dst}** ({tot:,} קולות): {parts}')
    md.append('\n## כמה מכל רשימה של 2022 נשארו איתה או עם הרשימה הממשיכה\n')
    rows = []
    for s in [x for x in p['from'] if x[1] not in ('dnv', 'other') and x[2] > 0]:
        out = sorted([f for f in fl if f['src'] == s[0]], key=lambda f: -f['votes'])
        rows.append([s[0], f"{s[2]:,}", ', '.join(f"{f['dst']} {f['rate']:.0f}%{ci(f)}" for f in out[:4])])
    md.append(table(rows, ['רשימה ב-2022', 'קולות', 'לאן הלכו (ארבעת הגדולים)']))
    md.append('\n## מגזרים\n')
    for sid, label in (('sector:haredi', 'חרדים'), ('sector:arab', 'ערבים'), ('sector:druze', 'דרוזים'), ('sector:general', 'יהודים לא-חרדים')):
        sp = load(sid)['pairs'].get(a.pair)
        md.append(f'### {label}\n')
        if not sp:
            md.append('אין מספיק נתונים.\n'); continue
        md.append(table([[f['src'], f['dst'], f"{f['votes']:,}", f"{f['rate']:.1f}%{ci(f)}",
                          f"{natrate.get((f['src'], f['dst']), 0):.1f}%"] for f in cross(flows(sp), 8)],
                        ['מ-2022', 'אל 2026', 'קולות', 'שיעור', 'ארצי']))
    md.append('\n## קבוצות אשכולות חברתיים-כלכליים\n')
    for flt, flabel in (('all', 'כל המגזרים'), ('general', 'יהודים לא-חרדים')):
        for g, glabel in (('g1', '1 עד 3'), ('g2', '4 עד 5'), ('g3', '6 עד 7'), ('g4', '8 עד 10')):
            try:
                sp = load(f'ses-{flt}-{g}')['pairs'].get(a.pair)
            except FileNotFoundError:
                sp = None
            md.append(f'### אשכולות {glabel} · {flabel}\n')
            if not sp:
                md.append('אין מספיק נתונים.\n'); continue
            # the flows that differ most from the national rate, weighted by size
            fs = [f for f in flows(sp) if f['src'] != f['dst'] and f['votes'] > 2000]
            fs.sort(key=lambda f: -abs(f['rate'] - natrate.get((f['src'], f['dst']), 0)) * f['src_total'])
            md.append(table([[f['src'], f['dst'], f"{f['votes']:,}", f"{f['rate']:.1f}%{ci(f)}",
                              f"{natrate.get((f['src'], f['dst']), 0):.1f}%"] for f in fs[:6]],
                            ['מ-2022', 'אל 2026', 'קולות', 'שיעור', 'ארצי']))
    md.append('\n## 20 היישובים הגדולים: המעבר הבולט ביותר ביחס לארצי\n')
    top = json.load(open(os.path.join(a.web, 'map.json')))['top']
    rows = []
    for cid, name, *_ in top:
        cp = load(cid)['pairs'].get(a.pair)
        if not cp:
            rows.append([name, 'אין מספיק נתונים', '', '', '']); continue
        fs = [f for f in flows(cp) if f['src'] != f['dst'] and f['votes'] > 500 and 'other' not in (f['sf'], f['tf'])]
        fs.sort(key=lambda f: -abs(f['rate'] - natrate.get((f['src'], f['dst']), 0)) * f['src_total'])
        for f in fs[:2]:
            rows.append([name, f"{f['src']} ← {f['dst']}", f"{f['votes']:,}", f"{f['rate']:.0f}%{ci(f)}",
                         f"{natrate.get((f['src'], f['dst']), 0):.0f}%"])
    md.append(table(rows, ['יישוב', 'מעבר', 'קולות', 'שיעור', 'ארצי']))
    open(a.out, 'w', encoding='utf-8').write('\n'.join(md) + '\n')
    print('briefing written to', a.out)


if __name__ == '__main__':
    main()
