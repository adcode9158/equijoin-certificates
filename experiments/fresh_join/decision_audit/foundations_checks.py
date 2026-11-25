"""Falsification checks for the foundations decision. Run with Python 3.10+."""
import csv
import json
import sqlite3
import sys
from collections import defaultdict
from itertools import product
from math import lcm, prod
from pathlib import Path
from random import Random
from statistics import median

HERE = Path(__file__).resolve().parent
FRESH = HERE.parent
sys.path[:0] = [str(FRESH / "count_precision"), str(FRESH / "uncertain_counts")]
from curve import PrecisionCurve
from one_total import minimum_one_total
from box_certificates_archived import oracle
from box_certificates_corrected import oracle as corrected_oracle


from badge import question_552_name

def certificate_checks():
    """Truth tables versus the dual implementation and a two-list primal method."""
    rng = Random(110301)
    huge = 2**85
    cases = [([], 0), ([0] * 7, 75), ([huge] * 7, 5),
             ([huge + 1, huge, huge - 1, 1, 1, 0], 1)]
    for _ in range(95):
        n = rng.randrange(1, 8)
        cases.append(([rng.choice([0, 4, 6, 9, huge, huge + 6]) for _ in range(n)],
                      rng.randrange(1 << n)))
    forward = inverse = 0
    for ws, actual in cases:
        n = len(ws)
        masks = range(1 << n)
        mass = [sum(w for i, w in enumerate(ws) if mask & (1 << i)) for mask in masks]
        yes = sorted([i for i in range(n) if actual & (1 << i)], key=ws.__getitem__)
        no = sorted(set(range(n)) - set(yes), key=ws.__getitem__, reverse=True)
        budgets = {mass[actual], mass[actual] + 1, sum(ws),
                   rng.randint(mass[actual], sum(ws))}
        for budget in budgets:
            curve = PrecisionCurve(dict(enumerate(ws)), set(yes), budget)
            answers = {}
            for cap in range(len(yes), n + 1):
                bad_diffs = [x ^ actual for x in masks if x.bit_count() <= cap and mass[x] > budget]
                truth = min(s.bit_count() for s in masks if all(s & d for d in bad_diffs))
                best = n
                for p in range(len(yes) + 1):
                    for q in range(len(no) + 1):
                        rest = sorted((ws[i] for i in yes[p:] + no[q:]), reverse=True)
                        worst = sum(ws[i] for i in yes[:p]) + sum(rest[:cap - p])
                        if worst <= budget:
                            best = min(best, p + q)
                assert best == curve.minimum(cap) == truth
                answers[cap] = truth
                forward += 1
            for k in range(n + 1):
                want = max((c for c, cost in answers.items() if cost <= k), default=None)
                assert curve.largest_cap(k) == want
                inverse += 1
    return dict(instances=len(cases), fit_decisions=forward, inverse_queries=inverse)


def total_checks():
    """Exhaust all disclosures; compute each worst completion by greedy load fill."""
    rng = Random(198701)
    huge = 2**85
    cases = [[], [(0, 0, [])], [(huge, huge - 1, [(0, 0), (huge, 1)])],
             [(huge + 4, 1, [(huge, 1)]), (huge, huge - 1, [(huge + 1, huge)])]]
    while len(cases) < 105:
        n = rng.randrange(1, 5)
        keys = []
        for _ in range(n):
            cap = rng.choice([0, 1, 2, 14, huge])
            partners = []
            for _ in range(rng.randrange(4)):
                cap_p = rng.choice([0, 1, 3, 5, huge + 1])
                partners.append((cap_p, rng.randrange(cap_p + 1)))
            keys.append((cap, rng.randrange(cap + 1), partners))
        if sum(1 + len(p) for c, a, p in keys) <= 12:
            cases.append(keys)
    checks = 0
    for keys in cases:
        n = sum(1 + len(p) for c, a, p in keys)
        total = sum(a for c, a, p in keys)
        truth = sum(a * prod(v for _, v in p) for c, a, p in keys)
        upper_by_cost = [None] * (n + 1)
        for mask in range(1 << n):
            free = []
            remain = total
            worst = bit = 0
            for cap, actual, partners in keys:
                pinned = bool(mask & (1 << bit))
                bit += 1
                weight = 1
                for c, a in partners:
                    weight *= a if mask & (1 << bit) else c
                    bit += 1
                if pinned:
                    worst += actual * weight
                    remain -= actual
                else:
                    free.append((weight, cap))
            for weight, cap in sorted(free, reverse=True):
                units = min(remain, cap)
                worst += weight * units
                remain -= units
            assert remain == 0 and worst >= truth
            k = mask.bit_count()
            if upper_by_cost[k] is None or worst < upper_by_cost[k]:
                upper_by_cost[k] = worst
        for budget in {v + offset for v in upper_by_cost for offset in (0, -1) if v + offset >= truth}:
            want = next(k for k, v in enumerate(upper_by_cost) if v <= budget)
            assert minimum_one_total(keys, budget) == want
            checks += 1
    return dict(instances=len(cases), fit_decisions=checks)


def two_total_max(caps, weights, target):
    # State holds the two counts already allocated. The bound is polynomial
    # when the input contains all rows, pseudo-polynomial for succinct counts.
    dp = {(0, 0): 0}
    for cap, w in zip(caps, weights):
        updated = {}
        for (i, j), old in dp.items():
            for x in range(min(cap, target-i) + 1):
                for y in range(min(cap, target-j) + 1):
                    key = (i+x, j+y)
                    updated[key] = max(updated.get(key, -1), old + w*x*y)
        dp = updated
    return dp[target, target]


