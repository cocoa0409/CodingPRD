"""Shared route plumbing: the globally ordered preamble every endpoint runs."""

import shapes
from authz import authenticate, require_acting_identity
from response import array_response, object_response, paginate, read_pagination
from store import db, serialize

ENUM = "enum"
FK = "fk"
TEXT = "text"


def read(roles):
    """GET-one preamble: roles (1-3) then the acting identity (5)."""
    caller = authenticate(roles)
    require_acting_identity(caller)
    return caller


def one(row):
    return object_response(serialize(row))


def ordered(rows, order=None):
    if order == "run_sequence":
        return sorted(rows, key=lambda row: (row["run_sequence"], row["_seq"]))
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))


def listing(roles, table, specs, order=None):
    """List preamble: roles, then query shapes and pagination, then identity, then FKs."""
    caller = authenticate(roles)
    values = {}
    pending = []
    for param, field, kind, extra in specs:
        if kind == ENUM:
            values[param] = (field, shapes.query_enum(param, extra))
        else:
            raw = shapes.query_id(param)
            values[param] = (field, raw)
            if kind == FK and raw is not None:
                pending.append((extra, raw))
    limit, offset = read_pagination()
    require_acting_identity(caller)
    for finder, raw in pending:
        finder(raw)
    rows = []
    for row in ordered(list(table.values()), order):
        keep = True
        for field, expected in values.values():
            if expected is not None and row.get(field) != expected:
                keep = False
                break
        if keep:
            rows.append(row)
    limited = paginate(rows, limit, offset)
    return array_response([serialize(row) for row in limited], limit, offset, len(rows))


def tier_of(member):
    return db.membership_tiers[member["tier_id"]]
