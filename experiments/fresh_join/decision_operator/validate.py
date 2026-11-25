"""Fit a physical-grant threshold on old full joins and validate on disjoint parent subplans."""
import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from time import perf_counter

HERE=Path(__file__).resolve().parent
OUTPUT=HERE
RESOURCE=HERE.parent/'engine_benchmarks'/'resource'
sys.path[:0]=[str(RESOURCE),str(RESOURCE.parent)]
from stats_sqlite import RAW,qt,statements
from stress import create_db,measure
from zipfile import ZipFile


def write(filename,rows):
    with (OUTPUT/filename).open('w',newline='',encoding='utf-8') as out:
        w=csv.DictWriter(out,fieldnames=list(rows[0]))
        w.writeheader();w.writerows(rows)

def read(path):
    with path.open(encoding='utf-8-sig',newline='') as src:
        return list(csv.DictReader(src))

def load(paper):
    with ZipFile(paper/'supplement.zip') as archive:
        cases=list(map(json.loads,archive.open('validation-data/inputs/query-cases.jsonl')))
        inputs={r['input_id']:(r['table'],r['column'],r['predicate'].replace('::timestamp',''))
                for r in map(json.loads,archive.open('validation-data/inputs/filtered-key-frequencies.jsonl'))}
    return cases,inputs

def cohort(all_cases,old,exclude=()):
    train={q['case_id']:q for q in all_cases if q['case_id'] in old}
    parents={o['parent'] for q in train.values() for o in q['benchmark_occurrences']}
    parents.update(o['parent'] for q in all_cases if q['case_id'] in exclude for o in q['benchmark_occurrences'])
    def eligible(q):
        return all(o['source']=='subplan' and o['parent'] not in parents for o in q['benchmark_occurrences'])
    eligible_cases=[q for q in all_cases if eligible(q)]
    selected=[]; inventory=[]
    for bottom,top in [(-1,65536),(65536,262144),(262144,1048576),(1048576,3000000)]:
        subset=[q for q in eligible_cases if bottom<q['observed_cardinality']<=top]
        subset.sort(key=lambda q:hashlib.sha256(('route-holdout-v1/'+q['case_id']).encode()).digest())
        selected.extend(subset[:8])
        inventory.append(dict(lower_exclusive=bottom,upper_inclusive=top,eligible=len(subset),selected=min(8,len(subset))))
    selected.sort(key=lambda q:min(o['line'] for o in q['benchmark_occurrences']))
    return train,selected,inventory,parents

def operation(original):
    prefix='SELECT COUNT(*) '
    assert original.startswith(prefix)
    body=original.strip().removesuffix(';')[len(prefix):]
    table_spec=body.split(' WHERE ')[0].removeprefix('FROM ')
    names=[re.fullmatch(r'\s*\w+\s+as\s+(\w+)\s*',t,re.I).group(1) for t in table_spec.split(',')]
    keys=','.join(qt(a)+'.Id' for a in names)
    return ('SELECT count(*) AS n,coalesce(sum(CAST(p%104729 AS HUGEINT)*CAST(h%1009 AS HUGEINT)),0) AS checksum '
            'FROM (SELECT row_number() OVER (ORDER BY '+keys+') AS p,hash('+keys+') AS h '+body+') AS ranked')

def original(case,full_lines,sub_lines):
    o=min(case['benchmark_occurrences'],key=lambda o:(o['source']!='full',o['line']))
    if o['source']=='full':
        _,sql=full_lines[o['line']-1].split('||',1)
    else:
        sql,_=sub_lines[o['line']-1].split('||',1)
    return sql

def estimate(db,stmt):
    plan=json.loads(db.execute('EXPLAIN (FORMAT JSON) '+stmt).fetchone()[1])
    def walk(node):
        yield node
        for c in node['children']:yield from walk(c)
    windows=[node for top in plan for node in walk(top) if node['name']=='WINDOW']
    assert len(windows)==1
    return int(windows[0]['extra_info']['Estimated Cardinality'])

def cut(rows,estimate_column):
    scored=[(r[estimate_column]*(16+8*r['arity']),r['risk']) for r in rows]
    pos=sum(y for _,y in scored); neg=len(scored)-pos
    def metric(t):
        tp=sum(y and x>t for x,y in scored); tn=sum(not y and x<=t for x,y in scored)
        return tp*neg+tn*pos, -sum(x>t for x,y in scored)
    return max(sorted({0}|{s for s,_ in scored}),key=metric)

def millis(s):return 1000*(perf_counter()-s)

