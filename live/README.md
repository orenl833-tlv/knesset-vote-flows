# Election night: Knesset 26 (27 October 2026)

## Downloading the results

`fetch.py` pulls the per-ballot results file, keeps every version that changed, and records when each ballot box first appears with votes. It needs only Python and curl; Claude is not involved.

```
# from the repository root; polls every 2 minutes until stopped
nohup python3 -I live/fetch.py > live/fetch.out 2>&1 &

# one download, to check that the file is up
python3 -I live/fetch.py --once

# if the committee publishes under another address, pass it (repeat --url for fallbacks)
python3 -I live/fetch.py --url https://media26.bechirot.gov.il/files/expb.csv
```

Output goes to `live/k26/`:

| File | Content |
|---|---|
| `snapshots/<UTC>.csv.gz` | every changed version, UTF-8 |
| `latest.csv` | newest version, read by the analysis |
| `first_seen.csv` | per ballot box: first time it had votes, with its counts then |
| `log.csv` | one line per poll |

A restart does not duplicate the last snapshot. A file with unexpected columns is logged as `bad file` and skipped; a change of columns between versions is logged as `COLUMNS CHANGED`.

## Order of counting

`first_seen.csv` records when each ballot box was reported, which follows the counting and reporting logistics after the polls close. It does not record when voters voted: the whole box is counted together. Comparing voting by time of day needs the committee's hourly turnout figures, which are published during election day, not the counting order.

## If the committee publishes no per-ballot CSV

`scrape_ballots.py` rebuilds the same file from the per-ballot pages of the results site (`votes26.bechirot.gov.il/ballotresults`): it lists the localities, each locality's ballot boxes, and reads each box's page. Tested against the 2022 site: 301 ballots of Holon and Modiin matched the official file in every cell. A full pass over all ballots takes about half an hour with 8 workers; `--sample 0.3` follows a fixed 30% and takes about 10 minutes. Counted ballots are not fetched again, and a restart resumes.

```
nohup python3 -I live/scrape_ballots.py --sample 0.3 > live/scrape.out 2>&1 &
K26=live/k26/scraped.csv bash live/night.sh
```

The pages carry no polling-place (ריכוז) number, so the 2022-2026 matching falls back to ballot numbers; coverage is a little lower.
