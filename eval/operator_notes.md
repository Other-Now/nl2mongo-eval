# Operator notes (retrieval corpus for the rag system)

Short, general notes on aggregation operators. They describe MongoDB, not the
eval questions; nothing here names a question's answer.

## $match filter documents
`{"$match": {"field": value}}` keeps documents where field equals value. Comparison: `$gt`, `$gte`, `$lt`, `$lte`, `$ne`, `$in`, `$nin`. For an array field, `{"genres": "Drama"}` matches documents whose array contains "Drama"; `{"genres": {"$all": ["A", "B"]}}` needs both. Combine with `$and` / `$or`. Dotted paths reach into sub-documents: `{"imdb.rating": {"$gte": 8}}`.

## $group aggregate count sum average
`{"$group": {"_id": "$field", "n": {"$sum": 1}, "avg": {"$avg": "$x"}}}`. `_id: null` groups everything into one row. Accumulators: `$sum`, `$avg`, `$min`, `$max`, `$first`, `$last`, `$push`, `$addToSet`. `$avg` ignores missing and non-numeric values. To count distinct values, `$addToSet` then `$size` in a later `$project`. `{"$count": "n"}` counts all documents that reach it.

## $unwind arrays per element
`{"$unwind": "$genres"}` emits one document per array element, so a movie with 3 genres becomes 3 documents. Needed before grouping by array elements (per genre, per actor, per country). Counting after `$unwind` counts elements, not the original documents. `$sortByCount: "$genres"` is `$group` + `$sort` in one stage.

## $sort $limit top N
`{"$sort": {"field": -1}}` descending, `1` ascending; sort before `$limit`. Documents missing the field sort as smallest (before numbers ascending, last descending). A field with mixed types (numbers and strings) sorts by BSON type order: numbers before strings. Filter to one type with `{"$type": "number"}` when ranking.

## $lookup join collections
`{"$lookup": {"from": "other", "localField": "a", "foreignField": "b", "as": "joined"}}` adds an array `joined` of matching documents from `other`. Follow with `$unwind: "$joined"` to get one row per match. A join on an ObjectId field must compare ObjectId with ObjectId, not with its string. For conditions beyond equality use `let` + `pipeline` with `$expr`.

## Dates ranges and parts
Date literals in a pipeline: `{"$date": "2010-01-01T00:00:00Z"}`. A calendar year is `{"$gte": start_of_year, "$lt": start_of_next_year}`. Extract parts with `$year`, `$month`, `$dayOfWeek` (1 = Sunday), `$hour`, all in UTC. Group by month: `{"$group": {"_id": {"$month": "$date"}}}`. `$dateTrunc` rounds to a unit.

## $project reshape and compute
`{"$project": {"title": 1, "_id": 0}}` keeps only title. Computed fields: `{"$project": {"ratio": {"$divide": ["$a", "$b"]}}}`. `$size` gives array length (fails on a missing array; guard with `$ifNull: ["$arr", []]`). `$concat`, `$toUpper`, `$substrCP` for strings; `$round: ["$x", 2]` for numbers.

## Strings and text search
`{"title": {"$regex": "^Star", "$options": "i"}}` matches a prefix, case-insensitive. Exact equality on a string is case-sensitive. `$regexMatch` works inside `$expr`. `$strLenCP` gives string length.

## Missing and null values
`{"field": {"$exists": true}}` checks presence; `{"field": null}` matches both null and missing. Some fields hold different types in different documents; `$type` filters to one (`"number"`, `"string"`, `"date"`).

## Geo queries
Geo points are GeoJSON: `{"type": "Point", "coordinates": [longitude, latitude]}`. `$geoNear` must be the first stage and needs a 2dsphere index; without one, compare coordinates with `$match` on `location.geo.coordinates.0` / `.1`.
