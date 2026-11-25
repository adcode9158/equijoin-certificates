"""Find the smallest number of user payload transpositions that cross the budget.

Verify each minimum-edit witness by running its dimension predicate on row data.
"""
import csv
import json
import re
import sys
from math import prod
from pathlib import Path
from zipfile import ZipFile

from bench_dimension import user_database
from dimension_certificates import BUDGET
from permutation_witness import load


def main(root,raw,out):
    cases,base,meta=load(root)
    dim=base['users','Id']
    db=user_database(raw)
    db.execute('CREATE TEMP TABLE row_swap (id INTEGER PRIMARY KEY, donor INTEGER UNIQUE NOT NULL)')
    columns={r[1] for r in db.execute('PRAGMA table_info(users)')}
    with ZipFile(root/'supplement.zip') as z:
        users=[r for r in map(json.loads,z.open('validation-data/inputs/filtered-key-frequencies.jsonl')) if r['table']=='users']
    attrs={a for r in users for a in re.findall(r'\b([A-Za-z]\w*)\s*[<>=]',r['predicate'])}
    assert attrs<=columns and 'Id' not in attrs
    assert all(r['column']=='Id' and len(r['key_frequency_pairs'])>24 and
               all(v==1 for _,v in r['key_frequency_pairs']) for r in users)
    project=','.join(('p.' if c in attrs else 'u.')+c+' AS '+c for c in sorted(columns))
    db.execute('CREATE TEMP VIEW changed AS SELECT '+project+
               ' FROM users u LEFT JOIN row_swap s ON u.Id=s.id JOIN users p ON p.Id=coalesce(s.donor,u.Id)')
    with (out/'dimension-swaps.csv').open('w',newline='') as f:
        writer=csv.writer(f)
        writer.writerow(['case_id','observed','min_disjoint_swaps','witness','users_payload_swaps'])
        for q in cases:
            ids=q['input_ids']
            key=[i for i in ids if meta[i][0]==('users','Id') and meta[i][1]!='TRUE']
            actual=q['observed_cardinality']
            if not key or actual>BUDGET: continue
            i,=key
            _,pred,source=meta[i]
            other=[meta[j][2] for j in ids if j!=i]
            w={k:prod(m.get(k,0) for m in other) for k in dim}
            yes=set(source)
            remove=sorted(yes,key=lambda x:(w[x],x))
            add=sorted(dim.keys()-yes,key=lambda x:(-w[x],x))
            changed=actual
            pairs=[]
            for a,b in zip(remove,add):
                gain=w[b]-w[a]
                if gain<=0 or changed>BUDGET: break
                pairs.append((a,b))
                changed+=gain
            if changed<=BUDGET: continue
            assert changed-(w[pairs[-1][1]]-w[pairs[-1][0]])<=BUDGET
            db.execute('DELETE FROM row_swap')
            db.executemany('INSERT INTO row_swap VALUES (?,?)',[(x,y) for a,b in pairs for x,y in ((a,b),(b,a))])
            result={k for k, in db.execute('SELECT Id FROM changed WHERE '+pred.replace('::timestamp',''))}
            assert len(result)==len(yes)
            assert result==(yes-{a for a,b in pairs})|{b for a,b in pairs}
            assert sum(w[k] for k in result)==changed
            writer.writerow([q['case_id'],actual,len(pairs),changed,json.dumps(pairs)])


if __name__=='__main__':
    main(*map(Path,sys.argv[1:]))
