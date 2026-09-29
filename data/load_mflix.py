"""Load sample_mflix into MongoDB and create the read-only user the eval runs as.

The JSON export is pinned to one commit of a public mirror of MongoDB's sample
data, so every run (laptop or CI) sees the same documents.

    python data/load_mflix.py            # uses MONGO_ADMIN_URI, default admin:admin@localhost
    python data/load_mflix.py --bootstrap-admin   # fresh local mongod --auth: create admin first
"""
import argparse
import os
import sys
import urllib.request
from pathlib import Path

from bson import json_util
from pymongo import MongoClient

COMMIT = "7b5ccdfa64940857f20f939c6c5aa6c37f477f8f"
BASE = f"https://raw.githubusercontent.com/neelabalan/mongodb-sample-dataset/{COMMIT}/sample_mflix"
COLLECTIONS = ["movies", "comments", "theaters", "users", "sessions"]
RAW = Path(__file__).resolve().parent / "raw"

ADMIN_URI = os.environ.get("MONGO_ADMIN_URI", "mongodb://admin:admin@localhost:27017/?authSource=admin")
READER_USER, READER_PASS = "reader", os.environ.get("MONGO_READER_PASSWORD", "reader")


def fetch(name):
    RAW.mkdir(exist_ok=True)
    path = RAW / f"{name}.json"
    if not path.exists():
        print(f"downloading {name}.json", flush=True)
        urllib.request.urlretrieve(f"{BASE}/{name}.json", path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap-admin", action="store_true",
                    help="create the admin user through mongod's localhost exception")
    args = ap.parse_args()

    if args.bootstrap_admin:
        c = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=3000)
        c.admin.command("createUser", "admin", pwd="admin", roles=["root"])
        print("created admin user")

    client = MongoClient(ADMIN_URI, serverSelectionTimeoutMS=5000)
    db = client["sample_mflix"]
    for name in COLLECTIONS:
        docs = [json_util.loads(line) for line in open(fetch(name), encoding="utf-8") if line.strip()]
        db[name].drop()
        for i in range(0, len(docs), 2000):
            db[name].insert_many(docs[i : i + 2000], ordered=False)
        print(f"{name}: {db[name].count_documents({})} documents", flush=True)

    db.comments.create_index("movie_id")
    db.movies.create_index("year")

    # Least privilege: the eval (and the model) only ever connect as this user.
    if READER_USER in [u["user"] for u in db.command("usersInfo")["users"]]:
        db.command("dropUser", READER_USER)
    db.command("createUser", READER_USER, pwd=READER_PASS, roles=[{"role": "read", "db": "sample_mflix"}])
    print(f"created read-only user {READER_USER!r} on sample_mflix")


if __name__ == "__main__":
    sys.exit(main())
