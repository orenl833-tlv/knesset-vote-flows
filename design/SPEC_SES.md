# Stage 3: socioeconomic clusters × sector

This stage extends SPEC.md. The rules there still hold unless this file changes them.

## Input

`config/ses_clusters.csv`, columns `code,name,cluster,source`. It gives the CBS 2019 socioeconomic cluster (1–10) for each locality code, and covers 99.3% of the k25 electorate. Localities missing from it are left out of every cluster aggregate. Report their bzb share per election.

Cluster groups:

| Group | Clusters |
|---|---|
| `g1` | 1–3 |
| `g2` | 4–5 |
| `g3` | 6–7 |
| `g4` | 8–10 |

A combo is any non-empty set of groups. There are 15. Name a combo by joining its group ids in order, for example `g2g3`.

## 1. Keep the fitted matrices

Rerun the stage-2 fits. For every fit and pair, store the main transfer matrix P and all bootstrap replicates P_b, together with the fit's row and column category lists. Put them in `out/fits/<pair>/<fit-id>.npz`.

Make the bootstrap deterministic: seed each fit's RNG from a hash of (fit id, pair). Then check whether the existing out/web files are reproduced. If they are not identical, regenerate all of out/web and say so. Either way, every existing out/web output must still be produced exactly as specified in SPEC.md.

## 2. New fit family: `jewish:<region>`

This is like `general:<region>`, but the units are those whose sector is `general` or `haredi`. Transitional units stay excluded.

- A region with ≥ 15 such units gets its own fit.
- All other jewish units go to one pooled fit, `jewish:pooled`.
- Run the bootstrap as for the other fits.

## 3. Per-locality vote matrices

For locality L in region R, pair a→b and sector filter F, choose the fit:

| F | Fit |
|---|---|
| `all` | the fit `region:R`, or the type-pooled fallback fit if R is thin, as in stage 2 |
| `general` | `general:R` if it exists, else `general:pooled` |
| `jewish` | `jewish:R` if it exists, else `jewish:pooled` |
| `arab` | only localities with `דת יישוב` 2 or 3 that are not Druze; use their `all` fit. Other localities contribute nothing. |

Then:

- **Category totals of L in election a:** use only the ballots of L that belong to F. Use the ballot-level classification from SPEC.md (Haredi means h_a ≥ 0.60; Arab or Druze follow the locality rules). For `all`, use every ballot.
- **Map to the fit's categories:** use the same folding the fit used (its parties below 3% become `אחרים`).
- **Votes:** P × totals for the main estimate, and P_b × totals for each replicate b.

## 4. Aggregates

For each F in {all, general, jewish, arab}, each combo, and each pair:

- Sum the per-locality matrices of all localities whose cluster falls in the combo.
- Merge categories by display name, and take the intervals from the summed replicates, exactly as the national aggregate does.
- Write `out/web/data/ses-<F>-<combo>.json` in the same format as the other area files:
  - `kind: "ses"`;
  - `name`: Hebrew text, for example `אשכולות 4–5, 6–7 · מגזר כללי`.
  - `coverage` and `coverage_core`: the bzb share in election a of the included ballots that sit in matched units, and in non-residual matched units.
  - If no locality contributes, write `null` for that pair.
- Write `out/web/ses_index.json`: `{"filters": {"all": "כל המגזרים", "jewish": "יהודי (חרדי + כללי)", "general": "כללי", "arab": "ערבי"}, "groups": {"g1": "1–3", "g2": "4–5", "g3": "6–7", "g4": "8–10"}, "available": [list of ses ids that have at least one non-null pair]}`.
- Do not add these areas to index.json.

## Checks to report

1. `ses-all-g1g2g3g4` vs `national`: per pair, the largest absolute difference in any link's votes and in each "to" total. The only expected difference is the uncovered 0.7%.
2. For F = all, the four single-group areas summed link by link must equal `ses-all-g1g2g3g4` up to rounding.
3. The bzb share of each group per election, overall and per filter.
4. For each filter and single group, the 5 largest cross-category flows for 24-25, with intervals.
5. Runtime per step, whether out/web was reproduced exactly, the jewish-fit counts (own vs pooled), and every problem or shortcut.
