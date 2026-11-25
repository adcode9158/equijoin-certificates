"""Compare access assumptions on every previously validated BIRD joined intermediate."""
import csv
import sqlite3
import sys
from pathlib import Path
from statistics import median

from box_certificates import oracle, online

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "impact_transfer"))
from bird_transfer import INPUTS, atoms, sql, sqlglot


def records():
    archive = {}
    for name in ("bird-results.csv", "bird-holdout-results.csv"):
        with (HERE.parent/"impact_transfer"/name).open() as source:
            for row in csv.DictReader(source):
                item = archive.setdefault((row["dataset"],row["reference"]), {})
                item[int(row["budget"])] = row
    return archive


def query_inputs(db, case, caches):
    tree = sqlglot.parse_one(case["reference"], read="sqlite")
    join = tree.args["joins"][0]
    eq = join.args["on"]
    keys = {v.table.lower():sql(v) for v in (eq.this,eq.expression)}
    tables = (tree.args["from_"].this,join.this)
    order = sorted(tables, key=lambda t:t.name.lower()!=case["dimension"].lower())
    conditions = {}
    for atom in atoms(tree.args["where"].this):
        col = next(atom.find_all(sqlglot.exp.Column))
        conditions.setdefault(col.table.lower(),[]).append(sql(atom))
    all_counts = []
    observed = []
    predicates = []
    for table in order:
        alias = table.alias_or_name.lower()
        key = keys[alias]
        group = f"SELECT {key}, COUNT(*) FROM {sql(table)}"
        tail = f" GROUP BY {key}"
        if group not in caches:
            caches[group] = dict(db.execute(group + tail))
        all_counts.append(caches[group])
        clauses = conditions.get(alias,[])
        predicates.append(len(clauses))
        observed.append(dict(db.execute(group+" WHERE "+" AND ".join("("+p+")" for p in clauses)+tail)) if clauses else caches[group])
    common = sorted(all_counts[0].keys() & all_counts[1].keys() - {None})
    caps = [tuple(t[k] for t in all_counts) for k in common]
    counts = [tuple(t.get(k,0) for t in observed) for k in common]
    assert sum(d*f for d,f in counts)==int(case["observed"])
    uncertain = sorted((i for i,n in enumerate(predicates) if n),key=lambda i:(-predicates[i],i))
    return caps, counts, uncertain


def main():
    archive = records()
    output=[]
    for dataset in sorted({db for db,ref in archive}):
        path=INPUTS/(dataset+".sqlite")
        wal=Path(str(path)+"-wal")
        assert not wal.exists() or wal.stat().st_size==0
        db=sqlite3.connect(path.as_uri()+"?mode=ro&immutable=1",uri=True)
        caches={}
        for (d,reference),budgets in archive.items():
            if d!=dataset:
                continue
            case=next(iter(budgets.values()))
            caps,truth,uncertain=query_inputs(db,case,caches)
            for budget, data in budgets.items():
                minimum=oracle(caps,truth,uncertain,budget)
                calls, fits=online(caps,uncertain,budget,lambda k,j:truth[k][j],"largest_current")
                assert fits==(int(case["observed"])<=budget) and minimum<=calls
                if data["minimum"]: assert int(data["minimum"]) <= minimum
                output.append(dict(dataset=dataset, question_id=case["question_id"],budget=budget,
                                   observed=case["observed"],fits=int(fits), unknown_inputs=len(uncertain),
                                   initial_upper=sum(d*f for d,f in caps), minimum=minimum,
                                   online=calls, previous_rich_min=data["minimum"],
                                   eligible_cells=len(caps)*len(uncertain)))
        db.close()
        print(dataset,flush=True)
    with (HERE/"bird.csv").open("w",newline="") as f:
        target=csv.DictWriter(f,fieldnames=output[0])
        target.writeheader()
        target.writerows(output)
    held=[r for r in output if r["dataset"] not in ("formula_1","financial")]
    for b in (10,100,1000,10000,100000):
        fits=[r for r in held if r["budget"]==b and r["fits"]]
        open_cases=[r for r in fits if r["minimum"]]
        old=[r for r in fits if int(r["previous_rich_min"])]
        print(b,len(fits),len(open_cases),len(old))
        for g in (open_cases,old):
            if g:
                print({f:median(int(r[f]) for r in g) for f in ("minimum","online","previous_rich_min")})

if __name__=="__main__":
    main()

