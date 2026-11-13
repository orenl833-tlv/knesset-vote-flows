"""Assemble the election-night site in out/site_live from the stage-4 output (out/live/web).

It reuses build_site.py for the shared files, then adds Knesset 26: the 25-26 pair in the views, a seat
projection from the current results file, and a banner with how much has been counted.

    python3 -I scripts/build_site_live.py [--k26 PATH]
    python3 -I scripts/build_site_live.py --pre    # before any 2026 results: the earlier elections, with a banner

Headline cards written during the night go in live/insights_night.json under "headlines" (same fields as
scripts/headlines.py writes, pair "25-26"); they are shown above the cards on earlier elections.
"""
import argparse, datetime as dt, json, os, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
import build_site
from zoneinfo import ZoneInfo
import headlines26

ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.join(ROOT, 'live'))
import seats as seatcalc


ELIGIBLE_26 = 7331981  # eligible voters, Knesset 26 (Central Elections Committee)
ENV_BALLOTS_22 = 838  # double-envelope ballots in 2022 (locality 9999), a yardstick for a finished count
MIN_COVER_AREA = 30  # percent of the 2022->2026 coverage an area needs for cards of its own
NIGHT_URL = 'https://claude.ai/artifact/9mV89K4g8dSPcKYNKnyQU3'



def env_ballots(path):
    """How many double-envelope ballots (locality 9999) the results file lists so far."""
    import csv
    with open(path, encoding='utf-8-sig') as f:
        r = csv.reader(f); col = next(r).index('סמל ישוב')
        return sum(1 for row in r if len(row) > col and row[col].strip() == '9999')


