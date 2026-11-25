#!/usr/bin/env python3
"""Replay the original strict-cutoff 51-word packing certificates from the supplement."""

import argparse
import csv
import io
import json
from collections import Counter
from dataclasses import dataclass
from itertools import product
from math import prod
from pathlib import Path
from zipfile import ZipFile


ROOT = "validation-data/"
LIMIT = 10_000_000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def json_rows(archive, path):
    with archive.open(ROOT + path) as stream:
        yield from map(json.loads, stream)


def csv_rows(archive, name):
    path = ROOT + "results/bounds/" + name + ".csv"
    with archive.open(path) as stream:
        return {r["case_id"]: r for r in csv.DictReader(io.TextIOWrapper(stream))}


@dataclass
class Catalog:
    listed: dict
    runs: dict


def encode_residual(sequence, pairs=13):
    """Return the stored mode/pairs and canonical multiplicities. Input is descending."""
    n = len(sequence)
    actual = Counter(sequence)
    rle = ("runs", tuple(sorted(actual.items())))
    if n <= pairs:
        return rle, actual
    ends = []
    for j in range(1, pairs + 1):
        rank = round(n ** (j / pairs))
        # Exact arithmetic confirms the rounding of the geometric rank.
        scaled = 2**pairs * n**j
        require((2 * rank - 1)**pairs < scaled < (2 * rank + 1)**pairs,
                "ambiguous or incorrect geometric endpoint")
        ends.append(min(n - (pairs - j), max((ends[-1] if ends else 0) + 1, rank)))
    start = 0
    blocks = []
    decoded = Counter()
    for end in ends:
        high = sequence[start]
        low = sequence[end] if end < n else 1
        size = end - start
        mass = sum(sequence[start:end])
        blocks.append((high, mass))
        count, extra = divmod(mass - size * low, high - low or 1)
        decoded[high] += count
        if extra:
            decoded[low + extra] += 1
        decoded[low] += size - count - bool(extra)
        start = end
    decoded = +decoded
    if len(actual) <= pairs and actual != decoded:
        return rle, actual
    return ("blocks", tuple(blocks)), decoded


def catalog(row):
    pairs = row["key_frequency_pairs"]
    counts = sorted((count for _, count in pairs), reverse=True)
    cutoff = counts[12] if len(counts) > 12 else 0
    listed = {key: count for key, count in pairs if count > cutoff}
    sequence = counts[len(listed):]
    encoding, decoded = encode_residual(sequence)
    decoded_sequence = list(v for v in sorted(decoded, reverse=True) for _ in range(decoded[v]))
    require(encode_residual(decoded_sequence)[0] == encoding, "degree re-encoding mismatch")
    require(len(decoded_sequence) < 13 - len(listed)
            or decoded_sequence[12 - len(listed)] == cutoff, "strict cutoff changed")
    return Catalog(listed, dict(sorted(decoded.items())))


def align_runs(runs):
    """Sum rankwise products for descending (degree,multiplicity) sequences."""
    if any(not r for r in runs):
        return 0
    cursors = [iter(sorted(r.items(), reverse=True)) for r in runs]
    current = [list(next(it)) for it in cursors]
    result = 0
    while True:
        take = min(n for _, n in current)
        result += take * prod(v for v, _ in current)
        for i, step in enumerate(current):
            step[1] -= take
            if step[1] == 0:
                entry = next(cursors[i], None)
                if entry is None:
                    return result
                current[i] = list(entry)


def binary(cats):
    total = 0
    leftovers = []
    for i, cat in enumerate(cats):
        other = cats[1 - i].listed
        if i == 0:
            total += sum(cat.listed[k] * other[k] for k in cat.listed.keys() & other.keys())
        weights = sorted((other[k] for k in other.keys() - cat.listed.keys()), reverse=True)
        remaining = cat.runs.copy()
        j = 0
        for degree in reversed(cat.runs):
            used = min(remaining[degree], len(weights) - j)
            total += degree * sum(weights[j:j + used])
            remaining[degree] -= used
            j += used
        leftovers.append({v: n for v, n in remaining.items() if n})
    return total + align_runs(leftovers)


