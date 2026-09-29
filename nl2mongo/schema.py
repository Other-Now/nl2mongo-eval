"""Infer a compact schema from sampled documents; this text goes into every prompt.

Types are reported with their share when a field is mixed (sample_mflix has
`year` as int in most documents and string in a few). Nothing is hand-edited:
the model sees what a new engineer running this would see.
"""
import datetime
from collections import Counter, defaultdict

from bson import ObjectId

from . import guard

SCHEMA_COLLECTIONS = ["movies", "comments", "theaters", "users"]
SAMPLE = 1000
MAX_DEPTH = 3


def _type(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "double"
    if isinstance(v, str):
        return "string"
    if isinstance(v, datetime.datetime):
        return "date"
    if isinstance(v, ObjectId):
        return "objectId"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    if v is None:
        return "null"
    return type(v).__name__


def infer(db, collection, sample=SAMPLE):
    types = defaultdict(Counter)
    elem = defaultdict(Counter)
    n = 0
    for doc in db[collection].find({}).sort("_id", 1).limit(sample):
        n += 1

        def rec(prefix, d, depth):
            for k, v in d.items():
                path = f"{prefix}{k}"
                t = _type(v)
                types[path][t] += 1
                if t == "object" and depth < MAX_DEPTH:
                    rec(path + ".", v, depth + 1)
                if t == "array":
                    for x in v[:5]:
                        elem[path][_type(x)] += 1
                    objs = [x for x in v[:5] if isinstance(x, dict)]
                    if objs and depth < MAX_DEPTH:
                        rec(path + ".", objs[0], depth + 1)

        rec("", doc, 1)
    return n, types, elem


def render(db):
    lines = []
    for c in SCHEMA_COLLECTIONS:
        n, types, elem = infer(db, c)
        lines.append(f"collection {c} ({db[c].estimated_document_count()} documents)")
        for path in sorted(types):
            counts = types[path]
            if list(counts) == ["object"]:
                continue  # its children are listed
            parts = []
            for t, k in counts.most_common():
                if t == "array" and elem[path]:
                    t = "array<" + "|".join(x for x, _ in elem[path].most_common()) + ">"
                share = k / n
                parts.append(t if len(counts) == 1 else f"{t} {share:.0%}")
            present = sum(counts.values()) / n
            note = "" if present > 0.95 else f"  (in {present:.0%} of docs)"
            if path.split(".")[-1] in guard.SENSITIVE_FIELDS:
                note += "  (SENSITIVE: never return or reference)"
            lines.append(f"  {path}: {', '.join(parts)}{note}")
        lines.append("")
    return "\n".join(lines)


def field_paths(db):
    """collection -> set of known dotted paths (used by the failure taxonomy)."""
    out = {}
    for c in SCHEMA_COLLECTIONS:
        _, types, _ = infer(db, c)
        out[c] = set(types)
    return out
