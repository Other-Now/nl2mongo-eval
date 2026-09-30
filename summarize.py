"""results/*.jsonl -> results/summary.md

Besides accuracy it prints paired comparisons: on the same questions and model,
how many did system B get right that A got wrong, and vice versa, with an exact
McNemar (sign-test) p-value. With 50 questions a 4-point gap can be noise; this
says which gaps are not.
"""
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RES = ROOT / "results"
SYSTEM_ORDER = ["zero_shot", "rag", "agent"]


def load():
    runs = defaultdict(dict)  # (system, model) -> id -> record
    for p in sorted(RES.glob("*__*.jsonl")):
        for line in open(p, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                runs[(r["system"], r["model"])][r["id"]] = r
    return runs


def mcnemar_p(b, c):
    """Exact two-sided sign test on the discordant pairs."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def fmt_p(p):
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def pct(x, n):
    return f"{100 * x / n:.0f}%" if n else "-"


def main():
    runs = load()
    keys = sorted(runs, key=lambda k: (k[1], SYSTEM_ORDER.index(k[0]) if k[0] in SYSTEM_ORDER else 9))
    out = []

    out.append("## Accuracy\n")
    out.append("| model | system | overall | answerable | refused unanswerable | p50 latency | mean LLM calls | mean tool calls | tokens / q | cost / q |")
    out.append("|---|---|---|---|---|---|---|---|---|---|")
    for k in keys:
        rs = list(runs[k].values())
        ans = [r for r in rs if r["answerable"]]
        una = [r for r in rs if not r["answerable"]]
        out.append("| {} | {} | {}/{} ({}) | {} | {} | {:.1f} s | {:.1f} | {:.1f} | {:.0f} | ${:.4f} |".format(
            k[1], k[0],
            sum(r["correct"] for r in rs), len(rs), pct(sum(r["correct"] for r in rs), len(rs)),
            pct(sum(r["correct"] for r in ans), len(ans)),
            pct(sum(r["correct"] for r in una), len(una)),
            statistics.median(r["latency_s"] for r in rs),
            statistics.mean(r["llm_calls"] for r in rs),
            statistics.mean(r["tool_calls"] for r in rs),
            statistics.mean(r["prompt_tokens"] + r["completion_tokens"] for r in rs),
            statistics.mean(r["cost_usd"] for r in rs),
        ))

    cats = sorted({r["category"] for k in keys for r in runs[k].values()})
    out.append("\n## Accuracy by question category\n")
    out.append("| model | system | " + " | ".join(cats) + " |")
    out.append("|---|---|" + "---|" * len(cats))
    for k in keys:
        rs = runs[k].values()
        cells = []
        for c in cats:
            cr = [r for r in rs if r["category"] == c]
            cells.append(f"{sum(r['correct'] for r in cr)}/{len(cr)}")
        out.append(f"| {k[1]} | {k[0]} | " + " | ".join(cells) + " |")

    fails = sorted({r["failure"] for k in keys for r in runs[k].values() if r["failure"]})
    out.append("\n## Failure taxonomy (count of wrong answers)\n")
    out.append("| model | system | " + " | ".join(fails) + " |")
    out.append("|---|---|" + "---|" * len(fails))
    for k in keys:
        cnt = Counter(r["failure"] for r in runs[k].values() if r["failure"])
        out.append(f"| {k[1]} | {k[0]} | " + " | ".join(str(cnt.get(f, 0)) for f in fails) + " |")

    out.append("\n## Paired comparisons (same model, same questions)\n")
    out.append("| model | A -> B | B fixed (A wrong, B right) | B broke (A right, B wrong) | net | McNemar p |")
    out.append("|---|---|---|---|---|---|")
    models = sorted({k[1] for k in keys})
    for m in models:
        for a, b in [("zero_shot", "rag"), ("zero_shot", "agent"), ("rag", "agent")]:
            if (a, m) in runs and (b, m) in runs:
                ra, rb = runs[(a, m)], runs[(b, m)]
                ids = ra.keys() & rb.keys()
                fixed = sum(1 for i in ids if not ra[i]["correct"] and rb[i]["correct"])
                broke = sum(1 for i in ids if ra[i]["correct"] and not rb[i]["correct"])
                out.append(f"| {m} | {a} -> {b} | {fixed} | {broke} | {fixed - broke:+d} | {fmt_p(mcnemar_p(fixed, broke))} |")

    text = "\n".join(out) + "\n"
    RES.mkdir(exist_ok=True)
    (RES / "summary.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
