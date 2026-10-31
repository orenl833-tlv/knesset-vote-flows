"""Write config/ses_clusters.csv: CBS 2019 socioeconomic cluster (1-10) per locality code.

Municipalities and local councils come from the CBS authorities table (t01); localities inside regional councils
take their council's cluster from the data.gov.il file. Where both exist, the authority's own value wins.
"""
import json, os
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), '..')


def main():
    t = pd.read_excel(os.path.join(ROOT, 'data/raw/ses2019_authorities_t01.xlsx'), header=None).iloc[10:]
    t = t[pd.to_numeric(t[1], errors='coerce').notna() & pd.to_numeric(t[6], errors='coerce').notna()]
    auth = pd.DataFrame({'code': t[1].astype(int), 'name': t[2].astype(str).str.strip(), 'cluster': t[6].astype(int), 'source': 'authority'})
    rc = pd.DataFrame(json.load(open(os.path.join(ROOT, 'data/raw/ses2019.json')))['result']['records'])
    rc = pd.DataFrame({'code': pd.to_numeric(rc['LOCALITY SYMBOL'], errors='coerce'), 'name': rc['HEBREW NAME OF LOCALITY'].str.strip(),
                       'cluster': pd.to_numeric(rc['ESHKOL 2019'], errors='coerce'), 'source': 'regional_council'}).dropna()
    rc[['code', 'cluster']] = rc[['code', 'cluster']].astype(int)
    out = pd.concat([auth, rc[~rc['code'].isin(auth['code'])]]).drop_duplicates('code').sort_values('code')
    out.to_csv(os.path.join(ROOT, 'config/ses_clusters.csv'), index=False)
    print(len(auth), 'authorities,', len(out) - len(auth), 'regional-council localities;', out['cluster'].value_counts().sort_index().to_dict())


if __name__ == '__main__':
    main()
