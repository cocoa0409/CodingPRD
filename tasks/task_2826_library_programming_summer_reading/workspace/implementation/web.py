"""Envelope, authentication, pagination and the endpoint decorator."""

import functools
import random
import string

from flask import request

import revision
from core import clock
from derive import SERIALIZERS
from errors import ApiError

ROLES = ("ProgramManager", "ProgramCoordinator", "ScreeningOfficer", "Reader")

_ALPHANUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def meta(extra=None):
    payload = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        payload.update(extra)
    return payload


def success_object(data, status=200):
    return {"meta": meta(), "response_type": "object", "data": data}, status


def success_array(items, page):
    total = page["total_count"]
    return (
        {
            "meta": meta(
                {
                    "limit": page["limit"],
                    "offset": page["offset"],
                    "total_count": total,
                    "has_more": page["offset"] + len(items) < total,
                }
            ),
            "response_type": "array",
            "data": items,
        },
        200,
    )


def error_body(error_id, message):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# authentication and authorization (ladder steps 1 and 2)
# --------------------------------------------------------------------------

def acting_user_id():
    for name in ("X-User-Id", "X-User-ID"):
        value = request.headers.get(name)
        if value is not None and value.strip() != "":
            return value
    return None


def acting_role():
    value = request.headers.get("X-User-Role")
    if value is not None and value.strip() != "":
        return value
    return None


def authenticate(allowed_roles):
    user_id = acting_user_id()
    role = acting_role()
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# --------------------------------------------------------------------------
# pagination (ladder step 4)
# --------------------------------------------------------------------------

def _pagination_int(raw, name):
    if raw is None:
        return None
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer." % name)
    value = int(text)
    return value


def pagination():
    limit = _pagination_int(request.args.get("limit"), "limit")
    offset = _pagination_int(request.args.get("offset"), "offset")
    if limit is None:
        limit = 10
    elif limit < 1 or limit > 100:
        raise ApiError(
            "ERR_INVALID_PAGINATION", "limit must be between 1 and 100."
        )
    if offset is None:
        offset = 0
    elif offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0.")
    return {"limit": limit, "offset": offset, "total_count": 0}


def paginate(items, table):
    page = pagination()
    page["total_count"] = len(items)
    window = items[page["offset"] : page["offset"] + page["limit"]]
    serializer = SERIALIZERS[table]
    return [serializer(item) for item in window], page


# --------------------------------------------------------------------------
# handler results
# --------------------------------------------------------------------------

class Obj(object):
    def __init__(self, table, entity, status=200):
        self.table = table
        self.entity = entity
        self.status = status


class Arr(object):
    def __init__(self, table, items):
        self.table = table
        self.items = items


class Empty(object):
    def __init__(self, status=200):
        self.status = status


def endpoint(roles, mutating=False):
    """Wrap a handler with steps 1-2 of the ladder and the response envelope."""

    def decorate(fn):
        @functools.wraps(fn)
        def inner(**path_params):
            user_id, role = authenticate(roles)
            if mutating:
                revision.begin()
            try:
                result = fn(user_id=user_id, role=role, **path_params)
            except Exception:
                revision.abort()
                raise
            if mutating:
                revision.finish()
            if isinstance(result, Arr):
                items, page = paginate(result.items, result.table)
                return success_array(items, page)
            if isinstance(result, Empty):
                return success_object({}, result.status)
            return success_object(
                SERIALIZERS[result.table](result.entity), result.status
            )

        return inner

    return decorate
