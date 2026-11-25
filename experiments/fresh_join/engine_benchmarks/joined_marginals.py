"""Column marginals on joined rows, with all build and fallback work measured.

One group per distinct value suffices to get an exact unary-clause mass.
Intersections are bounded by the Fréchet bounds. All unsupported predicates receive
an unconstrained mass interval. Native COUNT and capped SQL remain available.
"""
from collections import Counter, defaultdict
from pathlib import Path
import argparse
import csv
import sqlite3
import shutil
import tempfile

from physical import (HERE, INPUTS, atoms, budget_query, elapsed, exp, load_rows,
                      native_index, now, quote, save, sql, sqlglot)


def histogram_keys(query, db):
    dim,fact,dk,fk,*_ = query["parts"]
    path = dim.name,dk.name,fact.name,fk.name
    aliases = {dim.alias_or_name.lower():"d",fact.alias_or_name.lower():"f"}
    unsafe = set()
    for table,side in [(dim,"d"),(fact,"f")]:
        creation, = db.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=? COLLATE NOCASE",(table.name,)).fetchone()
        if "COLLATE" in creation.upper(): unsafe.add(side)
    tree=sqlglot.parse_one(query["reference"],read="sqlite")
    groups=defaultdict(list)
    unknown=False
    for atom in atoms(tree.args["where"].this):
        ids={(aliases[c.table.lower()],c.name) for c in atom.find_all(exp.Column)}
        if len(ids)!=1 or next(iter(ids))[0] in unsafe:
            unknown=True
            continue
        col=next(iter(ids))
        projected=atom.transform(lambda node: exp.column("v") if isinstance(node, exp.Column) else node)
        groups[path+col].append("("+sql(projected)+")")
    return path,{k:" AND ".join(v) for k,v in groups.items()},unknown


def mass(db,key,name):
    dim,pk,fact,fk,side,col=key
    base=f" FROM {quote(dim)} AS d JOIN {quote(fact)} AS f ON d.{quote(pk)}=f.{quote(fk)}"
    v=f"{side}.{quote(col)}"
    start=now()
    db.execute(f"CREATE TEMP TABLE {name} AS SELECT {v} AS v,count(*) AS w"+base+f" GROUP BY {v},typeof({v})")
    db.execute(f"CREATE INDEX temp.{name}_value ON {name}(v)")
    n,cap=db.execute(f"SELECT count(*),sum(w) FROM {name}").fetchone()
    return n,int(cap or 0),elapsed(start)


def check(db,groups,tables,unknown,total,budget,capped):
    if total is None:
        return db.execute(capped).fetchone()[0],"fallback-no-column"
    lows=[]
    upper=total
    for k,pred in groups.items():
        m,=db.execute(f"SELECT coalesce(sum(w),0) FROM {tables[k]} WHERE {pred}").fetchone()
        lows.append(m)
        upper=min(upper,m)
        if upper<=budget:
            return True,"upper-admit"
    if not unknown and sum(lows)-(len(lows)-1)*total>budget:
        return False,"lower-reject"
    return bool(db.execute(capped).fetchone()[0]),"fallback"


