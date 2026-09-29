"""Shared route plumbing: generic listing and reads."""

from flask import request

from lookup import get
from response import ok, paginated
from serializers import serialize
from store import sorted_records, store


def _serializer(collection):
    return lambda rec: serialize(collection, rec)


def read_one(collection, identifier):
    return ok(serialize(collection, get(collection, identifier)))


def listing(collection, filters=None):
    """Conjunctive filters, default sort by created_at ascending, then window."""
    records = sorted_records(getattr(store, collection).values())
    for param, field in (filters or {}).items():
        value = request.args.get(param)
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    return paginated(records, _serializer(collection))
