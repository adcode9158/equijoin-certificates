"""Exact minimax query budget for a count-capped threshold, with independent tree checks."""
import csv
import json
import sys
from collections import Counter
from functools import lru_cache
from itertools import accumulate, combinations_with_replacement
from pathlib import Path
from random import Random
from statistics import median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from validate import BIRD, FRESH, db_open, dump, eligible


def first_pivotal_caps(weights, budget):
    """Minimum number of positives in a pair of worlds that makes each weight pivotal.
    For an integer row budget, this implementation is pseudo-polynomial in B.
    None means never pivotal. Store only weights that can occur in a fitting context.
    """
    counts = Counter(weights)
    usable = sorted(w for w in counts if 0 < w <= budget)
    first = {}
    for w in counts:
        if w == 0:
            first[w] = None
            continue
        if w > budget:
            first[w] = 1
            continue
        # Minimum cardinality attaining each exact sum in [0,B] without this copy.
        infinity = budget + 2
        fewest = [0] + [infinity] * budget
        for v in usable:
            copies = min(counts[v] - int(v == w), budget // v)
            # Binary blocks and a final remainder represent every count.
            block = 1
            while copies:
                take = min(block, copies)
                mass = v * take
                for total in range(budget, mass - 1, -1):
                    fewest[total] = min(fewest[total], fewest[total-mass] + take)
                copies -= take
                block *= 2
        c = min(fewest[budget-w+1:])
        first[w] = c + 1 if c < infinity else None
    return first


def profile(weights, budget):
    counts = Counter(weights)
    caps = first_pivotal_caps(counts.elements(), budget)
    threshold_counts = Counter()
    for w, n in counts.items():
        if caps[w] is not None:
            threshold_counts[caps[w]] += n
    return threshold_counts


def cost(threshold_counts, cap):
    return sum(n for c, n in threshold_counts.items() if c <= cap)


def inverse(threshold_counts, k, domain):
    total = 0
    for c, count in sorted(threshold_counts.items()):
        total += count
        if total > k:
            return c - 1
    return domain


def descending_cost(weights, positives, cap, budget):
    """Query only the next label, and stop when either answer is forced."""
    ordered = sorted(weights, key=lambda k: (-weights[k], k))
    prefix = list(accumulate((weights[k] for k in ordered), initial=0))
    known, remaining = 0, cap
    for idx in range(len(ordered) + 1):
        upper = known + prefix[min(len(ordered), idx + remaining)] - prefix[idx]
        if known > budget or upper <= budget:
            return idx, known <= budget
        key = ordered[idx]
        if key in positives:
            known += weights[key]
            remaining -= 1
    raise AssertionError("All labels were read without deciding")


def decision_tree(weights, cap, budget):
    """Optimal adaptive tree over the entire feasible set, independent of the DP."""
    worlds = tuple(mask for mask in range(1 << len(weights)) if mask.bit_count() <= cap)
    labels = {m: sum(w for i, w in enumerate(weights) if m >> i & 1) > budget for m in worlds}
    @lru_cache(None)
    def search(compatible):
        if len({labels[m] for m in compatible}) == 1:
            return 0
        best = len(weights)
        for i in range(len(weights)):
            split = tuple(m for m in compatible if m >> i & 1)
            if split and len(split) != len(compatible):
                other = tuple(m for m in compatible if not m >> i & 1)
                best = min(best, 1 + max(search(split), search(other)))
        return best
    return search(worlds)


def test():
    cases = [(w, b) for n in range(6) for w in combinations_with_replacement((0,1,2,4), n) for b in range(7)]
    rng = Random(718293)
    cases.extend((tuple(rng.randrange(12) for _ in range(n)), rng.randrange(25)) for n in (6,7,8) for j in range(5))
    compared = 0
    for weights, b in cases:
        hist = profile(weights, b)
        for cap in range(len(weights) + 1):
            optimum = decision_tree(weights, cap, b)
            observed_depth = 0
            for mask in range(1 << len(weights)):
                if mask.bit_count() > cap:
                    continue
                passing = [i for i in range(len(weights)) if mask >> i & 1]
                used, admits = descending_cost(dict(enumerate(weights)), passing, cap, b)
                assert admits == (sum(weights[i] for i in passing) <= b)
                observed_depth = max(observed_depth, used)
            assert observed_depth == optimum == cost(hist, cap), (weights, b, cap)
            compared += 1
        for k in range(len(weights) + 1):
            assert inverse(hist, k, len(weights)) == max(m for m in range(len(weights)+1) if cost(hist, m) <= k)
    return compared


def main():
    checks = test()
    archived = list(csv.DictReader((FRESH/"count_precision"/"precision.csv").open(encoding="utf-8")))
    gold = {str(q["question_id"]):q for q in json.loads((BIRD/"dev.json").read_text(encoding="utf-8"))}
    out = []
    cache = {}
    for r in archived:
        if r["source"] == "STATS":
            continue
        dbid, qid = r["source"], r["case_id"]
        with db_open(BIRD, dbid) as db:
            w, passed, truth, *_ = eligible(gold[qid], db)
        n, m, b = len(w), len(passed), int(r["budget"])
        ident = (b, tuple(sorted(Counter(w.values()).items())))
        if ident not in cache:
            cache[ident] = profile(w.values(), b)
        hist = cache[ident]
        M = min(int(r["histogram_cap"]), int(r["exceptions_cap"]))
        assert m <= M and truth == int(r["observed"])
        descending_actual, admit = descending_cost(w, passed, M, b)
        assert admit
        row = dict(db=dbid, question_id=qid, n=n, observed=truth, true_passing_count=m, combined_catalog_cap=M,
                   offline_at_m=int(r["exact"]), worst_at_m=cost(hist, m), offline_at_m1=int(r["plus1"]), worst_at_m1=cost(hist,min(m+1,n)),
                   offline_combined=int(r["combined"]), actual_descending_combined=descending_actual, worst_combined=cost(hist, M),
                   largest_cap_for_64=inverse(hist, 64, n), worst_uncapped=cost(hist,n),
                   changes=json.dumps(hist,sort_keys=True))
        assert row["offline_at_m"] <= row["worst_at_m"] and row["offline_combined"] <= descending_actual <= row["worst_combined"]
        out.append(row)
    dump("online-budget", out)
    def summarize(rows):
        return dict(n=len(rows), offline_64=sum(r["offline_combined"] <= 64 for r in rows),
                    descending_actual_64=sum(r["actual_descending_combined"] <= 64 for r in rows),
                    guaranteed_64=sum(r["worst_combined"] <= 64 for r in rows),
                    exact_cap_worst_64=sum(r["worst_at_m"] <= 64 for r in rows),
                    median_worst_combined=median(r["worst_combined"] for r in rows) if rows else None)
    holdout = [r for r in out if r["db"] not in ("financial", "formula_1")]
    difficult = [r for r in holdout if r["offline_at_m"] > 0]
    summary = dict(tiny_decision_trees=checks, all_bird=summarize(out), holdout=summarize(holdout),
                   difficult_holdout=summarize(difficult), difficult_no_codebase=summarize([r for r in difficult if r["db"] != "codebase_community"]),
                   badge=next(r for r in out if r["db"] == "codebase_community" and r["question_id"] in ("551","552")))
    (HERE/"online-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()

