"""Run both complete grant policies with real immediate OOM retries on one connection per stream."""
import argparse
import csv
import json
import subprocess
import sys
import tempfile
import threading
from contextlib import closing
from pathlib import Path
from time import perf_counter

import validate
from stress import TEMP_MIB,TIMEOUT_SECONDS,create_db,sql_string

HERE=Path(__file__).resolve().parent

def write(path,rows):
    with path.open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)

def grants(db,rows,limit,threshold,policy,fixture,executable,stage):
    if policy=='native':
        estimates=[(validate.estimate(db,sql)*(16+8*len(q['input_ids'])),q['case_id']) for q,sql in rows]
        return {k for _,k in sorted(estimates,key=lambda e:(-e[0],e[1]))[:limit]}
    schedule=stage/'budget.txt'; predicted=stage/'decisions.csv'
    schedule.write_text(''.join(q['case_id']+' '+str(threshold//(16+8*len(q['input_ids'])))+'\n' for q,_ in rows))
    subprocess.run([executable,fixture,schedule,predicted,'certificate'],check=True)
    return {r['case_id'] for r in validate.read(predicted) if r['high']=='1'}

def physical(duckdb,db,sql,grant):
    timer=threading.Timer(TIMEOUT_SECONDS,db.interrupt)
    start=perf_counter();timer.start()
    try:
        db.execute('SET memory_limit='+sql_string(str(grant)+'MiB'))
        n,checksum=db.execute(sql).fetchone()
        status='completed';error=''
    except duckdb.Error as exc:
        n=checksum='';status='out-of-memory' if isinstance(exc,duckdb.OutOfMemoryException) else 'engine-error'
        error=str(exc).splitlines()[0]
    finally:
        timer.cancel();timer.join()
    return dict(grant_mib=grant,status=status,error=error,rows=n,checksum=checksum,elapsed_ms=round((perf_counter()-start)*1000,3))

def stream(duckdb,dbfile,cohort,test,limit,threshold,policy,rnd,full_sql,sub_sql,args):
    start=perf_counter();attempts=[]
    with tempfile.TemporaryDirectory() as temp:
        stage=Path(temp);spill=stage/'spill';spill.mkdir()
        with closing(duckdb.connect(str(dbfile),read_only=True)) as db:
            db.execute('SET threads=1');db.execute('SET max_temp_directory_size='+sql_string(str(TEMP_MIB)+'MiB'))
            db.execute('SET temp_directory='+sql_string(spill))
            rows=[(q,validate.operation(validate.original(q,full_sql,sub_sql))) for q in test]
            stage_start=perf_counter()
            use_high=grants(db,rows,limit,threshold,policy,args.fixture,args.router,stage)
            policy_ms=1000*(perf_counter()-stage_start)
            assert len(use_high)==limit
            for q,sql in rows:
                k=q['case_id'];grant=128 if k in use_high else 32
                for attempt in (1,2):
                    m=physical(duckdb,db,sql,grant)
                    attempts.append(dict(cohort=cohort,round=rnd,policy=policy,case=k,attempt=attempt,**m))
                    if m['status']=='completed':assert m['rows']==q['observed_cardinality']
                    if m['status']!='out-of-memory' or grant!=32:break
                    grant=128
    wall=1000*(perf_counter()-start)
    return attempts,dict(cohort=cohort,round=rnd,policy=policy,queries=len(test),initial_high=len(use_high),
        high_attempts=sum(r['grant_mib']==128 for r in attempts),attempts=len(attempts),
        low_oom=sum(r['grant_mib']==32 and r['status']=='out-of-memory' for r in attempts),
        successes=sum(r['status']=='completed' for r in attempts),decision_ms=round(policy_ms,3),wall_ms=round(wall,3))

def main(args):
    sys.path.insert(0,str(args.driver_lib))
    import _duckdb as duckdb
    cases,inputs=validate.load(args.paper)
    old={r['case'] for r in validate.read(HERE/'calibration.csv')}
    _,a,_,_=validate.cohort(cases,old)
    _,b,_,_=validate.cohort(cases,old,{q['case_id'] for q in a})
    threshold=json.loads((HERE/'calibration.json').read_text())['true_cut']
    full_sql=(validate.RAW/'stats_CEB.sql').read_text(encoding='utf-8-sig').splitlines()
    sub_sql=(validate.RAW/'stats_CEB_sub_queries.sql').read_text(encoding='utf-8-sig').splitlines()
    total=[];records=[];output={}
    with tempfile.TemporaryDirectory() as tmp:
        dbfile=Path(tmp)/'base.duckdb';create_db(duckdb,dbfile,inputs)
        for rnd in (0,1):
            for cohort,test,limit in [('A',a,12),('B',b,13)]:
                assert len(test)==32
                order=['certificate','native'] if (rnd==0)==(cohort=='A') else ['native','certificate']
                for policy in order:
                    attempts,summary=stream(duckdb,dbfile,cohort,test,limit,threshold,policy,rnd,full_sql,sub_sql,args)
                    for row in attempts:
                        if row['status']=='completed':
                            value=(row['rows'],row['checksum']);assert output.setdefault(row['case'],value)==value
                    total.extend(attempts);records.append(summary)
                    write(HERE/'live_attempts.csv',total);write(HERE/'live_streams.csv',records)
                    print(summary,flush=True)

if __name__=='__main__':
    arg=argparse.ArgumentParser(description=__doc__)
    for k in ('paper','driver_lib','fixture','router'):arg.add_argument(k,type=Path)
    main(arg.parse_args())
