"""Shared route helpers: serialization, list pagination (PRD 2.3)."""
from flask import request

from db import db
from errors import raise_error, ERR_VALIDATION
from middleware import ALL_ROLES, authorized
from response import success_list, success_object
from validate import require_path_resource


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise_error(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is None or offset_raw == "":
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_error(ERR_VALIDATION, "offset must be an integer")
        if isinstance(offset, bool) or offset < 0:
            raise_error(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def list_response(collection, filters=None, items=None):
    """List with created_at-ascending sort, exact-match filters, pagination.
    All list endpoints are readable by any authenticated role and never 404."""
    authorized(ALL_ROLES)
    if items is None:
        items = list(db[collection].values())
    if filters:
        for field, value in filters.items():
            if value is None:
                continue
            items = [r for r in items if r.get(field) == value]
    items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


def get_one(collection, rid, transform=None):
    """GET one resource; readable by any authenticated role."""
    authorized(ALL_ROLES)
    rec = require_path_resource(collection, rid)
    if transform is not None:
        rec = transform(rec)
    return success_object(public(rec))
