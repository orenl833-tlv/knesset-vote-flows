#!/usr/bin/env python3
"""Fallback for election night: if the committee does not publish the per-ballot CSV (expb.csv), rebuild it from
the per-ballot pages of the results site, votes<N>.bechirot.gov.il/ballotresults.

The site lists every locality, each locality lists its ballot boxes, and each ballot page shows the eligible
voters, votes cast, valid and invalid votes, and the votes per list letter. This script walks those pages and
writes a CSV in the same layout as expb.csv (without ריכוז, so the 2022-2026 matching uses ballot numbers).

    python3 -I elections/live/scrape_ballots.py                     # Knesset 26, every ballot, loop until stopped
    python3 -I elections/live/scrape_ballots.py --sample 0.3 --once # a fixed random 30% of ballots, one pass
    python3 -I elections/live/scrape_ballots.py --knesset 25 --towns 6600,8300 --once   # test against 2022

Then run the analysis on it:  K26=elections/live/k26/scraped.csv bash elections/live/night.sh

A ballot is fetched until it shows valid votes; after that it is kept and not fetched again. Ballots not fetched
yet are written with zeros, so the analysis knows they exist and treats them as not counted. State is kept in
live/k<N>/scrape/ so a restart resumes. The site is a public government service: keep --workers modest.
Downloads go through curl, like fetch.py (the government hosts reject Python's TLS handshake).
"""
import argparse, csv, datetime as dt, html, json, os, random, re, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
HEAD = ['סמל ועדה', 'ברזל', 'שם ישוב', 'סמל ישוב', 'קלפי', 'שופט', 'בזב', 'מצביעים', 'פסולים', 'כשרים']


def get(url, timeout=40):
    for attempt in range(3):
        r = subprocess.run(['curl', '-sS', '-L', '--compressed', '-m', str(timeout), '-A', UA, '-w', '%{http_code}', url],
                           capture_output=True)
        code = r.stdout[-3:].decode(errors='replace')
        if r.returncode == 0 and code == '200':
            return r.stdout[:-3].decode('utf-8', errors='replace')
        time.sleep(2 * (attempt + 1))
    raise IOError(f'{url}: curl {r.returncode} http {code}')


def towns(base):
    s = get(f'{base}/ballotresults')
    s = s[s.find('id=select1'):s.find('</datalist>', s.find('id=select1')) if '</datalist>' in s else None]
    return [(int(c), html.unescape(n).strip()) for c, n in re.findall(r'VALUE=(\d+)>([^<]+)</OPTION>', s, re.I) if c != '0']


def ballots(base, code):
    s = get(f'{base}/ballotresults?cityID={code}')
    i = s.find('id=select2')
    out = []
    for num, text in re.findall(r'<OPTION VALUE=([\d.]+)>([^<]*)</OPTION>', s[i:], re.I):
        m = re.search(r'מספר ברזל (\d+)', text)
        out.append((num, m.group(1) if m else ''))
    return out


def num(x):
    x = x.replace(',', '').strip()
    return int(float(x)) if re.fullmatch(r'[\d.]+', x) else 0


