"""Translate the public raw CSVs and original query specifications into a typed fixture."""
import argparse
import csv
import json
import re
import sys
from array import array
from pathlib import Path
from zipfile import ZipFile


def number(value):
    if value == "":
        return -(1 << 63)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', value):
        return int(re.sub(r'\D', '', value))
    return int(value)


def main(paper, raw, out):
    out.mkdir(parents=True, exist_ok=True)
    with ZipFile(paper / 'supplement.zip') as archive:
        folder = 'validation-data/inputs/'
        cases = list(map(json.loads, archive.open(folder + 'query-cases.jsonl')))
        inputs = [(r['input_id'], r['table'], r['column'], r['predicate'])
                  for r in map(json.loads, archive.open(folder + 'filtered-key-frequencies.jsonl'))]
    tables = sorted({t for _,t,_,_ in inputs})
    headers = {}
    with (out/'catalog.txt').open('w') as schema, (out/'columns.bin').open('wb') as data:
        print(len(tables), file=schema)
        for table in tables:
            with (raw/(table+'.csv')).open(encoding='utf-8-sig', newline='') as src:
                reader = csv.reader(src)
                headers[table] = next(reader)
                columns = [array('q') for _ in headers[table]]
                for row in reader:
                    assert len(row) == len(columns)
                    for col, cell in zip(columns,row):
                        col.append(number(cell))
            print(len(columns),len(columns[0]),file=schema)
            assert sys.byteorder == 'little' and columns[0].itemsize == 8
            for col in columns:
                col.tofile(data)
        print(len(inputs),file=schema)
        for _,table,key,predicate in inputs:
            terms = [] if predicate=='TRUE' else predicate.split(' AND ')
            print(tables.index(table),headers[table].index(key),len(terms),file=schema)
            for term in terms:
                attr,op,lit = re.fullmatch(r"([A-Za-z]+)(>=|<=|=)(-?\d+|'[^']+'::timestamp)",term).groups()
                value = number(lit[1:lit.index("'",1)] if lit.startswith("'") else lit)
                print(headers[table].index(attr),{'=':0,'>=':1,'<=':-1}[op],value,file=schema)
        def origin(q):
            return min((0 if row['source']=='full' else 1,row['line']) for row in q['benchmark_occurrences'])
        lookup={i:j for j,(i,_,_,_) in enumerate(inputs)}
        print(len(cases),file=schema)
        for case in sorted(cases,key=origin):
            print(case['case_id'],int(origin(case)[0]==0),case['observed_cardinality'],len(case['input_ids']),
                  *(lookup[i] for i in case['input_ids']),file=schema)


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('paper','raw','out'): p.add_argument(name,type=Path)
    main(**vars(p.parse_args()))

