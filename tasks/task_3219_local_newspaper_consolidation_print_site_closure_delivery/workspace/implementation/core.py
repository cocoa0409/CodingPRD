"""Core in-memory store, error type, response envelope and time helpers."""
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP


# --------------------------------------------------------------------------
# Decimal helpers
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(1 if value else 0)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    q = Decimal(1).scaleb(-places)
    return float(D(value).quantize(q, rounding=ROUND_HALF_UP))


def money(value):
    """Round half up to 2 decimals and return a JSON-friendly number."""
    return rhu(value, 2)


def rate(value):
    """Round half up to 4 decimals and return a JSON-friendly number."""
    return rhu(value, 4)


def itrunc(value):
    """Truncate toward zero to an integer."""
    return int(D(value).to_integral_value(rounding=ROUND_HALF_UP)) if False else int(value)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def _parse_iso(text):
    if text is None:
        return None
    s = str(text).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03d" % (dt.microsecond // 1000,) + "Z"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.started_at = datetime.now(timezone.utc)

    def set(self, current_utc):
        self.now = _parse_iso(current_utc)

    def iso(self):
        return _fmt(self.now)

    def date(self):
        return self.now.date()

    def stamp(self):
        return _fmt(self.now)


class Store:
    def __init__(self):
        self.clock = Clock()
        self.colls = {}
        self.volume = {}          # (site_id, ISO date) -> charge_cents
        self.requests = {}

    def col(self, coll_name):
        return self.colls.setdefault(coll_name, {})

    def all(self, coll_name):
        return list(self.col(coll_name).values())

    def get(self, coll_name, rid):
        return self.col(coll_name).get(rid)

    def put(self, coll_name, row):
        self.col(coll_name)[row["id"]] = row
        return row

    def find(self, coll_name, **criteria):
        out = []
        for row in self.all(coll_name):
            if all(row.get(k) == v for k, v in criteria.items()):
                out.append(row)
        return out

    def find_one(self, coll_name, **criteria):
        rows = self.find(coll_name, **criteria)
        return rows[0] if rows else None

    def duplicate(self, coll_name, exclude_id, **criteria):
        for row in self.all(coll_name):
            if row.get("id") == exclude_id:
                continue
            if all(row.get(k) == v for k, v in criteria.items()):
                return row
        return None


DB = Store()


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
HTTP_STATUS = {
    "ERR_INVALID_REQUEST": 400,
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_REFERENCE_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_MARKET_NOT_WITHDRAWABLE": 409,
    "ERR_CONTRACTOR_TERMINAL": 409,
    "ERR_STOP_NOT_ACTIVE": 409,
    "ERR_SUBSCRIBER_TERMINAL": 409,
    "ERR_RETENTION_ALREADY_SETTLED": 409,
    "ERR_NOTICES_NOT_DISPATCHED": 409,
    "ERR_LEGAL_NOTICE_HOLD": 422,
    "ERR_PRESS_POSTURE_LOCKED": 422,
    "ERR_PRESS_CAPACITY_EXCEEDED": 422,
    "ERR_BACKED_OUT_REFERENCE": 422,
    "ERR_NO_ROUTE_IN_TIME": 422,
    "ERR_DUPLICATE_HUB_CODE": 409,
    "ERR_STOP_CAPACITY_EXCEEDED": 422,
    "ERR_OVERLAP_PAUSE_WINDOW": 422,
    "ERR_DOCK_SLOT_CONFLICT": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_EFFECTIVE_DATE_NOT_FUTURE": 422,
    "ERR_PAUSE_WINDOW_NOT_OPEN": 422,
    "ERR_PAUSE_WINDOW_STILL_OPEN": 422,
    "ERR_COOLOFF_EXPIRED": 409,
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 409,
    "ERR_REFUND_WINDOW_CLOSED": 409,
    "ERR_COST_RUN_REGRESSION": 409,
    "ERR_RUN_NOT_COSTED": 409,
    "ERR_SITE_NOT_RECEIVING": 422,
    "ERR_NO_PRINT_CAPACITY": 422,
    "ERR_FLOOR_COPIES_EXCEED_CAPACITY": 422,
    "ERR_TRANSFER_COST_CEILING_EXCEEDED": 422,
    "ERR_ROUTE_COST_CEILING_EXCEEDED": 422,
    "ERR_PRINT_BUDGET_EXCEEDED": 402,
}

