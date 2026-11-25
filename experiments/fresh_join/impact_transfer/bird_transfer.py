"""Cross-schema validation on pre-existing BIRD financial and Formula 1 SQL."""
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INPUTS = ROOT / 'inputs' / 'bird'
sys.path.insert(0, str(HERE.parent / 'impact_schema'))
import sqlglot
from sqlglot import exp
from dimension_certificates import bounds, high_weight_first, minimum_certificate

BUDGETS = (10, 100, 1000, 10_000, 100_000)
DATASETS = ('financial', 'formula_1')


def atoms(node):
    if isinstance(node, exp.And):
        return atoms(node.this) + atoms(node.expression)
    return [node]


def sql(node):
    return node.sql(dialect='sqlite', identify=True)


def eligible(row, db):
    tree = sqlglot.parse_one(row['SQL'], read='sqlite')
    if not isinstance(tree,exp.Select) or len(list(tree.find_all(exp.Select))) != 1:
        return
    joins = tree.args.get('joins',[])
    if len(joins)!=1 or tree.args.get('where') is None or 'from_' not in tree.args:
        return
    join = joins[0]
    eq = join.args.get('on')
    if (join.args.get('side') or join.args.get('kind','').upper() not in ('','INNER')
            or not isinstance(eq,exp.EQ) or not all(isinstance(x,exp.Column) for x in [eq.this,eq.expression])):
        return
    tables=[tree.args['from_'].this,join.this]
    if not all(isinstance(t,exp.Table) for t in tables) or tables[0].name==tables[1].name:
        return
    aliases=[t.alias_or_name.lower() for t in tables]
    keys={x.table.lower():x for x in [eq.this,eq.expression]}
    if set(keys)!=set(aliases):
        return
    conditions=defaultdict(list)
    for condition in atoms(tree.args['where'].this):
        names={c.table.lower() for c in condition.find_all(exp.Column)}
        if len(names)!=1 or not names.issubset(aliases): return
        conditions[names.pop()].append(condition)
    for d,table in enumerate(tables):
        name=table.name.replace('"','""')
        pk=[p for p in db.execute(f'pragma table_info("{name}")') if p[5]]
        alias=aliases[d]
        if (conditions[alias] and len(pk)==1 and pk[0][1].lower()==keys[alias].name.lower()
                and pk[0][2].upper()=='INTEGER'):
            break
    else:
        return
    di,fa=aliases[d],aliases[1-d]
    # Predicates on a known dimension identifier can reveal labels directly.
    # Exclude the entire case if any dimension restriction mentions the chosen PK.
    if any(c.name.lower() == keys[di].name.lower()
           for cond in conditions[di] for c in cond.find_all(exp.Column)):
        return
    dim,fact=map(sql,[tables[d],tables[1-d]])
    dk,fk=map(sql,[keys[di],keys[fa]])
    fwhere=' AND '.join('('+sql(x)+')' for x in conditions[fa]) or 'TRUE'
    dwhere=' AND '.join('('+sql(x)+')' for x in conditions[di])
    domain=[x for x, in db.execute(f'SELECT {dk} FROM {dim}')]
    passed={x for x, in db.execute(f'SELECT {dk} FROM {dim} WHERE {dwhere}')}
    grouped=dict(db.execute(f'SELECT {fk},count(*) FROM {fact} WHERE {fwhere} GROUP BY {fk}'))
    weights={x:grouped.get(x,0) for x in domain}
    # Verify the actual joined, filtered row set before projection, grouping, ordering and LIMIT.
    reference='SELECT COUNT(*) '+sql(tree.args['from_'])+' '+sql(join)+' '+sql(tree.args['where'])
    actual=db.execute(reference).fetchone()[0]
    assert actual==sum(weights[x] for x in passed)
    return weights,passed,actual,tables[d].name,tables[1-d].name,reference


def main():
    dev=json.loads((INPUTS/'dev.json').read_text(encoding='utf-8'))
    rows=[]
    for name in DATASETS:
        dbfile=INPUTS/(name+'.sqlite')
        db=sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True)
        records=[r for r in dev if r['db_id']==name]
        n=0
        for row in records:
            item=eligible(row,db)
            if not item: continue
            weights,passed,actual,dim,fact,reference=item
            n+=1
            lo,hi=bounds(weights.values(),len(passed),0)
            for budget in BUDGETS:
                probes,adm=high_weight_first(weights,len(passed),passed.__contains__,budget)
                oracle=len(minimum_certificate(weights,passed,budget)) if adm else None
                assert adm==(actual<=budget) and lo<=actual<=hi and (not adm or oracle<=probes)
                rows.append(dict(dataset=name,question_id=row['question_id'],dimension=dim,fact=fact,
                                 domain=len(weights),passed=len(passed),observed=actual,initial_min=lo,
                                 initial_max=hi,budget=budget,admitted=int(adm),minimum=oracle,
                                 descending_probes=probes,reference=reference))
        print(name,'eligible',n,'of',len(records),'sha256',hashlib.sha256(dbfile.read_bytes()).hexdigest())
        db.close()
    with (HERE/'bird-results.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
    summary=[]
    for name in DATASETS:
        for b in BUDGETS:
            selected=[r for r in rows if r['dataset']==name and r['budget']==b]
            fit=[r for r in selected if r['admitted']]
            hard=[r for r in fit if r['minimum']>0]
            def med(key):return median(r[key] for r in hard) if hard else None
            summary.append(dict(dataset=name,budget=b,queries=len(selected),fit=len(fit),
                                initial_admissions=len(fit)-len(hard),additional_yes=len(hard),
                                min_median_among_additional=med('minimum'),descending_median_among_additional=med('descending_probes'),
                                min_max_among_additional=max((r['minimum'] for r in hard),default=None)))
    with (HERE/'bird-summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=summary[0]);w.writeheader();w.writerows(summary)
    for r in summary: print(list(r.values()))

if __name__=='__main__':main()
