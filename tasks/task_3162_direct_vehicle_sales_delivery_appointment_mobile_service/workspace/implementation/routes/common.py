"""Shared request parsing helpers for the route blueprints."""

import re

from flask import g, request

from errors import fail, parse_dt
from repository import created_at_key, listed, read_paging

UUID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def body():
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data(as_text=True)
        if raw:
            fail("ERR_INVALID_REQUEST")
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST")
    return data


def need(data, field):
    if field not in data or data[field] is None:
        fail("ERR_INVALID_REQUEST", f"{field} is required.")
    return data[field]


def text_field(data, field, default=None):
    value = data.get(field, default)
    if value is None:
        return default
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", f"{field} must be a string.")
    return value


def string_list(data, field, default=None):
    value = data.get(field)
    if value is None:
        return list(default or [])
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", f"{field} must be an array.")
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", f"{field} must contain strings.")
    return value


def int_field(data, field, default=None):
    value = data.get(field, default)
    if value is None:
        return default
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", f"{field} must be an integer.")
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", f"{field} must be an integer.")


def number_field(data, field, default=None):
    value = data.get(field, default)
    if value is None:
        return default
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", f"{field} must be numeric.")
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", f"{field} must be numeric.")


def bool_field(data, field, default=False):
    value = data.get(field, default)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def instant_field(data, field, required=True, default=None):
    if field in data and data[field] is not None:
        return parse_dt(data[field], field)
    if required:
        fail("ERR_INVALID_REQUEST", f"{field} is required.")
    return default


def acting_user_id():
    return getattr(g, "user_id", "")


def acting_role():
    return getattr(g, "role", "")


def is_admin():
    return acting_role() == "PlatformAdmin"


def require_owner(order):
    """A Buyer may only act on an order whose buyer_id equals their own X-User-ID."""
    if acting_role() == "Buyer":
        if order["buyer_id"] != acting_user_id():
            fail("ERR_ORDER_NOT_OWNED")


def require_self(buyer):
    if acting_role() == "Buyer":
        if buyer["id"] != acting_user_id():
            fail("ERR_INSUFFICIENT_PERMISSIONS")


def check_version(payload, field, row):
    """Optimistic concurrency: compare only when the client supplied the field."""
    if field not in payload or payload[field] is None:
        if field in ("expected_order_version", "expected_service_appointment_version"):
            fail("ERR_INVALID_REQUEST", f"{field} is required.")
        return
    supplied = payload[field]
    if isinstance(supplied, bool) or not isinstance(supplied, int):
        try:
            supplied = int(supplied)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", f"{field} must be an integer.")
    if supplied != row.get("version"):
        fail("ERR_STALE_VERSION")


def paged(rows):
    page, ordered, limit, offset = listed(rows, request.args)
    return page, limit, offset


class _Staged(object):
    """Sorts a filtered collection once, then publishes it in full.

    The response layer slices the page itself, so handing it the whole sorted
    collection lets `meta.total_count` report the number of matching rows across
    all pages (PRD 2.3) while the enclosing route's own slice is what is sent.
    """

    def __init__(self, rows):
        self.ordered = sorted(rows, key=created_at_key)
        self.limit, self.offset = read_paging(request.args)
        self.count = len(self.ordered)

    def page(self):
        return self.ordered[self.offset:self.offset + self.limit]


def counted(rows):
    """`paged`, plus the total number of matching rows across all pages."""
    staged = _Staged(rows)
    return staged.page(), staged.limit, staged.offset, staged.count


def page_and_total(rows):
    page, ordered, limit, offset = listed(rows, request.args)
    return page, len(ordered), limit, offset