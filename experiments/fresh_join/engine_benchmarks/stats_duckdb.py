"""Native DuckDB filtered factorized SQL control on original STATS inputs."""
import argparse
import csv
from pathlib import Path
import sys

from stats_sqlite import RAW,BUDGET,now,ms,qt,records,statements,write


def run(paper, rounds, prefix='stats-duckdb'):
    import _duckdb as duckdb
    queries,inputs=records(paper)
    db=duckdb.connect()
    loaded=[]; timings=[]; preparation=[]
    db.execute("SET threads=1")
    for table in sorted({x[0] for x in inputs.values()}):
        file=RAW/(table+'.csv')
        with file.open(encoding='utf-8-sig',newline='') as f: cols=next(csv.reader(f))
        types='{'+','.join("'"+c+"':'"+("TIMESTAMP" if "Date" in c else "BIGINT")+"'" for c in cols)+'}'
        start=now()
        db.execute(f"CREATE TABLE {qt(table)} AS SELECT * FROM read_csv(?,header=true,columns={types})",[str(file)])
        loaded.append(dict(stage='csv-load',table=table,ms=ms(start),version=duckdb.__version__))
    for threads in (1,4):
        db.execute('SET threads='+str(threads))
        for i,q in enumerate(queries):
            start=now()
            direct,_,driven=statements([inputs[k] for k in q['input_ids']],{},boolean_product=False)
            # Physical grouping has no need for a table-cardinality oracle.
            prepare=ms(start)
            stmts={'grouped_exact':direct,'driver_exact':'SELECT coalesce(sum(x),0) FROM ('+driven+') AS query(x)'}
            kind="fixed_grouped_"+str(i)+"_"+str(threads)
            begin=now()
            db.execute("PREPARE "+kind+" AS "+direct)
            preparation.append(dict(case=q["case_id"],threads=threads,ms=ms(begin)))
            stmts['grouped_prepared']="EXECUTE "+kind
            names=list(stmts)
            for r in range(-1,rounds):
                offset=(r+i)%len(names)
                for name in names[offset:]+names[:offset]:
                    start=now()
                    answer=db.execute(stmts[name]).fetchone()[0]
                    elapsed=ms(start)
                    assert answer==q['observed_cardinality'],(q['case_id'],answer,q['observed_cardinality'])
                    if r>=0: timings.append(dict(threads=threads,case=q['case_id'],observed=q['observed_cardinality'],
                                                  budget=BUDGET,method=name,rewrite_ms=prepare,round=r,ms=elapsed))
            if i%20==19: print(threads,i+1,flush=True)
        write(prefix+'-timings.csv',timings)
        write(prefix+'-preparation.csv',preparation)
    write(prefix+'-setup.csv',loaded)
    db.close()

if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('paper',type=Path)
    a.add_argument('--driver-lib',type=Path)
    a.add_argument('--rounds',type=int,default=3)
    a.add_argument('--prefix',default='stats-duckdb')
    o=a.parse_args()
    if o.driver_lib: sys.path.insert(0,str(o.driver_lib))
    run(o.paper,o.rounds,o.prefix)