MESSAGES = {
    "ERR_INVALID_REQUEST": "The request body does not match the endpoint's declared input.",
    "ERR_UNAUTHENTICATED": "The acting identity is missing or does not resolve.",
    "ERR_UNAUTHORIZED": "The acting role may not perform this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "An operator may not approve a change it created itself.",
    "ERR_RESOURCE_NOT_FOUND": "A resource named in the request path does not resolve.",
    "ERR_REFERENCE_NOT_FOUND": "A foreign key supplied in the request body does not resolve.",
    "ERR_INVALID_STATE": "The target resource is not in a state that permits this operation.",
    "ERR_MARKET_NOT_WITHDRAWABLE": "The market has no active delivery boycott.",
    "ERR_CONTRACTOR_TERMINAL": "The delivery contractor is terminated.",
    "ERR_STOP_NOT_ACTIVE": "The delivery stop is not active.",
    "ERR_SUBSCRIBER_TERMINAL": "The subscriber contract is churned.",
    "ERR_RETENTION_ALREADY_SETTLED": "The retention action is already settled.",
    "ERR_NOTICES_NOT_DISPATCHED": "The frequency reduction notices are not dispatched.",
    "ERR_LEGAL_NOTICE_HOLD": "The owning hub is under a legal-notice hold.",
    "ERR_PRESS_POSTURE_LOCKED": "The site or hub posture forbids this write.",
    "ERR_PRESS_CAPACITY_EXCEEDED": "The run would exceed the site's installed press capacity.",
    "ERR_BACKED_OUT_REFERENCE": "The referenced row was already terminated by a reverse action.",
    "ERR_NO_ROUTE_IN_TIME": "No eligible direct hop clears the market's publication deadline.",
    "ERR_DUPLICATE_HUB_CODE": "The identifier is already taken within its container.",
    "ERR_STOP_CAPACITY_EXCEEDED": "The route's stop capacity would be exceeded.",
    "ERR_OVERLAP_PAUSE_WINDOW": "The pause window is malformed.",
    "ERR_DOCK_SLOT_CONFLICT": "The dock loading window conflicts with an existing departure.",
    "ERR_STALE_VERSION": "The submitted expected_hub_version is stale.",
    "ERR_EFFECTIVE_DATE_NOT_FUTURE": "The effective date is not strictly in the future.",
    "ERR_PAUSE_WINDOW_NOT_OPEN": "The logical date is outside the declared pause window.",
    "ERR_PAUSE_WINDOW_STILL_OPEN": "The pause window has not yet closed.",
    "ERR_COOLOFF_EXPIRED": "The cooling-off window has lapsed.",
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": "The statutory notice period has not elapsed.",
    "ERR_REFUND_WINDOW_CLOSED": "The paid-through instant has passed.",
    "ERR_COST_RUN_REGRESSION": "The run date does not advance the cost calendar.",
    "ERR_RUN_NOT_COSTED": "An edition in the market has not been costed.",
    "ERR_SITE_NOT_RECEIVING": "The receiving print site cannot take this transfer.",
    "ERR_NO_PRINT_CAPACITY": "The receiving site has insufficient remaining capacity.",
    "ERR_FLOOR_COPIES_EXCEED_CAPACITY": "The guaranteed floor exceeds the site's remaining capacity.",
    "ERR_TRANSFER_COST_CEILING_EXCEEDED": "The transfer cost would exceed the hub ceiling.",
    "ERR_ROUTE_COST_CEILING_EXCEEDED": "The market's route night cost ceiling would be exceeded.",
    "ERR_PRINT_BUDGET_EXCEEDED": "The hub's print tonnage budget would be exceeded.",
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or MESSAGES.get(error_id, error_id)
        self.http_status = HTTP_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def new_request_id():
    chars = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(chars) for _ in range(18))


def envelope(data, response_type, pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": _fmt(DB.clock.now),
    }
    if pagination:
        meta.update(pagination)
    return {"meta": meta, "response_type": response_type, "data": data}


def paginate(rows, limit_raw, offset_raw):
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
    if offset < 0:
        offset = 0
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }