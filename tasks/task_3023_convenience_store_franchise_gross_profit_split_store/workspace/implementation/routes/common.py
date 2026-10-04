"""Shared route helpers."""

from flask import request

import db
import middleware
import schemas
from response import ok

RESTRICTED = ("FranchisorAdmin",)
SHARED = ("FranchisorAdmin", "Franchisee")


def filters_from_args(allowed):
    """Filter records by the query parameters the endpoint declares."""
    criteria = {}
    for field in allowed:
        value = request.args.get(field)
        if value is not None:
            criteria[field] = value
    return criteria


def list_records(table, allowed_filters, sort_key=None):
    records = db.all_of(table)
    criteria = filters_from_args(allowed_filters)
    if criteria:
        filtered = []
        for record in records:
            match = True
            for field, raw in criteria.items():
                value = record.get(field)
                if isinstance(value, bool):
                    as_bool = raw.lower() in ("true", "1", "yes")
                    if value != as_bool:
                        match = False
                        break
                elif isinstance(value, int):
                    try:
                        if value != int(raw):
                            match = False
                            break
                    except (TypeError, ValueError):
                        match = False
                        break
                elif str(value) != raw:
                    match = False
                    break
            if match:
                filtered.append(record)
        records = filtered
    if sort_key is not None:
        records = sorted(records, key=sort_key)
    rows, meta = middleware.paginated(records, lambda r: schemas.dump(table, r))
    return ok(rows, 200, pagination=meta)


def read_one(table, record_id):
    record = db.get(table, record_id)
    if record is None:
        from errors import fail
        fail("ERR_RESOURCE_NOT_FOUND")
    return ok(schemas.dump(table, record))