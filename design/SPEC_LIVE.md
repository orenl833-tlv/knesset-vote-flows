# Stage 4: election night, Knesset 26 (pair 25-26)

This stage extends SPEC.md and SPEC_SES.md. Their rules still hold unless this file changes them. Never modify `out/web`, `out/site`, `out/fits` or anything a previous stage wrote. This stage writes only to `out/live/`.

## Input

- `config/parties.json` now has election "26": party codes, names, families and sector parties.
- The Knesset 26 results file is a per-ballot CSV in the same format as k22–k25, and should include `ריכוז`. Its path is a command-line argument; the default is `live/k26/latest.csv` (UTF-8). It may be partial: ballots not yet counted have `כשרים` = 0 and `מצביעים` = 0, or are missing altogether. Columns may differ slightly from k25, so look them up by name and fail with a clear message if a required one is missing.
- Envelope rows have `סמל ישוב` 9999 or `בזב` 0. Exclude them from modelling, as before.

## Partial counting

A k26 ballot is **counted** if `כשרים` > 0.

- **Units for 25-26:** use only counted k26 ballots. With the place method, a place takes part only if all its k26 ballots are counted. Its k25 side is all of its k25 ballots, as usual.
- **Votes:** keep votes = P × 2022 totals of the region (all its ballots). Each area is therefore a projection of the whole area, under the assumption that the counted units are representative.
- **"to" totals:** the modelled column sums, as before. Also write `to_counted`: the actual k26 totals of the counted ballots in the area.
- **Fields per area for 25-26:**
  - `counted_share`: the k25 bzb share of the area whose k26 ballots are counted.
  - `counted_ballots`: the number of counted k26 ballots.
  - `total_ballots`: the number of k26 ballots in the file for the area.
- **Thin regions:** a region with fewer than 12 units falls back to its type pool, as in stage 2. If even the pool has fewer than 12 units, the pair is null for every area that depends on it.

## Entry point: `scripts/live_update.py`

```
python3 -I scripts/live_update.py [--k26 PATH] [--boot B] [--workers 4]
```

1. Run only pair 25-26: matching, the replacement filter, sectors, and all fit families (region, general, jewish, haredi, arab, druze).
   - Bootstrap B (default 0). With B = 0 the intervals are null, and the page shows none.
   - Store the fits in `out/live/fits/25-26/`.
2. Build every area, using the same ids as out/web: national, the four sectors, the 99 cities, and the 60 ses areas.
   - For each area, read its existing file from `out/web/data/` and add the key `"25-26"`.
   - Write the result to `out/live/web/data/`, with the same file names.
   - Copy `index.json`, `ses_index.json` and `map.json` from out/web to out/live/web unchanged.
3. Write `out/live/web/live.json`:
   ```
   {"updated_utc", "k26_file", "counted_ballots", "total_ballots", "counted_share_national", "boot"}
   ```
4. Print the runtime of each step.

**Runtime targets** on 4 workers: B = 0 in under 2 minutes; B = 30 in under 10 minutes. If B = 0 misses its target, say where the time goes.

## Simulated night file (for testing): `scripts/make_sim26.py`

Build `data/sim/k26_sim_<pct>.csv` from `data/raw/k25.csv`. The result must look like a Knesset 26 file.

- **Rename the party columns** of 2022 to 2026 codes:

| 2022 code | 2026 code |
|---|---|
| מחל | מחל |
| פה | רק |
| כן | כן |
| ט | ט |
| שס | שס |
| ג | ג |
| ל | ל |
| עם | עם |
| ום | ודם |
| ד | ודם |
| אמת | אמת |
| מרצ | אמת |
| every other code | `זז` |

  Several 2022 columns map to the same 2026 code: sum them.
- **Add a little noise:** move 5% of the מחל votes in each ballot to `ב`, and 3% of the רק votes to `דרך`, rounding down.
- **Simulate a partial count:** keep a random <pct>% of the ballots counted (seeded). For the rest, set every vote column, `כשרים`, `מצביעים` and `פסולים` to 0, but keep `בזב`.
- Produce pct = 30 and pct = 100.

## Checks to report

Run the following:

1. `make_sim26.py`, then `live_update.py --k26 data/sim/k26_sim_100.csv --boot 0`.
   - Report the runtime.
   - **National:** the five largest 25-26 flows, and the modelled vs actual 2026 totals. With 100% counted these must agree as closely as the stage-2 sanity check does.
   - **Expected flows:** since the sim is a relabelled 2022, flows such as יש עתיד → ביחד and הליכוד → הליכוד must be close to 100% minus the noise. Report them.
2. The same with `k26_sim_30.csv --boot 0`: report the runtime, the national counted_share, and the same flows. They should be near the 100% run.
3. `k26_sim_30.csv --boot 30`: report the runtime.
4. Confirm that out/web, out/site and out/fits are unchanged: compare checksums before and after.
5. List every problem, ambiguity or shortcut.
