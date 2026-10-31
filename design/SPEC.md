# Vote-transfer estimates for Israel, Knesset 19–25

Estimate how votes moved between parties across consecutive Knesset elections, for the whole country, for each large locality, and for four sectors (Haredi, Arab, Druze, general).

Run Python with `python3 -I`. numpy, pandas, scipy are installed.

## Inputs (already downloaded)

- `data/raw/k19.csv` … `data/raw/k25.csv`: one row per ballot box, UTF-8.
  - Columns: `סמל ישוב` (CBS locality code), `שם ישוב`, the ballot number (`מספר קלפי` in 19–21, `קלפי` in 22–25), `בזב` (eligible), `מצביעים`, `פסולים` (invalid), `כשרים` (valid), then one column per party letter code. 22–25 also have `ריכוז` (polling-place ID, unique within a locality). Strip whitespace from column names and locality names; drop `Unnamed` columns.
  - Rows with `סמל ישוב` 9999 (22–25 only) are double envelopes (soldiers, diplomats, …). Exclude them from all modelling. Report their valid-vote count per election in the diagnostics.
- `data/raw/bycode2023.json`: CBS locality file (datastore JSON, records under `result.records`). Use `סמל יישוב`, `שם מחוז`, `דת יישוב` (1 Jewish, 2 Arab, 3 Bedouin tribe, 4 mixed), `צורת יישוב שוטפת - ארעי` (codes below 300 are urban).
- `config/parties.json`: per election, party code → [display name, colour family]. Unlisted codes fold into `אחרים`. Also lists the Haredi and Arab party codes per election and the Druze localities.

## Categories

For an election and a set of ballots, the categories are the mapped parties, `אחרים` (valid votes of unlisted codes), and `לא הצביעו` = `בזב − כשרים` (this includes invalid ballots).

## Pairs

`19-20, 20-21, 21-22, 22-23, 23-24, 24-25`, plus the skip pair `20-25` (2015 → 2022 directly).

## Regions

- **Large localities:** every locality with at least 20 ballot boxes in k25 (excluding 9999) is its own region. These are the localities the user can pick.
- **Clusters:** every other locality goes to a cluster keyed by district (`שם מחוז`) × type. The type is:
  - `druze`: the locality is in `druze_localities`.
  - `arab`: `דת יישוב` is 2 or 3.
  - `jewish_urban`: `דת יישוב` is 1 or 4 and the form code is below 300.
  - `jewish_rural`: `דת יישוב` is 1 or 4 and the form code is 300 or above.
  - A locality missing from the CBS file goes to cluster `unknown`.
  - A cluster with fewer than 25 ballot boxes in k25 merges into a national cluster of its type.
- Region membership is fixed by locality code, the same for every pair.

## Matching units between elections a → b (within each region)

1. **Both elections have `ריכוז`** (pairs 22-23, 23-24, 24-25). This is the place method:
   - Group ballots by (locality, `ריכוז`). Keep a place if |bzb_b / bzb_a − 1| ≤ 0.08.
   - Inside a kept place, a ballot number present in both elections with |ratio − 1| ≤ 0.05 becomes its own unit.
   - The rest of the place becomes one more unit if its own ratio is within 0.08; otherwise it is dropped.
2. **Otherwise** (19-20, 20-21, 21-22, 20-25). This is the number method:
   - Group ballots by (locality, floor(ballot number)), summing decimal sub-ballots like 33.1, 33.2.
   - A group present in both elections with |ratio − 1| ≤ 0.08 is a unit.
3. **Population-replacement filter (all pairs).** For each unit, let h = Haredi-party share of valid votes and r = Arab-party share. Drop the unit if |h_b − h_a| > T or |r_b − r_a| > T. The default is T = 0.15. Count the drops.

## Sector of a unit (per pair)

- `druze`: the locality is in `druze_localities`. In `druze_mixed_localities`, a unit is `druze` if r < 0.40 in both elections, and `arab` otherwise.
- `arab`: `דת יישוב` is 2 or 3 (and not Druze). In localities with `דת יישוב` 4, a unit is `arab` if r ≥ 0.50 in both elections.
- `haredi`: h ≥ 0.60 in both elections. If h ≥ 0.60 in exactly one, the unit is `transitional` and is used in no sector fit.
- `general`: everything else.

To scale sector results to votes, classify every ballot of election a on its own, with the same rules using only election a's shares. Haredi means h_a ≥ 0.60. Sum the category totals per sector.

## Model

For a set of units with earlier shares X (n×k, each row = category counts / unit bzb in a), later shares Y (n×m, divided by the unit's bzb in b) and weights w (mean of the unit's two bzb values, normalised to mean 1):

minimise Σ_i w_i ‖x_i P − y_i‖², where each row of P lies on the probability simplex.

