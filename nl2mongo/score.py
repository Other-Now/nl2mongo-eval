"""Execution accuracy: does the predicted result set match the gold one?

Field names are ignored ("count" vs "n" vs "total" are all fine), because the
question never names them. A row is compared as the multiset of its scalar
values, and a predicted row may carry extra values (an _id the model forgot to
drop is not a wrong answer). Row counts must match exactly. Order matters only
when the question asks for it (top-k, "sorted by").
"""
import datetime
from collections import Counter

from bson import ObjectId


def _scalar(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    if isinstance(v, datetime.datetime):
        if v.tzinfo is not None:
            v = v.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return v.isoformat()
    if isinstance(v, ObjectId):
        return str(v)
    return v


def flatten(row):
    """All scalar leaves of a document, as a Counter."""
    out = Counter()

    def rec(v):
        if isinstance(v, dict):
            for x in v.values():
                rec(x)
        elif isinstance(v, list):
            for x in v:
                rec(x)
        else:
            out[_scalar(v)] += 1

    rec(row)
    return out


def _covers(pred, gold):
    return all(pred[k] >= n for k, n in gold.items())


def match(pred_rows, gold_rows, ordered=False):
    if len(pred_rows) != len(gold_rows):
        return False
    pred = [flatten(r) for r in pred_rows]
    gold = [flatten(r) for r in gold_rows]
    if ordered:
        return all(_covers(p, g) for p, g in zip(pred, gold))
    # Unordered: greedy matching is enough here because gold rows are distinct
    # and small; each gold row takes the first unused predicted row covering it.
    used = [False] * len(pred)
    for g in gold:
        for i, p in enumerate(pred):
            if not used[i] and _covers(p, g):
                used[i] = True
                break
        else:
            return False
    return True
