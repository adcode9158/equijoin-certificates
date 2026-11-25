"""Read the filter literal used by BIRD development question 552."""
import json
import re


def question_552_name(input_dir):
    with (input_dir / "dev.json").open(encoding="utf-8") as stream:
        question = next(row for row in json.load(stream)
                        if row["db_id"] == "codebase_community" and row["question_id"] == 552)
    match = re.search(r"\bDisplayName\s*=\s*'((?:[^']|'')*)'", question["SQL"], re.IGNORECASE)
    if not match:
        raise ValueError("The expected DisplayName filter was absent from BIRD question 552")
    return match.group(1).replace("''", "'")