def as_of(path):
    """Israel time (HH:MM) at which the results file in use was first downloaded: the newest snapshot that fetch.py
    stored, which is the version in latest.csv; for any other file, its modification time."""
    snaps = os.path.join(os.path.dirname(path), 'snapshots')
    names = sorted(n for n in os.listdir(snaps) if n.endswith('.csv.gz')) if os.path.isdir(snaps) else []
    if os.path.basename(path) == 'latest.csv' and names:
        t = dt.datetime.strptime(names[-1][:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=dt.timezone.utc)
    else:
        t = dt.datetime.fromtimestamp(os.path.getmtime(path), dt.timezone.utc)
    return t.astimezone(ZoneInfo('Asia/Jerusalem')).strftime('%H:%M')

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--k26', default=os.path.join(ROOT, 'live/k26/latest.csv'))
    p.add_argument('--test', action='store_true', help='mark the page as a dry run on simulated data')
    p.add_argument('--final', action='store_true', help='the committee has published its final results: no provisional marks')
    p.add_argument('--pre', action='store_true', help='no 2026 data yet: earlier elections and a waiting banner')
    p.add_argument('--day', action='store_true', help='election day, polls open: as --pre, with the election-day banner')
    p.add_argument('--waiting', action='store_true', help='polls closed, no results yet: as --pre, plus the four fixed 2026 headlines as placeholders')
    a = p.parse_args()
    build_site.SITE = os.path.join(ROOT, 'out/site_live')
    if a.pre or a.waiting or a.day:
        build_site.main()
        site = build_site.SITE
        page = os.path.join(site, 'index.html')
        html = open(page, encoding='utf-8').read().replace('<title>נדידת הקולות בישראל</title>', '<title>ליל הבחירות 2026</title>', 1)
        if a.day or a.waiting:
            # on election day the turnout table is the news, so it starts open
            html = html.replace('<details class="card" id="turnout-box">', '<details class="card" id="turnout-box" open>', 1)
        # the seats panel stays closed until the results come; it opens on the 2026 projection then
        open(page, 'w', encoding='utf-8').write(html)
        # one banner per stage of the day; turnout by hour is published from the morning, the flows from about 02:30
        banner = ('ביום הבחירות, שלישי 27 באוקטובר, יתעדכן כאן אחוז ההצבעה שעה אחר שעה, מול אותה שעה ב-2022. '
                  'אחרי סגירת הקלפיות, בערך מ-02:30, יופיעו ההערכות הראשונות לנדידת הקולות מ-2022 ל-2026. עד אז: מה קרה בבחירות הקודמות.')
        if a.day:
            banner = ('הקלפיות נפתחו. אחוז ההצבעה מתעדכן כאן במהלך היום, מול אותה שעה ב-2022 (בלשונית "אחוז ההצבעה לפי שעה"). '
                      'ההערכות הראשונות לנדידת הקולות יופיעו אחרי סגירת הקלפיות, בערך מ-02:30.')
        if a.waiting:
            banner = ('הספירה מתקדמת, אבל התוצאות לפי קלפי עדיין לא זמינות כאן. ההערכות לנדידת הקולות מ-2022 ל-2026 יופיעו ברגע שיהיו, '
                      'ויתעדכנו לאורך הספירה. אחוז ההצבעה לאורך היום נמצא בלשונית "אחוז ההצבעה לפי שעה".')
            # the night layout before results: the 2026 tab leads and stays empty until the numbers come, with the
            # earlier elections' cards one switch away; the chart opens on 2022 against the 2026 lists marked "?"
            hp = os.path.join(site, 'headlines.json')
            old = [dict(h, group='הבחירות הקודמות') for h in json.load(open(hp))]
            soon = dict(id='soon-2026', group='ליל הבחירות 2026', big='?', unit='', area='national', area_name='כל הארץ',
                        links=[], check=None, pair=None, title='מי עבר לאן? התשובות בדרך',
                        body='התוצאות לפי קלפי מתעכבות. ברגע שקובץ הקלפיות יהיה זמין, יופיעו כאן ממצאים שנכתבים אוטומטית מתוך התוצאות ומתעדכנים לאורך הספירה: '
                             'כמה מצביעי ליכוד עזבו ולאן, מאיפה הגיעו המצביעים של איזנקוט, לאן הלכו המצביעים של לפיד, '
                             'ומי הצביע לציבור החרדי. ועוד ממצאים מעניינים, לפי מה שהקלפיות יגלו.')
            json.dump([soon] + old, open(hp, 'w'), ensure_ascii=False, indent=1)
        extra = {'views': {'last': ['25-26']}, 'default_view': 'last'} if a.waiting else {}
        json.dump({'url': NIGHT_URL, 'banner': banner, 'pending26': build_site.pending26(), **extra},
                  open(os.path.join(site, 'site.json'), 'w'), ensure_ascii=False)
        print('pre-election site ready:', site)
        return
    build_site.WEB = os.path.join(ROOT, 'out/live/web')
    build_site.main()
    site = build_site.SITE
    live = json.load(open(os.path.join(build_site.WEB, 'live.json')))
    # exact 2026 shares of what has been counted, for the country and each locality
    exact26 = build_site.raw_shares({'26': a.k26}, only_counted=True)
    votes, valid, eligible = seatcalc.totals(a.k26)
    names = json.load(open(os.path.join(ROOT, 'config/parties.json')))['elections']['26']['parties']
    # lists under the electoral threshold in the national count so far; the chart tags them in every area
    below26 = [names[c][0] for c, v in votes.items() if c in names and v < seatcalc.THRESHOLD * valid]
    # lists that always show on the chart, even with no flow over the small-flow threshold
    always26 = [names[c][0] for c in json.load(open(os.path.join(ROOT, 'config/parties.json')))['always_kept']['26']]
    for name in os.listdir(os.path.join(site, 'data')):
        area = name[:-5]
        path = os.path.join(site, 'data', name)
        d = json.load(open(path))
        if area in exact26:
            d.setdefault('shares', {})['26'] = exact26[area]['26']
        d['below26'] = below26
        d['always26'] = always26
        json.dump(d, open(path, 'w'), ensure_ascii=False, separators=(',', ':'))

    agreements = json.load(open(os.path.join(ROOT, 'config/surplus_agreements.json')))['26']
    seats = seatcalc.allocate(votes, valid, agreements)
    blocs = json.load(open(os.path.join(ROOT, 'config/blocs26.json')))
    bloc_of = {c: b for b, codes in blocs.items() if not b.startswith('_') for c in codes}
    # the seat bar keeps a fixed order of lists (blocs26.json), so lists do not swap places as the count moves
    draw_order = {c: i for i, c in enumerate(c for b in ('bibi', 'mid', 'joint', 'raam', 'anti') if b in blocs for c in blocs[b])}
    # findings written on election night (country first) replace or add to the built ones
    night = os.path.join(ROOT, 'live/insights_night.json')
    if os.path.exists(night):
        # on the night page the findings above the chart are only those written for 2026 (none for now): the built
        # ones are about earlier elections, and the 2026 headline cards below the chart carry the story
        ins = {}
        nj = json.load(open(night))
        ins.update({k: v for k, v in nj.items() if not k.startswith('_') and k != 'headlines'})  # an empty list hides an area's built findings
        json.dump(ins, open(os.path.join(site, 'insights.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    else:
        nj = {}
    # once results arrive the page leads with 2026: the four fixed headlines, then any written during the night;
    # the earlier elections' cards stay one switch away
    hp = os.path.join(site, 'headlines.json')
    old = [dict(h, group='הבחירות הקודמות') for h in json.load(open(hp))]
    new = [dict(h, group='ליל הבחירות 2026', view=h.get('view', 'last')) for h in nj.get('headlines', [])]
    taken = [l for h in new for l in h.get('links', [])]
    json.dump(headlines26.order(headlines26.make(site, a.k26, taken=taken, total=max(0, 12 - len(new))) + new) + old, open(hp, 'w'), ensure_ascii=False, indent=1)
    # the same flow cards for every other area, so the 2026 cards follow the area the reader picks; a card with
    # no numbers there is left out, and none has an id (no share image or link of its own); an area whose 2022->2026
    # coverage (as shown on the chart) is under MIN_COVER_AREA keeps the national cards, as a few ballots make noise
    by_area = {}
    for name in sorted(os.listdir(os.path.join(site, 'data'))):
        f = name[:-5]
        if f == 'national' or not name.endswith('.json'):
            continue
        d = json.load(open(os.path.join(site, 'data', name)))
        p = (d.get('pairs') or {}).get('25-26')
        c = p and p.get('coverage_core', p.get('coverage'))
        if not c or (c if c > 1 else c * 100) < MIN_COVER_AREA:
            continue
        area = 'sector:' + f[7:] if f.startswith('sector-') else f
        cards = [dict(c, id=None) for c in headlines26.make(site, a.k26, f, d.get('name') or f) if c['pair']]
        for c in cards:
            c['area'] = area
        if cards:
            by_area[area] = cards
    json.dump(by_area, open(os.path.join(site, 'headlines_by_area.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    s = json.load(open(os.path.join(site, 'seats.json')))
    s['26'] = [[names.get(c, [c])[0], n, names.get(c, [c, 'other'])[1], bloc_of.get(c, 'anti')]
               for c, n in sorted(seats.items(), key=lambda x: (draw_order.get(x[0], len(draw_order)), -x[1])) if n]
    # votes per seat for the chart's flows, which estimate the whole electorate: the modelled 2026 valid votes
    # times the counted share of lists over the threshold, over 120 (the counted votes alone are only part)
    p26 = json.load(open(os.path.join(site, 'data', 'national.json')))['pairs'].get('25-26')
    if p26 and valid:
        modelled = sum(t[2] for t in p26['to'] if t[1] != 'dnv')
        s.setdefault('quota', {})['26'] = round(seatcalc.quota(votes, valid) / valid * modelled)
    # nearly final: every regular ballot counted, and as many double-envelope ballots as in 2022 (838)
    n_env = env_ballots(a.k26)
    near_final = n_env >= ENV_BALLOTS_22 and eligible / ELIGIBLE_26 >= 0.99
    if a.final:
        s.setdefault('final', {})['26'] = 'תוצאות סופיות, כולל המעטפות הכפולות. הגושים לפי עמדות הרשימות לפני הבחירות.'
    else:
        s.setdefault('provisional', {})['26'] = (
            'לפי כמעט כל הקולות, כולל המעטפות הכפולות. התוצאות הרשמיות עוד לא פורסמו. הגושים לפי עמדות הרשימות לפני הבחירות.'
            if near_final else 'תחזית לפי הקולות שנספרו עד כה. הגושים לפי עמדות הרשימות לפני הבחירות.')
        if near_final:
            s.setdefault('near_final', {})['26'] = True
        s['as_of'] = {'26': as_of(a.k26)}
    json.dump(s, open(os.path.join(site, 'seats.json'), 'w'), ensure_ascii=False, separators=(',', ':'))

    t = dt.datetime.fromisoformat(live['updated_utc'].replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=2)))
    share = live.get('counted_share_national') or 0
    # the committee's file can list only the ballots counted so far, so the share counted is their eligible voters
    # over the national roll (7,331,981 per the committee on election day), not counted over listed ballots
    counted_share = eligible / ELIGIBLE_26 * 100
    if a.final:
        # the committee's final tally differs from the ballot file by about a hundred votes moved from invalid to
        # valid on review (5,690,778 valid against 5,690,685), which changes no seat
        banner = (f"תוצאות סופיות של בחירות 2026, כולל {n_env:,} קלפיות של מעטפות כפולות. "
                  "המעבר 2022 ← 2026 הוא הערכה מתוצאות הקלפיות. המעטפות הכפולות נכללות במנדטים, לא במעברים "
                  "(אין להן קלפי ב-2022 להשוואה). החישוב לפי קובץ הקלפיות של ועדת הבחירות. בסיכום הרשמי שלה "
                  "הועברו כ-100 קולות מפסולים לכשרים, בלי השפעה על המנדטים.")
    elif near_final:
        banner = (f"תוצאות כמעט סופיות של בחירות 2026: נספרו כל הקלפיות הרגילות ו-{n_env:,} קלפיות של מעטפות כפולות. "
                  f"עודכן ב-{t:%H:%M}. התוצאות הרשמיות של ועדת הבחירות יפורסמו בימים הקרובים. "
                  "המעבר 2022 ← 2026 הוא הערכה מתוצאות הקלפיות. המעטפות הכפולות נכללות במנדטים, לא במעברים "
                  "(אין להן קלפי ב-2022 להשוואה).")
    else:
        banner = (f"תוצאות חלקיות של בחירות 2026: נספרו {live['counted_ballots']:,} קלפיות "
                  f"(כ-{counted_share:.0f}% מבעלי זכות הבחירה). עודכן ב-{t:%H:%M}. "
                  "המעבר 2022 ← 2026 הוא תחזית מהקלפיות שנספרו. " +
                  ("המעטפות הכפולות שנספרו עד כה נכללות במנדטים, לא במעברים (אין להן קלפי ב-2022 להשוואה)."
                   if n_env else "המעטפות הכפולות עוד לא נספרו."))
    if a.test:
        banner = 'ניסיון על נתונים מדומים (תוצאות 2022 בשמות של 2026), לא תוצאות אמת. ' + banner
    page = os.path.join(site, 'index.html')
    html = open(page, encoding='utf-8').read().replace('<title>נדידת הקולות בישראל</title>',
                                                       '<title>בחירות 2026 · ניסיון</title>' if a.test else
                                                       '<title>בחירות 2026</title>' if a.final else '<title>ליל הבחירות 2026</title>', 1)
    html = html.replace('<details class="card seats" id="seats-box">', '<details class="card seats" id="seats-box" open>', 1)
    html = html.replace('כנסת 19 עד כנסת 25 · 2013 עד 2022', 'כנסת 19 עד כנסת 26 · 2013 עד 2026', 1)
    html = html.replace('מ-2013 ועד 2022.', 'מ-2013 ועד 2026.', 1)
    # the 2022-2026 pair groups localities by the newer CBS index; say so where the clusters are explained
    html = html.replace('צירוף עם פחות מ-20,000 בעלי זכות בחירה לא מוצג.',
                        'צירוף עם פחות מ-20,000 בעלי זכות בחירה לא מוצג. במעבר 2022 ← 2026 החלוקה לאשכולות היא לפי המדד המעודכן של הלמ"ס לשנת 2021, '
                        'שבו גם ליישובים במועצות אזוריות יש אשכול משלהם. לכן קבוצה עשויה להכיל בעמודת 2026 יישובים קצת שונים מאשר בעמודות הקודמות.', 1)
    open(page, 'w', encoding='utf-8').write(html)
    json.dump({'views': {'full': ['19-20', '20-21', '21-22', '22-23', '23-24', '24-25', '25-26'],
                         'skip': ['19-20', '20-25', '25-26'], 'last': ['25-26']},
               'default_view': 'last', 'url': NIGHT_URL, 'banner': banner}, open(os.path.join(site, 'site.json'), 'w'), ensure_ascii=False)
    print('live site ready:', site, '| seats', sum(seats.values()), '| counted', live['counted_ballots'])


if __name__ == '__main__':
    main()
