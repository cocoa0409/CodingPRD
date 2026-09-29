"""Ladder rungs 1-6 helpers: authentication, role authorisation, path/body
existence resolution, and request-shape validation (PRD 2.1, 2.3, 2.6, 2.7)."""

import re

from flask import request

from errors import ApiError
from store import db

# PRD 2.1 — the seven role names.
ROLE_SHOW_PRODUCER = "ShowProducer"
ROLE_MERCH = "MerchandisingManager"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_MODERATOR = "Moderator"
ROLE_HOST = "Host"
ROLE_VIEWER = "Viewer"
ROLE_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_SHOW_PRODUCER,
    ROLE_MERCH,
    ROLE_COMPLIANCE,
    ROLE_MODERATOR,
    ROLE_HOST,
    ROLE_VIEWER,
    ROLE_ADMIN,
]
ROLE_SET = set(ALL_ROLES)

_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{3})?Z$")
_INT_RE = re.compile(r"^-?\d+$")


# ---------------------------------------------------------------- rungs 1 & 2
def authenticate(allowed_roles):
    """Rung 1: both headers present and the role one of the seven declared names.
    Rung 2: the acting role appears in the endpoint's authorised role list."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# --------------------------------------------------------------------- bodies
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


# ------------------------------------------------------------ rungs 4 & 5
def _fetch(table, key, error_id):
    row = table.get(key)
    if row is None:
        raise ApiError(error_id)
    return row


def get_host(host_id):
    return _fetch(db.hosts, host_id, "ERR_HOST_NOT_FOUND")


def get_product(product_id):
    return _fetch(db.products, product_id, "ERR_PRODUCT_NOT_FOUND")


def get_viewer(viewer_id):
    return _fetch(db.viewers, viewer_id, "ERR_VIEWER_NOT_FOUND")


def get_show(show_id):
    return _fetch(db.shows, show_id, "ERR_SHOW_NOT_FOUND")


def get_channel(channel_id):
    return _fetch(db.channels, channel_id, "ERR_STREAM_CHANNEL_NOT_FOUND")


def get_booking(booking_id):
    return _fetch(db.bookings, booking_id, "ERR_HOST_BOOKING_NOT_FOUND")


def get_slot(slot_id):
    return _fetch(db.slots, slot_id, "ERR_LINEUP_SLOT_NOT_FOUND")


def get_offer(offer_id):
    return _fetch(db.offers, offer_id, "ERR_FLASH_OFFER_NOT_FOUND")


def get_disclosure(record_id):
    return _fetch(db.disclosures, record_id, "ERR_DISCLOSURE_RECORD_NOT_FOUND")


def get_cart(cart_id):
    return _fetch(db.carts, cart_id, "ERR_CART_NOT_FOUND")


def get_cart_item(item_id):
    return _fetch(db.cart_items, item_id, "ERR_CART_ITEM_NOT_FOUND")


def get_order(order_id):
    return _fetch(db.orders, order_id, "ERR_ORDER_NOT_FOUND")


def get_interaction(interaction_id):
    return _fetch(db.interactions, interaction_id, "ERR_INTERACTION_NOT_FOUND")


def fk_id(payload, field):
    """A body foreign key must be a present, non-empty string before it can be
    resolved; a missing one is a request-shape failure."""
    value = payload.get(field)
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", field + " is required.")
    return value


# ------------------------------------------------------------------- rung 6
def req_str(payload, field, min_len=1, max_len=None):
    value = payload.get(field)
    if not isinstance(value, str) or len(value) < min_len:
        raise ApiError("ERR_INVALID_REQUEST", field + " is required.")
    if max_len is not None and len(value) > max_len:
        raise ApiError("ERR_INVALID_REQUEST", field + " is out of range.")
    return value


def opt_str(payload, field, default=None):
    if field not in payload or payload.get(field) is None:
        return default
    value = payload.get(field)
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", field + " must be a string.")
    return value


def req_int(payload, field, minimum=None, maximum=None):
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", field + " must be an integer.")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", field + " is out of range.")
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", field + " is out of range.")
    return value


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if field not in payload or payload.get(field) is None:
        return default
    return req_int(payload, field, minimum, maximum)


def req_fraction(payload, field, minimum, maximum):
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", field + " must be a number.")
    if value < minimum or value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", field + " is out of range.")
    return value


def req_bool(payload, field, default=False):
    if field not in payload or payload.get(field) is None:
        return default
    value = payload.get(field)
    if not isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", field + " must be a boolean.")
    return value


def req_enum(payload, field, allowed):
    value = payload.get(field)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", field + " is not a permitted value.")
    return value


def parse_dt(raw, field):
    """PRD 2.5: either second precision with a trailing Z, or the
    three-fractional-digit form. Anything else is ERR_INVALID_REQUEST."""
    from datetime import datetime, timezone
    if not isinstance(raw, str):
        raise ApiError("ERR_INVALID_REQUEST", field + " must be an ISO 8601 UTC timestamp.")
    match = _DT_RE.match(raw)
    if not match:
        raise ApiError("ERR_INVALID_REQUEST", field + " must be an ISO 8601 UTC timestamp.")
    frac = match.group(7)
    micro = int(frac[1:]) * 1000 if frac else 0
    try:
        return datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)),
            int(match.group(4)), int(match.group(5)), int(match.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", field + " must be an ISO 8601 UTC timestamp.")


def req_dt(payload, field):
    if field not in payload or payload.get(field) is None:
        raise ApiError("ERR_INVALID_REQUEST", field + " is required.")
    return parse_dt(payload.get(field), field)


# -------------------------------------------------------------- pagination
def pagination():
    """PRD 2.3: limit defaults to 10, min 1, max 100; offset defaults to 0 and
    may not be negative. Anything outside those bounds is ERR_INVALID_REQUEST."""
    limit = 10
    offset = 0
    raw = request.args.get("limit")
    if raw is not None:
        if not _INT_RE.match(raw):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit is out of range.")
    raw = request.args.get("offset")
    if raw is not None:
        if not _INT_RE.match(raw):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset is out of range.")
    return limit, offset


def slice_rows(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
