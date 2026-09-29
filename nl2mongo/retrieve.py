"""BM25 over worked examples and short operator notes.

This stands in for Atlas Vector Search. With ~40 small documents, keyword
retrieval is a fair baseline, and it keeps the experiment about *whether
retrieved context helps*, not about which index serves it.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent.parent / "eval"


def tokens(text):
    return re.findall(r"[a-z0-9$]+", text.lower())


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = docs
        self.toks = [tokens(d) for d in docs]
        self.avg = sum(map(len, self.toks)) / max(len(self.toks), 1)
        self.k1, self.b = k1, b
        df = Counter(t for ts in self.toks for t in set(ts))
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def top(self, query, k):
        q = tokens(query)
        scores = []
        for i, ts in enumerate(self.toks):
            tf = Counter(ts)
            s = 0.0
            for t in q:
                if t in tf:
                    f = tf[t]
                    s += self.idf[t] * f * (self.k1 + 1) / (
                        f + self.k1 * (1 - self.b + self.b * len(ts) / self.avg)
                    )
            scores.append((s, i))
        scores.sort(key=lambda x: (-x[0], x[1]))
        return [i for s, i in scores[:k] if s > 0]


def load_examples(path=EVAL_DIR / "examples.jsonl"):
    out = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("answerable") is False:
            a = {"answerable": False, "reason": r["reason"]}
        else:
            a = {"collection": r["collection"], "pipeline": r["pipeline"]}
        out.append(f"Q: {r['question']}\nA: {json.dumps(a)}")
    return out


def load_notes(path=EVAL_DIR / "operator_notes.md"):
    text = open(path, encoding="utf-8").read()
    return [c.strip() for c in text.split("\n## ") if c.strip() and not c.startswith("# ")]


class Retriever:
    def __init__(self, k_examples=4, k_notes=2):
        self.examples = load_examples()
        self.notes = load_notes()
        self.ex_index = BM25(self.examples)
        self.note_index = BM25(self.notes)
        self.k_examples, self.k_notes = k_examples, k_notes

    def context(self, question):
        ex = [self.examples[i] for i in self.ex_index.top(question, self.k_examples)]
        notes = [self.notes[i] for i in self.note_index.top(question, self.k_notes)]
        return ex, notes
