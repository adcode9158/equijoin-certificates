"""Physically time safe join admission on the existing BIRD filtered-join cohort.

Native SQL runs against immutable original databases. Separate TEMP structures
supply a reusable frequency summary and a matched FK-to-row index.
"""
import argparse
import csv
import hashlib
import math
import platform
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from time import perf_counter_ns

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "impact_transfer"))
from bird_transfer import INPUTS, atoms, exp, sql, sqlglot


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def now():
    return perf_counter_ns()


def elapsed(start):
    return (now() - start) / 1_000_000


def decomposition(row):
    tree = sqlglot.parse_one(row["reference"], read="sqlite")
    join = tree.args["joins"][0]
    tables = [tree.args["from_"].this, join.this]
    dim = next(t for t in tables if t.name == row["dimension"])
    fact = next(t for t in tables if t.name == row["fact"])
    aliases = [dim.alias_or_name.lower(), fact.alias_or_name.lower()]
    keys = {c.table.lower(): c for c in (join.args["on"].this, join.args["on"].expression)}
    filters = defaultdict(list)
    for atom in atoms(tree.args["where"].this):
        alias, = {col.table.lower() for col in atom.find_all(exp.Column)}
        filters[alias].append("(" + sql(atom) + ")")
    select = lambda alias: " AND ".join(filters[alias]) or "1"
    return (dim, fact, keys[aliases[0]], keys[aliases[1]], select(aliases[0]), select(aliases[1]))


def budget_query(rows_sql, budget):
    return f"SELECT NOT EXISTS(SELECT 1 {rows_sql} LIMIT 1 OFFSET {budget})"


def native_index(db, table, key):
    info = list(db.execute("PRAGMA table_info(" + quote(table) + ")"))
    pks = [r for r in info if r[5] > 0]
    if len(pks) == 1 and pks[0][1].lower() == key.lower() and pks[0][2].upper() == "INTEGER":
        return True
    for entry in db.execute("PRAGMA index_list(" + quote(table) + ")"):
        if entry[4]:
            continue
        cols = list(db.execute("PRAGMA index_info(" + quote(entry[1]) + ")"))
        if cols and str(cols[0][2]).lower() == key.lower():
            return True
    return False


def prepare(db, queries):
    structures = {}
    builds = []
    for table,key in sorted({(q["fact"],q["parts"][3].name) for q in queries}):
        n = len(structures)
        tab, col = quote(table), quote(key)
        syn, ind = "degree_" + str(n), "fk_" + str(n)
        indexed = native_index(db, table, key)
        start = now()
        db.execute(f"CREATE TEMP TABLE {syn}(k INTEGER PRIMARY KEY,w INTEGER NOT NULL) WITHOUT ROWID")
        db.execute(f"INSERT INTO {syn} SELECT {col},count(*) FROM {tab} WHERE {col} IS NOT NULL GROUP BY {col}")
        syn_ms = elapsed(start)
        # Like a conventional covering FK index, it stores one key/rowid pair per fact row.
        idx_ms = 0
        if not indexed:
            start = now()
            db.execute(f"CREATE TEMP TABLE {ind}(k INTEGER NOT NULL,r INTEGER NOT NULL,PRIMARY KEY(k,r)) WITHOUT ROWID")
            db.execute(f"INSERT INTO {ind} SELECT {col},rowid FROM {tab} WHERE {col} IS NOT NULL")
            idx_ms = elapsed(start)
        structures[table,key] = (syn, ind, indexed)
        nodes, base_rows, largest = db.execute(f"SELECT count(*),coalesce(sum(w),0),coalesce(max(w),0) FROM {syn}").fetchone()
        builds.append(dict(fact=table, key=key, groups=nodes, nonnull_rows=base_rows, max_degree=largest,
                           already_indexed=int(indexed), degree_build_ms=syn_ms, index_build_ms=idx_ms))
    return structures, builds


