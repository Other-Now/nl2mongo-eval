"""Tests that need no database and no model."""
import datetime

import pytest
from bson import ObjectId

from nl2mongo import guard
from nl2mongo.parse import Answer, ParseError, Refusal, parse_reply
from nl2mongo.retrieve import BM25, Retriever
from nl2mongo.score import match
from nl2mongo.taxonomy import invented_fields


# ---- guard ---------------------------------------------------------------

@pytest.mark.parametrize("pipeline", [
    [{"$match": {"year": 2000}}, {"$out": "x"}],
    [{"$merge": {"into": "x"}}],
    [{"$facet": {"a": [{"$out": "x"}]}}],
    [{"$lookup": {"from": "comments", "as": "c", "pipeline": [{"$merge": {"into": "x"}}]}}],
    [{"$match": {"$where": "this.year > 2000"}}],
    [{"$addFields": {"x": {"$function": {"body": "f", "args": [], "lang": "js"}}}}],
])
def test_guard_blocks_writes_and_js_at_any_depth(pipeline):
    with pytest.raises(guard.GuardError):
        guard.check("movies", pipeline)


def test_guard_blocks_secrets_and_unknown_collections():
    with pytest.raises(guard.GuardError):
        guard.check("users", [{"$project": {"email": 1, "password": 1}}])
    with pytest.raises(guard.GuardError):
        guard.check("users", [{"$group": {"_id": "$password"}}])
    with pytest.raises(guard.GuardError):
        guard.check("sessions", [])
    with pytest.raises(guard.GuardError):
        guard.check("movies", [{"$lookup": {"from": "sessions", "localField": "a", "foreignField": "b", "as": "s"}}])


def test_guard_allows_normal_pipeline():
    p = [{"$match": {"genres": "Drama"}}, {"$group": {"_id": "$year", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}]
    assert guard.check("movies", p) is p


def test_redact_removes_joined_passwords():
    rows = [{"name": "a", "u": [{"email": "e", "password": "hash"}]}]
    assert guard.redact(rows) == [{"name": "a", "u": [{"email": "e"}]}]


# ---- score ---------------------------------------------------------------

def test_field_names_do_not_matter():
    assert match([{"count": 12}], [{"n": 12}])
    assert match([{"_id": None, "total": 12}], [{"n": 12}])  # extra null _id is fine


def test_extra_columns_ok_missing_columns_not():
    assert match([{"_id": ObjectId(), "title": "A", "year": 2000}], [{"title": "A"}])
    assert not match([{"title": "A"}], [{"title": "A", "year": 2000}])


def test_row_count_must_match():
    assert not match([{"t": "A"}, {"t": "B"}], [{"t": "A"}])
    assert not match([], [{"t": "A"}])


def test_order_only_when_asked():
    a, b = [{"t": "A"}, {"t": "B"}], [{"t": "B"}, {"t": "A"}]
    assert match(a, b, ordered=False)
    assert not match(a, b, ordered=True)


def test_numbers_rounded_and_int_equals_float():
    assert match([{"avg": 6.123456}], [{"avg": 6.12}])
    assert match([{"n": 5.0}], [{"n": 5}])
    assert not match([{"avg": 6.2}], [{"avg": 6.12}])


def test_dates_compare_in_utc():
    utc = datetime.datetime(2015, 1, 1, tzinfo=datetime.timezone.utc)
    ist = utc.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
    assert match([{"d": ist}], [{"d": utc}])


def test_group_key_as_value():
    gold = [{"_id": "Drama", "n": 3}, {"_id": "Comedy", "n": 2}]
    pred = [{"genre": "Comedy", "count": 2}, {"genre": "Drama", "count": 3}]
    assert match(pred, gold)
    assert not match([{"genre": "Comedy", "count": 3}, {"genre": "Drama", "count": 2}], gold)


# ---- parse ---------------------------------------------------------------

def test_parse_fenced_json_with_dates():
    a = parse_reply('Sure:\n```json\n{"collection": "comments", "pipeline": '
                    '[{"$match": {"date": {"$gte": {"$date": "2015-01-01T00:00:00Z"}}}}]}\n```')
    assert isinstance(a, Answer) and a.collection == "comments"
    assert isinstance(a.pipeline[0]["$match"]["date"]["$gte"], datetime.datetime)


def test_parse_refusal_and_garbage():
    assert isinstance(parse_reply('{"answerable": false, "reason": "no revenue field"}'), Refusal)
    with pytest.raises(ParseError):
        parse_reply("I think you should use $group")
    with pytest.raises(ParseError):
        parse_reply('{"collection": "movies"}')


def test_parse_braces_inside_strings():
    a = parse_reply('{"collection": "movies", "pipeline": [{"$match": {"title": "a}b"}}]} trailing')
    assert a.pipeline == [{"$match": {"title": "a}b"}}]


# ---- retrieval -----------------------------------------------------------

def test_bm25_ranks_relevant_first():
    idx = BM25(["group by genre count", "lookup join comments movies", "date range year"])
    assert idx.top("join the comments to movies", 1) == [1]
    assert idx.top("zzz", 3) == []


def test_retriever_loads_corpus():
    r = Retriever()
    ex, notes = r.context("average imdb rating per genre")
    assert ex and notes


# ---- taxonomy ------------------------------------------------------------

KNOWN = {"movies": {"title", "year", "imdb", "imdb.rating", "genres"}, "comments": {"movie_id", "text", "date"}}


def test_invented_fields():
    assert invented_fields("movies", [{"$match": {"boxOffice": {"$gt": 1}}}], KNOWN) == ["boxOffice"]
    assert invented_fields("movies", [{"$match": {"imdb.rating": {"$gt": 8}}}], KNOWN) == []
    # Names created by the pipeline itself are fine.
    p = [{"$lookup": {"from": "comments", "localField": "_id", "foreignField": "movie_id", "as": "c"}},
         {"$addFields": {"k": {"$size": "$c"}}}, {"$match": {"k": {"$gt": 1}, "c.text": {"$exists": 1}}}]
    assert invented_fields("movies", p, KNOWN) == []
    # After a $group the names are the model's own and are not judged.
    assert invented_fields("movies", [{"$group": {"_id": "$year", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}], KNOWN) == []
