"""Write out/web/map.json: a faint dot per locality (gives the country its shape) and the 20 largest localities.

CBS packs Israel Transverse Mercator coordinates into one twelve-digit number: six digits of easting,
then six of northing, both in metres. ITM is planar, so the page can draw them without reprojection.
"""
import json, os
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), '..')
TOP_N = 20


def itm(code):
    s = str(int(code)).zfill(12)
    return int(s[:6]), int(s[6:])


def main():
    cbs = pd.DataFrame(json.load(open(os.path.join(ROOT, 'data/raw/bycode2023.json')))['result']['records'])
    cbs = cbs[cbs['קואורדינטות'].notna() & (cbs['קואורדינטות'] > 0)]
    xy = {int(r['סמל יישוב']): itm(r['קואורדינטות']) for _, r in cbs.iterrows()}
    # a few records carry malformed coordinates far outside the country
    xy = {c: (x, y) for c, (x, y) in xy.items() if 120000 <= x <= 280000 and 370000 <= y <= 800000}

    k25 = pd.read_csv(os.path.join(ROOT, 'data/raw/k25.csv'))
    k25.columns = [c.strip() for c in k25.columns]
    k25 = k25[k25['סמל ישוב'] != 9999]
    size = k25.groupby('סמל ישוב')['בזב'].sum().sort_values(ascending=False)

    index = {a['id']: a['name'] for a in json.load(open(os.path.join(ROOT, 'out/web/index.json')))}
    top = []
    for code, bzb in size.items():
        if str(code) in index and code in xy:
            top.append([str(code), index[str(code)], *xy[code], int(bzb)])
        if len(top) == TOP_N:
            break
    dots = sorted({(round(x / 500) * 500, round(y / 500) * 500) for x, y in xy.values()})
    json.dump({'top': top, 'dots': dots}, open(os.path.join(ROOT, 'out/web/map.json'), 'w'), ensure_ascii=False, separators=(',', ':'))
    print(len(top), 'cities,', len(dots), 'background dots')


if __name__ == '__main__':
    main()
