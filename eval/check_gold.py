"""Run every gold pipeline, show its result, and flag ties at a top-N cutoff.

    python eval/check_gold.py          # review
    python eval/check_gold.py --write  # also store expect_rows (checked in CI)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bson import json_util  # noqa: E402

from nl2mongo.db import Runner  # noqa: E402
from run_eval import load_questions  # noqa: E402

PATH = Path(__file__).resolve().parent / "questions.jsonl"


def tie_at_cutoff(runner, q):
    """For pipelines ending in $sort,$limit (+$lookup/$project): is row limit+1 equal to row limit?"""
    p = q["pipeline"]
    idx = [i for i, s in enumerate(p) if "$limit" in s]
    if not idx:
        return False
    i = idx[-1]
    if i == 0 or "$sort" not in p[i - 1]:
        return False
    k = p[i]["$limit"]
    rows = runner.run(q["collection"], p[:i] + [{"$limit": k + 1}])
    if len(rows) <= k:
        return False
    key = list(p[i - 1]["$sort"])[0]

    def get(r):
        for part in key.split("."):
            r = r.get(part) if isinstance(r, dict) else None
        return r

    return get(rows[k - 1]) == get(rows[k])


def main():
    runner = Runner()
    qs = load_questions()
    raw = [json.loads(l) for l in open(PATH, encoding="utf-8") if l.strip()]
    bad = 0
    for q, r in zip(qs, raw):
        if not q["answerable"]:
            continue
        rows = runner.run(q["collection"], q["pipeline"])
        tie = tie_at_cutoff(runner, q)
        flag = "  <-- TIE AT CUTOFF" if tie else ""
        if not rows:
            flag += "  <-- EMPTY"
        bad += bool(flag)
        shown = json_util.dumps(rows[:6])
        print(f"{q['id']} rows={len(rows)}{flag}\n   {q['question']}\n   {shown[:300]}")
        r["expect_rows"] = len(rows)
    if "--write" in sys.argv:
        with open(PATH, "w", encoding="utf-8") as f:
            for r in raw:
                f.write(json.dumps(r) + "\n")
        print("wrote expect_rows")
    print(f"{bad} flagged")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
