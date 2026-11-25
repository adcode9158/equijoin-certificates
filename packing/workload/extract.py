"""Build frequency maps and verified single-key cardinalities for STATS-CEB."""
import collections
import gzip
import hashlib
import json
import math
from pathlib import Path
import re

import duckdb

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'raw'
ATTR = r'[a-zA-Z]+\.[a-zA-Z]+'
LOCAL = re.compile(rf"({ATTR})\s*(?:<=|>=|=|<|>)\s*(?:-?\d+|'[0-9 :\-]+'::timestamp)", re.I)

def parse(query):
    match = re.fullmatch(r'SELECT COUNT\(\*\) FROM (.+) WHERE (.+);', query, re.I)
    rels, conds = match.groups()
    aliases = {}
    for source in rels.split(','):
        table, alias = re.fullmatch(r'\s*(\w+)\s+as\s+(\w+)\s*', source, re.I).groups()
        aliases[alias] = table
    edges = []
    filters = collections.defaultdict(list)
    for clause in re.split(r'\s+AND\s+', conds, flags=re.I):
        equality = re.fullmatch(rf'({ATTR})\s*=\s*({ATTR})', clause)
        if equality:
            edges.append(tuple(equality.groups()))
        else:
            local = LOCAL.fullmatch(clause)
            if not local:
                raise ValueError(clause)
            alias = local[1].split('.')[0]
            filters[alias].append(clause.replace(alias+'.',''))
    keys = {}
    for a,b in edges:
        for attr in (a,b):
            table, col = attr.split('.')
            if keys.setdefault(table,col) != col:
                return None
    if keys.keys() != aliases.keys():
        return None
    reached = {edges[0][0]}
    for _ in edges:
        for edge in edges:
            if reached.intersection(edge): reached.update(edge)
    if len(reached)!=len(aliases):
        return None
    specs = [(aliases[a],keys[a],' AND '.join(sorted(filters[a])) or 'TRUE') for a in keys]
    return sorted(specs)

def id_for(info):
    return hashlib.sha256(json.dumps(info).encode()).hexdigest()[:20]

def main():
    sources = []
    for filename in (RAW/'stats_CEB.sql', RAW/'stats_CEB_sub_queries.sql'):
        full = filename.name == 'stats_CEB.sql'
        for line_number,line in enumerate(filename.read_text().splitlines(),1):
            left,right = line.strip().split('||')
            query = right if full else left
            origin = dict(source='full' if full else 'subplan', line=line_number,
                          parent=line_number if full else int(right)+1)
            if full: origin['published_truth'] = int(left)
            sources.append((query,origin))
    db = duckdb.connect()
    db.execute('set threads=1')
    for file in sorted(RAW.glob('*.csv')):
        assert file.stem.isidentifier()
        db.execute(f"CREATE TABLE {file.stem} AS SELECT * FROM read_csv(?,header=true,sample_size=-1)",[str(file)])
    cases, maps = {}, {}
    counts = collections.Counter()
    for query,origin in sources:
        specs = parse(query)
        if specs is None: continue
        counts[origin['source']] += 1
        inputs = []
        for table,col,predicate in specs:
            map_id = id_for((table,col,predicate))
            if map_id not in maps:
                relation = f"SELECT {col} AS k,count(*) AS n FROM {table} WHERE {col} IS NOT NULL AND {predicate} GROUP BY 1"
                values = db.execute(relation+' ORDER BY 1').fetchall()
                maps[map_id] = dict(id=map_id,table=table,column=col,predicate=predicate,counts=values)
                db.execute(f'CREATE TEMP TABLE m{map_id} AS {relation}')
            inputs.append(map_id)
        case_id = id_for(inputs)
        if case_id not in cases:
            vals = [dict(maps[i]['counts']) for i in inputs]
            truth = sum(math.prod(v.get(k,0) for v in vals) for k in min(vals,key=len))
            # Evaluate every eligible case exactly using count-preserving group-by pushdown.
            product = '*'.join(f'm{i}.n::HUGEINT' for i in inputs)
            joins = f'm{inputs[0]}'+''.join(f' JOIN m{i} USING (k)' for i in inputs[1:])
            sql_truth = db.execute(f'SELECT coalesce(sum({product}),0) FROM {joins}').fetchone()[0]
            assert truth == sql_truth, (query,truth,sql_truth)
            direct = truth <= 100000
            if direct: assert db.execute(query).fetchone()[0] == truth
            cases[case_id] = dict(id=case_id,inputs=inputs,truth=truth,query=query,
                                  direct_count_checked=direct,origins=[])
        cases[case_id]['origins'].append(origin)
    with gzip.open(ROOT/'frequencies.jsonl.gz','wt',encoding='utf8',compresslevel=4) as f:
        for record in maps.values(): f.write(json.dumps(record,separators=(',',':'))+'\n')
    with (ROOT/'cases.jsonl').open('w',encoding='utf8') as f:
        for record in cases.values(): f.write(json.dumps(record)+'\n')
    report = dict(engine=duckdb.__version__, eligible_occurrences=counts,distinct_cases=len(cases),
                  maps=len(maps), direct_count_checks=sum(x['direct_count_checked'] for x in cases.values()),
                  arity=collections.Counter(len(x['inputs']) for x in cases.values()),
                  published_mismatches=[(o['parent'],o['published_truth'],c['truth']) for c in cases.values()
                      for o in c['origins'] if o['source']=='full' and o['published_truth']!=c['truth']])
    (ROOT/'summary.json').write_text(json.dumps(report,indent=2))
    print(report)

if __name__ == '__main__':
    main()
