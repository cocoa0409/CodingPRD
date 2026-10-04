"""Shared route helpers: record creation, listing and ownership guards."""

from flask import request

from db import DB, created_key, stamp_create
from errors import (
    ERR_MEMBER_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND,
    ApiError,
)
from middleware import auth, paginate, query_filter, raw_body, require_owner
from response import ok_array, ok_object
from services import serialize


def mk(collection, **fields):
    record = {"id": DB.next_id()}
    record.update(fields)
    stamp_create(record, DB.clock())
    DB.put(collection, record)
    return record


def list_response(items, serializer, filters=None):
    if filters:
        items = query_filter(items, filters)
    items = sorted(items, key=created_key)
    page, limit, offset, total = paginate(items)
    return ok_array([serializer(x) for x in page], limit, offset, total)


def fetch(collection, entity_id, error_id=ERR_RESOURCE_NOT_FOUND):
    record = DB.get(collection, entity_id)
    if record is None:
        raise ApiError(error_id)
    return record


def fetch_member(member_id):
    return fetch("members", member_id, ERR_MEMBER_NOT_FOUND)


def guard_member_view(user_id, role, member_id):
    """Ownership guard for member-scoped reads performed by a Member."""
    if role == "Member":
        require_owner(user_id, member_id)


def body():
    return raw_body()


def object_response(serializer, record):
    return ok_object(serializer(record))


def path(name):
    return request.view_args.get(name)


# Convenience re-exports used by route modules.
__all__ = [
    "mk",
    "list_response",
    "fetch",
    "fetch_member",
    "guard_member_view",
    "body",
    "object_response",
    "path",
    "auth",
    "serialize",
    "created_key",
    "ok_object",
    "ok_array",
]