"""Download per-ballot Knesset results (19th-25th) into data/raw/kNN.csv (UTF-8)."""
import json, sys, time, urllib.request, io, csv, os, subprocess
RAW = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
DATASTORE = {19: '432d3185-545a-41d9-8c72-d10ee515919c', 20: 'c3db5581-f48d-45fc-b221-e7635e940c41'}
MEDIA = {21: ('https://media21.bechirot.gov.il/files/expb.csv', 'cp1255'),
         22: ('https://media22.bechirot.gov.il/files/expb.csv', 'cp1255'),
         23: ('https://media23.bechirot.gov.il/files/expb.csv', 'cp1255'),
         24: ('https://media24.bechirot.gov.il/files/expb.csv', 'cp1255'),
         25: ('https://media25.bechirot.gov.il/files/expb.csv', 'utf-8-sig')}
def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r: return r.read()
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(2 ** (i + 1))
def curl(url):
    # the results hosts reject Python's TLS handshake, so fetch them with curl
    return subprocess.run(['curl', '-sS', '-m', '180', '--retry', '4', url], check=True, capture_output=True).stdout
def datastore(rid):
    rows, off = [], 0
    while True:
        d = json.loads(get(f'https://data.gov.il/api/3/action/datastore_search?resource_id={rid}&limit=5000&offset={off}'))['result']
        rows += d['records']; off += len(d['records'])
        if not d['records'] or off >= d['total']: break
    fields = [f['id'] for f in d['fields'] if f['id'] != '_id']
    return fields, rows
for k in (int(a) for a in sys.argv[1:]) if len(sys.argv) > 1 else range(19, 26):
    out = os.path.join(RAW, f'k{k}.csv')
    if k in DATASTORE:
        fields, rows = datastore(DATASTORE[k])
        with open(out, 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    else:
        url, enc = MEDIA[k]
        for i in range(4):
            raw = curl(url)
            if not raw.lstrip().startswith(b'<'): break
            time.sleep(3)
        open(out, 'w', encoding='utf-8').write(raw.decode(enc))
    print(k, sum(1 for _ in open(out, encoding='utf-8')) - 1, 'rows')
