# Equijoin experiments

These experiments measure the cost of membership queries and compare execution strategies for joins under row and memory limits. Run the commands from the repository root. Use a working copy for a new run because some drivers write to the same paths as the recorded measurements.

| Experiment | Implementation and evidence under `experiments/fresh_join/` |
|---|---|
| STATS membership certificates and counterexamples | `impact_schema/` contains the per-instance calculation, filter-row swap and tie-prefix checks, and their per-query results. |
| BIRD and Spider | `impact_transfer/` selects the eligible BIRD joins. The two `*-metrics.csv` files retain the measurements by dataset, question and budget. `count_precision/` measures the effects of count precision and the histogram. `uncertain_counts/` contains the count-capacity and one-total routines. `decision_validation/` contains the minimax decision rule, the Spider census, and per-query prices. `decision_audit/` holds the independent small-instance checks. |
| Capped SQL and exact traversal | `multiway_joins/` contains the C++17 traversal, fixture builder, and complete STATS rotation timings. `engine_benchmarks/` contains the grouped-count SQL comparison, joined-column summaries, and the initial memory-limit measurements. `decision_transfer/` contains the matched BIRD SQLite tests, pilot selection, affinity checks and measured times. |
| DuckDB memory-limit choices | `decision_operator/` contains the C++ router, selection and calibration code, protocols, the two disjoint cohorts, paired measurements, and live retry results. The live results include the failed low-memory attempts. |

## STATS inputs and physical runs

The fetcher downloads the STATS-CEB inputs and checks their SHA-256 hashes against the pinned manifest. The fixture builder reads the benchmark rows and the query descriptions in `packing/supplement.zip`. It requires a little-endian system with 64-bit integers. The C++ code uses a compiler supporting unsigned 128-bit integers, such as GCC.

```sh
python packing/workload/fetch.py
mkdir -p run
python experiments/fresh_join/multiway_joins/prepare.py packing packing/workload/raw run/fixture
g++ -O3 -std=c++17 -DNDEBUG experiments/fresh_join/multiway_joins/bench.cpp -o run/bench
run/bench run/fixture run/traversal.csv 8
g++ -O3 -std=c++17 -DNDEBUG experiments/fresh_join/decision_operator/router.cpp -o run/router
```

For the DuckDB ordered-window experiments, use the Python package for **DuckDB 2.0.1**. The following POSIX-shell commands pass the installed package directory to the existing runner. The archived system used two passes. Timings, spills and out-of-memory behavior depend on the engine version and machine.

```sh
DRIVER_LIB=$(python -c 'import duckdb; from pathlib import Path; print(Path(duckdb.__file__).resolve().parent.parent)')
python experiments/fresh_join/decision_operator/validate.py packing "$DRIVER_LIB" run/fixture run/router
python experiments/fresh_join/decision_operator/summarize.py
python experiments/fresh_join/decision_operator/validate.py --replicate packing "$DRIVER_LIB" run/fixture run/router
python experiments/fresh_join/decision_operator/summarize.py --replicate
python experiments/fresh_join/decision_operator/live.py packing "$DRIVER_LIB" run/fixture run/router
```

## BIRD and Spider inputs

Obtain the June 2024 **BIRD development** release and the **Spider 1.0 development** split from their publishers. For each dataset place its original `dev.json` and its development databases at `experiments/inputs/bird/<db_id>.sqlite` or `experiments/inputs/spider/<db_id>.sqlite`, alongside the corresponding JSON file. The SQLite snapshots used for these tests must be fully checkpointed. Install `sqlglot==28.10.1` in the Python environment. [BIRD](https://bird-bench.github.io/) · [Spider](https://yale-lily.github.io/spider)

```sh
python experiments/fresh_join/impact_transfer/bird_transfer.py
python experiments/fresh_join/impact_transfer/bird_holdout.py
python experiments/fresh_join/count_precision/evaluate.py packing
python experiments/fresh_join/decision_validation/online.py
python experiments/fresh_join/decision_validation/validate.py
python experiments/fresh_join/decision_transfer/run.py
python experiments/fresh_join/decision_transfer/summarize.py
```

The first two commands reconstruct local normalized SQL from upstream inputs. The published measurement projections omit the source SQL and display-name literals. For the badge example, the independent check reads the filter from BIRD question 552.

## Recorded runs and small-instance checks

The repository includes held-out-template decisions and six paired timing runs for each SDSS, SQLShare and classroom SQLite replay setting. The full original arrival-stream harness and snapshots are unavailable here. The paired timing blocks support recalculation of each policy's measured cost.

The following commands enumerate small instances or compare their certificate sizes. They use Python 3.10 or later and run offline.

```sh
python experiments/fresh_join/count_precision/check.py
python experiments/fresh_join/impact_schema/check_dimension_certificates.py
python experiments/fresh_join/uncertain_counts/check_small.py
```
