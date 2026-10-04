"""In-memory data store. Empty on every boot; never seeded."""
import uuid

import clock

TABLES = [
    "employers", "record_layouts", "payroll_feed_batches", "employment_records",
    "covered_workers", "verifiers", "verification_products", "consumer_authorizations",
    "verification_requests", "verification_responses", "consumer_disclosures",
    "record_disputes", "compensation_accruals", "data_currency_reviews",
    "verification_attestations", "compensation_settlements",
]

_store = {name: {} for name in TABLES}


def reset():
    for name in TABLES:
        _store[name] = {}


class DB:
    def __getattr__(self, name):
        if name in _store:
            return _store[name]
        raise AttributeError(name)


db = DB()


def new_id():
    return str(uuid.uuid4())


def insert(table, row):
    _store[table][row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = clock.now()
    row["version"] += 1
    return row


def get(table, row_id):
    return _store[table].get(row_id)


def all_rows(table):
    return list(_store[table].values())


def delete(table, row_id):
    return _store[table].pop(row_id, None)