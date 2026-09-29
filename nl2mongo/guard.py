"""Read-only safety checks for model-written pipelines.

The database user is already read-only (role `read`), so writes fail at the
server anyway. This layer exists because "the server would have refused" is not
a good enough answer for things the read role still allows: server-side
JavaScript, reading secrets, and unbounded scans.
"""

ALLOWED_COLLECTIONS = {"movies", "comments", "theaters", "users"}

ALLOWED_STAGES = {
    "$match", "$project", "$group", "$sort", "$limit", "$skip", "$unwind",
    "$lookup", "$addFields", "$set", "$unset", "$count", "$sortByCount",
    "$facet", "$bucket", "$replaceRoot", "$replaceWith",
}

# Anywhere in the pipeline, at any depth.
FORBIDDEN_OPERATORS = {"$out", "$merge", "$function", "$accumulator", "$where"}

# Never returned, never referenced.
SENSITIVE_FIELDS = {"password", "jwt"}

MAX_ROWS = 1000
MAX_TIME_MS = 5000


class GuardError(Exception):
    pass


def _walk(node):
    """Yield every dict key and every string value in a nested structure."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)
    elif isinstance(node, str):
        yield node


def _check_stages(pipeline):
    if not isinstance(pipeline, list):
        raise GuardError("pipeline must be a list of stages")
    for stage in pipeline:
        if not isinstance(stage, dict) or len(stage) != 1:
            raise GuardError(f"each stage must be an object with one key: {stage!r}")
        (name, spec), = stage.items()
        if name not in ALLOWED_STAGES:
            raise GuardError(f"stage {name} not allowed")
        if name == "$lookup":
            if spec.get("from") not in ALLOWED_COLLECTIONS:
                raise GuardError(f"$lookup from {spec.get('from')!r} not allowed")
            if "pipeline" in spec:
                _check_stages(spec["pipeline"])
        if name == "$facet":
            for sub in spec.values():
                _check_stages(sub)


def check(collection, pipeline):
    """Raise GuardError if the pipeline may not run. Returns it unchanged otherwise."""
    if collection not in ALLOWED_COLLECTIONS:
        raise GuardError(f"collection {collection!r} not allowed")
    _check_stages(pipeline)
    for token in _walk(pipeline):
        if token in FORBIDDEN_OPERATORS:
            raise GuardError(f"operator {token} not allowed")
        leaf = token.lstrip("$").split(".")[-1]
        if leaf in SENSITIVE_FIELDS:
            raise GuardError(f"sensitive field {token!r} referenced")
    return pipeline


def redact(node):
    """Drop sensitive keys from results (e.g. a $lookup into users pulls in password)."""
    if isinstance(node, dict):
        return {k: redact(v) for k, v in node.items() if k not in SENSITIVE_FIELDS}
    if isinstance(node, list):
        return [redact(v) for v in node]
    return node
