"""Fetch immutable STATS-CEB input files from the benchmark authors' repository."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parent
COMMIT = '670cb8d4bf4cbfa32f94fdf17f33973d3fd67d1b'
BASE = f'https://raw.githubusercontent.com/Nathaniel-Han/End-to-End-CardEst-Benchmark/{COMMIT}/'
FILES = [
    'datasets/stats_simplified/' + name for name in [
        'badges.csv', 'comments.csv', 'postHistory.csv', 'postLinks.csv',
        'posts.csv', 'tags.csv', 'users.csv', 'votes.csv', 'stats.sql'
    ]
] + [
    'workloads/stats_CEB/stats_CEB.sql',
    'workloads/stats_CEB/sub_plan_queries/stats_CEB_sub_queries.sql',
]

def fetch(path, expected):
    target = ROOT / 'raw' / Path(path).name
    data = urllib.request.urlopen(BASE + path, timeout=90).read()
    if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError(f"download does not match the pinned manifest: {target.name}")
    tmp = target.with_suffix(target.suffix+'.part')
    tmp.write_bytes(data)
    tmp.replace(target)
    return target.name

if __name__ == '__main__':
    (ROOT / 'raw').mkdir(exist_ok=True)
    manifest = {row['url']: row for row in json.loads((ROOT/'sources.json').read_text())}
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        for name in pool.map(fetch, FILES, [manifest[BASE+path] for path in FILES]):
            print(name)
