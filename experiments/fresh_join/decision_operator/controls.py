"""Score fixed-head estimates on old labels, replay new paired grants and attribute spill bytes."""
import argparse
import csv
import json
import subprocess
import tempfile
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

import validate

HERE=Path(__file__).resolve().parent
METHODS=('head_lower','head_ratio','unfiltered')

def save(path,rows):
    with path.open('w',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)

def estimate(executable,fixture,keys):
    with tempfile.TemporaryDirectory() as tmp:
        schedule=Path(tmp)/'schedule.txt';out=Path(tmp)/'counts.csv'
        schedule.write_text('\n'.join(keys)+'\n')
        start=perf_counter()
        subprocess.run([executable,fixture,schedule,out],check=True)
        rows=validate.read(out)
        return {q['case']:q for q in rows},start

def evaluate(folder,parents,thresholds,executable,fixture):
    decisions=validate.read(folder/'decisions.csv')
    physical={(q['case'],int(q['round']),int(q['memory_mib'])):q for q in validate.read(folder/'measurements.csv')}
    result=[];scored=[];attribution=[]
    for rnd in (0,1):
        rows=[q for q in decisions if int(q['round'])==rnd]
        native_high=sum(int(q['certificate_high']) for q in rows)
        estimates,start=estimate(executable,fixture,[q['case'] for q in rows]);score={}
        for q in rows:
            k=q['case']; arity=int(q['arity']); base=16+8*arity
            score[k]={m:float(estimates[k][m])*base for m in METHODS}
            scored.append(dict(round=rnd,case=k,**score[k]))
        for method in METHODS:
            for placement in ('calibrated','matched'):
                clock=perf_counter()
                if placement=='matched':
                    high=set(sorted(score,key=lambda k:(-score[k][method],k))[:native_high])
                else:
                    high={k for k in score if score[k][method]>thresholds[method]}
                scoring_ms=1000*(perf_counter()-clock)
                observations=[physical[k,rnd,128 if k in high else 32] for k in score]
                result.append(dict(round=rnd,method=method,placement=placement,cut=thresholds[method],high=len(high),
                    differs_certificate=sum((q['case'] in high)!=bool(int(q['certificate_high'])) for q in rows),
                    failures=sum(q['status']!='completed' for q in observations),spills=sum(int(q['risk']) for q in observations),
                    spill_bytes=sum(int(q['profiler_total_spill_bytes'] or 0) for q in observations),
                    preflight_ms=0,total_ms=round(sum(float(q['elapsed_ms']) for q in observations)+scoring_ms,3),score_ms=scoring_ms))
        full=1000*(perf_counter()-start)
        for x in result[-2*len(METHODS):]:
            x['preflight_ms']=round(full,3);x['total_ms']=round(x['total_ms']+full-x.pop('score_ms'),3)
        for q in rows:
            k=q['case']; refs=parents[k]; cert=physical[k,rnd,128 if int(q['certificate_high']) else 32];native=physical[k,rnd,128 if int(q['matched_native_high']) else 32]
            a=cert['profiler_total_spill_bytes']; b=native['profiler_total_spill_bytes']
            comparable=cert['status']==native['status']=='completed'
            attribution.append(dict(round=rnd,case=k,canonical_parent=refs[0],all_parents='|'.join(map(str,sorted(set(refs)))),certificate_high=q['certificate_high'],native_high=q['matched_native_high'],certificate_status=cert['status'],native_status=native['status'],certificate_bytes=a,native_bytes=b,saved_bytes=int(b)-int(a) if comparable else ''))
    save(folder/'approximate_scores.csv',scored);save(folder/'approximate.csv',result);save(folder/'attribution.csv',attribution)
    for rnd in (0,1):
        rows=[r for r in attribution if r['round']==rnd]
        for sign in (-1,1):
            affected=[r for r in rows if r['saved_bytes']!='' and sign*r['saved_bytes']>0]
            print(folder.name,rnd,sign,len(affected),'canonical parents',sorted({r['canonical_parent'] for r in affected}),'diff',sum(r['saved_bytes'] for r in affected))
    print(folder.name, 'parents',len({p for r in rows for p in parents[r['case']]}))
    for r in result: print(r['round'],r['method'],r['placement'],r['high'],r['spills'],r['spill_bytes'],r['total_ms'])

def main(args):
    with ZipFile(args.paper/'supplement.zip') as archive:
        qs=list(map(json.loads,archive.open('validation-data/inputs/query-cases.jsonl')))
    parents={q['case_id']:[o['parent'] for o in sorted(q['benchmark_occurrences'],key=lambda a:a['line'])] for q in qs}
    train=validate.read(HERE/'calibration.csv')
    estimates,_=estimate(args.executable,args.fixture,[x['case'] for x in train]);thresholds={}
    for method in METHODS:
        rows=[dict(arity=int(x['arity']),risk=int(x['risk']),estimate=float(estimates[x['case']][method])) for x in train]
        thresholds[method]=validate.cut(rows,'estimate')
    for folder in [HERE,HERE/'replication']:
        evaluate(folder,parents,thresholds,args.executable,args.fixture)

if __name__=='__main__':
    arg=argparse.ArgumentParser(description=__doc__)
    for name in ('paper','fixture','executable'):arg.add_argument(name,type=Path)
    main(arg.parse_args())