def ballot_page(base, code, bnum):
    s = get(f'{base}/ballotresults?cityID={code}&BallotNumber={bnum}')
    cells = lambda t: [html.unescape(re.sub(r'<[^>]+>', '', c)).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', t, re.S)]
    i = s.find('ResultsSummaryTable')
    summ = [c for c in cells(s[i:s.find('</table>', i)]) if c] if i > 0 else []
    vals = [num(c) for c in summ if '%' not in c]
    if len(vals) < 4:
        raise ValueError(f'{code}/{bnum}: no summary table')
    bzb, voters, valid, invalid = vals[:4]
    votes = {}
    j = s.find('TableData')
    if j > 0:
        t = s[j:s.find('</table>', j)]
        for row in re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S):
            c = cells(row)
            if len(c) >= 4 and re.fullmatch(r'[א-ת]{1,4}', c[1]):
                votes[c[1]] = num(c[-1])
    return dict(bzb=bzb, voters=voters, valid=valid, invalid=invalid, votes=votes)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--knesset', type=int, default=26)
    p.add_argument('--base', help='site root (default https://votes<N>.bechirot.gov.il)')
    p.add_argument('--sample', type=float, default=1.0, help='fraction of ballots to follow (fixed seed), default all')
    p.add_argument('--towns', help='comma-separated locality codes only (testing)')
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--interval', type=int, default=300, help='seconds between passes')
    p.add_argument('--once', action='store_true')
    a = p.parse_args()
    base = (a.base or f'https://votes{a.knesset}.bechirot.gov.il').rstrip('/')
    d = os.path.join(HERE, f'k{a.knesset}', 'scrape'); os.makedirs(d, exist_ok=True)
    out = os.path.join(HERE, f'k{a.knesset}', 'scraped.csv')
    lists_p, done_p = os.path.join(d, 'ballot_lists.json'), os.path.join(d, 'counted.json')
    lists = json.load(open(lists_p)) if os.path.exists(lists_p) else {}
    done = json.load(open(done_p)) if os.path.exists(done_p) else {}
    cfg = json.load(open(os.path.join(HERE, '..', 'config', 'parties.json')))['elections'].get(str(a.knesset), {})
    letters = list(cfg.get('parties', {}))
    while True:
        t0 = time.time()
        try:
            if not lists:
                tw = towns(base)
                if a.towns:
                    keep = {int(x) for x in a.towns.split(',')}
                    tw = [t for t in tw if t[0] in keep]
                print(f'{len(tw)} localities; reading their ballot lists', flush=True)
                with ThreadPoolExecutor(a.workers) as ex:
                    for (code, name), bl in zip(tw, ex.map(lambda t: ballots(base, t[0]), tw)):
                        lists[str(code)] = dict(name=name, ballots=bl)
                json.dump(lists, open(lists_p, 'w'), ensure_ascii=False)
            rnd = random.Random(26)
            todo = [(c, b) for c, v in sorted(lists.items()) for b, _ in v['ballots']
                    if rnd.random() < a.sample and f'{c}|{b}' not in done]

            def one(cb):
                try:
                    return cb, ballot_page(base, *cb)
                except Exception as e:  # a ballot that fails now is tried again next pass
                    return cb, e
            errors = 0
            with ThreadPoolExecutor(a.workers) as ex:
                for (c, b), r in ex.map(one, todo):
                    if isinstance(r, Exception):
                        errors += 1
                    elif r['valid'] > 0:
                        done[f'{c}|{b}'] = r
            json.dump(done, open(done_p, 'w'), ensure_ascii=False)
            seen = sorted({k for r in done.values() for k in r['votes']} | set(letters))
            tmp = out + '.tmp'
            with open(tmp, 'w', newline='', encoding='utf-8-sig') as f:
                w = csv.writer(f)
                w.writerow(HEAD + seen)
                for c, v in sorted(lists.items(), key=lambda x: int(x[0])):
                    for b, barzel in v['ballots']:
                        r = done.get(f'{c}|{b}')
                        row = ['', barzel, v['name'], c, b, 0]
                        if r:
                            w.writerow(row + [r['bzb'], r['voters'], r['invalid'], r['valid']] + [r['votes'].get(x, 0) for x in seen])
                        else:
                            w.writerow(row + [0, 0, 0, 0] + [0] * len(seen))
            os.replace(tmp, out)
            nb = sum(len(v['ballots']) for v in lists.values())
            print(f'{dt.datetime.now(dt.timezone.utc):%H:%M:%SZ} pass done in {time.time() - t0:.0f}s: '
                  f'{len(done)} of {nb} ballots counted, {len(todo)} fetched, {errors} errors -> {out}', flush=True)
        except Exception as e:
            print(f'pass failed: {e}', file=sys.stderr, flush=True)
        if a.once:
            break
        time.sleep(a.interval)


if __name__ == '__main__':
    main()
