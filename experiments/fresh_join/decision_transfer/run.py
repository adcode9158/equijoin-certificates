"""Prospective buy-or-continue experiment for certifying selected binary joins."""
import argparse
import csv
import json
import shutil
import sqlite3
import sys
import tempfile
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from statistics import median
from time import perf_counter_ns

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine_benchmarks"))
from physical import INPUTS, budget_query, decomposition, native_index, quote, sql
from joined_marginals import histogram_keys

BUDGETS=(100,512)
PILOT=("financial","formula_1")
CAP="cap"
GRID=[(v,k) for v,k in product((0,2048,16384),(1,8,32))]

def write_csv(name,rows):
    if not rows: return
    with (HERE/name).open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def read_cohort(stage):
    name='bird-results.csv' if stage=='pilot' else 'bird-holdout-results.csv'
    source=HERE.parent/'impact_transfer'/name
    grouped=defaultdict(list); seen=set()
    with source.open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            id_=(r['dataset'],r['reference'])
            if int(r['budget'])!=100 or id_ in seen: continue
            seen.add(id_)
            grouped[r['dataset']].append({k:r[k] for k in ('dataset','question_id','reference','observed','dimension','fact')})
    return grouped


def connect(path,readonly):
    address=path.resolve().as_uri()+('?mode=ro&immutable=1' if readonly else '?mode=rw')
    db=sqlite3.connect(address,uri=True,isolation_level=None,cached_statements=0)
    db.execute('PRAGMA temp_store=MEMORY')
    db.execute('PRAGMA cache_size=-65536')
    if not readonly:
        db.execute('PRAGMA journal_mode=OFF')
        db.execute('PRAGMA synchronous=OFF')
    return db


def configure(db,rows):
    """All policies share this design; charge its full discovery, build and ANALYZE."""
    start=perf_counter_ns()
    features=set(); keys=set()
    for q in rows:
        parts=decomposition(q)
        keys.add((parts[1].name,parts[3].name))
        path,groups,_=histogram_keys(dict(q,parts=parts),db)
        dim,pk,fact,fk=path
        for (_,_,_,_,side,attr) in groups:
            features.add((dim,attr,pk) if side=='d' else (fact,attr,fk))
    discovery=perf_counter_ns()-start
    add_start=perf_counter_ns(); num=0
    for table,col in sorted(keys):
        if not native_index(db,table,col):
            db.execute(f'CREATE INDEX decision_fk{num} ON {quote(table)}({quote(col)})')
            num+=1
    num_fk=num
    for table,attr,key in sorted(features):
        db.execute(f'CREATE INDEX decision_cover{num} ON {quote(table)}({quote(attr)},{quote(key)})')
        num+=1
    built=perf_counter_ns()-add_start
    a=perf_counter_ns();db.execute('ANALYZE'); analyze=perf_counter_ns()-a
    return discovery,built,analyze,num_fk,num-num_fk


def scalar(db,stmt,params=()):
    return db.execute(stmt,params).fetchone()[0]


def perform(db,q,budget,method,v=0,k=1):
    """Input is normalized SQL. Re-decompose only when actually switching access path."""
    body=q['reference'][len('SELECT COUNT(*) '):]
    capped=budget_query(body,budget)
    if method=='cap':
        return bool(scalar(db,capped)),'native',0
    if method=='count':
        return scalar(db,q['reference'])<=budget,'count',0
    if v:
        stopped=[False]
        def interrupt():
            stopped[0]=True
            return 1
        db.set_progress_handler(interrupt,v)
        try:
            answer=scalar(db,capped)
            return bool(answer),'native-finished',0
        except sqlite3.OperationalError as e:
            if not stopped[0] or e.sqlite_errorcode!=sqlite3.SQLITE_INTERRUPT: raise
        finally:
            db.set_progress_handler(None,0)
    start=perf_counter_ns()
    dim,fact,dk,fk,dwhere,fwhere=decomposition(q)
    dimension_sql=f'SELECT {sql(dk)} FROM {sql(dim)} WHERE {dwhere} LIMIT {k+1}'
    fact_sql=sql(fact); key_sql=sql(fk)
    rewrite=perf_counter_ns()-start
    keys=[item[0] for item in db.execute(dimension_sql)]
    if len(keys)>k:
        return bool(scalar(db,capped)),'capped-fallback',rewrite
    if not keys: return True,'empty-dimension',rewrite
    placeholder=','.join('?' for _ in keys)
    unfiltered=f'FROM {fact_sql} WHERE {key_sql} IN ({placeholder})'
    if method=='cert' or fwhere=='1':
        allowed=bool(scalar(db,budget_query(unfiltered,budget),keys))
        if allowed or fwhere=='1':
            return allowed,('upper' if fwhere!='1' else 'exact-keyset'),rewrite
    actual=budget_query(unfiltered+' AND ('+fwhere+')',budget)
    return bool(scalar(db,actual,keys)),'filtered-keyset',rewrite


