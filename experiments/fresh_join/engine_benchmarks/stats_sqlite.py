"""SQLite end-to-end factorized join cardinality on 86 full STATS queries."""
import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from time import perf_counter_ns
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent
RAW=HERE.parents[2]/'packing'/'workload'/'raw'
BUDGET=10_000_000


def now(): return perf_counter_ns()
def ms(t): return (now()-t)/1_000_000
def qt(s):
    assert s.isidentifier()
    return '"'+s+'"'


def records(paper):
    with ZipFile(paper/'supplement.zip') as z:
        query=[r for r in map(json.loads,z.open('validation-data/inputs/query-cases.jsonl'))
               if any(o['source']=='full' for o in r['benchmark_occurrences'])]
        needed={i for q in query for i in q['input_ids']}
        inputs={}
        for r in map(json.loads,z.open('validation-data/inputs/filtered-key-frequencies.jsonl')):
            if r['input_id'] in needed:
                pred=r['predicate'].replace('::timestamp','')
                inputs[r['input_id']]=(r['table'],r['column'],pred)
    assert len(query)==86 and max(q['observed_cardinality'] for q in query)<2**63-1
    return query,inputs


def load_data(db, inputs):
    setup=[]
    for t in sorted({r[0] for r in inputs.values()}):
        start=now()
        with (RAW/(t+'.csv')).open(encoding='utf-8-sig',newline='') as source:
            reader=csv.reader(source); cols=next(reader)
            decl=[qt(c)+(' INTEGER PRIMARY KEY' if c=='Id' else ' TEXT' if 'Date' in c else ' INTEGER') for c in cols]
            db.execute(f'CREATE TABLE {qt(t)}('+','.join(decl)+')')
            db.executemany(f'INSERT INTO {qt(t)} VALUES ('+','.join('?' for c in cols)+')',
                           ([v if v!='' else None for v in row] for row in reader))
        setup.append(dict(stage='load',item=t,ms=ms(start)))
    return setup


def indexes(db, inputs,rich):
    cols=defaultdict(set)
    for table, key, pred in inputs.values():
        cols[table,key].update(re.findall(r'\b([A-Za-z]\w*)\s*[<>=]',pred))
    designs=set()
    for (table,key),attrs in cols.items():
        if rich:
            if attrs:
                designs.add((table,(key,*sorted(attrs))))
            designs.update((table,(c,key)) for c in attrs if c!=key)
        elif key!='Id':
            designs.add((table,(key,)))
    rows=[]
    for j,(table,fields) in enumerate(sorted(designs)):
        start=now()
        db.execute(f'CREATE INDEX ix_{int(rich)}_{j} ON {qt(table)}('+','.join(map(qt,fields))+')')
        rows.append(dict(stage='covering-index' if rich else 'fk-index',item=table+'/'+','.join(fields),ms=ms(start)))
    start=now(); db.execute('ANALYZE')
    rows.append(dict(stage='covering-analyze' if rich else 'fk-analyze',item='',ms=ms(start)))
    return rows


def sizes(db):
    # Native catalog estimates of the number of distinct keys help choose a single driver.
    output={}
    for t,ix,st in db.execute('SELECT tbl,idx,stat FROM sqlite_stat1'):
        if ix is None: continue
        stats=list(map(int,st.split()))
        if len(stats)<2: continue
        c=db.execute('PRAGMA index_info('+qt(ix)+')').fetchone()[2]
        output[t,c]=max(1,stats[0]//max(1,stats[1]))
        output[t,'Id']=stats[0]
    return output


def group(table,k,p):
    cond=' WHERE '+qt(k)+' IS NOT NULL AND ('+p+')'
    if k=='Id':
        return f'SELECT {qt(k)} AS k,1 AS n FROM {qt(table)}'+cond
    return f'SELECT {qt(k)} AS k,count(*) AS n FROM {qt(table)}'+cond+' GROUP BY '+qt(k)


def statements(details,est,boolean_product=True):
    aliases=['g'+str(i) for i in range(len(details))]
    groups=[group(*x) for x in details]
    first=min(range(len(details)),key=lambda i:est.get(details[i][:2],10**12))
    joins=' FROM '+aliases[0]+''.join(' JOIN '+alias+' USING(k)' for alias in aliases[1:])
    cte='WITH '+','.join(a+' AS ('+g+')' for a,g in zip(aliases,groups))+' '
    term='*'.join(a+'.n' for a in aliases)
    exact=cte+f'SELECT coalesce(sum({term}),0)'+joins
    bounded=cte+'SELECT '+term+joins
    factors=['d.n']
    for i,(t,k,p) in enumerate(details):
        if i==first: continue
        source=' FROM '+qt(t)+' WHERE '+qt(k)+'=d.k AND ('+p+')'
        if k=='Id' and boolean_product: factors.append('EXISTS(SELECT 1'+source+')')
        else: factors.append('(SELECT count(*)'+source+')')
    pivot='WITH d AS ('+groups[first]+') SELECT '+'*'.join(factors)+' FROM d'
    return exact,bounded,pivot


def stream(db,stmt,budget):
    s=0
    for (x,) in db.execute(stmt):
        s+=x
        if s>budget: return False
    return True


def write(name,rows):
    with (HERE/name).open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)


def run(paper, rounds, indexed_only):
    cases,inputs=records(paper)
    db=sqlite3.connect(':memory:',cached_statements=0)
    db.execute('PRAGMA temp_store=MEMORY')
    db.execute('PRAGMA automatic_index=ON')
    setup=load_data(db,inputs)
    timings=[]
    for rich in (False,True):
        setup+=indexes(db,inputs,rich)
        if indexed_only and not rich: continue
        est=sizes(db)
        for qi,q in enumerate(cases):
            start=now()
            direct,grouped,driven=statements([inputs[i] for i in q['input_ids']],est)
            rewrite=ms(start)
            ops=[('grouped_exact',lambda:db.execute(direct).fetchone()[0]),
                 ('grouped_capped',lambda:stream(db,grouped,BUDGET)),
                 ('driver_capped',lambda:stream(db,driven,BUDGET))]
            actual=q['observed_cardinality']
            for r in range(-1,rounds):
                off=(r+qi)%len(ops)
                for name,call in ops[off:]+ops[:off]:
                    start=now(); result=call(); duration=ms(start)
                    assert result==(actual if name=='grouped_exact' else actual<=BUDGET),(name,q['case_id'],result,actual)
                    if r>=0:
                        timings.append(dict(design='covering' if rich else 'fk-indexes',case=q['case_id'],
                                            observed=actual,budget=BUDGET,method=name,round=r,rewrite_ms=rewrite,ms=duration))
            if qi%20==19: print('covering' if rich else 'fk-only', qi+1,flush=True)
        write('stats-timings.csv',timings)
        write('stats-setup.csv',setup)
    db.close()


if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('paper',type=Path)
    a.add_argument('--rounds',type=int,default=3)
    a.add_argument('--indexed-only',action='store_true')
    args=a.parse_args()
    run(args.paper,args.rounds,args.indexed_only)


