"""Turn a model reply into an Answer or a Refusal."""
import json
import re
from dataclasses import dataclass

from bson import json_util


@dataclass
class Answer:
    collection: str
    pipeline: list


@dataclass
class Refusal:
    reason: str


class ParseError(Exception):
    pass


def _first_json_object(text):
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    if start < 0:
        raise ParseError("no JSON object in reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise ParseError("unbalanced JSON object")


def from_obj(obj):
    """obj is a plain dict (already JSON-decoded); convert Extended JSON inside it."""
    if not isinstance(obj, dict):
        raise ParseError("reply is not a JSON object")
    if obj.get("answerable") is False:
        return Refusal(str(obj.get("reason", "")))
    if "collection" not in obj or "pipeline" not in obj:
        raise ParseError("missing collection or pipeline")
    try:
        # Round-trip through json_util so {"$date": ...} and {"$oid": ...} become BSON types.
        pipeline = json_util.loads(json.dumps(obj["pipeline"]))
    except Exception as e:  # json_util raises several types
        raise ParseError(f"bad extended JSON: {e}") from e
    if not isinstance(pipeline, list):
        raise ParseError("pipeline is not a list")
    return Answer(str(obj["collection"]), pipeline)


def parse_reply(text):
    try:
        obj = json.loads(_first_json_object(text or ""))
    except json.JSONDecodeError as e:
        raise ParseError(f"invalid JSON: {e}") from e
    return from_obj(obj)
