"""Certified dimension count caps from conventional range histograms and duplicate counts."""
import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from math import ceil, prod
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE.parent/'impact_transfer'),str(HERE.parent/'impact_schema')]
from bird_transfer import INPUTS, atoms, eligible, exp, sqlglot
from bench_dimension import user_database
from permutation_witness import load
from curve import PrecisionCurve


def quote(name):
    return '"'+name.replace('"','""')+'"'


def conditions(tree,alias):
    """Unsupported conjuncts are omitted, which only widens the upper bound."""
    output=defaultdict(list)
    ops={exp.EQ:'=',exp.LT:'<',exp.LTE:'<=',exp.GT:'>',exp.GTE:'>='}
    for cond in atoms(tree):
        if not isinstance(cond.this,exp.Column):
            continue
        col=cond.this
        if col.table and col.table.lower()!=alias.lower():
            continue
        if type(cond) in ops:
            tests=[(ops[type(cond)],cond.expression)]
        elif isinstance(cond,exp.Between):
            tests=[('>=',cond.args['low']),('<=',cond.args['high'])]
        else:
            continue
        for operator,literal in tests:
            if isinstance(literal,exp.Literal) or (isinstance(literal,exp.Neg) and isinstance(literal.this,exp.Literal)):
                output[col.name].append((operator,literal.sql(dialect='sqlite')))
    return output


class Catalog:
    def __init__(self,db):
        self.source=db
        self.aux=sqlite3.connect(':memory:')
        self.columns={}

    def build(self,table,col):
        name=table,col
        if name in self.columns:
            return self.columns[name]
        source_sql=self.source.execute('SELECT sql FROM sqlite_master WHERE type="table" AND name=?',(table,)).fetchone()[0]
        # Collations can change both equivalence classes and order. Default to no bound.
        if re.search(r'\bCOLLATE\b',source_sql,re.I):
            self.columns[name]=None
            return
        typ=next(r[2].upper() for r in self.source.execute('PRAGMA table_info('+quote(table)+')') if r[1].lower()==col.lower())
        affinity=('INTEGER' if 'INT' in typ else 'TEXT' if any(x in typ for x in ('CHAR','CLOB','TEXT'))
                  else 'BLOB' if 'BLOB' in typ or not typ else 'REAL' if any(x in typ for x in ('REAL','FLOA','DOUB')) else 'NUMERIC')
        table_sql,col_sql=quote(table),quote(col)
        groups=list(self.source.execute(f'SELECT {col_sql},count(*) FROM {table_sql} WHERE {col_sql} IS NOT NULL GROUP BY {col_sql} ORDER BY {col_sql}'))
        index=len(self.columns)
        hist,exceptions=f'h{index}',f'e{index}'
        self.aux.execute(f'CREATE TABLE {hist}(lo {affinity},hi {affinity},mass INTEGER,peak INTEGER)')
        self.aux.execute(f'CREATE TABLE {exceptions}(val {affinity} PRIMARY KEY,n INTEGER) WITHOUT ROWID')
        self.aux.executemany(f'INSERT INTO {exceptions} VALUES (?,?)',((v,c) for v,c in groups if c>1))
        target=max(1,ceil(sum(c for _,c in groups)/64))
        bins=[]
        mass=peak=0
        for value,count in groups:
            if not mass: first=value
            mass+=count
            peak=max(peak,count)
            if mass>=target:
                bins.append((first,value,mass,peak)); mass=peak=0
        if mass: bins.append((first,groups[-1][0],mass,peak))
        assert len(bins)<=64
        self.aux.executemany(f'INSERT INTO {hist} VALUES (?,?,?,?)',bins)
        self.columns[name]=hist,exceptions,len(bins),sum(c>1 for _,c in groups),len(groups)
        return self.columns[name]

    def caps(self,table,constraints,n):
        histogram,duplicate=n,n
        for col,tests in constraints.items():
            layout=self.build(table,col)
            if layout is None: continue
            hist,exceptions=layout[:2]
            possible=[]; equal=[]
            for op,lit in tests:
                if op=='=':
                    possible.extend(['lo <= '+lit,'hi >= '+lit])
                    equal.append(lit)
                else: possible.append(('lo ' if '<' in op else 'hi ')+op+' '+lit)
            field='peak' if equal else 'mass'
            q=f'SELECT coalesce(sum({field}),0) FROM {hist} WHERE '+' AND '.join(possible)
            histogram=min(histogram,self.aux.execute(q).fetchone()[0])
            for lit in equal:
                row=self.aux.execute(f'SELECT n FROM {exceptions} WHERE val = '+lit).fetchone()
                duplicate=min(duplicate,row[0] if row else 1)
        return histogram,duplicate


