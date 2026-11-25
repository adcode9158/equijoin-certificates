# STATS-CEB workload extraction

The public release contains eight simplified Stack Exchange tables, 146 full benchmark queries and 2,603 recorded PostgreSQL subplan queries. The file `sources.json` identifies every downloaded file by immutable URL, byte size and SHA-256 digest. The benchmark authors describe the construction and selection of these SQL queries. [Benchmark repository](https://github.com/Nathaniel-Han/End-to-End-CardEst-Benchmark/tree/670cb8d4bf4cbfa32f94fdf17f33973d3fd67d1b) · [Han et al., PVLDB](https://doi.org/10.14778/3503585.3503586)

Run `python fetch.py` to obtain the source files, then `python extract.py` in a Python environment with DuckDB. The archived run used DuckDB 1.4.4 on Python 3.11. Paths are relative to each script. Input tables use CSV type inference with full-file sampling. Local predicates are executed as SQL, including their timestamp casts. SQL joins omit null keys.

The parser accepts a query if every input contributes one join column and all equality conditions connect the columns into a single equivalence class. It rejects multi-class joins and disconnected relations. It checks the predicate grammar of the complete release. Eligible occurrences comprise 89 full and 1,832 subplan queries. Sorting each input tuple by table, key and local predicates deduplicates repeated queries across both files, retaining 1,605 cases. Eighty-six are distinct full-query tuples, of which six are binary.

* `cases.jsonl` records stable case and input IDs, a representative original query, its exact cardinality, and all source occurrences. The source file type, line number and parent full-query number use one-based indexing.
* `frequencies.jsonl.gz` records 419 distinct filtered input maps. Each row identifies the SQL table, join column and local predicate and contains sorted pairs of non-null key and positive count.
* `summary.json` records coverage, arity and validation. Each answer was evaluated using a join of grouped SQL counts with 128-bit multiplication and checked by summing products in Python arbitrary-precision integers. Original SQL counts for 662 distinct cases with at most 100,000 answer rows agreed. The official labels of all 89 eligible full queries matched.

The benchmark supplies the local filters. The extraction pays the cost of evaluating them and grouping their keys in advance. Performance experiments with these maps therefore condition on availability of accurate filtered per-input statistics.