def reduction_checks():
    count = 0
    for caps in ((4,), (4, 4, 7), (2, 3, 5, 7), (3, 3, 3, 5), (7, 11, 13)):
        scale = lcm(*caps)
        weights = [scale // v for v in caps]
        subsets = {sum(c * v for c, v in zip(caps, b)) for b in product([0, 1], repeat=len(caps))}
        for target in range(1, sum(caps)):
            def fill(order):
                left = target
                vector = [0] * len(caps)
                for i in order:
                    vector[i] = min(left, caps[i])
                    left -= vector[i]
                return vector
            x, y = fill(range(len(caps))), fill(reversed(range(len(caps))))
            assert sum(w * a * b for w, a, b in zip(weights, x, y)) < scale * target
            assert (two_total_max(caps, weights, target) == scale * target) == (target in subsets)
            count += 1
    return dict(targets=count)


def zero_capacity_example():
    # The theorem discards zero-product keys, as does the STATS input adapter.
    # The bare oracle attempts Fraction(0,0) if given arbitrary capacity boxes.
    caps = [(0, 1), (1, 1)]
    actual = [(0, 1), (0, 1)]
    try:
        raw = oracle(caps, actual, [0], 0)
    except ZeroDivisionError:
        raw = "ZeroDivisionError"
    assert corrected_oracle(caps, actual, [0], 0) == 1
    # Direct truth table over four uncertain cells. Every possible actual
    # database and every feasible threshold is exercised, including rejection.
    checked = 0
    for cap in product(range(3), repeat=4):
        worlds = list(product(*(range(c + 1) for c in cap)))
        joins = {w:w[0]*w[1]+w[2]*w[3] for w in worlds}
        for labels in worlds:
            for budget in range(max(joins.values())+1):
                diffs = [sum((a != b) << i for i, (a,b) in enumerate(zip(w,labels)))
                         for w,v in joins.items() if (v <= budget) != (joins[labels] <= budget)]
                best = min(s.bit_count() for s in range(16) if all(s & d for d in diffs))
                computed = corrected_oracle([cap[:2],cap[2:]], [labels[:2],labels[2:]], [0,1], budget)
                assert best == computed
                checked += 1
    return dict(raw_oracle=raw, repaired_minimum=1, exact_answer=1,
                positive_support_oracle=oracle([(1, 1)], [(0, 1)], [0], 0),
                exhaustive_repair_checks=checked)


def q552():
    source = FRESH.parent / "inputs/bird/codebase_community.sqlite"
    name = question_552_name(source.parent)
    with sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True) as db:
        records = list(db.execute("""
            SELECT u.Id, u.DisplayName = ?, coalesce(c.n, 0)
              FROM users u LEFT JOIN
                (SELECT UserId, count(*) n FROM badges GROUP BY UserId) c
                ON c.UserId = u.Id""", (name,)))
        truth, = db.execute("""SELECT count(*) FROM badges b JOIN users u
            ON b.UserId=u.Id WHERE u.DisplayName=?""", (name,)).fetchone()
    weights = {k: w for k, p, w in records}
    yes = {k for k, p, w in records if p}
    assert len(yes) == 1 and truth == sum(weights[k] for k in yes) == 95
    curve = PrecisionCurve(weights, yes, 100)
    heavy = sum(w > 100 for w in weights.values())
    return dict(users=len(records), passed=sorted(yes), join=truth, max_fanout=max(weights.values()),
                point_minima={m:curve.minimum(m) for m in (1, 2, 11)}, heavy=heavy,
                cap_one_minimax=heavy)


def physical_reanalysis():
    def read(path):
        with path.open(newline="") as f:
            return list(csv.DictReader(f))
    data = read(FRESH / "multiway_joins/timing.csv")
    times = defaultdict(int)
    for r in data:
        times[r["cohort"], r["policy"], int(r["round"])] += int(r["ns"])
    result = {}
    for cohort in ("full", "subplan"):
        diffs = [(times[cohort,"natural_resume",i] - times[cohort,"head_resume",i]) / 1e6
                 for i in range(8)]
        result[cohort] = dict(wins=sum(d > 0 for d in diffs), rounds=len(diffs),
                              median_paired_ms=median(diffs), min_paired_ms=min(diffs), max_paired_ms=max(diffs))
    original = {r["case_id"] for r in read(FRESH.parents[1] / "evidence/all-cases.csv")
                if int(r["original_upper"]) <= 10**7}
    for mem in ("32", "128"):
        rows = [r for r in read(FRESH / "engine_benchmarks/resource/results.csv")
                if r["memory_mib"] == mem and r["fits_row_budget"] == "1"]
        def spill(r):
            return any(int(r[k] or 0) > 0 for k in ("profiler_total_spill_bytes","profiler_peak_temp_bytes"))
        certified = [r for r in rows if r["case"] in original]
        result[mem + "_MiB"] = dict(fits=len(rows), fit_spills=sum(map(spill, rows)),
                                    certified=len(certified), certified_spills=sum(map(spill,certified)))
    return result


if __name__ == "__main__":
    observations = dict(count_cap=certificate_checks(), one_total=total_checks(),
                        two_totals=reduction_checks(), zero_capacity=zero_capacity_example(),
                        q552=q552(), recorded_physical_runs=physical_reanalysis())
    dest = HERE / "foundations_results.json"
    dest.write_text(json.dumps(observations, indent=2) + "\n", encoding="utf-8")
    print(dest.read_text())
