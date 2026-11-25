"""Search for concrete over-budget filter permutations on the original base-key rows."""
import argparse
import csv
import heapq
import json
import re
import zipfile
from collections import Counter
from math import prod
from pathlib import Path


def size(maps):
    return sum(prod(m.get(x,0) for m in maps) for x in min(maps, key=len))


def load(root):
    with zipfile.ZipFile(root / "supplement.zip") as src:
        def rows(name):
            with src.open(f"validation-data/inputs/{name}.jsonl") as stream:
                yield from map(json.loads, stream)
        cases = [r for r in rows("query-cases") if any(
            t["source"] == "full" for t in r["benchmark_occurrences"])]
        needed = {i for r in cases for i in r["input_ids"]}
        base = {}
        meta = {}
        attributes = {}
        join_columns = {}
        for r in rows("filtered-key-frequencies"):
            t,c,p = r["table"], r["column"], r["predicate"]
            key = t,c
            join_columns.setdefault(t,set()).update([c,"Id"])
            attributes.setdefault(t,set()).update(re.findall(r"\b([A-Za-z]\w*)\s*[<>=]",p))
            if p == "TRUE":
                base[key] = dict(r["key_frequency_pairs"])
            if r["input_id"] in needed:
                meta[r["input_id"]] = (key,p,dict(r["key_frequency_pairs"]))
        assert all(not (attributes[t] & join_columns[t]) for t in attributes)
    return cases,base,meta


def improve(others,base_order,ranked,k):
    cutoff = ranked[k][1] if len(ranked)>k else 0
    chosen = dict((x,v) for x,v in ranked[:k] if v>cutoff)
    # Highest remaining degree must use some still-unassigned key that can hold it.
    # Assign it to the eligible key with maximum weight. The key displaced from
    # any optimum can accept the smaller degree that previously occupied that key.
    ordered = [(x,v) for x,v in base_order if x not in chosen]
    heap = []
    pos = 0
    for _,d in ranked[len(chosen):]:
        while pos<len(ordered) and ordered[pos][1]>=d:
            x = ordered[pos][0]
            weight = prod(m.get(x,0) for m in others)
            heapq.heappush(heap,(-weight,x))
            pos += 1
        _,x=heapq.heappop(heap)
        chosen[x]=d
    return chosen


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("paper",type=Path)
    p.add_argument("--names",type=int,default=24)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--witnesses",type=Path)
    args=p.parse_args()
    cases,base,meta=load(args.paper)
    ordered={c:sorted(counts.items(), key=lambda kv:(-kv[1],kv[0])) for c,counts in base.items()}
    ranks={i:sorted(m.items(),key=lambda kv:(-kv[1],kv[0])) for i,(_,_,m) in meta.items()}
    source=args.paper.parent/"evidence/hard-41-certified.csv"
    with source.open() as src: hard={r["case_id"] for r in csv.DictReader(src)}
    cap=10_000_000
    result=[]
    output_witnesses=[]
    for case in cases:
        if case["case_id"] not in hard:
            continue
        ids=case["input_ids"]
        assert len(set(meta[i][0][0] for i in ids))==len(ids)
        initial=[meta[i][2] for i in ids]
        val=size(initial)
        assert val==case["observed_cardinality"]
        best=val
        best_maps=initial
        for direction in (range(len(ids)), reversed(range(len(ids)))):
            order=list(direction)
            maps=initial.copy()
            current=val
            for _ in range(4):
                prior=current
                for j in order:
                    i=ids[j]
                    col,predicate,_=meta[i]
                    if predicate=="TRUE":
                        continue
                    candidate=improve(maps[:j]+maps[j+1:],ordered[col],ranks[i],args.names)
                    revised=size(maps[:j]+[candidate]+maps[j+1:])
                    assert revised>=current
                    if revised>current:
                        maps[j]=candidate
                        current=revised
                if current>cap or current==prior:
                    break
            if current>best:
                best=current
                best_maps=maps
            if best>cap:
                break
        for i,m in zip(ids,best_maps):
            col,predicate,src=meta[i]
            assert Counter(src.values())==Counter(m.values())
            assert all(0<v<=base[col].get(x,0) for x,v in m.items())
            ranked=ranks[i]
            cutoff=ranked[args.names][1] if len(ranked)>args.names else 0
            assert {x:v for x,v in src.items() if v>cutoff}=={x:v for x,v in m.items() if v>cutoff}
            if predicate=="TRUE": assert m==src
        assert best==size(best_maps)
        result.append([case["case_id"],val,best,int(best>cap)])
        if args.witnesses and best>cap:
            output_witnesses.append({"case":case["case_id"],"keys":ids,"cardinality":best,"maps":[list(m.items()) for m in best_maps]})
    if args.witnesses:
        import gzip
        with gzip.open(args.witnesses,"wt",encoding="utf-8") as stream:
            for row in output_witnesses:
                stream.write(json.dumps(row,separators=(",",":"))+"\n")
    with args.output.open("w",newline="") as out:
        w=csv.writer(out);w.writerow(["case_id","observed","attained","over"]);w.writerows(result)
    print("Over-budget witnesses:",sum(r[-1] for r in result),"/",len(result))


if __name__=="__main__":
    main()