def run(args):
    global OUTPUT
    sys.path.insert(0,str(args.driver_lib))
    import _duckdb as duckdb
    cases,inputs=load(args.paper)
    old={r['case']:r for r in read(RESOURCE/'results.csv') if r['memory_mib']=='32'}
    previous=set()
    if args.replicate:
        previous={r['case'] for r in read(HERE/'decisions.csv')}
        OUTPUT=HERE/'replication'
        OUTPUT.mkdir(exist_ok=True)
    train,test,inventory,parents=cohort(cases,old,previous)
    if args.replicate:assert previous.isdisjoint(q['case_id'] for q in test)
    write('cohort.csv',inventory)
    fl=(RAW/'stats_CEB.sql').read_text(encoding='utf-8-sig').splitlines()
    sl=(RAW/'stats_CEB_sub_queries.sql').read_text(encoding='utf-8-sig').splitlines()
    print('train/test/parents',len(train),len(test),len(parents),flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp);dbfile=stage/'base.duckdb'
        create_db(duckdb,dbfile,inputs)
        db=duckdb.connect(str(dbfile),read_only=True)
        db.execute('SET threads=1')
        calibration=[]
        for cid,q in train.items():
            o=old[cid]
            risk=(o['status']!='completed' or int(o['profiler_peak_temp_bytes'] or 0)>0 or int(o['profiler_total_spill_bytes'] or 0)>0)
            cal=dict(case=cid,arity=len(q['input_ids']),row_count=q['observed_cardinality'],
                     native=estimate(db,operation(original(q,fl,sl))),risk=int(risk))
            calibration.append(cal)
        write('calibration.csv',calibration)
        truth_cut=cut(calibration,'row_count');native_cut=cut(calibration,'native')
        if args.replicate:
            fixed=json.loads((HERE/'calibration.json').read_text())
            assert (truth_cut,native_cut)==(fixed['true_cut'],fixed['native_cut'])
        (OUTPUT/'calibration.json').write_text(json.dumps(dict(true_cut=truth_cut,native_cut=native_cut,
            previous_physical_parents=sorted(parents),version=duckdb.__version__),indent=2))
        schedule=stage/'schedule.txt'
        schedule.write_text(''.join(q['case_id']+' '+str(truth_cut//(16+8*len(q['input_ids'])))+'\n' for q in test))
        db.close()
        sql={q['case_id']:operation(original(q,fl,sl)) for q in test}
        outcomes=[];decisions=[];startup=[];peak_flags={}
        for r in range(2):
            prof={}
            for method in (['certificate','natural','indexed','memo'] if r==0 else ['memo','indexed','natural','certificate']):
                costs=stage/(method+'.csv')
                start=perf_counter()
                subprocess.run([str(args.router),str(args.fixture),str(schedule),str(costs),method],check=True)
                wall=millis(start)
                data=read(costs); prof[method]={v['case_id']:v for v in data}
                inner=sum(int(t['preflight_ns'])/1e6 for t in data)
                startup.append(dict(round=r,method=method,wall_ms=wall,inner_ms=inner,extra_ms=wall-inner))
            rows=[]
            db=duckdb.connect(str(dbfile),read_only=True)
            db.execute('SET threads=1')
            for q in test:
                k=q['case_id']; arity=len(q['input_ids'])
                st=perf_counter();guess=estimate(db,sql[k]);explain_ms=millis(st)
                st=perf_counter();aggregate=statements([inputs[i] for i in q['input_ids']],{},boolean_product=False)[0]
                exact=int(db.execute(aggregate).fetchone()[0]);exact_ms=millis(st)
                assert exact==q['observed_cardinality']
                route=int(exact*(16+arity*8)>truth_cut)
                assert all(int(v[k]['high'])==route for v in prof.values())
                rows.append(dict(case=k,round=r,arity=arity,rows=exact,native=guess,certificate_high=route,
                                 native_high=int(guess*(16+arity*8)>native_cut),native_score=guess*(16+arity*8),
                                 native_ms=explain_ms,sql_ms=exact_ms,
                                 **{method+'_ms':int(v[k]['preflight_ns'])/1e6 for method,v in prof.items()}))
            db.close()
            h=sum(o['certificate_high'] for o in rows)
            top={o['case'] for o in sorted(rows,key=lambda x:(-x['native_score'],x['case']))[:h]}
            for o in rows:o['matched_native_high']=int(o['case'] in top)
            decisions.extend(rows);write('decisions.csv',decisions);write('preflight.csv',startup)
            for i,q in enumerate(test):
                cid=q['case_id']
                mems=(32,128) if (i+r)%2==0 else (128,32)
                results=[]
                for mem in mems:
                    v=measure(duckdb,dbfile,q,sql[cid],mem,stage)
                    risk=int(v['status']!='completed' or int(v['profiler_peak_temp_bytes'] or 0)>0 or int(v['profiler_total_spill_bytes'] or 0)>0)
                    results.append(dict(case=cid,round=r,memory_mib=mem,risk=risk,**v))
                if all(o['status']=='completed' for o in results):
                    assert results[0]['checksum']==results[1]['checksum']
                outcomes.extend(results)
                write('measurements.csv',outcomes)
            print('round',r,'n',len(test),'high',h,'native high',sum(o['native_high'] for o in rows),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replicate',action='store_true')
    for k in ('paper','driver_lib','fixture','router'):p.add_argument(k,type=Path)
    run(p.parse_args())

