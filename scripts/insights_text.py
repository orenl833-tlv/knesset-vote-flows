"""Word the per-city facts (out/llm_facts.json) as short Hebrew findings in out/insights_auto.json.

A fixed template, so every number in the text comes straight from the facts and the output is reproducible.
"""
import json, os

OUT = os.path.join(os.path.dirname(__file__), '..', 'out')
DNV = 'לא הצביעו'


def b(year):
    # "ב-2015" before digits, "באפריל 2019" before a word
    return f'ב-{year}' if year[0].isdigit() else f'ב{year}'


def to(party):
    # the lamed prefix replaces a leading definite article: הליכוד → לליכוד
    return 'ל' + (party[1:] if party.startswith('ה') else party)


def national(f):
    n = f['national_rate_pct']
    return f' (בכל הארץ: כ-{n}%)' if n is not None and (f['kind'].endswith('_distinct') or f['kind'] == 'low_retention') else ''


def interval(f):
    lo, hi = f['interval_pct']
    return f' טווח אי-ודאות: בין {lo}% ל-{hi}%.' if hi - lo > 20 else ''


def finding(f):
    src, dst, y0, y1, v, r = f['from_party'], f['to_party'], f['from_year'], f['to_year'], f['votes'], f['rate_pct']
    if f['kind'] == 'low_retention':
        return dict(title=f'שימור נמוך של מצביעי {src}',
                    text=f'לפי ההערכה, רק כ-{r}% ממצביעי {src} {b(y0)} הצביעו לאותה רשימה גם {b(y1)}{national(f)}.{interval(f)}')
    if src == DNV:
        return dict(title=f'מצביעים חדשים {to(dst)}',
                    text=f'לפי ההערכה, כ-{v} תושבים שלא הצביעו {b(y0)} הצביעו {b(y1)} {to(dst)}, כ-{r}% מאלה שלא הצביעו{national(f)}.{interval(f)}')
    if dst == DNV:
        return dict(title=f'מצביעי {src} נשארו בבית',
                    text=f'לפי ההערכה, כ-{r}% ממצביעי {src} {b(y0)}, כ-{v} איש, לא הצביעו {b(y1)}{national(f)}.{interval(f)}')
    return dict(title=f'מעבר מ{src} {to(dst)}',
                text=f'לפי ההערכה, כ-{r}% ממצביעי {src} {b(y0)}, כ-{v} קולות, הצביעו {b(y1)} {to(dst)}{national(f)}.{interval(f)}')


def main():
    facts = json.load(open(os.path.join(OUT, 'llm_facts.json')))
    out = {cid: [finding(f) for f in v['facts']] for cid, v in facts.items()}
    json.dump(out, open(os.path.join(OUT, 'insights_auto.json'), 'w'), ensure_ascii=False, indent=1)
    print(len(out), 'cities,', sum(map(len, out.values())), 'findings')


if __name__ == '__main__':
    main()
