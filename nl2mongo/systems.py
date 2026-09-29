"""The three systems under test. All share the same schema text and rules, so the
only difference between them is what they add on top:

  zero_shot  schema + question
  rag        + retrieved worked examples and operator notes
  agent      + tools to look at documents and run pipelines, then fix them
"""
import json
from dataclasses import dataclass, field

from bson import json_util

from . import guard
from .llm import Usage
from .parse import Answer, ParseError, Refusal, from_obj, parse_reply

SYSTEM = """You answer questions about a MongoDB database (sample_mflix: movies, comments, theaters, users) by writing one aggregation pipeline.

Schema, inferred from up to 1000 sampled documents per collection:
{schema}
Rules:
- The pipeline runs on one collection; use $lookup to join. It is read-only: $out and $merge are rejected.
- Dates in the pipeline: {{"$date": "YYYY-MM-DDT00:00:00Z"}}. ObjectIds: {{"$oid": "<hex>"}}.
- Return only the fields that answer the question. For "top N" questions, sort and limit.
- If the data cannot answer the question, or it asks for passwords, tokens or other secrets, refuse.
"""

JSON_REPLY = """
Reply with one JSON object and nothing else:
{"collection": "<name>", "pipeline": [ ... ]}
or, to refuse:
{"answerable": false, "reason": "<short reason>"}"""

AGENT_REPLY = """
Use run_pipeline to check your pipeline against the real data before answering, and fix it if it errors or the result looks wrong.
Finish by calling submit_answer (or refuse). You have at most {steps} turns."""

MAX_STEPS = 8


@dataclass
class Outcome:
    answer: object = None  # Answer | Refusal | None
    error: str = ""
    tool_calls: int = 0
    usage: Usage = field(default_factory=Usage)
    trace: list = field(default_factory=list)


def _one_shot(llm, system, question):
    out = Outcome()
    msg = llm.chat([{"role": "system", "content": system}, {"role": "user", "content": question}], out.usage)
    out.trace.append(msg.content)
    try:
        out.answer = parse_reply(msg.content)
    except ParseError as e:
        out.error = f"parse: {e}"
    return out


def zero_shot(llm, schema_text, question, **_):
    return _one_shot(llm, SYSTEM.format(schema=schema_text) + JSON_REPLY, question)


def rag(llm, schema_text, question, retriever, **_):
    examples, notes = retriever.context(question)
    ctx = ""
    if notes:
        ctx += "\nNotes on MongoDB operators:\n" + "\n\n".join(notes) + "\n"
    if examples:
        ctx += "\nWorked examples (different questions on the same database):\n" + "\n\n".join(examples) + "\n"
    return _one_shot(llm, SYSTEM.format(schema=schema_text) + ctx + JSON_REPLY, question)


_PIPELINE_ARGS = {
    "type": "object",
    "properties": {
        "collection": {"type": "string"},
        "pipeline": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["collection", "pipeline"],
}

TOOLS = [
    {"type": "function", "function": {
        "name": "sample_documents",
        "description": "Show up to 3 documents from a collection, optionally matching a filter. Long values are cut.",
        "parameters": {"type": "object", "properties": {
            "collection": {"type": "string"},
            "filter": {"type": "object", "description": "optional $match filter"}},
            "required": ["collection"]}}},
    {"type": "function", "function": {
        "name": "run_pipeline",
        "description": "Run a read-only aggregation pipeline. Returns the row count and the first 5 rows, or the error.",
        "parameters": _PIPELINE_ARGS}},
    {"type": "function", "function": {
        "name": "submit_answer",
        "description": "Final answer: the pipeline whose full result answers the question.",
        "parameters": _PIPELINE_ARGS}},
    {"type": "function", "function": {
        "name": "refuse",
        "description": "Final answer when the data cannot answer the question, or it asks for secrets.",
        "parameters": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}}},
]


def _shorten(node):
    if isinstance(node, dict):
        return {k: _shorten(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_shorten(v) for v in node[:5]] + (["..."] if len(node) > 5 else [])
    if isinstance(node, str) and len(node) > 120:
        return node[:120] + "..."
    return node


def _run_tool(runner, name, args):
    try:
        if name == "sample_documents":
            flt = json_util.loads(json.dumps(args.get("filter") or {}))
            rows = runner.run(args["collection"], [{"$match": flt}], limit=3)
            return json_util.dumps(_shorten(rows))
        if name == "run_pipeline":
            pipeline = json_util.loads(json.dumps(args["pipeline"]))
            rows = runner.run(args["collection"], pipeline)
            return json.dumps({"rows": len(rows), "first": json.loads(json_util.dumps(_shorten(rows[:5])))})
        return f"unknown tool {name}"
    except guard.GuardError as e:
        return f"blocked by guard: {e}"
    except Exception as e:  # server errors are the feedback the agent is meant to use
        return f"error: {e}"[:600]


def agent(llm, schema_text, question, runner, **_):
    out = Outcome()
    msgs = [
        {"role": "system", "content": SYSTEM.format(schema=schema_text) + AGENT_REPLY.format(steps=MAX_STEPS)},
        {"role": "user", "content": question},
    ]
    for _ in range(MAX_STEPS):
        m = llm.chat(msgs, out.usage, tools=TOOLS)
        calls = m.tool_calls or []
        msgs.append({
            "role": "assistant",
            "content": m.content or "",
            **({"tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name, "arguments": c.function.arguments}}
                               for c in calls]} if calls else {}),
        })
        if not calls:
            # Small models sometimes answer in plain text; accept it if it parses.
            # Qwen3-4B also sometimes writes "refuse\n<reason>" as text instead of
            # calling the refuse tool; that is a refusal, not a parse failure.
            out.trace.append({"text": m.content})
            text = (m.content or "").strip()
            if text.lower().startswith("refuse"):
                out.answer = Refusal(text[len("refuse"):].strip())
                return out
            try:
                out.answer = parse_reply(text)
            except ParseError as e:
                out.error = f"parse: {e}"
            return out
        for c in calls:
            name = c.function.name
            try:
                args = json.loads(c.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            out.trace.append({"tool": name, "args": c.function.arguments})
            if args is None:
                result = "error: arguments were not valid JSON"
            elif name == "submit_answer":
                try:
                    out.answer = from_obj(args)
                except ParseError as e:
                    out.error = f"parse: {e}"
                return out
            elif name == "refuse":
                out.answer = Refusal(str(args.get("reason", "")))
                return out
            else:
                out.tool_calls += 1
                result = _run_tool(runner, name, args)
            out.trace.append({"result": result[:300]})
            msgs.append({"role": "tool", "tool_call_id": c.id, "content": result})
    out.error = "step limit"
    return out


SYSTEMS = {"zero_shot": zero_shot, "rag": rag, "agent": agent}

__all__ = ["SYSTEMS", "Outcome", "Answer", "Refusal"]
