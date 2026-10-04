"""In-memory store, clock, money helpers, response envelope and auth.

Storage is a plain process-local dict keyed by id. Nothing is persisted to
disk and nothing is preloaded: the store starts empty on every boot and every
entity is built at runtime through the declared API surface.
"""
from __future__ import annotations

import calendar
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from flask import g, jsonify, request

# ─── Response envelope (§2.2) ────────────────────────────────────────────────
META = "meta"
RESPONSE_TYPE = "response_type"
DATA = "data"
ERROR_TYPE = "error"
OBJECT_TYPE = "object"
ARRAY_TYPE = "array"

# ─── Logical clock (§2.9) ────────────────────────────────────────────────────
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# ─── Pagination (§2.3) ───────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# ─── Errors ──────────────────────────────────────────────────────────────────
class ApiError(Exception):
    """Carries the catalog error_id and the HTTP status for the envelope."""

    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id: str, http_status: int, message: str) -> ApiError:
    return ApiError(error_id, http_status, message)


def bad_request(message: str = "The request body is not usable.") -> ApiError:
    return ApiError("ERR_INVALID_REQUEST", 400, message)


# ─── Timestamps (§2.6) ───────────────────────────────────────────────────────
def now_iso() -> str:
    """Server timestamp: ISO 8601 UTC, millisecond precision, trailing Z."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_ts(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise bad_request(f"{field} must be an ISO 8601 UTC timestamp string.")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request(f"{field} must be an ISO 8601 UTC timestamp.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_str() -> str:
    return STATE.clock


def clock_dt() -> datetime:
    return parse_ts(STATE.clock, "current_utc")


# ─── Money (§2.7) ────────────────────────────────────────────────────────────
def dec(value: Any) -> Decimal:
    """Exact Decimal from a JSON number without a float round-trip."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except Exception:
            raise bad_request(f"'{value}' is not a number.")
    raise bad_request(f"'{value}' is not a number.")


def round_half_up_cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_CEILING))


def floor_cents(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_FLOOR))


def month_bounds(clock: datetime) -> tuple:
    """Half-open calendar month window containing the clock (§3.9)."""
    start = datetime(clock.year, clock.month, 1, tzinfo=timezone.utc)
    if clock.month == 12:
        nxt = datetime(clock.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(clock.year, clock.month + 1, 1, tzinfo=timezone.utc)
    return start, nxt


def add_calendar_months(dt: datetime, months: int) -> datetime:
    idx = dt.month - 1 + months
    year = dt.year + idx // 12
    month = idx % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return datetime(year, month, day, dt.hour, dt.minute, dt.second, dt.microsecond,
                    tzinfo=timezone.utc)


# ─── Store ───────────────────────────────────────────────────────────────────
class Store:
    """Empty on boot. Every row is created through a declared endpoint."""

    COLLECTIONS = (
        "agents", "capacity_owners", "equipment", "compliance_documents",
        "customer_accounts", "loads", "load_offers", "trips", "settlements",
        "escrow_transactions",
    )

    def __init__(self) -> None:
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        # Per-trip record of which split variants have been computed, so
        # variant_delta_cents stays 0 until both have been.
        self.split_variants = {}
        # A monotonic creation ordinal, so a ranking tie-break never depends on
        # a random identifier (§2.4 pins the tie-break to creation order).
        self.sequence = 0
        self.clock = DEFAULT_CLOCK

    def insert(self, collection: str, row: Dict[str, Any]) -> Dict[str, Any]:
        getattr(self, collection)[row["id"]] = row
        return row

    def all(self, collection: str) -> List[Dict[str, Any]]:
        return list(getattr(self, collection).values())


STATE = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:16].upper()


