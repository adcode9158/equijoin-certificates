"""Compare output of the STATS SQL extractor with the published numerical inputs."""

import argparse
import gzip
import json
from itertools import zip_longest
from pathlib import Path
from zipfile import ZipFile


def main():
    folder = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workload-dir", type=Path, default=folder)
    directory = parser.parse_args().workload_dir
    missing = object()
    aliases = {}
    ncases = 0
    with ZipFile(folder.parent / "supplement.zip") as archive:
        with gzip.open(directory / "frequencies.jsonl.gz", "rt", encoding="utf-8") as local, \
                archive.open("validation-data/inputs/filtered-key-frequencies.jsonl") as released:
            for old, new in zip_longest(map(json.loads, local), map(json.loads, released), fillvalue=missing):
                if old is missing or new is missing:
                    raise ValueError("Different numbers of filtered input maps")
                if any(old[field] != new[field] for field in ("table", "column", "predicate")) \
                        or old["counts"] != new["key_frequency_pairs"]:
                    raise ValueError(f"Filtered map differs: {new['input_id']}")
                aliases[old["id"]] = new["input_id"]
        with (directory / "cases.jsonl").open(encoding="utf-8") as local, \
                archive.open("validation-data/inputs/query-cases.jsonl") as released:
            for old, new in zip_longest(map(json.loads, local), map(json.loads, released), fillvalue=missing):
                if old is missing or new is missing:
                    raise ValueError("Different numbers of join cases")
                expected = [aliases[key] for key in old["inputs"]]
                if expected != new["input_ids"] or old["truth"] != new["observed_cardinality"] \
                        or old["origins"] != new["benchmark_occurrences"] \
                        or old["direct_count_checked"] != new["direct_count_checked"]:
                    raise ValueError(f"Join case differs: {new['case_id']}")
                ncases += 1
    print(f"Matched {len(aliases)} filtered input maps and {ncases} join cases.")


if __name__ == "__main__":
    main()
