# Packing bounds on STATS-CEB

This directory contains the integer-packing implementation, the STATS-CEB filtered key-frequency maps, and the certificates for the 51-word catalog experiment. Run the commands below from the repository root.

## Run the solver

The solver requires NumPy and SciPy. The reported experiments used Python 3.11 and SciPy 1.16.3 with HiGHS. The following commands produce JSON Lines on standard output.

~~~sh
python packing/solve.py --case query-0007
python packing/solve.py --all > initial.jsonl
python packing/solve.py --refine-open > refined.jsonl
~~~

The first command runs a three-input join with a certified maximum of 1,158,858 rows. The second solves all 1,605 cases at the original 40-round limit. The third applies an integer optimization pass to the six cases left open in the recorded initial run. Solver and platform differences can change the chosen witness and timing. Each output record contains the case ID, attainable lower bound, certified upper bound and, for multiway cases, the selected column multiplicities and scaled integer prices.

The solver lives in [profile_solver.py](profile_solver.py). It builds the catalog, generates columns, constructs feasible assignments, and rounds and checks candidate prices. [pricing.py](pricing.py) implements pricing over sums of planar convex hulls. [bounds.py](bounds.py), [combined.py](combined.py), [compressed_degree.py](compressed_degree.py) and [baselines.py](baselines.py) supply binary matching, three-counter bounds, the direct formula and rank-block decoding. The command-line driver reads case IDs and their filtered key counts from the bundled inputs.

## Inputs and benchmark extraction

[supplement.zip](supplement.zip) contains seven files. The two JSON Lines input files describe filtered integer join-key frequencies and benchmark case membership. The two certificate files record the initial and refined solutions. Three CSV files contain the corresponding endpoints and the final comparison. ZIP compression uses LZMA. Python can extract the archive with the following command.

~~~sh
python -m zipfile -e packing/supplement.zip extracted-packing
~~~

The numerical inputs are derived from the eight simplified Stack Exchange tables and SQL workload released with STATS-CEB. The source manifest pins the upstream revision, file sizes and SHA-256 hashes. The public maps retain the benchmark's integer keys so their frequencies can also be matched to the engine replays. Each map contains its table, join column, filter, keyed row counts and input ID. Filters use numerical or timestamp comparisons. The original table rows can be obtained from the benchmark authors. [STATS-CEB release](https://github.com/Nathaniel-Han/End-to-End-CardEst-Benchmark/tree/670cb8d4bf4cbfa32f94fdf17f33973d3fd67d1b) · [Han et al., PVLDB](https://doi.org/10.14778/3503585.3503586)

To repeat the SQL extraction, install DuckDB 1.4.4 for Python and run the following commands. The first downloads and checks the published benchmark source files. The second rebuilds the maps and checks available cardinalities. The last compares the resulting maps, conditions, row counts and workload occurrences with those in this release.

~~~sh
python packing/workload/fetch.py
python packing/workload/extract.py
python packing/workload/check_inputs.py
~~~

## Verify the recorded experiment

Use Python 3.10 or later with the standard library, including LZMA support.

~~~sh
python evidence/verify_packing.py packing/supplement.zip
~~~

The checker reconstructs the exact frequent-key lists and residual-degree encodings from 419 input maps. For binary joins it calculates the optimum by sorting. For multiway joins it checks the witness allocation and every dual inequality using integer arithmetic, independently of the optimization solver.

The expected output includes 1,605 distinct cases, 438 binary optima and 1,599 closed intervals. The checker evaluates 25,117,918 inequalities for the initial certificates and another 691,186 for the six refined intervals. Of the 59 full queries whose observed results fit ten million rows, 18 are certified and 41 have compatible over-budget witnesses.
