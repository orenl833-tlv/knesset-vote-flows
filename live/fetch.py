#!/usr/bin/env python3
"""Download the per-ballot results file on election night, keep every changed version, and log when each ballot
box first appears.

No Claude involved: run it directly, in the background, for the whole night.

    python3 -I elections/live/fetch.py                  # poll every 120 s until stopped
    python3 -I elections/live/fetch.py --once           # one download (for cron or a quick check)
    python3 -I elections/live/fetch.py --url URL --knesset 25 --once   # dry run against an old election

Output, under elections/live/k<N>/:
  snapshots/<UTC time>.csv.gz   every version whose content changed (UTF-8)
  latest.csv                    the newest version (UTF-8), for the analysis pipeline
  first_seen.csv                one row per ballot box: when it first appeared with votes, and its counts then
  log.csv                       one row per poll: time, HTTP outcome, rows, ballots with votes, valid votes, changed

The results host rejects Python's TLS handshake, so the download goes through curl.
"""
import argparse, csv, datetime as dt, gzip, hashlib, io, os, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_URLS = ['https://media{k}.bechirot.gov.il/files/expb.csv',
                # a public GitHub mirror of the committee's per-ballot file (OmerCohenBI/k26-turnout-live), updated
                # after each committee round; used because the committee's site turns away non-browser downloads
                'https://raw.githubusercontent.com/OmerCohenBI/k{k}-turnout-live/main/k{k}_expb.csv',
                # a friend's service that fetches data.gov.il through an Israeli exit; it has the file only once
                # data.gov.il publishes it (usually days later), and allows one download per IP per 20 s
                'https://elections.tunnel-massive-sites.xyz/download/{k}.csv']


def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def download(url, timeout, agent=True):
    ua = ['-A', 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'] if agent else []
    r = subprocess.run(['curl', '-sS', '-L', '--compressed', '-m', str(timeout), '-w', '%{http_code}', *ua, url],
                       capture_output=True)
    if r.returncode:
        return None, f'curl {r.returncode}: {r.stderr.decode(errors="replace").strip()[:120]}'
    body, code = r.stdout[:-3], r.stdout[-3:].decode()
    if code != '200':
        return None, f'http {code}'
    if body.lstrip()[:1] == b'<':
        return None, 'html instead of csv'
    return body, 'ok'


def decode(raw):
    # older files are cp1255, newer ones UTF-8 with a BOM
    for enc in ('utf-8-sig', 'cp1255'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode('utf-8', errors='replace')


def ballots(text):
    rows = list(csv.reader(io.StringIO(text)))
    head = [h.strip() for h in rows[0]] if rows else []
    col = {h: i for i, h in enumerate(head)}
    if 'סמל ישוב' not in col or not ({'קלפי', 'מספר קלפי'} & col.keys()):
        raise ValueError('unexpected columns: ' + ','.join(head[:8]))
    num = 'קלפי' if 'קלפי' in col else 'מספר קלפי'
    out = {}
    for r in rows[1:]:
        if len(r) < len(head) or not r[col['סמל ישוב']].strip():
            continue
        key = (r[col['סמל ישוב']].strip(), r[col[num]].strip())
        def n(h):
            try:
                return int(float(r[col[h]] or 0))
            except (KeyError, ValueError):
                return 0
        out[key] = (r[col['שם ישוב']].strip(), n('בזב'), n('מצביעים'), n('כשרים'))
    return head, out


def poll(args, state):
    base = os.path.join(HERE, f'k{args.knesset}')
    os.makedirs(os.path.join(base, 'snapshots'), exist_ok=True)
    t = now()
    raw, status, used = None, 'no url', None
    for u in args.url or [x.format(k=args.knesset) for x in DEFAULT_URLS]:
        for agent in ((True, False) if 'bechirot' in u else (True,)):
            # some hosts refuse a bare client and others (the CBS) refuse a browser agent, so try both
            raw, status = download(u, args.timeout, agent)
            if raw:
                used = u
                break
        if raw:
            break
    changed, nrows, nvoted, valid = False, 0, 0, 0
    if 'digest' not in state and os.path.exists(os.path.join(base, 'latest.csv')):
        # a restarted poller must not store the version it already has as a new one
        state['digest'] = hashlib.sha256(open(os.path.join(base, 'latest.csv'), 'rb').read()).hexdigest()
    if raw:
        text = decode(raw)
        try:
            head, b = ballots(text)
        except ValueError as e:
            raw, status = None, f'bad file: {e}'[:60]
    if raw:
        digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
        nrows = len(b)
        counted = {k: v for k, v in b.items() if v[3] > 0}
        nvoted, valid = len(counted), sum(v[3] for v in counted.values())
        if digest != state.get('digest'):
            changed = True
            state['digest'] = digest
            with gzip.open(os.path.join(base, 'snapshots', f'{t}.csv.gz'), 'wt', encoding='utf-8') as f:
                f.write(text)
            tmp = os.path.join(base, 'latest.csv.tmp')
            open(tmp, 'w', encoding='utf-8').write(text)
            os.replace(tmp, os.path.join(base, 'latest.csv'))
            seen_path = os.path.join(base, 'first_seen.csv')
            if 'seen' not in state:
                state['seen'] = set()
                if os.path.exists(seen_path):
                    with open(seen_path, encoding='utf-8') as f:
                        state['seen'] = {(r['סמל ישוב'], r['קלפי']) for r in csv.DictReader(f)}
            new = [k for k in counted if k not in state['seen']]
            if new:
                fresh = not os.path.exists(seen_path)
                with open(seen_path, 'a', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    if fresh:
                        w.writerow(['first_seen_utc', 'סמל ישוב', 'שם ישוב', 'קלפי', 'בזב', 'מצביעים', 'כשרים'])
                    for k in sorted(new):
                        name, bzb, voters, v = counted[k]
                        w.writerow([t, k[0], name, k[1], bzb, voters, v])
                state['seen'].update(new)
            if state.get('head') and head != state['head']:
                status = 'ok, COLUMNS CHANGED'
            state['head'] = head
    log = os.path.join(base, 'log.csv')
    fresh = not os.path.exists(log)
    with open(log, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if fresh:
            w.writerow(['time_utc', 'status', 'url', 'rows', 'ballots_with_votes', 'valid_votes', 'changed'])
        w.writerow([t, status, used or '', nrows, nvoted, valid, int(changed)])
    print(f'{t} {status:<22} rows={nrows} counted={nvoted} valid={valid:,} {"NEW VERSION" if changed else ""}', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--knesset', type=int, default=26)
    p.add_argument('--url', action='append', help='override the download URL (repeat for fallbacks, tried in order)')
    p.add_argument('--interval', type=int, default=120, help='seconds between polls (default 120)')
    p.add_argument('--timeout', type=int, default=90)
    p.add_argument('--once', action='store_true')
    args = p.parse_args()
    state = {}
    while True:
        try:
            poll(args, state)
        except Exception as e:  # keep polling through a malformed or truncated download
            print(f'{now()} error: {e}', file=sys.stderr, flush=True)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == '__main__':
    main()