def run(scope,budget,rounds,indexed=False,covering=False):
    data=load_rows(scope,budget)
    builds=[]; answers=[]; timing=[]; indexes=[]
    for dataset,qs in data.items():
        file=INPUTS/(dataset+".sqlite")
        wal=Path(str(file)+"-wal")
        assert not wal.exists() or not wal.stat().st_size
        disposable=None
        if indexed:
            disposable=tempfile.TemporaryDirectory(dir=HERE)
            copy=Path(disposable.name)/"disposable.sqlite"
            shutil.copyfile(file,copy)
            db=sqlite3.connect(copy,cached_statements=0,isolation_level=None)
            db.execute("PRAGMA journal_mode=OFF")
            db.execute("PRAGMA synchronous=OFF")
        else:
            db=sqlite3.connect(file.as_uri()+"?mode=ro&immutable=1",uri=True,cached_statements=0)
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("PRAGMA cache_size=-65536")
        if indexed:
            for j,(table,key) in enumerate(sorted({(q["fact"],q["parts"][3].name) for q in qs})):
                if not native_index(db,table,key):
                    db.execute(f"CREATE INDEX research_fk_{j} ON {quote(table)}({quote(key)})")
            if covering:
                candidate=set()
                for q in qs:
                    schema,groups,_=histogram_keys(q,db)
                    dim,pk,fact,fk=schema
                    for (_,_,_,_,side,attr) in groups:
                        candidate.add((dim,attr,pk) if side=="d" else (fact,attr,fk))
                for j,(tab,attr,join_key) in enumerate(sorted(candidate)):
                    start=now()
                    db.execute(f"CREATE INDEX research_pred_{j} ON {quote(tab)}({quote(attr)},{quote(join_key)})")
                    indexes.append(dict(dataset=dataset,table=tab,column=attr,join_key=join_key,ms=elapsed(start)))
            db.execute("ANALYZE")
        tables={}; totals={}; counts=Counter()
        for q in qs:
            start=now()
            path,groups,unknown=histogram_keys(q,db)
            q.update(path=path,groups=groups,unknown=unknown,rewrite_ms=elapsed(start))
            counts.update(groups.keys())
        for q in qs:
            for k in q["groups"]:
                if k in tables: continue
                name="h_"+str(len(tables)); tables[k]=name
                n,njoin,duration=mass(db,k,name)
                assert totals.setdefault(k[:4],njoin)==njoin
                builds.append(dict(dataset=dataset,histogram="|".join(k),groups=n,total=njoin,uses=counts[k],build_ms=duration))
        for i,q in enumerate(qs):
            cap=budget_query(q["reference"][len("SELECT COUNT(*) "):],budget)
            def stats():
                return check(db,q["groups"],tables,q["unknown"],totals.get(q["path"]),budget,cap)
            def plain():
                return bool(db.execute(cap).fetchone()[0]),"cap"
            ops=[("joined_marginals",stats),("cap",plain)]
            actual=int(q["observed"])
            total=totals.get(q["path"])
            exact_masses=[db.execute(f"SELECT coalesce(sum(w),0) FROM {tables[k]} WHERE {pred}").fetchone()[0] for k,pred in q["groups"].items()]
            if total is None:
                lower=0; upper=None
            else:
                lower=0 if q["unknown"] else max(0,sum(exact_masses)-(len(exact_masses)-1)*total)
                upper=min([total,*exact_masses])
                assert lower<=actual<=upper,(dataset,q["question_id"],actual,lower,upper,q["groups"])
            for r in range(-1,rounds):
                order=ops if (r+i)%2 else ops[::-1]
                for name,op in order:
                    start=now()
                    answer,why=op()
                    ms=elapsed(start)
                    assert answer==(actual<=budget)
                    if r>=0: timing.append(dict(dataset=dataset,question=q["question_id"],round=r,method=name,ms=ms))
                    if r==0 and name=="joined_marginals":
                        answers.append(dict(dataset=dataset,question=q["question_id"],observed=actual,budget=budget,
                                            total=total,lower=lower,upper=upper,reason=why,
                                            histograms=";".join("|".join(k) for k in q["groups"]),unsupported=int(q["unknown"]),
                                            parse_ms=q["parse_ms"],rewrite_ms=q["rewrite_ms"]))
        db.close()
        if disposable: disposable.cleanup()
        print(dataset,len(qs),len(tables),flush=True)
    stem=f"{scope}-{budget}-marginal"+("-covering" if covering else "-indexed" if indexed else "")
    save(HERE/(stem+"-timings.csv"),timing)
    save(HERE/(stem+"-builds.csv"),builds)
    save(HERE/(stem+"-decisions.csv"),answers)
    if indexes: save(HERE/(stem+"-indexes.csv"),indexes)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scope",default="holdout")
    p.add_argument("--budget",type=int,default=100)
    p.add_argument("--rounds",type=int,default=3)
    p.add_argument("--indexed",action="store_true")
    p.add_argument("--covering",action="store_true")
    a=p.parse_args()
    run(a.scope,a.budget,a.rounds,a.indexed or a.covering,a.covering)

