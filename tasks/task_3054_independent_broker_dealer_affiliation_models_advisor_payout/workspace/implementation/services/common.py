"""Shared request parsing, pagination and OCC plumbing."""

import flask

from db import iso_now
from errors import fail

# Endpoints whose declared input carries a version field require it; omitting
# it is a malformed request -> ERR_INVALID_REQUEST (PRD 2.8).
VERSION_FIELDS = ("expected_branch_version", "expected_advisor_version")


def body():
    """A JSON object body, or an empty object when no body was supplied.

    A missing body is not itself malformed; whatever field the operation
    declares is what fails, with ERR_INVALID_REQUEST.
    """
    data = flask.request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST")
    return data


def query():
    return flask.request.args


def pagination_params():
    """limit defaults 10, clamped to [1, 100]; offset defaults 0 (PRD 2.3)."""
    raw_limit = flask.request.args.get("limit")
    raw_offset = flask.request.args.get("offset")
    limit = 10
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    offset = 0
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST")
    if offset < 0:
        offset = 0
    return limit, offset


def page(rows, limit, offset):
    ordered = sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    return ordered[offset:offset + limit], len(ordered)


def require_field(data, name):
    if name not in data or data[name] is None:
        fail("ERR_INVALID_REQUEST")
    return data[name]


def optional_field(data, name, default=None):
    return data.get(name, default)


def required_version(data, field):
    """A declared version input is mandatory; omission is ERR_INVALID_REQUEST."""
    if field not in data or data[field] is None:
        fail("ERR_INVALID_REQUEST")
    return data[field]


def check_occ(resource, field, supplied):
    """Mismatch against the parent's current version -> ERR_STALE_VERSION (412)."""
    if supplied is None:
        return
    if int(supplied) != int(resource.get("version", 0)):
        fail("ERR_STALE_VERSION")


def touch(resource):
    """Any mutation refreshes updated_at and advances version by one."""
    resource["version"] = int(resource.get("version", 0)) + 1
    resource["updated_at"] = iso_now()
    return resource


def touch_quiet(resource):
    """Recompute a derived field without declaring a business mutation.

    A derived-field recomputation driven by a child's transition still refreshes
    updated_at (PRD 2.6), and it advances version so that a cached observation
    is truthfully stale.
    """
    return touch(resource)


def paginate_query(rows, filters):
    limit, offset = pagination_params()
    selected = []
    for row in rows:
        if all(row.get(key) == value for key, value in filters.items() if value is not None):
            selected.append(row)
    return page(selected, limit, offset)