- **Solver:** FISTA (accelerated projected gradient), projecting each row onto the simplex. Use the standard sort-based projection. Step size is 1/L with L = 2·λ_max(Xᵀ W X). Start from the uniform matrix. Stop when max|ΔP| < 1e-8 or after 20,000 iterations, and record whether it converged.
- **Validation before anything else:** run the full pipeline for Holon (locality 6600) on pairs 23-24 and 24-25, and compare with the reference values at the end of this file.
- **Categories inside a fit:** keep a party as its own category only if it has ≥ 3% of the valid votes in that set of units in that election. Exception: the lists in `always_kept` (config) are kept from 0.5%, so the chart shows them under the electoral threshold. Fold the rest into `אחרים`. Then, while k or m exceeds max(4, floor(n_units / 4)), fold the smallest party on that side into `אחרים`. `לא הצביעו` and `אחרים` are always kept.
- **Votes:** votes(i→j) = P[i,j] × total of category i in election a over **all** ballots of the region (or sector), matched or not.
- **Bootstrap:** 100 resamples of units with replacement, warm-started from the main fit. Keep every replicate's vote matrix so it can be aggregated later. Skip the bootstrap when n_units < 10, and mark that fit as `no_interval`.
- Use multiprocessing with 4 workers.

## Fits to run, per pair

1. `region:<id>`, all units of each region.
2. `general:<id>`, the general units of each region that has ≥ 15 general units. All remaining general units across the country form one pooled fit, `general:pooled`. Its votes scale by the general-sector totals of the regions that were not fitted separately.
3. `haredi`, `arab`, `druze`: one national pooled fit each, over all units of that sector in the country.

**Aggregates.** Map every category to its display name: folded parties are already `אחרים`, and the categories of different regions merge by name.

- `national`: the sum of the `region:*` vote matrices.
- `sector:general`: the sum of the `general:*` matrices.
- `sector:haredi`, `sector:arab`, `sector:druze`: as fitted.
- **Intervals for aggregates:** for replicate b, sum each fit's b-th vote matrix (use the main fit for `no_interval` fits), then take the 5th/95th percentiles of the votes per link. The rate interval is that interval divided by the row total.

## Outputs

- `out/diagnostics_units.csv`, one row per pair × region:
  - n_units;
  - coverage of bzb in a and in b;
  - units dropped by the bzb rule (place or number level);
  - units dropped by the replacement filter;
  - sector unit counts.
- `out/diagnostics_summary.txt`:
  - national coverage per pair;
  - double-envelope votes per election;
  - any locality code in the elections that is missing from the CBS file (with its names);
  - runtime of each stage.
- `out/sanity.csv`: per fit and pair, the modelled later totals (Σ_i votes) vs the actual later totals of that region, for categories with ≥ 3% share. Include the max absolute percentage deviation.
- `out/web/index.json`: the ordered list of areas, `[{"id","name","kind"}]`:
  1. `national`;
  2. `sector:haredi`, `sector:arab`, `sector:druze`, `sector:general`;
  3. the large localities, in this order: ירושלים (3000), תל אביב -יפו (5000), חיפה (4000), באר שבע (9000) first, then all others sorted by Hebrew name (plain Unicode order of the stripped name).
- `out/web/data/<id>.json` for each area (use the locality code as the id for cities). Content:
  ```
  {"id","name","kind","pairs":{"19-20":{
      "from":[[name,family,total],...], "to":[[name,family,actual_total],...],
      "links":[[i,j,votes,rate_pct,lo_pct,hi_pct],...],
      "n_units":…, "coverage":…, "dropped_replacement":…, "no_interval":bool}, ...}}
  ```
  - Links: only those with votes ≥ 10. Round votes to integers and percentages to one decimal.
  - Families come from `config/parties.json`. Use `other` for `אחרים` and `dnv` for `לא הצביעו`.
  - Every pair key must be present for every area. If a fit could not run, put `null`.
- `out/sensitivity.csv`: rerun the `national` aggregate (no bootstrap) with T = 0.10 and T = 0.20. List the 20 largest cross-category national flows per pair under each T, next to the T = 0.15 value.

## Stages

- **Stage 1:** preparation, regions, matching, sectors, diagnostics (no model fits). Also the solver, plus the Holon validation. Then stop and report.
- **Stage 2:** all fits, bootstrap, aggregates, sanity, web JSON, sensitivity.

## Reference values for the Holon validation

These come from an earlier SLSQP fit of the same model with the same place method. Your category sets may differ slightly because of the 3% rule and the replacement filter, so expect agreement within about 3 percentage points on these large flows.

| Pair | Flow | Rate |
|---|---|---|
| 23-24 | כחול לבן → יש עתיד | ≈ 50% |
| 23-24 | כחול לבן → כחול לבן | ≈ 24% |
| 23-24 | הליכוד → הליכוד | ≈ 76% |
| 23-24 | ש"ס → ש"ס | ≈ 85% |
| 23-24 | ישראל ביתנו → ישראל ביתנו | ≈ 80% |
| 24-25 | הליכוד → הליכוד | ≈ 85% |
| 24-25 | הליכוד → הציונות הדתית | ≈ 13% |
| 24-25 | יש עתיד → יש עתיד | ≈ 82% |
| 24-25 | כחול לבן → המחנה הממלכתי | ≈ 72% |
| 24-25 | ש"ס → ש"ס | ≈ 97% |
