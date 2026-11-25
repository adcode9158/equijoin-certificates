"""Price one high-grant retry on a low-grant OOM using the existing paired physical executions."""
import csv
from pathlib import Path

import validate

HERE=Path(__file__).resolve().parent

for folder in (HERE,HERE/'replication'):
    decisions=validate.read(folder/'decisions.csv'); measurements=validate.read(folder/'measurements.csv')
    costs=validate.read(folder/'comparison.csv'); rows=[]
    for rnd in ('0','1'):
        stream=[r for r in decisions if r['round']==rnd]
        physical={(r['case'],int(r['memory_mib'])):r for r in measurements if r['round']==rnd}
        assert len(physical)==2*len(stream)
        outcomes=[]; final=[]; high=retry=0
        for q in stream:
            key=q['case']; grant=128 if int(q['matched_native_high']) else 32
            low=physical[key,grant];high+=int(grant==128);outcomes.append(low)
            if low['status']=='out-of-memory' and grant==32:
                high+=1;retry+=1;outcomes.append(physical[key,128])
            final.append(outcomes[-1])
        native_ms=sum(float(q['native_ms']) for q in stream)
        operator_ms=sum(float(r['elapsed_ms']) for r in outcomes)
        certificate=next(r for r in costs if r['round']==rnd and r['method']=='certificate_cold')
        rows.append(dict(round=rnd,queries=len(stream),attempts=len(outcomes),extra_high_retries=retry,total_high_grants=high,
            successes=sum(r['status']=='completed' for r in final),risk_on_final_attempt=sum(int(r['risk']) for r in final),
            observed_spill_bytes_final=sum(int(r['profiler_total_spill_bytes'] or 0) for r in final),
            unprofiled_attempts=sum(not r['profiler_total_spill_bytes'] for r in outcomes),
            native_explain_ms=round(native_ms,3),native_retry_ms_with_explain=round(operator_ms+native_ms,3),
            native_retry_ms_free_explain=round(operator_ms,3),certificate_cold_ms=certificate['total_ms']))
    with (folder/'retry.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    for r in rows: print(folder.name,*r.values())
