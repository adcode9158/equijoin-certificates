"""Generate packing witnesses and upper certificates for the archived STATS cases."""

import argparse
import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

from profile_solver import DENOM, inner, make_problem, stable_catalog


def select_cases(archive, args):
    with archive.open("validation-data/inputs/query-cases.jsonl") as stream:
        cases = list(map(json.loads, stream))
    if args.case:
        selected = [case for case in cases if case["case_id"] == args.case]
        if not selected:
            raise ValueError(f"Unknown case ID: {args.case}")
        return selected
    if args.refine_open:
        with archive.open("validation-data/results/bounds/initial-packing.csv") as stream:
            rows = csv.DictReader(io.TextIOWrapper(stream, encoding="utf-8"))
            ids = {row["case_id"] for row in rows if row["lower"] != row["upper"]}
        return [case for case in cases if case["case_id"] in ids]
    return cases


def serialize_certificate(proof):
    if proof is None:
        return None
    selected, (prices, allowances) = proof
    return {
        "selected_configurations": [
            {"listed_slot": slot, "degree_supply_indices": indices, "multiplicity": count}
            for slot, indices, count in selected
        ],
        "residual_price_numerators": prices,
        "listed_slot_allowance_numerators": allowances[:-1],
        "unlisted_allowance_numerator": allowances[-1],
        "price_denominator": DENOM,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path(__file__).with_name("supplement.zip"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--case", help="Solve one case, such as query-0007.")
    mode.add_argument("--all", action="store_true", help="Repeat the initial run on all cases.")
    mode.add_argument("--refine-open", action="store_true", help="Refine the archived open intervals.")
    args = parser.parse_args()
    with ZipFile(args.archive) as archive:
        cases = select_cases(archive, args)
        requested = {key for case in cases for key in case["input_ids"]}
        with archive.open("validation-data/inputs/filtered-key-frequencies.jsonl") as stream:
            catalogs = {
                row["input_id"]: stable_catalog(dict(row["key_frequency_pairs"]))
                for row in map(json.loads, stream) if row["input_id"] in requested
            }
    for case in cases:
        problem = make_problem([catalogs[key] for key in case["input_ids"]])
        result = inner(problem, rounds=40, integer_polish=args.refine_open)
        print(json.dumps({
            "case_id": case["case_id"],
            "lower": result["lower"],
            "upper": result["upper"],
            "certificate": serialize_certificate(result.get("proof")),
        }, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