def mint(collection: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Create a row carrying the four system-managed properties (§2.6)."""
    stamp = now_iso()
    STATE.sequence += 1
    row = {"id": new_id(), "created_at": stamp, "updated_at": stamp, "version": 1,
           "_seq": STATE.sequence}
    row.update(fields)
    return STATE.insert(collection, row)


def touch(row: Dict[str, Any]) -> Dict[str, Any]:
    """A mutation of any kind refreshes updated_at and bumps version."""
    row["updated_at"] = now_iso()
    row["version"] = row.get("version", 1) + 1
    return row


# ─── Request context / RBAC (§2.1) ───────────────────────────────────────────
ROLES = (
    "FreightAgent", "CapacityOwnerOperator", "SafetyReviewer",
    "SettlementOperator", "NetworkAdministrator", "AgentManager",
)


def bind_context() -> None:
    g.user_id = request.headers.get("X-User-ID")
    g.user_role = request.headers.get("X-User-Role")


def require_auth() -> str:
    """Priority 1: both headers present and the role declared."""
    user_id, role = g.get("user_id"), g.get("user_role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 401,
            "X-User-ID and X-User-Role are both required and the role must be "
            "one of FreightAgent, CapacityOwnerOperator, SafetyReviewer, "
            "SettlementOperator, NetworkAdministrator, AgentManager.",
        )
    return role


def require_role(*allowed: str) -> str:
    """Priority 2: the caller's role must be permitted for this operation."""
    role = require_auth()
    if role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS", 403,
            f"Role {role} is not authorized for this operation.",
        )
    return role


# ─── Body parsing ────────────────────────────────────────────────────────────
def body() -> Dict[str, Any]:
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("The request body must be a JSON object.")
    return data


def client_fields(payload: Dict[str, Any], declared: List[str]) -> Dict[str, Any]:
    """Only the endpoint's declared inputs are read; anything else is decorative
    and ignored (a client-supplied system field never overrides the server's)."""
    return {k: payload[k] for k in declared if k in payload}


def require_text(payload: Dict[str, Any], field: str, default: Any = None) -> str:
    if field not in payload:
        if default is not None:
            return default
        raise bad_request(f"{field} is required.")
    value = payload[field]
    if not isinstance(value, str) or not value.strip():
        raise bad_request(f"{field} must be a non-empty string.")
    return value


def opt_text(payload: Dict[str, Any], field: str, default: Optional[str] = None) -> Optional[str]:
    if field not in payload or payload[field] is None:
        return default
    value = payload[field]
    if not isinstance(value, str):
        raise bad_request(f"{field} must be a string.")
    return value


def require_int(payload: Dict[str, Any], field: str, default: Any = None,
                minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    if field not in payload:
        if default is not None:
            return default
        raise bad_request(f"{field} is required.")
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request(f"{field} must be an integer.")
    if minimum is not None and value < minimum:
        raise bad_request(f"{field} must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise bad_request(f"{field} must be at most {maximum}.")
    return value


def require_pct(payload: Dict[str, Any], field: str) -> Decimal:
    if field not in payload:
        raise bad_request(f"{field} is required.")
    value = dec(payload[field])
    if value < 0 or value > 1:
        raise bad_request(f"{field} must be between 0.0 and 1.0 inclusive.")
    return value


def require_bool(payload: Dict[str, Any], field: str, default: bool = False) -> bool:
    if field not in payload:
        return default
    value = payload[field]
    if not isinstance(value, bool):
        raise bad_request(f"{field} must be a boolean.")
    return value


def require_enum(payload: Dict[str, Any], field: str, allowed: tuple) -> str:
    value = require_text(payload, field)
    if value not in allowed:
        raise bad_request(f"{field} must be one of {', '.join(allowed)}.")
    return value


def require_ts(payload: Dict[str, Any], field: str) -> datetime:
    if field not in payload:
        raise bad_request(f"{field} is required.")
    return parse_ts(payload[field], field)


def require_state_code(payload: Dict[str, Any], field: str) -> str:
    value = require_text(payload, field)
    if len(value) != 2:
        raise bad_request(f"{field} must be a two-letter state code.")
    return value.upper()


# ─── Lookups ─────────────────────────────────────────────────────────────────
# One (error_id, human label) pair per resource type, so an unknown id is
# refused with the error the path's resource type names (§2.10 priority 3).
KIND = {
    "agent": ("ERR_AGENT_NOT_FOUND", "agent"),
    "capacity_owner": ("ERR_CAPACITY_OWNER_NOT_FOUND", "capacity owner"),
    "load": ("ERR_LOAD_NOT_FOUND", "load"),
    "offer": ("ERR_OFFER_NOT_FOUND", "board offer"),
    "equipment": ("ERR_EQUIPMENT_NOT_FOUND", "fleet unit"),
    "trip": ("ERR_TRIP_NOT_FOUND", "trip"),
    "settlement": ("ERR_SETTLEMENT_NOT_FOUND", "settlement"),
    "customer_account": ("ERR_CUSTOMER_ACCOUNT_NOT_FOUND", "customer account"),
    "compliance_document": ("ERR_COMPLIANCE_DOCUMENT_NOT_FOUND", "compliance document"),
    "escrow_transaction": ("ERR_ESCROW_TRANSACTION_NOT_FOUND", "ledger entry"),
}

COLLECTION_OF = {
    "agent": "agents",
    "capacity_owner": "capacity_owners",
    "load": "loads",
    "offer": "load_offers",
    "equipment": "equipment",
    "trip": "trips",
    "settlement": "settlements",
    "customer_account": "customer_accounts",
    "compliance_document": "compliance_documents",
    "escrow_transaction": "escrow_transactions",
}


def fetch(kind: str, row_id: str) -> Dict[str, Any]:
    """Priority 3: existence, refused per the resource type in the path."""
    error_id, label = KIND[kind]
    row = getattr(STATE, COLLECTION_OF[kind]).get(row_id)
    if row is None:
        raise ApiError(error_id, 404, f"No {label} with id {row_id}.")
    return row


def find(collection: str, predicate) -> List[Dict[str, Any]]:
    return [r for r in STATE.all(collection) if predicate(r)]


# ─── Responses ───────────────────────────────────────────────────────────────
def _meta(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = {"api_request_id": new_request_id(), "api_request_timestamp": now_iso()}
    if extra:
        meta.update(extra)
    return meta


def ok(payload: Any, status: int = 200, response_type: Optional[str] = None):
    if response_type is None:
        response_type = ARRAY_TYPE if isinstance(payload, list) else OBJECT_TYPE
    return jsonify({META: _meta(), RESPONSE_TYPE: response_type, DATA: payload}), status


def ok_empty(status: int = 200):
    return jsonify({META: _meta(), RESPONSE_TYPE: OBJECT_TYPE, DATA: {}}), status


def ok_list(rows: List[Dict[str, Any]], total: int, limit: int, offset: int):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(rows) < total,
    })
    return jsonify({META: meta, RESPONSE_TYPE: ARRAY_TYPE, DATA: rows}), 200


def error_response(api_error: ApiError):
    return jsonify({
        META: _meta(),
        RESPONSE_TYPE: ERROR_TYPE,
        DATA: {"error_id": api_error.error_id, "message": api_error.message},
    }), api_error.http_status


# ─── Query-string helpers ────────────────────────────────────────────────────
def query_str(name: str) -> Optional[str]:
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_ts(name: str) -> Optional[datetime]:
    value = query_str(name)
    if value is None:
        return None
    return parse_ts(value, name)


def paging() -> tuple:
    limit_raw = request.args.get("limit", str(DEFAULT_LIMIT))
    offset_raw = request.args.get("offset", str(DEFAULT_OFFSET))
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise bad_request("limit and offset must be integers.")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise bad_request(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}.")
    if offset < 0:
        raise bad_request("offset must be non-negative.")
    return limit, offset


def paginate(rows: List[Dict[str, Any]]):
    limit, offset = paging()
    total = len(rows)
    return rows[offset:offset + limit], total, limit, offset