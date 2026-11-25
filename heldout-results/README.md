# Held-out join results

These two files supply the data for Table 4, admissions on previously unseen templates.

`decisions.csv` contains 1,604 canonical STATS-CEB cases and 330 Lahman cases for each of two snapshots (2,264 rows). The same 330 Lahman case IDs repeat for 2024 and 2025. Identify a row by dataset, snapshot and case ID. On STATS-CEB, `fold` identifies the held-out join template and `full=1` identifies a full query. On Lahman, `snapshot` is the final included season. Empty fields mean inapplicable. The area-plus-equality method was reported only on STATS-CEB.

`actual` is the observed join cardinality. The row budget is 10,000,000 on STATS-CEB and 1,000,000 on Lahman. A method column contains 1 for certification and 0 for abstention. To reproduce each count, sum the method column for the relevant dataset/snapshot, additionally filtering on `full=1` for the STATS-CEB full column. Denominators count rows with `actual` at or below the budget.

`serialized-bytes.csv` contains one row per STATS-CEB deployment (59 folds) and one per Lahman deployment (two snapshots). Each numeric method entry is its complete serialized catalog size, including the baseline. Take each STATS-CEB column's median over the 59 folds. The Lahman values are reported directly by year, using the complete train-inferred template domain and the 16,144-byte capacity.

| Column | Statistic available to the certifier |
|---|---|
| `single_column` | Unfiltered join and single-column prefix/suffix endpoints. |
| `four_equal_groups` | Single-column baseline plus up to four equal-count groups of ordered unsafe corners for a cross-input predicate pair. |
| `four_area_plus_equality` | Single-column baseline plus area-selected groups of corners and low-cardinality equality slices, ranked together. |
| `nonnull_first_then_equality` | Single-column baseline plus all retained endpoints conditional on the partner column being nonnull, followed by affordable equality slices. Lahman training supplied no eligible cross-input equality pair. |

Run `python check_results.py` from the artifact root to recompute the admissions and summarize serialized sizes for all three dataset snapshots.
