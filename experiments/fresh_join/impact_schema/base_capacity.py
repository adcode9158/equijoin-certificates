"""Bound joins of filters using reusable per-base-key capacities and filtered catalogs."""
import argparse
import csv
import json
import sys
import zipfile
from collections import Counter
from itertools import accumulate
from math import prod
from pathlib import Path


def load(root):
    verifier = root.parent / "evidence"
    sys.path.insert(0, str(verifier))
    from verify_packing import encode_residual
    with zipfile.ZipFile(root / "supplement.zip") as archive:
        def rows(name):
            with archive.open(f"validation-data/inputs/{name}.jsonl") as src:
                yield from map(json.loads, src)
        cases = [q for q in rows("query-cases") if any(
            item["source"] == "full" for item in q["benchmark_occurrences"])]
        required = {name for case in cases for name in case["input_ids"]}
        base = {}
        filters = {}
        for row in rows("filtered-key-frequencies"):
            col = row["table"], row["column"]
            raw = row["key_frequency_pairs"]
            if row["predicate"] == "TRUE":
                base[col] = dict(raw)
            if row["input_id"] in required:
                ranks = sorted((v for _, v in raw), reverse=True)
                cutoff = ranks[12] if len(ranks) > 12 else 0
                head = {x:v for x,v in raw if v > cutoff}
                _, decoded = encode_residual(ranks[len(head):], 13)
                canonical = [v for v in sorted(decoded, reverse=True) for _ in range(decoded[v])]
                filters[row["input_id"]] = (col, head, canonical, row["predicate"] == "TRUE")
    with (verifier/"all-cases.csv").open() as src:
        original = {r["case_id"]: int(r["original_upper"]) for r in csv.DictReader(src)}
    return cases, base, filters, original


def evaluate(case, base, filters):
    meta = [filters[i] for i in case["input_ids"]]
    bases = [base[col] for col,_,_,_ in meta]
    common = set(min(bases, key=len)).intersection(*bases)
    names = [head for _,head,_,_ in meta]
    tails = [tail for _,_,tail,_ in meta]
    caps = [max(tail, default=0) for tail in tails]
    prefix = [[0, *accumulate(tail)] for tail in tails]
    col_count = len(meta)
    unfiltered = 0
    clipped = 0
    fixed = [0] * col_count
    weighted = [[] for _ in meta]
    for x in common:
        b = [col[x] for col in bases]
        unfiltered += prod(b)
        c = [bi if meta[i][3] else names[i].get(x, min(bi, caps[i])) for i,bi in enumerate(b)]
        joint = prod(c)
        if joint == 0:
            continue
        clipped += joint
        for i, val in enumerate(c):
            if x in names[i] or meta[i][3]:
                fixed[i] += joint
            else:
                weighted[i].append((joint // val, val))
    marginal = []
    for i, values in enumerate(weighted):
        # With weights descending, bound each prefix of frequencies by both
        # its coordinatewise capacities and its decoded degree prefix.
        capacity_sum = 0
        last = 0
        partial = fixed[i]
        for t, (weight, localcap) in enumerate(sorted(values, reverse=True), start=1):
            capacity_sum += localcap
            upper = min(capacity_sum, prefix[i][min(t, len(prefix[i])-1)])
            partial += (upper - last) * weight
            last = upper
        marginal.append(partial)
    return unfiltered, clipped, min(marginal)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    cases, base, filters, original = load(args.paper)
    rows = []
    for case in cases:
        whole, box, weighted = evaluate(case, base, filters)
        actual = case["observed_cardinality"]
        assert actual <= weighted <= box <= whole
        rows.append(dict(case=case["case_id"], actual=actual, original=original[case["case_id"]],
                         base_only=whole, capped_product=box, weighted_prefix=weighted,
                         combined=min(original[case["case_id"]],weighted)))
    with args.output.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print("Base entries", sum(map(len, base.values())), "columns",len(base))
    for col in list(rows[0])[1:]:
        print(col, sum(r[col]<=10**7 for r in rows), "of", len(rows))
    hard = [r for r in rows if r["actual"]<=10**7<r["original"]]
    for col in ("base_only","capped_product","weighted_prefix"):
        print(col,"rescued",sum(r[col]<=10**7 for r in hard),"of",len(hard))


if __name__ == "__main__":
    main()
