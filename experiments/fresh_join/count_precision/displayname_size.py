"""Illustrative byte cost of the actual display-name exceptions and a locator index."""
import json
import sqlite3
import sys
from pathlib import Path

def main(input_db):
    source=sqlite3.connect(Path(input_db).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    counts=list(source.execute('SELECT DisplayName, count(*) FROM users WHERE DisplayName IS NOT NULL GROUP BY DisplayName'))
    keys=list(source.execute('SELECT DisplayName, Id FROM users WHERE DisplayName IS NOT NULL'))
    outputs={}
    for method in ('duplicates','frequency_dictionary','locator'):
        db=sqlite3.connect(':memory:')
        db.execute('PRAGMA page_size=4096')
        if method=='locator':
            db.execute('CREATE TABLE data(name TEXT, id INTEGER, PRIMARY KEY(name,id)) WITHOUT ROWID')
            data=keys
        else:
            db.execute('CREATE TABLE data(name TEXT PRIMARY KEY, n INTEGER) WITHOUT ROWID')
            data=counts if method=='frequency_dictionary' else [r for r in counts if r[1]>1]
        db.executemany('INSERT INTO data VALUES (?,?)',sorted(data))
        db.commit()
        outputs[method]={'rows':len(data),'bytes':len(db.serialize())}
        db.close()
    print(json.dumps(outputs,indent=2))

if __name__=='__main__':
    main(sys.argv[1])