def setup(stage,layout,rows,profiles,tmp):
    schema=rows[0]['dataset']
    original=INPUTS/(schema+'.sqlite')
    wal=Path(str(original)+'-wal')
    assert not wal.exists() or wal.stat().st_size==0
    path=original
    if layout=='cover':
        path=Path(tmp)/'disposable.sqlite'
        shutil.copyfile(original,path)
    db=connect(path,layout=='released')
    disc=build=analyze=num_fk=num_cover=0
    if layout=='cover':
        disc,build,analyze,num_fk,num_cover=configure(db,rows)
    profiles.append(dict(stage=stage,schema=schema,layout=layout,discovery_ns=disc,
                         index_build_ns=build,analyze_ns=analyze,added_fk=num_fk,added_cover=num_cover))
    return db


def strategy_label(method,v,k):
    return method if method in ('count','cap') else f'{method}/{v}/{k}'


def warm(db,rows,budget):
    for q in rows:
        ans,_,_=perform(db,q,budget,'cap')
        assert ans==(int(q['observed'])<=budget)


def measure(db,stage,layout,rows,budget,recipes,repetitions,output):
    warm(db,rows,budget)
    for rep in range(repetitions):
        for i,q in enumerate(rows):
            offset=(rep+i)%len(recipes)
            for label,method,v,k in recipes[offset:]+recipes[:offset]:
                start=perf_counter_ns()
                ans,why,rewrite=perform(db,q,budget,method,v,k)
                duration=perf_counter_ns()-start
                assert ans==(int(q['observed'])<=budget),(q,budget,method,v,k,ans)
                output.append(dict(stage=stage,layout=layout,schema=q['dataset'],id=q['question_id'],
                                   budget=budget,round=rep,policy=label,method=method,vm_steps=v,
                                   candidate_limit=k,ns=duration,rewrite_ns=rewrite,route=why,
                                   admission=int(ans)))


def choose(observations):
    rounds=defaultdict(lambda:defaultdict(int))
    for r in observations:
        rounds[r['layout'],r['budget'],r['policy']][r['round']]+=r['ns']
    times={k:median(v.values()) for k,v in rounds.items()}
    selected={}
    for layout,b in product(('released','cover'),BUDGETS):
        scores=lambda x: times[layout,b,x]
        recipes=[strategy_label('cert',v,k) for v,k in GRID]
        best=min(recipes,key=scores)
        always=min((strategy_label('cert',0,k) for k in (1,8,32)),key=scores)
        deploy=min([best,'cap','count'],key=scores)
        selected[layout,str(b)]={'challenger':best,'fixed_cert':always,'deployment':deploy,
             'fixed_native':min(('cap','count'),key=scores),'training_plan_time_ms':scores(best)/1e6}
    return selected


def recipe(label,policy):
    if policy in ('cap','count'): return label,policy,0,0
    m,v,k=policy.split('/')
    return label,m,int(v),int(k)


def run():
    all_profiles=[]
    obs=[]
    pilot=read_cohort('pilot')
    assert set(pilot)==set(PILOT)
    for schema,rows in sorted(pilot.items()):
        for layout in ('released','cover'):
            with tempfile.TemporaryDirectory(prefix='vldb-validation-',ignore_cleanup_errors=False) as tmp:
                db=setup('pilot',layout,rows,all_profiles,tmp)
                for b in BUDGETS:
                    candidates=[('cap','cap',0,0),('count','count',0,0)]+[(strategy_label('cert',v,k),'cert',v,k) for v,k in GRID]
                    measure(db,'pilot',layout,rows,b,candidates,2,obs)
                db.close()
            print('pilot',schema,layout,flush=True)
    selection=choose(obs)
    (HERE/'selection.json').write_text(json.dumps({f'{l}:{b}':choice for (l,b),choice in selection.items()},
                                                   indent=2),encoding='utf-8')
    write_csv('pilot.csv',obs)
    write_csv('setup.csv',all_profiles)
    obs=[]
    for schema,rows in sorted(read_cohort('test').items()):
        assert schema not in PILOT
        for layout in ('released','cover'):
            with tempfile.TemporaryDirectory(prefix='vldb-validation-') as tmp:
                db=setup('test',layout,rows,all_profiles,tmp)
                for b in BUDGETS:
                    chosen=selection[layout,str(b)]
                    # Execute unique configurations once per round, then refer to them by parameter.
                    active={'cap','count',chosen['challenger'],chosen['fixed_cert'],
                            chosen['challenger'].replace('cert/','direct/')}
                    for other in ('deployment','fixed_native'): assert chosen[other] in active
                    recipes=[recipe(l,l) for l in sorted(active)]
                    measure(db,'test',layout,rows,b,recipes,5,obs)
                db.close()
            print('test',schema,layout,flush=True)
        write_csv('test.csv',obs);write_csv('setup.csv',all_profiles)
    print('complete',flush=True)


if __name__=='__main__':
    run()

