"""Measure the cost of eager compilation of every probe on the test schemas."""
from statistics import median
from time import perf_counter_ns

from run import decomposition, read_cohort, sql, write_csv


def prepare_probe(query, key_limit):
    dimension, fact, primary_key, foreign_key, condition, _ = decomposition(query)
    dimension_sql = (
        f"SELECT {sql(primary_key)} FROM {sql(dimension)} "
        f"WHERE {condition} LIMIT {key_limit + 1}"
    )
    return dimension_sql, sql(fact), sql(foreign_key)


def main():
    cohorts = read_cohort("test")
    records = []
    for schema, queries in cohorts.items():
        for query in queries:
            prepare_probe(query, 8)
        for repeat in range(5):
            start = perf_counter_ns()
            for query in queries:
                prepare_probe(query, 8)
            records.append(dict(schema=schema, repeat=repeat, queries=len(queries),
                                elapsed_ns=perf_counter_ns() - start))
    write_csv("front_end.csv", records)
    totals = [sum(row["elapsed_ns"] for row in records if row["repeat"] == repeat and
                  row["schema"] != "codebase_community") for repeat in range(5)]
    print(f"Primary cohort median eager compilation, B=100, K=8: {median(totals)/1e6:.2f} ms")


if __name__ == "__main__":
    main()
