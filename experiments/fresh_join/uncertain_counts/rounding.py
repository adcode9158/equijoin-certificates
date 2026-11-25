"""Controlled effect of rounding one dimension cardinality while the fact is unfiltered."""
import csv
import sqlite3
from bisect import bisect_left,bisect_right
from itertools import accumulate
from pathlib import Path
from statistics import median

from bird_boxes import HERE, INPUTS, records
from bird_transfer import eligible
import json

def minima(weights, passed, caps, budget):
    yes=sorted(weights[i] for i in passed)
    no=sorted(v for i,v in weights.items() if i not in passed)
    assert sum(yes)<=budget
    sy=list(accumulate(yes,initial=0))
    sn=list(accumulate(no,initial=0))
    best=[len(weights)]*len(caps)
    for t in set(weights.values())|{0}:
        py,pn=bisect_right(yes,t),bisect_right(no,t)
        excess=(sy[-1]-sy[py]-(len(yes)-py)*t
                +sn[-1]-sn[pn]-(len(no)-pn)*t)
        def savings(g):
            a,b=bisect_right(yes,t-g),bisect_left(no,t+g)
            return a+len(no)-b,a*t-sy[a]+sn[-1]-sn[b]-(len(no)-b)*t
        maximum=savings(1)[1]
        for j,cap in enumerate(caps):
            need=cap*t+excess-budget
            if need<=0:
                best[j]=0
            elif need<=maximum and best[j]:
                lo,hi=1,max(t,(no[-1] if no else 0)-t)+1
                while lo+1<hi:
                    mid=(lo+hi)//2
                    if savings(mid)[1]>=need: lo=mid
                    else: hi=mid
                n,saved=savings(lo+1)
                best[j]=min(best[j],n+(need-saved+lo-1)//lo)
    return best


def main():
    questions={r['question_id']:r for r in json.loads((INPUTS/'dev.json').read_text(encoding='utf-8'))}
    with (HERE/'bird.csv').open() as f:
        cohort=[r for r in csv.DictReader(f) if r['fits']=='1' and r['budget']=='100' and r['unknown_inputs']=='1']
    result=[]
    for domain in sorted({r['dataset'] for r in cohort}):
        db=sqlite3.connect((INPUTS/(domain+'.sqlite')).as_uri()+'?mode=ro&immutable=1',uri=True)
        for row in (r for r in cohort if r['dataset']==domain):
            q=questions[int(row['question_id'])]
            weights,passed,truth,*_=eligible(q,db)
            n,m=len(weights),len(passed)
            caps=[m,min(n,m+1),min(n,m+10),min(n,m+100),min(n,16*((m+15)//16)),n]
            optimum=minima(weights,passed,caps,100)
            assert optimum[0]==int(row['previous_rich_min']) and optimum[-1]==int(row['minimum'])
            result.append(dict(dataset=domain,question=q['question_id'],observed=truth,domain=n,passing=m,
                               exact=optimum[0],one_extra=optimum[1],ten_extra=optimum[2],
                               hundred_extra=optimum[3],rounded16=optimum[4],no_count=optimum[5]))
        db.close()
    with (HERE/'rounding.csv').open('w',newline='') as f:
        out=csv.DictWriter(f,fieldnames=result[0]);out.writeheader();out.writerows(result)
    hard=[r for r in result if r['dataset'] not in ('formula_1','financial') and r['exact']>0]
    for name,group in [('heldout',hard),('without codebase',[r for r in hard if r['dataset']!='codebase_community'])]:
        print(name,len(group),[(k,median(r[k] for r in group)) for k in ('exact','one_extra','ten_extra','hundred_extra','rounded16','no_count')])
    print([r for r in result if r['question']==552])

if __name__=='__main__':
    main()

