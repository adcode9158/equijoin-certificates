# Equijoin size experiments

How large can a join be when each input gives exact counts for frequent keys and summarizes the rest? This repository contains the packing solver, workloads, and measurements used to study that question. It also includes experiments on how many key memberships a query service must read to decide whether a join fits a row budget, and how that decision affects execution in SQLite and DuckDB.

## Run a join

Run the solver from the repository root in a Python 3.11 environment.

~~~sh
python -m pip install numpy scipy==1.16.3
python packing/solve.py --case query-0007
~~~

This three-input STATS-CEB join uses the filtered key counts bundled in `packing/supplement.zip`. The solver prints one JSON record with `lower` and `upper` both equal to **1,158,858 rows**. A database compatible with the input summaries achieves that size, and the upper bound rules out a larger join. Use `--all` in place of `--case query-0007` to run all 1,605 cases. [Solver and STATS-CEB input guide](packing/README.md)

## Experiments and data

- **Membership and execution.** The experiment drivers cover key lookups on BIRD and Spider, capped SQL versus exact traversal, and memory-limit choices for ordered-window queries in DuckDB. The guide specifies which upstream databases, engine versions, and build steps each run needs. [Experiment guide](experiments/README.md)
- **Held-out queries.** Per-query admissions and catalog sizes are recorded for STATS-CEB and two Lahman snapshots. [Held-out results](heldout-results/)
- **Request streams.** The SDSS, SQLShare, and classroom SQLite measurements include per-request outcomes and six paired timing runs. Their original end-to-end timing harness is incomplete. The recorded runs can be summarized with `python check_results.py`. [Timing data and protocols](evidence/)
- **Figures.** To plot observed join sizes against their witnesses for the 86 STATS-CEB full queries, install Matplotlib and NumPy and run `python figures/plot_admission.py`. It writes `figures/admission-witnesses.pdf`. [Plotting scripts](figures/)

The classroom SQLite measurements derive from the ICPC 2022 replication package by Daphne Miedema, George Fletcher, and Efthimia Aivaloglou. [Original dataset and license](https://doi.org/10.6084/m9.figshare.19430375.v2)
