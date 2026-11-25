"""Compare archived BIRD fact weights to per-dimension-key SQLite joins."""
import csv
import json
import sqlite3
import sys
from pathlib import Path

from run import HERE, INPUTS, connect, decomposition, read_cohort, sql, write_csv
from bird_transfer import eligible, sqlglot

sys.path.insert(0, str(HERE.parent / "count_precision"))
from curve import PrecisionCurve


def minima(weights, passed):
    curve = PrecisionCurve(weights, passed, 100)
    return curve.minimum(len(passed)), curve.minimum(min(len(weights), len(passed) + 1))


def audit_row(db, archived, original, precision, stage):
    historical, passed, observed, dim, fact, reference = eligible(original, db)
    assert (reference, dim, fact, observed) == (
        archived["reference"], archived["dimension"], archived["fact"], int(archived["observed"])
    )
    _, _, dk, fk, _, fact_filter = decomposition(archived)
    tree = sqlglot.parse_one(reference, read="sqlite")
    from_join = sql(tree.args["from_"]) + " " + sql(tree.args["joins"][0])
    # Group by the original dimension-side operand; dimension predicates are intentionally absent.
    statement = f"SELECT {sql(dk)},count(*) {from_join} WHERE {fact_filter} GROUP BY {sql(dk)}"
    positive = dict(db.execute(statement))
    assert positive.keys() <= historical.keys()
    native = {key: positive.get(key, 0) for key in historical}
    native_actual = sum(native[key] for key in passed)
    assert native_actual == observed
    changed = [key for key in native if native[key] != historical[key]]
    old = new = ("", "")
    if observed <= 100:
        old = minima(historical, passed)
        new = minima(native, passed)
        p = precision[archived["dataset"], str(original["question_id"])]
        assert old == (int(p["exact"]), int(p["plus1"]))
    row = dict(stage=stage, schema=archived["dataset"], question_id=original["question_id"],
               dimension=dim, dimension_key=dk.name, fact=fact, fact_key=fk.name,
               dimension_keys=len(native), passing=len(passed), observed=observed,
               original_total=sum(historical.values()), sqlite_total=sum(native.values()),
               changed_keys=len(changed), changed_passing_keys=sum(key in passed for key in changed),
               original_min_exact=old[0], sqlite_min_exact=new[0],
               original_min_plus1=old[1], sqlite_min_plus1=new[1],
               reference=reference, native_weights_sql=statement)
    return row, [
        dict(schema=row["schema"], question_id=row["question_id"], key=key,
             passing=int(key in passed), original_weight=historical[key], sqlite_weight=native[key])
        for key in sorted(changed)
    ]


def check_silent_mismatch():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE dim(pk INTEGER PRIMARY KEY, selected INTEGER)")
    db.execute("CREATE TABLE fact(fk TEXT, use_row INTEGER)")
    db.executemany("INSERT INTO dim VALUES (?,?)", [(1, 1), (2, 0)])
    db.executemany("INSERT INTO fact VALUES (?,?)", [("02", 1)] * 101 + [("01", 0)])
    original = {"question_id": 1, "SQL":
        "SELECT COUNT(*) FROM dim AS d JOIN fact AS f ON f.fk = d.pk "
        "WHERE d.selected = 1 AND f.use_row = 1"}
    _, _, actual, dim, fact, reference = eligible(original, db)
    archived = dict(dataset="fixture", reference=reference, dimension=dim, fact=fact, observed=actual)
    row, changes = audit_row(db, archived, original, {("fixture", "1"): {"exact": 0, "plus1": 0}},
                             "fixture")
    assert actual == 0 and len(changes) == 1
    assert (changes[0]["key"], changes[0]["sqlite_weight"], changes[0]["passing"]) == (2, 101, 0)
    assert row["sqlite_min_exact"] == row["sqlite_min_plus1"] == 1
    db.close()


def main():
    check_silent_mismatch()
    dev_rows = json.loads((INPUTS / "dev.json").read_text(encoding="utf-8"))
    originals = {(row["db_id"], str(row["question_id"])): row for row in dev_rows}
    with (HERE.parent / "count_precision" / "precision.csv").open(encoding="utf8", newline="") as f:
        precision = {(row["source"], row["case_id"]): row for row in csv.DictReader(f)}
    results = []
    changes = []
    for stage in ("pilot", "test"):
        for schema, cohort in read_cohort(stage).items():
            path = INPUTS / (schema + ".sqlite")
            wal = Path(str(path) + "-wal")
            assert not wal.exists() or not wal.stat().st_size
            db = connect(path, True)
            for archived in cohort:
                row, keys = audit_row(db, archived, originals[schema, archived["question_id"]],
                                      precision, stage)
                results.append(row)
                changes.extend(keys)
            db.close()
            print(stage, schema, len(cohort), flush=True)
    write_csv("affinity-audit.csv", results)
    with (HERE / "affinity-changed-keys.csv").open("w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=["schema", "question_id", "key", "passing",
                                          "original_weight", "sqlite_weight"])
        w.writeheader()
        w.writerows(changes)
    summaries = []
    for group, subset in [("all", results), ("pilot", [r for r in results if r["stage"] == "pilot"]),
                          ("test", [r for r in results if r["stage"] == "test"])]:
        summaries.append(dict(cohort=group, joins=len(subset),
            dimension_key_query_pairs=sum(r["dimension_keys"] for r in subset),
            joins_with_changed_keys=sum(bool(r["changed_keys"]) for r in subset),
            changed_key_query_pairs=sum(r["changed_keys"] for r in subset),
            changed_passing_key_query_pairs=sum(r["changed_passing_keys"] for r in subset),
            fits_at_100=sum(r["observed"] <= 100 for r in subset),
            changed_exact_min=sum(r["original_min_exact"] != r["sqlite_min_exact"] for r in subset),
            changed_plus1_min=sum(r["original_min_plus1"] != r["sqlite_min_plus1"] for r in subset)))
    write_csv("affinity-summary.csv", summaries)
    print(summaries, flush=True)


if __name__ == "__main__":
    main()
