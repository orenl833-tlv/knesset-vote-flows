"""Headlines for the top of the page: a few findings written for a reader who will not open the chart.

The choice of stories and the wording are by hand; every number is read from the built site data, so a rebuild keeps
them in step with the model. Where the INES election survey covers the same move, the card says whether it agrees
(survey figures from the INES comparison run on 25 Oct 2026: survey answers adjusted to the official totals).

Run after build_site.py:  python3 -I scripts/headlines.py [siteDir]   -> <siteDir>/headlines.json
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'out', 'site')

# links: (from key, to key) in the pair; the first is the one the numbers {n} {pct} {lo} {hi} describe,
# the second fills {n2} {pct2}. check: 'agree' | 'disputed' with the survey text, or None when the survey has no figure.
CARDS = [
    dict(id='gantz', unit='אלף קולות לגנץ', area='national', pair='20-21', links=[('labor', 'bluewhite'), ('yeshatid', 'bluewhite')], big='{sum}',
         title='ממי גנץ קיבל את הקולות',
         body='באפריל 2019 הצביעו לכחול לבן כ-{pct}% ממצביעי המחנה הציוני ב-2015 וכ-{pct2}% ממצביעי יש עתיד. '
              'יחד כ-{sum} אלף קולות. מהליכוד הגיעו אליה פחות מ-2%: כחול לבן נבנתה מהשמאל ומהמרכז.'),
    dict(id='arab-split', unit='אלף נשארו בבית', area='sector:arab', pair='23-24', links=[('joint', 'dnv')], big='{n}',
         title='הפיצול שהשאיר את הבוחרים הערבים בבית',
         body='אחרי שרע"מ יצאה מהרשימה המשותפת ב-2021, כשליש ממצביעי המשותפת ב-2020 ({pct}%) לא הצביעו בכלל. '
              'זה קרה גם בפיצול הקודם: באפריל 2019 נשארו בבית {pct_alt}% ממצביעיה ב-2015.',
         alt=('sector:arab', '20-21', ('joint', 'dnv')),
         check=('agree', 'סקר INES מצא 33% עד 45%.')),
    dict(id='likud-far-right', unit='אלף לציונות הדתית', area='national', pair='24-25', links=[('likud', 'far_right')], big='{n}',
         title='אחד מכל עשרה מצביעי ליכוד עבר לבן גביר וסמוטריץ\'',
         body='כ-{pct}% ממצביעי הליכוד ב-2021 הצביעו לציונות הדתית ב-2022. הליכוד כמעט לא הרגיש: '
              'הוא קיבל בחזרה כ-{pct2}% ממצביעי ימינה, וקולות של מי שלא הצביעו ב-2021.',
         extra=[('new_right', 'likud')],
         check=('agree', 'סקר INES מצא כ-12%.')),
    dict(id='left-to-gantz', unit='עברו לכחול לבן', area='national', pair='22-23', links=[('labor', 'bluewhite'), ('meretz', 'bluewhite')], big='{pct}%',
         title='יותר מרבע מהשמאל עבר לגנץ במרץ 2020',
         body='כ-{pct}% ממצביעי העבודה-גשר וכ-{pct2}% ממצביעי המחנה הדמוקרטי בספטמבר 2019 הצביעו לכחול לבן במרץ 2020, '
              'כשהעבודה, גשר ומרצ רצו יחד.',
         check=('agree', 'סקר INES מצא 26% עד 27%. זו ההסכמה החזקה ביותר בין שני המקורות.')),
    dict(id='lapid', unit='עברו ליש עתיד', area='national', pair='23-24', links=[('bluewhite', 'yeshatid')], big='{pct}%',
         title='לפיד לקח חצי מגנץ',
         body='בפירוק כחול לבן ב-2021 עברו ליש עתיד כ-{n} אלף ממצביעיה ב-2020. רק כ-{stay}% נשארו עם גנץ.',
         stay=('bluewhite', 'bluewhite')),
    dict(id='arab-return', unit='אלף חזרו להצביע', area='national', pair='21-22', links=[('dnv', 'joint')], big='{n}',
         title='האיחוד החזיר את הבוחרים הערבים לקלפי',
         body='בספטמבר 2019, כשהרשימה המשותפת התאחדה מחדש, הצביעו לה כ-{n} אלף איש שלא הצביעו באפריל: '
              '{pct}% מכל מי שנשארו בבית.',
         check=('agree', 'סקר INES מצא 5% עד 7%.')),
    dict(id='saar', unit='עברו למחנה הממלכתי', area='national', pair='24-25', links=[('center', 'bluewhite')], big='{pct}%',
         title='חצי ממצביעי סער הלכו איתו לגנץ',
         body='כ-{n} אלף ממצביעי תקווה חדשה ב-2021 הצביעו למחנה הממלכתי ב-2022, אחרי שסער וגנץ רצו יחד.'),
    dict(id='likud-home', unit='אלף נשארו בבית', area='national', pair='23-24', links=[('likud', 'dnv')], big='{n}',
         title='ב-2021 הליכוד הפסיד קודם כל לספה',
         body='לפי ההערכה שלנו, כ-{pct}% ממצביעי הליכוד ב-2020 לא הצביעו ב-2021. הליכוד ירד באותן בחירות בכ-280 אלף קולות.',
         check=('disputed', 'שנוי במחלוקת: סקר INES מצא 25%, הערכה אחרת לפי קלפיות מצאה 4%. האמת כנראה באמצע.')),
    dict(id='yamina', unit='לציונות הדתית', area='national', pair='24-25', links=[('new_right', 'far_right'), ('new_right', 'bluewhite'), ('new_right', 'likud')],
         big='{pct}%', title='ימינה התפרקה לשלושה כיוונים',
         body='אחרי ממשלת בנט-לפיד, מצביעי ימינה ב-2021 התפזרו ב-2022: כ-{pct}% לציונות הדתית, כ-{pct2}% למחנה הממלכתי '
              'וכ-{pct3}% לליכוד.'),
]


def find(d, pair, s, t):
    p = d['pairs'][pair]
    fr, to = [x[1] for x in p['from']], [x[1] for x in p['to']]
    for l in p['links']:
        if fr[l[0]] == s and to[l[1]] == t:
            return dict(sn=p['from'][l[0]][0], tn=p['to'][l[1]][0], n=l[2], pct=l[3], lo=l[4], hi=l[5])
    raise KeyError(f'{pair} {s}->{t}')


def load(area):
    return json.load(open(os.path.join(SITE, 'data', area.replace(':', '-') + '.json')))


def thousands(n):
    return f'{round(n / 1000):,}'


def main():
    out = []
    for c in CARDS:
        d = load(c['area'])
        ls = [find(d, c['pair'], *k) for k in c['links']]
        v = dict(n=thousands(ls[0]['n']), pct=round(ls[0]['pct']), lo=ls[0]['lo'], hi=ls[0]['hi'])
        if len(ls) > 1:
            v.update(n2=thousands(ls[1]['n']), pct2=round(ls[1]['pct']), sum=thousands(ls[0]['n'] + ls[1]['n']))
        if len(ls) > 2:
            v['pct3'] = round(ls[2]['pct'])
        for k in c.get('extra', []):
            v['pct2'] = round(find(d, c['pair'], *k)['pct'])
        if 'stay' in c:
            v['stay'] = round(find(d, c['pair'], *c['stay'])['pct'])
        if 'alt' in c:
            a, pr, k = c['alt']
            v['pct_alt'] = round(find(load(a), pr, *k)['pct'])
        big = c['big'].format(**v)
        out.append(dict(
            id=c['id'], title=c['title'], big=big, unit=c.get('unit') or ('' if big.endswith('%') else 'אלף קולות'),
            body=c['body'].format(**v), area=c['area'], pair=c['pair'], view=c.get('view', 'full'),
            area_name='כל הארץ' if d['kind'] == 'national' else d['name'],
            links=[[x['sn'], x['tn']] for x in ls],
            check=list(c['check']) if c.get('check') else None))
    json.dump(out, open(os.path.join(SITE, 'headlines.json'), 'w'), ensure_ascii=False, indent=1)
    for h in out:
        print(f"{h['big']:>6} {h['unit']:<9} {h['title']}\n       {h['body']}")


if __name__ == '__main__':
    main()
