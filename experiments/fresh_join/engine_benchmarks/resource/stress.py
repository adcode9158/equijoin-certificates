"""Bounded STATS joined-row sort using a fresh DuckDB connection per run."""
import argparse
import csv
import json
import re
import sys
import tempfile
import threading
from pathlib import Path
from time import perf_counter

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from stats_sqlite import BUDGET, RAW, qt, records

LIMITS=(32,128)
TEMP_MIB=256
TIMEOUT_SECONDS=12


def run_cohort(cases):
    cases=sorted(cases,key=lambda q:q["case_id"])
    small=[q for q in cases if q["observed_cardinality"]<=1_000_000]
    near=[q for q in cases if 1_000_000<q["observed_cardinality"]<=BUDGET]
    above=[q for q in cases if BUDGET<q["observed_cardinality"]<=12_000_000]
    return [(q,t) for t,group in [("all-at-most-1M",small),("first-three-1M-to-10M",near[:3]),
                                 ("first-three-over-10M-to-12M",above[:3])] for q in group]


def create_db(duckdb,dbfile,inputs):
    db=duckdb.connect(str(dbfile))
    db.execute("SET threads=1")
    for table in sorted({x[0] for x in inputs.values()}):
        file=RAW/(table+".csv")
        with file.open(newline="",encoding="utf-8-sig") as f: cols=next(csv.reader(f))
        types="{"+",".join("'"+c+"':'"+("TIMESTAMP" if "Date" in c else "BIGINT")+"'" for c in cols)+"}"
        db.execute(f"CREATE TABLE {qt(table)} AS SELECT * FROM read_csv(?,header=true,columns={types})",[str(file)])
    db.execute("CHECKPOINT")
    db.close()


def operator(case, lines):
    occurrence=next(o for o in case["benchmark_occurrences"] if o["source"]=="full")
    truth,original=lines[occurrence["line"]-1].split("||",1)
    assert int(truth)==case["observed_cardinality"]
    body=original.strip().removesuffix(";")[len("SELECT COUNT(*) "):]
    tables=body.split(" WHERE ")[0].removeprefix("FROM ").split(",")
    names=[re.fullmatch(r"\s*\w+\s+as\s+(\w+)\s*",t,re.I).group(1) for t in tables]
    keys=",".join(qt(name)+'.Id' for name in names)
    # Order positions are consumed in a checksum coupled to each unique joined ID tuple.
    return ("SELECT count(*) AS n,coalesce(sum(CAST(p%104729 AS HUGEINT)*CAST(h%1009 AS HUGEINT)),0) AS checksum "
            "FROM (SELECT row_number() OVER (ORDER BY "+keys+") AS p,hash("+keys+") AS h "+body+") AS ranked")


def sql_string(s):
    return "'"+str(s).replace("'","''")+"'"


def monitor_temp(path,stop,result):
    while not stop.is_set():
        try:
            result[0]=max(result[0],sum(x.stat().st_size for x in path.iterdir() if x.is_file()))
        except FileNotFoundError:
            pass
        stop.wait(0.015)


def physical_operators(node):
    yield node
    for child in node.get("children",[]):
        yield from physical_operators(child)


def measure(duckdb,dbfile,case,sql,mem,staging):
    with tempfile.TemporaryDirectory(dir=staging) as sandbox:
        working=Path(sandbox)
        temp=(working/"temp");temp.mkdir()
        profile=working/"profile.json"
        db=duckdb.connect(str(dbfile),read_only=True)
        db.execute("SET threads=1")
        db.execute("SET memory_limit="+sql_string(f"{mem}MiB"))
        db.execute("SET max_temp_directory_size="+sql_string(f"{TEMP_MIB}MiB"))
        db.execute("SET temp_directory="+sql_string(temp))
        plan=" ".join(r[1] for r in db.execute("EXPLAIN "+sql).fetchall())
        assert "WINDOW" in plan.upper(),plan[:1500]
        db.execute("SET enable_profiling='json'")
        db.execute("SET profiling_output="+sql_string(profile))
        samples=[0]
        stop=threading.Event(); interrupted=threading.Event()
        def out_of_time():
            interrupted.set()
            db.interrupt()
        timer=threading.Timer(TIMEOUT_SECONDS,out_of_time)
        thread=threading.Thread(target=monitor_temp,args=(temp,stop,samples),daemon=True)
        start=perf_counter();thread.start(); timer.start()
        n=checksum=None; status="completed"; error=""
        try:
            n,checksum=db.execute(sql).fetchone()
        except duckdb.Error as e:
            error=str(e).splitlines()[0]
            status="timeout" if interrupted.is_set() else "out-of-memory" if isinstance(e,duckdb.OutOfMemoryException) else "engine-error"
        finally:
            timer.cancel(); timer.join();elapsed=perf_counter()-start
            stop.set();thread.join();db.close()
        if status=="completed":
            assert int(n)==case["observed_cardinality"]
            assert profile.exists()
            info=json.loads(profile.read_text(encoding="utf-8"))
            windows=[node for root in info["operator"] for node in physical_operators(root) if node.get("type")=="WINDOW"]
            assert windows and max(node["intermediate_rows"] for node in windows)==n
            memory=info["system"]["peak_buffer_memory"]
            spilled=info["system"]["peak_temp_dir_size"]
            spill_bytes=info["system"]["total_bytes_spilled"]
        else:
            assert status in ("timeout","out-of-memory"),error
            memory=spilled=spill_bytes=None
        return dict(status=status,error=error,elapsed_ms=round(elapsed*1000,3),output_count=n,checksum=checksum,
                    profiler_peak_buffer_bytes=memory,profiler_peak_temp_bytes=spilled,profiler_total_spill_bytes=spill_bytes,sampled_peak_temp_bytes=samples[0])


def main(paper):
    import _duckdb as duckdb
    cases,inputs=records(paper)
    cohort=run_cohort(cases)
    lines=(RAW/"stats_CEB.sql").read_text(encoding="utf-8-sig").splitlines()
    rows=[]
    with tempfile.TemporaryDirectory(dir=HERE) as loc:
        staging=Path(loc)
        dbfile=staging/"input.duckdb"
        create_db(duckdb,dbfile,inputs)
        for case,stratum in cohort:
            sql=operator(case,lines)
            pair=[]
            for mem in LIMITS:
                r=measure(duckdb,dbfile,case,sql,mem,staging)
                row=dict(case=case["case_id"],source_line=next(o["line"] for o in case["benchmark_occurrences"] if o["source"]=="full"),
                         stratum=stratum,inputs=len(case["input_ids"]),observed=case["observed_cardinality"],
                         fits_row_budget=int(case["observed_cardinality"]<=BUDGET), memory_mib=mem,
                         max_temp_mib=TEMP_MIB,version=duckdb.__version__,**r)
                rows.append(row);pair.append(row)
            if all(r["status"]=="completed" for r in pair):
                assert pair[0]["checksum"]==pair[1]["checksum"]
            with (HERE/"results.csv").open("w",newline="",encoding="utf-8") as f:
                writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            print(case["case_id"],case["observed_cardinality"],[(r["status"],r["profiler_peak_temp_bytes"]) for r in pair],flush=True)
    assert len(rows)==len(cohort)*len(LIMITS)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("paper",type=Path)
    p.add_argument("--driver-lib",type=Path)
    a=p.parse_args()
    if a.driver_lib: sys.path.insert(0,str(a.driver_lib))
    main(a.paper)



