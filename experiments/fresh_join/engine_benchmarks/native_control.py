"""Native CREATE INDEX control on disposable byte-for-byte database copies."""
import argparse
import collections
import shutil
import sqlite3
import tempfile
from pathlib import Path

from physical import HERE, INPUTS, budget_query, elapsed, load_rows, methods, native_index, now, quote, save


def run(scope, budget, rounds):
    data = load_rows(scope, budget)
    timing, builds, plans = [], [], []
    for dataset, rows in data.items():
        source = INPUTS / (dataset + ".sqlite")
        wal = Path(str(source) + "-wal")
        assert not wal.exists() or not wal.stat().st_size
        with tempfile.TemporaryDirectory(dir=HERE) as temp:
            path = Path(temp) / "disposable.sqlite"
            shutil.copyfile(source, path)
            db = sqlite3.connect(path, cached_statements=0, isolation_level=None)
            db.execute("PRAGMA temp_store=MEMORY")
            db.execute("PRAGMA cache_size=-65536")
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
            keys = sorted({(q["fact"],q["parts"][3].name) for q in rows})
            structs = {}
            for n,(tab,key) in enumerate(keys):
                idx = "research_fk_" +str(n)
                start = now()
                existed = native_index(db,tab,key)
                if not existed:
                    db.execute("CREATE INDEX "+quote(idx)+" ON "+quote(tab)+"("+quote(key)+")")
                cost = elapsed(start)
                builds.append(dict(dataset=dataset,fact=tab,key=key,kind="native-index",ms=cost,existed=int(existed)))
                syn = "syn_"+str(n)
                structs[tab,key] = syn, "", True
            # With the new index available, grouping can use its covering scan.
            for n,(tab,key) in enumerate(keys):
                syn = structs[tab,key][0]
                start = now()
                db.execute(f"CREATE TEMP TABLE {syn}(k INTEGER PRIMARY KEY,w INTEGER NOT NULL) WITHOUT ROWID")
                db.execute(f"INSERT INTO {syn} SELECT {quote(key)},count(*) FROM {quote(tab)} WHERE {quote(key)} IS NOT NULL GROUP BY {quote(key)}")
                builds.append(dict(dataset=dataset,fact=tab,key=key,kind="degree-on-index",ms=elapsed(start),existed=0))
            for analyzed in (False,True):
                if analyzed:
                    start=now()
                    db.execute("ANALYZE")
                    builds.append(dict(dataset=dataset,fact="",key="",kind="analyze",ms=elapsed(start),existed=0))
                for i,q in enumerate(rows):
                    choices=methods(db,q,structs,budget)
                    names=["cap","count","degree_stream","degree_if_unfiltered"]
                    cap=budget_query(q["reference"][len("SELECT COUNT(*) "):],budget)
                    plans.append(dict(dataset=dataset,question=q["question_id"],analyzed=int(analyzed),
                                      plan=" / ".join(r[-1] for r in db.execute("EXPLAIN QUERY PLAN "+cap))))
                    for repeat in range(-1, rounds):
                        k=(i+repeat)%len(names)
                        for name in names[k:]+names[:k]:
                            start=now()
                            fit,way=choices[name]()
                            ms=elapsed(start)
                            assert fit==(int(q["observed"])<=budget)
                            if repeat>=0:
                                timing.append(dict(dataset=dataset,question=q["question_id"],budget=budget,analyzed=int(analyzed),
                                                   method=name,round=repeat,ms=ms,decision=way))
            db.close()
        print(dataset,"native complete",flush=True)
    stem=f"{scope}-{budget}-native"
    save(HERE/(stem+"-timings.csv"),timing)
    save(HERE/(stem+"-builds.csv"),builds)
    save(HERE/(stem+"-plans.csv"),plans)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scope",default="holdout")
    p.add_argument("--budget",type=int,default=100)
    p.add_argument("--rounds",type=int,default=3)
    a=p.parse_args()
    run(a.scope,a.budget,a.rounds)