def methods(db, row, structures, budget):
    dim, fact, dk, fk, dwhere, fwhere = row["parts"]
    syn, idx, indexed = structures[fact.name,fk.name]
    # The supplied COUNT SQL is a normalized original FROM/JOIN/WHERE expression.
    body = row["reference"][len("SELECT COUNT(*) "):]
    capped = budget_query(body,budget)
    exact = f"SELECT ({row['reference']})<={budget}"
    dimsql, dksql = sql(dim), sql(dk)
    via_index = capped
    if not indexed:
        source = f"FROM {dimsql} JOIN {idx} AS i ON i.k={dksql}"
        if fwhere != "1":
            source += f" JOIN {sql(fact)} ON {quote(fact.alias_or_name)}.rowid=i.r"
        via_index = budget_query(source + f" WHERE {dwhere} AND {fwhere}",budget)
    weight_sql = f"SELECT s.w FROM {dimsql} JOIN {syn} AS s ON s.k={dksql} WHERE {dwhere}"
    sum_sql = f"SELECT coalesce(sum(s.w),0) FROM {dimsql} JOIN {syn} AS s ON s.k={dksql} WHERE {dwhere}"

    def scalar(stmt):
        return db.execute(stmt).fetchone()[0]

    def by_weight(fallback=capped):
        total = 0
        for (w,) in db.execute(weight_sql):
            total += w
            if total > budget:
                if fwhere == "1":
                    return False, "compressed-reject"
                return bool(scalar(fallback)), "fallback"
        return True, "upper-admit"

    def full_weight():
        upper = scalar(sum_sql)
        if upper <= budget:
            return True, "upper-admit"
        if fwhere == "1":
            return False, "compressed-reject"
        return bool(scalar(capped)), "fallback"

    def conservative():
        if fwhere == "1":
            return by_weight()
        return bool(scalar(capped)), "direct"

    return {
        "count": lambda: (bool(scalar(exact)), "count"),
        "cap": lambda: (bool(scalar(capped)), "cap"),
        "indexed_cap": lambda: (bool(scalar(via_index)), "indexed-cap"),
        "degree_stream": by_weight,
        "degree_sum": full_weight,
        "degree_if_unfiltered": conservative,
    }


def load_rows(scope, budget):
    data = defaultdict(list)
    seen = set()
    files = {"pilot":"bird-results.csv","holdout":"bird-holdout-results.csv"}
    for group, file in files.items():
        if scope != "all" and scope != group:
            continue
        with (HERE.parent/"impact_transfer"/file).open(encoding="utf-8-sig",newline="") as f:
            for row in csv.DictReader(f):
                if int(row["budget"]) != budget: continue
                token = row["dataset"],row["reference"]
                if token in seen: continue
                seen.add(token)
                start = now()
                parts = decomposition(row)
                row.update(parts=parts, parse_ms=elapsed(start),scope=group)
                data[row["dataset"]].append(row)
    return data


def save(path, rows):
    with path.open("w",newline="",encoding="utf-8") as file:
        out = csv.DictWriter(file,fieldnames=list(rows[0]))
        out.writeheader()
        out.writerows(rows)


def run(scope, budget, rounds):
    data = load_rows(scope,budget)
    timings,admissions,builds = [],[],[]
    for dataset, rows in data.items():
        path = INPUTS/(dataset + ".sqlite")
        wal = Path(str(path)+"-wal")
        assert not wal.exists() or not wal.stat().st_size
        db = sqlite3.connect(path.as_uri()+"?mode=ro&immutable=1",uri=True,cached_statements=0)
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA cache_size=-65536")
        banks,built = prepare(db, rows)
        for r in built: builds.append(dict(dataset=dataset,**r))
        for i,q in enumerate(rows):
            routines = methods(db,q,banks,budget)
            names = list(routines)
            common = dict(dataset=dataset,question=q["question_id"],fact=q["fact"],key=q["parts"][3].name,
                          filtered_fact=int(q["parts"][5]!="1"), budget=budget,truth=q["observed"])
            for repeat in range(-1, rounds):
                offset = (i+repeat)%len(names)
                for name in names[offset:]+names[:offset]:
                    start = now()
                    answer,reason = routines[name]()
                    ms = elapsed(start)
                    assert answer == (int(q["observed"])<=budget),(dataset,q["question_id"],name,answer)
                    if repeat >= 0:
                        timings.append(dict(**common,round=repeat,method=name,ms=ms))
                    if repeat == 0:
                        admissions.append(dict(**common,method=name,reason=reason,parse_ms=q["parse_ms"]))
        db.close()
        print(dataset,len(rows),"done",flush=True)
    stem = f"{scope}-{budget}"
    save(HERE/(stem+"-timings.csv"),timings)
    save(HERE/(stem+"-decisions.csv"),admissions)
    save(HERE/(stem+"-builds.csv"),builds)


if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scope",choices=["pilot","holdout","all"],default="holdout")
    p.add_argument("--budget",type=int,default=100)
    p.add_argument("--rounds",type=int,default=3)
    args=p.parse_args()
    run(args.scope,args.budget,args.rounds)

