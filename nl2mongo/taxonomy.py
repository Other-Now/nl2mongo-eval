"""Put every wrong answer into one bucket, automatically, so the counts are reproducible.

Order matters: the first rule that applies wins.
"""

STAGE_OUTPUTS = {"$group", "$project", "$replaceRoot", "$replaceWith", "$count", "$sortByCount", "$facet", "$bucket"}


def _refs(node):
    """Field paths a stage reads: "$a.b" strings and plain keys of $match."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _refs(v)
    elif isinstance(node, str) and node.startswith("$") and not node.startswith("$$") and len(node) > 1:
        yield node[1:]


def invented_fields(collection, pipeline, known_paths):
    """Paths the pipeline reads that exist nowhere in the collection (or in a joined one).

    Only checked up to the first stage that reshapes documents; after a $group the
    names are the model's own and cannot be judged against the schema.
    """
    known = set(known_paths.get(collection, set()))
    roots = {p.split(".")[0] for p in known}
    bad = set()
    for stage in pipeline:
        if not isinstance(stage, dict) or len(stage) != 1:
            break
        (name, spec), = stage.items()
        # A $lookup sub-pipeline reads the *other* collection; only its `let` reads this one.
        refs = list(_refs(spec.get("let", {}) if name == "$lookup" and isinstance(spec, dict) else spec))
        if name == "$match" and isinstance(spec, dict):
            refs += [k for k in spec if not k.startswith("$")]
        for r in refs:
            if r not in known and r.split(".")[0] not in roots:
                bad.add(r)
        if name == "$lookup" and isinstance(spec, dict):
            other = known_paths.get(spec.get("from"), set())
            as_ = spec.get("as", "")
            known |= {f"{as_}.{p}" for p in other} | {as_}
            roots.add(as_)
        elif name in ("$addFields", "$set") and isinstance(spec, dict):
            known |= set(spec)
            roots |= {k.split(".")[0] for k in spec}
        elif name in STAGE_OUTPUTS:
            break
    return sorted(bad)


def classify(q, outcome, pred_rows, gold_n, exec_error, known_paths):
    """Category of a wrong answer (call only when the answer was judged wrong)."""
    from .parse import Answer, Refusal

    ans = outcome.answer
    if outcome.error == "step limit":
        return "step_limit"
    if outcome.error:
        return "unparseable_reply"
    if not q["answerable"]:
        if exec_error and exec_error.startswith("guard"):
            return "answered_unanswerable_guard_blocked"
        return "answered_unanswerable"
    if isinstance(ans, Refusal):
        return "refused_answerable"
    assert isinstance(ans, Answer)
    if exec_error:
        if exec_error.startswith("guard"):
            return "blocked_by_guard"
        return "execution_error"
    if invented_fields(ans.collection, ans.pipeline, known_paths):
        return "invented_field"
    if ans.collection != q["collection"] and not any("$lookup" in s for s in ans.pipeline):
        return "wrong_collection"
    if not pred_rows:
        return "empty_result"
    if len(pred_rows) != gold_n:
        return "wrong_row_count"
    return "wrong_values"
