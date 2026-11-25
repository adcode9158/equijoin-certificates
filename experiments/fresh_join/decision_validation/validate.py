"""Reproduce the Spider census and singleton-assignment tests in PROTOCOL.md."""
import csv
import itertools
import json
import sqlite3
import sys
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
FRESH = HERE.parent
ROOT = FRESH.parent
sys.path[:0] = [str(FRESH / "impact_transfer"), str(FRESH / "count_precision")]
from bird_transfer import eligible, atoms, exp, sqlglot, sql
from curve import PrecisionCurve

BIRD = ROOT / "inputs" / "bird"
SPIDER = ROOT / "inputs" / "spider"
BUDGETS = (10, 100, 1000, 10_000, 100_000)


def db_open(directory, name):
    return sqlite3.connect((directory / (name + ".sqlite")).as_uri() + "?mode=ro&immutable=1", uri=True)


def dump(name, rows):
    with (HERE / (name + ".csv")).open("w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def table_info(db, name):
    escaped = name.replace('"', '""')
    return list(db.execute(f'PRAGMA table_info("{escaped}")'))


def inspect_spider(query, db):
    tree = sqlglot.parse_one(query, read="sqlite")
    if not isinstance(tree, exp.Select) or len(list(tree.find_all(exp.Select))) != 1:
        return
    joins = tree.args.get("joins", [])
    if len(joins) != 1 or tree.args.get("where") is None or not tree.args.get("from_"):
        return
    join = joins[0]
    on = join.args.get("on")
    if (join.args.get("side") or (join.args.get("kind") or "").upper() not in ("", "INNER")
            or not isinstance(on, exp.EQ) or not all(isinstance(c, exp.Column) for c in (on.this, on.expression))):
        return
    tables = [tree.args["from_"].this, join.this]
    if not all(isinstance(t, exp.Table) for t in tables) or tables[0].name.lower() == tables[1].name.lower():
        return
    infos = [table_info(db, t.name) for t in tables]
    aliases = [t.alias_or_name.lower() for t in tables]
    if len(set(aliases)) != 2:
        return
    names = [{p[1].lower() for p in info} for info in infos]
    original = "SELECT count(*) " + " ".join(x.sql(dialect="sqlite") for x in (tree.args["from_"], join, tree.args["where"]))
    for node in (on, tree.args["where"]):
        for col in node.find_all(exp.Column):
            if col.table:
                if col.table.lower() not in aliases or col.name.lower() not in names[aliases.index(col.table.lower())]:
                    return
            else:
                owners = [i for i in (0, 1) if col.name.lower() in names[i]]
                if len(owners) != 1:
                    return
                col.set("table", exp.to_identifier(aliases[owners[0]]))
    keys = {c.table.lower(): c for c in (on.this, on.expression)}
    if set(keys) != set(aliases):
        return
    conditions = defaultdict(list)
    for cond in atoms(tree.args["where"].this):
        owners = {c.table.lower() for c in cond.find_all(exp.Column)}
        if len(owners) != 1:
            return
        conditions[owners.pop()].append(cond)
    for di, info in enumerate(infos):
        pk = [p for p in info if p[5]]
        if conditions[aliases[di]] and len(pk) == 1 and pk[0][1].lower() == keys[aliases[di]].name.lower():
            break
    else:
        return
    fa = 1 - di
    d, f = aliases[di], aliases[fa]
    if any(c.name.lower() == keys[d].name.lower() for cond in conditions[d] for c in cond.find_all(exp.Column)):
        return
    dim, fact = sql(tables[di]), sql(tables[fa])
    dk, fk = sql(keys[d]), sql(keys[f])
    dw = " AND ".join("(" + sql(x) + ")" for x in conditions[d])
    fw = " AND ".join("(" + sql(x) + ")" for x in conditions[f]) or "TRUE"
    domain = [x for x, in db.execute(f"select {dk} from {dim}")]
    if None in domain or len(set(domain)) != len(domain):
        return
    passed = {x for x, in db.execute(f"select {dk} from {dim} where {dw}")}
    grouped = dict(db.execute(f"select {fk},count(*) from {fact} where {fw} group by {fk}"))
    weights = {x: grouped.get(x, 0) for x in domain}
    # This diagnostic runs outside preflight timing. SQLite may equate a
    # text FK with a numeric PK, including on non-passing dimension keys.
    joined = dict(db.execute(f"select {dk},count(*) from {dim} join {fact} on {sql(on)} where {fw} group by {dk}"))
    sql_weights = {x: joined.get(x, 0) for x in domain}
    affinity_keys = sum(weights[x] != sql_weights[x] for x in domain)
    actual = db.execute(original).fetchone()[0]
    assert actual == sum(sql_weights[x] for x in passed)
    def canonical(cond):
        copy = cond.copy()
        for col in copy.find_all(exp.Column):
            col.set("table", exp.to_identifier(tables[aliases.index(col.table.lower())].name.lower()))
            col.set("this", exp.to_identifier(col.name.lower()))
        return sql(copy)
    signature = [tables[di].name.lower(), keys[d].name.lower(), tables[fa].name.lower(), keys[f].name.lower(),
                 sorted(canonical(c) for c in conditions[d]), sorted(canonical(c) for c in conditions[f])]
    return sql_weights, passed, actual, tables[di].name, tables[fa].name, original, json.dumps(signature), affinity_keys


def singleton_cost(ordered, value, budget):
    threshold = budget - value
    split = bisect_right(ordered, threshold)
    compulsory = len(ordered) - split - int(value > threshold)
    left = ordered[max(0, split - 2):split]
    if value > threshold:
        left = left + [value]
    residual = sum(sorted(left)[-2:])
    return compulsory + int(residual > budget)


def singleton_row(corpus, dbid, qid, weights, passed, budget):
    if len(passed) != 1 or len(weights) < 1:
        return
    actual = next(iter(passed))
    if weights[actual] > budget:
        return
    ordered = sorted(weights.values())
    costs = {w: singleton_cost(ordered, w, budget) for w in set(ordered) if w <= budget}
    by_key = {k: costs[w] for k, w in weights.items() if w <= budget}
    cheapest = min(by_key, key=lambda k:(by_key[k], k))
    dearest = max(by_key, key=lambda k:(by_key[k], k))
    for k in {actual, cheapest, dearest}:
        independent = PrecisionCurve(weights, {k}, budget).minimum(min(2, len(weights)))
        assert independent == by_key[k], (dbid, qid, independent, by_key[k])
    return dict(corpus=corpus, db=dbid, question=qid, keys=len(weights), fitting_singletons=len(by_key),
                actual_key=actual, actual_weight=weights[actual], actual_cost=by_key[actual],
                cheapest_key=cheapest, cheapest_weight=weights[cheapest], min_cost=by_key[cheapest],
                median_cost=median(by_key.values()), max_cost=by_key[dearest], dearest_key=dearest,
                below_actual=sum(v < by_key[actual] for v in by_key.values()),
                above_actual=sum(v > by_key[actual] for v in by_key.values()))


def tiny():
    count = 0
    for n in range(1, 6):
        keys = set(range(n))
        worlds = [set(x) for j in range(min(2, n) + 1) for x in itertools.combinations(keys, j)]
        sets = [set(x) for j in range(n + 1) for x in itertools.combinations(keys, j)]
        for ws in itertools.combinations_with_replacement((0, 1, 3), n):
            for i in keys:
                for b in (0, 1, 2, 3, 4):
                    if ws[i] > b:
                        continue
                    bad = [w for w in worlds if sum(ws[k] for k in w) > b]
                    optimum = next(len(s) for s in sets if all((s & {i}) != (s & w) for w in bad))
                    assert optimum == singleton_cost(list(ws), ws[i], b)
                    count += 1
    return count


def main():
    checks = tiny()
    by_id = defaultdict(list)
    spider_rows = json.loads((SPIDER/"dev.json").read_text(encoding="utf-8"))
    for idx, row in enumerate(spider_rows):
        by_id[row["db_id"]].append((idx, row["query"]))
    census, priced, singles, errors = [], [], [], []
    for dbid, entries in by_id.items():
        with db_open(SPIDER, dbid) as db:
            seen, strict_seen = {}, set()
            extended_count = strict_count = 0
            for idx, q in entries:
                try:
                    old = eligible({"SQL": q}, db)
                except (sqlite3.Error, AssertionError, sqlglot.errors.ParseError) as exc:
                    errors.append(dict(db=dbid, question=idx, parser="previous", detail=repr(exc)))
                    old = None
                try:
                    item = inspect_spider(q, db)
                except (sqlite3.Error, ValueError, sqlglot.errors.ParseError) as exc:
                    errors.append(dict(db=dbid, question=idx, parser="extended", detail=repr(exc)))
                    item = None
                if not item:
                    assert old is None, (dbid, idx)
                    continue
                weights, passed, actual, dim, fact, reference, sig, affinity_keys = item
                extended_count += 1
                if old:
                    assert old[1:3] == item[1:3] and (affinity_keys or old[0] == weights), (dbid, idx)
                    strict_seen.add(sig)
                    strict_count += 1
                if sig not in seen:
                    seen[sig] = (idx, item)
                else:
                    assert seen[sig][1][:3] == item[:3]
            for sig, (idx, item) in seen.items():
                weights, passed, actual, dim, fact, reference, _, affinity_keys = item
                single = singleton_row("Spider", dbid, idx, weights, passed, 100)
                if single:
                    singles.append(single)
                for b in BUDGETS:
                    minimum = one = none = None
                    if actual <= b:
                        curve = PrecisionCurve(weights, passed, b)
                        minimum, one, none = [curve.minimum(u) for u in (len(passed), min(len(weights), len(passed)+1), len(weights))]
                        assert 0 <= minimum <= one <= none <= len(weights)
                    priced.append(dict(db=dbid, question_index=idx, original_parser=int(sig in strict_seen), affinity_keys=affinity_keys, dim=dim, fact=fact,
                                       domain=len(weights), passed=len(passed), actual=actual, budget=b,
                                       exact_count=minimum, plus_one=one, uncapped=none, gold_intermediate_sql=reference))
            census.append(dict(db=dbid, questions=len(entries), original_questions=strict_count, extended_questions=extended_count,
                               original_unique=len(strict_seen), extended_unique=len(seen)))
    bird = {str(r["question_id"]): r for r in json.loads((BIRD/"dev.json").read_text(encoding="utf-8"))}
    seen = set()
    for file in ("bird-results.csv", "bird-holdout-results.csv"):
        with (FRESH/"impact_transfer"/file).open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["budget"] != "100" or row["passed"] != "1" or row["admitted"] != "1":
                    continue
                identity = (row["dataset"], row["reference"])
                if identity in seen:
                    continue
                seen.add(identity)
                with db_open(BIRD, row["dataset"]) as db:
                    item = eligible(bird[row["question_id"]], db)
                singles.append(singleton_row("BIRD", row["dataset"], row["question_id"], *item[:2], 100))
    badge = next(s for s in singles if s["db"] == "codebase_community" and str(s["question"]) in ("551", "552"))
    with db_open(BIRD, "codebase_community") as db:
        orig, alt = badge["actual_key"], badge["cheapest_key"]
        weight_map = eligible(bird["552"], db)[0]
        ordered = sorted(weight_map.values())
        # The minimum-cost example with positive output allows a second check
        # that does not depend on moving the display name to a zero-fanout user.
        regular = min((k for k, w in weight_map.items() if k > 0 and 0 < w <= 100 and k != orig),
                      key=lambda k: (singleton_cost(ordered, weight_map[k], 100), k))
        cte = """WITH changed AS (SELECT u.Id, CASE WHEN u.Id=? THEN (SELECT DisplayName FROM users WHERE Id=?)
          WHEN u.Id=? THEN (SELECT DisplayName FROM users WHERE Id=?) ELSE u.DisplayName END AS DisplayName FROM users u) """
        predicates = f" WHERE DisplayName=(SELECT DisplayName FROM users WHERE Id={int(orig)})"
        swapped_join = db.execute(cte+"SELECT count(*) FROM badges JOIN changed ON badges.UserId=changed.Id"+predicates,(orig,alt,alt,orig)).fetchone()[0]
        swapped_users = db.execute(cte+"SELECT count(*) FROM changed"+predicates,(orig,alt,alt,orig)).fetchone()[0]
        actual_join = db.execute("SELECT count(*) FROM badges JOIN users ON badges.UserId=users.Id"+predicates).fetchone()[0]
        assert swapped_users == 1 and swapped_join == badge["cheapest_weight"] and actual_join == badge["actual_weight"]
        regular_join = db.execute(cte+"SELECT count(*) FROM badges JOIN changed ON badges.UserId=changed.Id"+predicates,
                                  (orig,regular,regular,orig)).fetchone()[0]
        regular_users = db.execute(cte+"SELECT count(*) FROM changed"+predicates,(orig,regular,regular,orig)).fetchone()[0]
        regular_cost = PrecisionCurve(weight_map, {regular}, 100).minimum(2)
        assert regular_users == 1 and regular_join == weight_map[regular] and regular_cost == singleton_cost(ordered, regular_join, 100)
    dump("spider-census", census)
    dump("spider-prices", priced)
    dump("singleton-worlds", singles)
    if errors:
        dump("spider-errors", errors)
    summaries = []
    for b in BUDGETS:
        for name, chosen in [("with_sql_equality", priced), ("homogeneous_mapping", [x for x in priced if x["affinity_keys"] == 0]), ("original", [x for x in priced if x["original_parser"]])]:
            rs = [x for x in chosen if x["budget"] == b]
            fitting = [x for x in rs if x["exact_count"] is not None]
            summaries.append(dict(budget=b, parser=name, cases=len(rs), fitting=len(fitting),
                exact_positive=sum(x["exact_count"] > 0 for x in fitting), extra_increases=sum(x["plus_one"] > x["exact_count"] for x in fitting),
                largest_jump=max((x["plus_one"]-x["exact_count"] for x in fitting), default=None)))
    dump("spider-summary", summaries)
    summary = dict(spider={k:sum(x[k] for x in census) for k in list(census[0])[1:]},
                   databases=len(by_id), eligible_databases=sum(x["extended_unique"] > 0 for x in census),
                   sqlite_or_parse_errors=errors, tiny_exhaustive=checks, badge=badge, badge_sql=dict(swapped_users=swapped_users, swapped_join=swapped_join, actual_join=actual_join,
                       positive_swap_key=regular, positive_swap_users=regular_users, positive_swap_join=regular_join, positive_swap_cost=regular_cost),
                   primary=[x for x in summaries if x["budget"] == 100], alternate_assignments={})
    for c in ("BIRD","Spider"):
        rs=[r for r in singles if r["corpus"]==c]
        summary["alternate_assignments"][c]=dict(cases=len(rs), varying=sum(r["min_cost"]<r["max_cost"] for r in rs))
    (HERE/"summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

