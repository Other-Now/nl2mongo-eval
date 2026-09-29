import os

from pymongo import MongoClient

from . import guard

READER_URI = os.environ.get(
    "MONGO_URI", "mongodb://reader:reader@localhost:27017/sample_mflix?authSource=sample_mflix"
)


class Runner:
    """Runs pipelines as the read-only user, through the guard, with a row cap and timeout."""

    def __init__(self, uri=READER_URI):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=3000, tz_aware=True)
        self.db = self.client.get_default_database()

    def run(self, collection, pipeline, limit=guard.MAX_ROWS):
        guard.check(collection, pipeline)
        cursor = self.db[collection].aggregate(
            list(pipeline) + [{"$limit": limit}], maxTimeMS=guard.MAX_TIME_MS
        )
        return guard.redact(list(cursor))

    def count(self, collection):
        return self.db[collection].estimated_document_count()
