"""Apply the frozen BIRD pilot rules to every remaining development database."""
import csv
import json
import sqlite3
from collections import Counter
from pathlib import Path
from statistics import median

from bird_transfer import (BUDGETS, DATASETS, HERE, INPUTS, bounds, eligible, high_weight_first,
                           minimum_certificate, sqlglot)


def write_csv(stem, fields, rows):
    with (HERE/(stem+'.csv')).open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    dev=json.loads((INPUTS/'dev.json').read_text(encoding='utf-8'))
    datasets=sorted({r['db_id'] for r in dev}-set(DATASETS))
    assert len(datasets)==9
    rows=[]; errors=[]; inventory=[]
    for name in datasets:
        dbfile=INPUTS/(name+'.sqlite')
        wal=Path(str(dbfile)+'-wal')
        if wal.exists() and wal.stat().st_size:
            raise RuntimeError('Live WAL cannot be ignored: '+str(wal))
        db=sqlite3.connect(dbfile.as_uri()+'?mode=ro&immutable=1',uri=True)
        db.execute('PRAGMA query_only=ON')
        records=[r for r in dev if r['db_id']==name]
        selected=0
        for row in records:
            try:
                item=eligible(row,db)
            except (sqlglot.errors.ParseError,sqlite3.Error) as exc:
                errors.append(dict(dataset=name,question_id=row['question_id'],type=type(exc).__name__,reason=str(exc)))
                continue
            if not item: continue
            weights,passed,actual,dim,fact,reference=item
            selected+=1
            lo,hi=bounds(weights.values(),len(passed),0)
            for budget in BUDGETS:
                if hi<=budget or lo>budget:
                    probes,adm=0,hi<=budget
                    oracle=0 if adm else None
                else:
                    probes,adm=high_weight_first(weights,len(passed),passed.__contains__,budget)
                    oracle=len(minimum_certificate(weights,passed,budget)) if adm else None
                assert adm==(actual<=budget) and lo<=actual<=hi and (not adm or oracle<=probes)
                rows.append(dict(dataset=name,question_id=row['question_id'],dimension=dim,fact=fact,
                                 domain=len(weights),passed=len(passed),observed=actual,initial_min=lo,
                                 initial_max=hi,budget=budget,admitted=int(adm),minimum=oracle,
                                 descending_probes=probes,reference=reference))
        db.close()
        inventory.append(dict(dataset=name,questions=len(records),eligible=selected,
                              distinct=len({r['reference'] for r in rows if r['dataset']==name}),
                              errors=sum(r['dataset']==name for r in errors)))
        print(inventory[-1],flush=True)
    write_csv('bird-holdout-results',list(rows[0]),rows)
    write_csv('bird-holdout-inventory',list(inventory[0]),inventory)
    write_csv('bird-holdout-errors', ['dataset','question_id','type','reason'],errors)
    summaries=[]
    for name in [*datasets,'all-nine']:
        for budget in BUDGETS:
            occurrences=[r for r in rows if r['budget']==budget and (r['dataset']==name or name=='all-nine')]
            unique={(r['dataset'],r['reference']):r for r in occurrences}
            selected=list(unique.values())
            fit=[r for r in selected if r['admitted']]
            hard=[r for r in fit if r['minimum']>0]
            stats=dict(dataset=name,budget=budget,questions=len(occurrences),joins=len(selected),fit=len(fit),
                       initial=len(fit)-len(hard),additional=len(hard))
            for key in ('minimum','descending_probes'):
                values=[r[key] for r in hard]
                stats[key+'_median']=median(values) if values else None
                stats[key+'_max']=max(values) if values else None
            summaries.append(stats)
    write_csv('bird-holdout-summary',list(summaries[0]),summaries)
    for r in summaries:
        if r['dataset']=='all-nine' or r['budget']==100: print(list(r.values()))

if __name__=='__main__':
    main()