def evaluate(case,source,truth,weights,passed,budget,caps):
    n,m=len(weights),len(passed)
    hist,dup=caps
    assert truth==sum(weights[k] for k in passed) and m<=min(hist,dup)<=n
    if truth>budget:
        return None
    curve=PrecisionCurve(weights,passed,budget)
    counts={'exact':m,'plus1':min(m+1,n),'plus10':min(m+10,n),'hist64':hist,
            'exceptions':dup,'combined':min(hist,dup),'none':n}
    costs={u:curve.minimum(u) for u in set(counts.values())}
    row=dict(source=source,case_id=case,budget=budget,observed=truth,dimension_keys=n,passing=m,
             histogram_cap=hist,exceptions_cap=dup)
    row.update((label,costs[u]) for label,u in counts.items())
    for k in (0,1,8,64):
        row['largest_cap_'+str(k)]=curve.largest_cap(k)
        assert (row['largest_cap_'+str(k)] is not None)==(costs[m]<=k)
    return row


def write(name,rows):
    with (HERE/name).open('w',newline='',encoding='utf-8') as dest:
        writer=csv.DictWriter(dest,fieldnames=rows[0])
        writer.writeheader(); writer.writerows(rows)


def run(paper):
    rows=[]; inventory=[]
    cases,base,meta=load(paper)
    db=user_database(ROOT.parent/'packing/workload/raw')
    cat=Catalog(db); domain=base['users','Id']
    for q in cases:
        dim=[i for i in q['input_ids'] if meta[i][0]==('users','Id') and meta[i][1]!='TRUE']
        if not dim: continue
        d,=dim; _,predicate,selected=meta[d]
        weights={k:prod(meta[i][2].get(k,0) for i in q['input_ids'] if i!=d) for k in domain}
        clauses=conditions(sqlglot.parse_one(predicate.replace('::timestamp',''),read='sqlite'),'')
        row=evaluate(q['case_id'],'STATS',q['observed_cardinality'],weights,set(selected),10**7,
                     cat.caps('users',clauses,len(domain)))
        if row: rows.append(row)
    def record(schema,cat):
        for (table,col),layout in cat.columns.items():
            if layout:
                inventory.append(dict(source=schema,table=table,column=col,bins=layout[2],
                                      duplicate_values=layout[3],distinct=layout[4]))
    record('STATS',cat)
    dev=json.loads((INPUTS/'dev.json').read_text(encoding='utf-8'))
    for name in sorted({q['db_id'] for q in dev}):
        db=sqlite3.connect((INPUTS/(name+'.sqlite')).as_uri()+'?mode=ro&immutable=1',uri=True)
        cat=Catalog(db); seen=set()
        for q in (q for q in dev if q['db_id']==name):
            item=eligible(q,db)
            if item is None: continue
            weights,passed,truth,dim,_,query=item
            if query in seen: continue
            seen.add(query)
            tree=sqlglot.parse_one(query,read='sqlite')
            alias=next(t.alias_or_name for t in tree.find_all(exp.Table) if t.name==dim)
            caps=cat.caps(dim,conditions(tree.args['where'].this,alias),len(weights))
            row=evaluate(q['question_id'],name,truth,weights,passed,100,caps)
            if row: rows.append(row)
        record(name,cat); cat.aux.close(); db.close()
    write('precision.csv',rows); write('histogram-inventory.csv',inventory)


if __name__=='__main__':
    run(Path(sys.argv[1]))

