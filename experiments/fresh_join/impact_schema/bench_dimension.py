"""Local SQLite pilot. Prebuilt fact frequency maps, known filtered dimension size.

Usage: python -B bench_dimension.py paper_root raw_stats_directory output.csv
"""
import csv
import sqlite3
import sys
from itertools import accumulate
from math import prod
from pathlib import Path
from time import perf_counter_ns

from permutation_witness import load


BUDGET=10_000_000


def user_database(raw):
    db=sqlite3.connect(':memory:')
    with (raw/'users.csv').open(newline='',encoding='utf-8-sig') as f:
        reader=csv.reader(f)
        cols=next(reader)
        assert all(c.isidentifier() for c in cols)
        defs=[c+(' INTEGER PRIMARY KEY' if c=='Id' else ' TEXT' if 'Date' in c else ' INTEGER') for c in cols]
        db.execute('CREATE TABLE users ('+','.join(defs)+')')
        db.executemany('INSERT INTO users VALUES ('+','.join('?' for c in cols)+')',
                       ([v if v!='' else None for v in row] for row in reader))
    return db


def terms(facts, domain):
    driver=min(facts,key=len)
    rest=[f for f in facts if f is not driver]
    for key,v in driver.items():
        if key in domain:
            weight=v
            for f in rest:
                weight*=f.get(key,0)
                if not weight: break
            if weight:
                yield key,weight


def prepare(facts,domain):
    ordered=sorted(terms(facts,domain),key=lambda r:(-r[1],r[0]))
    prefix=list(accumulate((w for _,w in ordered),initial=0))
    return ordered,prefix


def probe(db,pred,bank,m,nkeys):
    ordered,prefix=bank
    fixed=0
    for i in range(len(ordered)+1):
        largest=fixed+prefix[min(i+m,len(ordered))]-prefix[i]
        smallest=fixed+prefix[-1]-prefix[min(nkeys-m,len(ordered))]
        if largest<=BUDGET or smallest>BUDGET:
            return largest<=BUDGET,i
        key,w=ordered[i]
        if db.execute('SELECT ('+pred+') FROM users WHERE Id=?',(key,)).fetchone()[0]:
            m-=1
            fixed+=w


def exact_scan(db,pred,facts):
    selected={k for k, in db.execute('SELECT Id FROM users WHERE '+pred)}
    groups=[*facts,selected]
    driver=min(range(len(groups)),key=lambda i:len(groups[i]))
    total=0
    for key in groups[driver]:
        if key in selected:
            total+=prod(f.get(key,0) for f in facts)
            if total>BUDGET:
                return False
    return True


def exact_lookups(db,pred,facts,domain):
    total=0
    for key,w in terms(facts,domain):
        if db.execute('SELECT ('+pred+') FROM users WHERE Id=?',(key,)).fetchone()[0]:
            total+=w
            if total>BUDGET: return False
    return True


def batched(db,pred,weights,m,nkeys,total=None):
    # Enumerate the smaller membership class in one SQL statement.
    inverted=m>nkeys//2
    where='('+pred+') IS NOT TRUE' if inverted else pred
    mass=sum(weights.get(k,0) for k, in db.execute('SELECT Id FROM users WHERE '+where))
    if inverted:
        mass=(sum(weights.values()) if total is None else total)-mass
    return mass<=BUDGET


def main(root,raw,output):
    cases,base,inputs=load(root)
    db=user_database(raw)
    db.execute('CREATE TEMP TABLE fact(k INTEGER PRIMARY KEY, w INTEGER NOT NULL)')
    domain=base['users','Id']
    with output.open('w',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['case_id','observed','fact_inputs','nonzero_weights','round','policy','elapsed_ns'])
        for q in cases:
            ids=q['input_ids']
            dim=[i for i in ids if inputs[i][0]==('users','Id') and inputs[i][1]!='TRUE']
            if not dim: continue
            dim,=dim
            facts=[inputs[i][2] for i in ids if i!=dim]
            pred=inputs[dim][1].replace('::timestamp','')
            m=len(inputs[dim][2])
            known=prepare(facts,domain)
            lookup=dict(known[0])
            db.execute('DELETE FROM fact')
            db.executemany('INSERT INTO fact VALUES (?,?)',lookup.items())
            aggregate=('SELECT coalesce(sum(fact.w),0) FROM fact CROSS JOIN users '
                       'ON users.Id=fact.k WHERE '+pred)
            n=len(domain)
            actual=q['observed_cardinality']
            verified=sum(lookup.get(k,0) for k, in db.execute('SELECT Id FROM users WHERE '+pred))
            assert verified==actual
            methods=[
                ('cold_probe',lambda:probe(db,pred,prepare(facts,domain),m,n)[0]),
                ('exact_scan',lambda:exact_scan(db,pred,facts)),
                ('exact_index',lambda:exact_lookups(db,pred,facts,domain)),
                ('ready_probe',lambda:probe(db,pred,known,m,n)[0]),
                ('ready_batch',lambda:batched(db,pred,lookup,m,n,known[1][-1])),
                ('ready_native_sql',lambda:db.execute(aggregate).fetchone()[0]<=BUDGET),
                ('cold_batch',lambda:batched(db,pred,dict(terms(facts,domain)),m,n))]
            for t in range(-1,len(methods)):
                offset=t%len(methods)
                for name,method in methods[offset:]+methods[:offset]:
                    start=perf_counter_ns()
                    decision=method()
                    elapsed=perf_counter_ns()-start
                    assert decision==(actual<=BUDGET)
                    if t>=0:
                        writer.writerow([q['case_id'],actual,'|'.join(i for i in ids if i!=dim),
                                         len(lookup),t,name,elapsed])


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