def multiway(cats, cert):
    owners, values, capacities = [], [], []
    by_owner = []
    for i, cat in enumerate(cats):
        indices = []
        for degree, count in cat.runs.items():
            indices.append(len(owners))
            owners.append(i)
            values.append(degree)
            capacities.append(count)
        by_owner.append(indices)

    all_owners = tuple(range(len(cats)))
    fixed = 0
    slots = []
    for key in sorted(set.union(*(set(cat.listed) for cat in cats))):
        missing = tuple(i for i in all_owners if key not in cats[i].listed)
        weight = prod(cat.listed[key] for cat in cats if key in cat.listed)
        if not missing:
            fixed += weight
        elif all(by_owner[i] for i in missing):
            slots.append((missing, weight))
    prices = cert["residual_price_numerators"]
    allowances = cert["listed_slot_allowance_numerators"]
    unlisted = cert["unlisted_allowance_numerator"]
    denom = cert["price_denominator"]
    require(len(prices) == len(values) and len(allowances) == len(slots),
            f"certificate shape mismatch: {len(allowances)} vs {len(slots)} slots")
    require(denom > 0 and min(prices + allowances + [unlisted]) >= 0, "invalid price")

    lower = fixed
    uses = [0] * len(values)
    selected = set()
    for column in cert["selected_configurations"]:
        slot = column["listed_slot"]
        multiplicity = column["multiplicity"]
        supply = column["degree_supply_indices"]
        require(slot == -1 or 0 <= slot < len(slots), "invalid listed slot")
        require(all(0 <= index < len(values) for index in supply), "invalid supply index")
        need, weight = (all_owners, 1) if slot == -1 else slots[slot]
        require(tuple(owners[index] for index in supply) == need, "incorrect configuration")
        require(isinstance(multiplicity, int) and multiplicity > 0, "invalid multiplicity")
        if slot != -1:
            require(multiplicity == 1 and slot not in selected, "listed key reused")
            selected.add(slot)
        for index in supply:
            uses[index] += multiplicity
        lower += multiplicity * weight * prod(values[index] for index in supply)
    require(all(n <= cap for n, cap in zip(uses, capacities)), "residual supply exceeded")

    # The original witness puts remaining degrees on fresh keys in descending order.
    remainders = [{values[j]: capacities[j] - uses[j] for j in indices
                   if capacities[j] > uses[j]} for indices in by_owner]
    lower += align_runs(remainders)

    # Cache products and price sums per missing-input pattern within this case.
    # Bounds use unbounded Python integers for all potentially large products.
    groups = {}
    for (missing, weight), allowance in zip(slots + [(all_owners, 1)], allowances + [unlisted]):
        groups.setdefault(missing, []).append((weight * denom, allowance))
    checked = 0
    for missing, terms in groups.items():
        for indices in product(*(by_owner[i] for i in missing)):
            v = prod(values[j] for j in indices)
            price = sum(prices[j] for j in indices)
            for scaled_weight, allowance in terms:
                require(scaled_weight * v <= price + allowance, "failed dual inequality")
            checked += len(terms)
    fresh_count = min(sum(cat.runs.values()) for cat in cats)
    numerator = sum(p * n for p, n in zip(prices, capacities)) + sum(allowances) + fresh_count * unlisted
    upper = fixed + numerator // denom
    return lower, upper, checked


def verify(archive):
    catalogs = {r["input_id"]: catalog(r) for r in json_rows(archive, "inputs/filtered-key-frequencies.jsonl")}
    cases = {r["case_id"]: r for r in json_rows(archive, "inputs/query-cases.jsonl")}
    expected = set(cases)
    endpoints = {}
    counts = Counter()
    for phase, name in [("initial", "initial-packing"), ("refined", "refined-intervals")]:
        table = csv_rows(archive, name)
        verified = {}
        for record in json_rows(archive, f"certificates/packing-{phase}.jsonl"):
            key = record["case_id"]
            require(key not in verified, f"duplicate certificate {key}")
            case = cases[key]
            cats = [catalogs[i] for i in case["input_ids"]]
            cert = record["certificate"]
            try:
                if len(cats) == 2:
                    require(cert is None, "unexpected binary certificate")
                    lower = upper = binary(cats)
                    counts["binary"] += 1
                else:
                    lower, upper, checked = multiway(cats, cert)
                    counts[f"{phase}_dual_inequalities"] += checked
                    counts[f"{phase}_multiway"] += 1
                pair = lower, upper
                require(lower <= upper, "unordered endpoints")
                require(pair == (record["lower"], record["upper"]), f"JSON endpoint mismatch {pair}")
                row = table[key]
                require(pair == (int(row["lower"]), int(row["upper"])), "CSV endpoint mismatch")
                require((len(cats), case["observed_cardinality"]) == (int(row["arity"]), int(row["truth"])),
                        "case metadata disagree")
            except Exception as error:
                raise ValueError(f"{phase} {key}: {error}") from error
            verified[key] = pair
        require(set(verified) == set(table) == expected, f"{phase} case coverage mismatch")
        for key, pair in verified.items():
            if phase == "refined":
                old_lower, old_upper = endpoints[key]
                require(old_lower <= pair[0] <= pair[1] <= old_upper, "interval widened")
        endpoints.update(verified)
        expected = {key for key, (lo, hi) in verified.items() if lo != hi}
    counts["maps"] = len(catalogs)
    counts["cases"] = len(cases)
    counts["closed_intervals"] = sum(lo == hi for lo, hi in endpoints.values())
    comparison = csv_rows(archive, "filtered-comparison")
    require(comparison.keys() == endpoints.keys(), "final comparison coverage mismatch")
    for k, case in cases.items():
        require(endpoints[k] == (int(comparison[k]["attainable"]),
                                 int(comparison[k]["certified"])), f"final interval mismatch {k}")
        if any(row["source"] == "full" for row in case["benchmark_occurrences"]):
            counts["full"] += 1
            if case["observed_cardinality"] <= LIMIT:
                counts["full_within_budget"] += 1
                lo, hi = endpoints[k]
                require(hi <= LIMIT or lo > LIMIT, "undecided baseline")
                counts["full_hard" if lo > LIMIT else "full_certified"] += 1
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", nargs="?", type=Path,
                        default=Path(__file__).resolve().parent.parent / "supplement.zip")
    args = parser.parse_args()
    with ZipFile(args.archive) as data:
        print(json.dumps(verify(data), indent=2, sort_keys=True))
