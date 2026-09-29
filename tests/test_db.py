"""Tests against a real MongoDB with sample_mflix loaded (skipped when none is reachable)."""
import json

import pytest
from bson import json_util
from pymongo.errors import OperationFailure, PyMongoError

from nl2mongo import guard
from nl2mongo.db import Runner
from nl2mongo.retrieve import EVAL_DIR
from run_eval import load_questions

try:
    RUNNER = Runner()
    RUNNER.client.admin.command("ping")
except PyMongoError:
    RUNNER = None

pytestmark = pytest.mark.skipif(RUNNER is None, reason="no MongoDB reachable at MONGO_URI")

QUESTIONS = load_questions()


@pytest.mark.parametrize("q", [q for q in QUESTIONS if q["answerable"]], ids=lambda q: q["id"])
def test_gold_pipeline_runs_and_has_expected_rows(q):
    rows = RUNNER.run(q["collection"], q["pipeline"])
    assert len(rows) == q["expect_rows"]


def test_question_set_shape():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids)) == 50
    assert sum(not q["answerable"] for q in QUESTIONS) == 8


def test_examples_run_and_do_not_copy_eval_questions():
    eval_q = {q["question"].lower() for q in QUESTIONS}
    for line in open(EVAL_DIR / "examples.jsonl", encoding="utf-8"):
        ex = json.loads(line)
        assert ex["question"].lower() not in eval_q
        if ex.get("answerable") is False:
            continue
        rows = RUNNER.run(ex["collection"], json_util.loads(json.dumps(ex["pipeline"])))
        assert rows, ex["question"]


def test_reader_cannot_write():
    with pytest.raises(OperationFailure):
        RUNNER.db.movies.insert_one({"x": 1})
    # Even past the guard, the server refuses $out for this user.
    with pytest.raises(OperationFailure):
        list(RUNNER.db.movies.aggregate([{"$limit": 1}, {"$out": "stolen"}]))


def test_join_into_users_is_redacted():
    rows = RUNNER.run("comments", [
        {"$limit": 3},
        {"$lookup": {"from": "users", "localField": "email", "foreignField": "email", "as": "u"}},
    ])
    assert rows and all("password" not in u for r in rows for u in r["u"])


def test_timeout_is_enforced():
    # A cross join of comments x comments cannot finish in MAX_TIME_MS.
    slow = [{"$lookup": {"from": "comments", "pipeline": [], "as": "all"}}, {"$count": "n"}]
    with pytest.raises(OperationFailure):
        RUNNER.run("comments", slow)
    assert guard.MAX_TIME_MS <= 5000
