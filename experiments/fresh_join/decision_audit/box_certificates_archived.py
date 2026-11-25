"""Point-certificate lengths with only unfiltered per-key capacities.

Inputs have independent integer intervals and distinct relation occurrences.
The STATS run measures the [0,base] specialization. Counts are logical disclosures.
"""
import argparse
import csv
import heapq
import sys
from fractions import Fraction
from math import prod
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "impact_schema"))
from permutation_witness import load


def prefix_length(gains, required):
    if required <= 0:
        return 0
    for count, gain in enumerate(sorted(gains, reverse=True), 1):
        required -= gain
        if required <= 0:
            return count
    raise AssertionError("available answers do not establish the decision")


def marginal_gains(capacities, actual, uncertain):
    """Optimal upper-bound decreases at a single key, one cell per purchase."""
    contribution = prod(capacities)
    order = sorted(uncertain, key=lambda i: Fraction(actual[i], capacities[i]))
    for i in order:
        updated = contribution // capacities[i] * actual[i]
        yield contribution - updated
        contribution = updated
        if contribution == 0:
            break


def oracle(caps, counts, uncertain, budget):
    upper = sum(prod(c) for c in caps)
    truth = [prod(row) for row in counts]
    if not uncertain:
        return 0
    if sum(truth) > budget:
        # Every unresolved input starts at zero, so purchases contribute to
        # the rejection proof only when a key has been fully disclosed.
        return len(uncertain) * prefix_length(truth, budget + 1)
    gains = [gain for c, a in zip(caps, counts)
             for gain in marginal_gains(c, a, uncertain) if gain]
    return prefix_length(gains, upper - budget)


def online(caps, uncertain, budget, buy, mode):
    """Both strategies see the same upper counts and SQL-text probe order."""
    terms = [prod(c) for c in caps]
    upper = sum(terms)
    if not uncertain or upper <= budget:
        return 0, upper <= budget
    heap = [(-p, r) for r, p in enumerate(terms)]
    heapq.heapify(heap)
    purchased = [0] * len(caps)
    lower = 0
    probes = 0
    while heap:
        neg, r = heapq.heappop(heap)
        partial = -neg
        while partial and purchased[r] < len(uncertain):
            j = uncertain[purchased[r]]
            value = buy(r, j)
            probes += 1
            purchased[r] += 1
            updated = partial // caps[r][j] * value
            upper -= partial - updated
            partial = updated
            if purchased[r] == len(uncertain):
                lower += partial
            if upper <= budget or lower > budget:
                return probes, upper <= budget
            if mode == "largest_current" and partial and purchased[r] < len(uncertain):
                heapq.heappush(heap, (-partial, r))
                break
    raise AssertionError("exact answer must decide")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paper", type=Path)
    parser.add_argument("--output", type=Path, default=HERE / "stats.csv")
    args = parser.parse_args()
    cases, base, metadata = load(args.paper)
    budget = 10_000_000
    rows = []
    for q in cases:
        inputs = [metadata[x] for x in q["input_ids"]]
        original = [base[col] for col, _, _ in inputs]
        actual = [counts for _, _, counts in inputs]
        keys = sorted(set(min(original, key=len)).intersection(*original))
        caps = [tuple(column[k] for column in original) for k in keys]
        counts = [tuple(column.get(k, 0) for column in actual) for k in keys]
        assert len({col[0] for col, _, _ in inputs}) == len(inputs)
        assert all(0 <= a <= c for row, complete in zip(counts, caps) for a,c in zip(row,complete))
        uncertain = [i for i, (_, p, _) in enumerate(inputs) if p != "TRUE"]
        # Fixed in advance. Put filters with more conjuncts first. Column
        # position breaks ties, without observing any conditional frequency.
        order = sorted(uncertain, key=lambda i: (-inputs[i][1].upper().count(" AND "), i))
        observed = sum(prod(row) for row in counts)
        assert observed == q["observed_cardinality"]
        optimal = oracle(caps, counts, uncertain, budget)
        row = dict(case=q["case_id"], observed=observed, arity=len(inputs),
                   uncertain_inputs=len(uncertain), common_keys=len(keys), initial_upper=sum(prod(c) for c in caps),
                   minimum=optimal, all_cells=len(keys)*len(uncertain))
        for mode in ("key_major", "largest_current"):
            probes, admit = online(caps, order, budget, lambda r,j: counts[r][j], mode)
            assert admit == (observed <= budget) and optimal <= probes
            row[mode] = probes
        rows.append(row)
    with args.output.open("w", newline="") as f:
        out = csv.DictWriter(f, fieldnames=list(rows[0]))
        out.writeheader()
        out.writerows(rows)
    for label, group in (("all", rows), ("fitting initially open", [r for r in rows if r["observed"] <= budget and r["minimum"]>0]),
                         ("over initially open", [r for r in rows if r["observed"]>budget and r["minimum"]>0])):
        print(label, len(group))
        for field in ("minimum", "key_major", "largest_current", "all_cells"):
            numbers = [r[field] for r in group]
            print(field, sum(numbers), median(numbers), max(numbers))


if __name__ == "__main__":
    main()

