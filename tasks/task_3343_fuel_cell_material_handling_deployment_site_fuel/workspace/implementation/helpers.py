"""Shared fetch / guard / pagination helpers."""

from flask import request

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_SITE_CLOSED, ERR_INVALID_REQUEST,
)


def get_or_404(store, key, what="resource"):
    obj = store.get(key)
    if obj is None:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found" % what)
    return obj


def get_site(site_id):
    return get_or_404(db.sites, site_id, "site")


def ensure_child(child, parent_key, parent_id, what="resource"):
    """Nested-ownership check: a child referenced under the wrong parent is
    a 404 (hierarchical consistency, PRD section 2.6)."""
    if child[parent_key] != parent_id:
        raise ApiError(ERR_NOT_FOUND, 404, "%s not found" % what)


def ensure_site_open(site):
    if site["status"] == "CLOSED":
        raise ApiError(ERR_SITE_CLOSED, 409, "site is closed")


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = db.stamp()


def create_rec(store, fields):
    now = db.stamp()
    rec = {"id": db.new_id(), "created_at": now, "updated_at": now, "version": 1}
    rec.update(fields)
    store[rec["id"]] = rec
    return rec


def sorted_by_created(items):
    return sorted(items, key=lambda r: r["created_at"])


def paginate(items):
    """items must be pre-sorted; returns (page, pagination meta dict).

    Pagination per PRD section 2.3: limit (default 10, min 1, max 100) and
    offset (default 0); invalid values are ERR_INVALID_REQUEST (400).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        if not raw_limit.isdigit():
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        if not raw_offset.isdigit():
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "offset must be a non-negative integer")
        offset = int(raw_offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
