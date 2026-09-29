"""Auth, request lifecycle, pagination and list helpers."""
import threading
from functools import wraps

from flask import g, request

import clock
import response
from db import commit, db
from errors import ApiError, fail

ROLES = (
    "CertifyingAgency",
    "CDESponsor",
    "ComplianceReviewer",
    "TaxCreditInvestor",
    "QALICBSponsor",
)
ALL_ROLES = list(ROLES)

_LOCK = threading.RLock()


class Page(object):
    """A paginated slice of a list endpoint's matches."""

    def __init__(self, items, limit, offset, total_count):
        self.items = items
        self.limit = limit
        self.offset = offset
        self.total_count = total_count


def force_bump(row):
    """Mark a row as mutated even when no stored field value changed."""
    if row is not None:
        g.forced_ids.add(row["id"])


def endpoint(roles, mutating=False, status=200):
    def decorator(fn):
        @wraps(fn)
        def wrapper(**path_args):
            with _LOCK:
                snapshot = None
                try:
                    user_id = request.headers.get("X-User-ID")
                    role = request.headers.get("X-User-Role")
                    if not user_id or not role:
                        fail("ERR_UNAUTHENTICATED")
                    if role not in ROLES:
                        fail("ERR_UNAUTHENTICATED")
                    if role not in roles:
                        fail("ERR_ROLE_NOT_PERMITTED")
                    g.user_id = user_id
                    g.role = role
                    g.forced_ids = set()
                    if mutating:
                        snapshot = db.snapshot()
                    result = fn(**path_args)
                    if mutating:
                        import services.derive as derive

                        derive.recompute_all()
                        commit(snapshot, g.forced_ids, clock.now())
                    if isinstance(result, Page):
                        return response.ok_list(
                            result.items, result.limit, result.offset, result.total_count
                        )
                    if isinstance(result, tuple):
                        payload, code = result
                        return response.ok(payload, code)
                    return response.ok(result, status)
                except ApiError as exc:
                    if snapshot is not None:
                        db.restore(snapshot)
                    return response.error(exc.error_id, exc.message, exc.http_status)

        return wrapper

    return decorator


def pagination():
    """Parse and validate limit/offset (PRD section 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        limit = _strict_int(raw_limit)
        if limit is None or limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        offset = _strict_int(raw_offset)
        if offset is None or offset < 0:
            fail("ERR_INVALID_PAGINATION")
    return limit, offset


def _strict_int(raw):
    text = raw.strip()
    if text == "":
        return None
    if text.startswith("+"):
        text = text[1:]
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        return None
    value = int(digits)
    return -value if negative else value


def paginate(rows, sort_key, descending=False):
    limit, offset = pagination()
    ordered = sorted(rows, key=sort_key, reverse=descending)
    total = len(ordered)
    return Page(ordered[offset:offset + limit], limit, offset, total)


def by_created_desc(rows):
    return paginate(rows, lambda r: (r["created_at"], r["_seq"]), descending=True)


def by_field_asc(rows, field):
    return paginate(rows, lambda r: (r[field], r["_seq"]))


def filter_str(rows, field, param=None):
    value = request.args.get(param or field)
    if value is None:
        return rows
    return [r for r in rows if r.get(field) == value]


def filter_int(rows, field, param=None):
    value = request.args.get(param or field)
    if value is None:
        return rows
    parsed = _strict_int(value)
    if parsed is None:
        return []
    return [r for r in rows if r.get(field) == parsed]


def filter_bool(rows, field, param=None):
    value = request.args.get(param or field)
    if value is None:
        return rows
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        wanted = True
    elif lowered in ("false", "0", "no"):
        wanted = False
    else:
        return []
    return [r for r in rows if r.get(field) is wanted]
