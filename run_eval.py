"""Run one or more systems over the question set with one model; append results as JSONL.

    python run_eval.py --system all --label qwen3-4b --model qwen3-4b \
        --base-url http://127.0.0.1:8081/v1
    python run_eval.py --system all --label gpt-x --model <name> \
        --base-url https://api.example.com/v1 --api-key-env API_KEY --price-in 1.25 --price-out 10

Re-running skips questions already in the output file, so an interrupted run resumes.
"""
import argparse
import json
from pathlib import Path

from bson import json_util

from nl2mongo import guard, schema, taxonomy
from nl2mongo.db import Runner
from nl2mongo.llm import LLM
from nl2mongo.parse import Answer, Refusal
from nl2mongo.retrieve import Retriever
from nl2mongo.score import match
from nl2mongo.systems import SYSTEMS

ROOT = Path(__file__).resolve().parent


def load_questions(path=ROOT / "eval" / "questions.jsonl"):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    for r in rows:
        if r.get("pipeline") is not None:
            r["pipeline"] = json_util.loads(json.dumps(r["pipeline"]))
    return rows


def judge(q, outcome, runner, gold_rows, known_paths):
    ans, pred_rows, exec_error = outcome.answer, None, ""
    if isinstance(ans, Answer):
        try:
            pred_rows = runner.run(ans.collection, ans.pipeline)
        except guard.GuardError as e:
            exec_error = f"guard: {e}"
        except Exception as e:
            exec_error = f"server: {e}"[:300]
    if q["answerable"]:
        correct = isinstance(ans, Answer) and not exec_error and match(pred_rows, gold_rows, q.get("ordered", False))
    else:
        correct = isinstance(ans, Refusal)
    failure = None if correct else taxonomy.classify(
        q, outcome, pred_rows, len(gold_rows or []), exec_error, known_paths)
    return correct, failure, exec_error, pred_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="all", help="zero_shot, rag, agent or all")
    ap.add_argument("--label", required=True, help="short model name used in result file names")
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key-env", default=None)
    ap.add_argument("--price-in", type=float, default=0.0, help="USD per million input tokens")
    ap.add_argument("--price-out", type=float, default=0.0, help="USD per million output tokens")
    ap.add_argument("--ids", default="", help="comma-separated question ids (default: all)")
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    args = ap.parse_args()

    systems = list(SYSTEMS) if args.system == "all" else args.system.split(",")
    questions = load_questions()
    if args.ids:
        wanted = set(args.ids.split(","))
        questions = [q for q in questions if q["id"] in wanted]

    runner = Runner()
    schema_text = schema.render(runner.db)
    known_paths = schema.field_paths(runner.db)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True)
    (out_dir / "schema.txt").write_text(schema_text, encoding="utf-8")

    gold = {q["id"]: runner.run(q["collection"], q["pipeline"]) for q in questions if q["answerable"]}
    llm = LLM(args.model, args.base_url, args.api_key_env)
    retriever = Retriever()

    for system in systems:
        path = out_dir / f"{system}__{args.label}.jsonl"
        done = set()
        if path.exists():
            done = {json.loads(l)["id"] for l in open(path, encoding="utf-8") if l.strip()}
        fn = SYSTEMS[system]
        with open(path, "a", encoding="utf-8") as f:
            for q in questions:
                if q["id"] in done:
                    continue
                try:
                    outcome = fn(llm, schema_text, q["question"], retriever=retriever, runner=runner)
                    correct, failure, exec_error, pred_rows = judge(q, outcome, runner, gold.get(q["id"]), known_paths)
                    llm_error = ""
                except Exception as e:  # network/server trouble: record it, don't lose the run
                    from nl2mongo.systems import Outcome
                    outcome, correct, failure, exec_error, pred_rows = Outcome(), False, "llm_error", "", None
                    llm_error = str(e)[:300]
                u = outcome.usage
                ans = outcome.answer
                rec = {
                    "id": q["id"], "category": q["category"], "answerable": q["answerable"],
                    "system": system, "model": args.label,
                    "correct": correct, "failure": failure,
                    "refused": isinstance(ans, Refusal),
                    "collection": ans.collection if isinstance(ans, Answer) else None,
                    "pipeline": json.loads(json_util.dumps(ans.pipeline)) if isinstance(ans, Answer) else None,
                    "pred_rows": None if pred_rows is None else len(pred_rows),
                    "exec_error": exec_error, "parse_error": outcome.error, "llm_error": llm_error,
                    "llm_calls": u.calls, "tool_calls": outcome.tool_calls,
                    "prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens,
                    "latency_s": round(u.seconds, 3),
                    "cost_usd": round((u.prompt_tokens * args.price_in + u.completion_tokens * args.price_out) / 1e6, 6),
                    "trace": json.loads(json_util.dumps(outcome.trace))[-12:],
                }
                f.write(json.dumps(rec) + "\n")
                f.flush()
                mark = "ok " if correct else "BAD"
                print(f"{system:9s} {q['id']:5s} {mark} {failure or '':28s} {u.seconds:6.1f}s tools={outcome.tool_calls}", flush=True)


if __name__ == "__main__":
    main()
