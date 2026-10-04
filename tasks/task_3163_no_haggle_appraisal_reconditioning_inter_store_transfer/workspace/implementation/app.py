"""No-Haggle Auto Retail API — task_3163.

In-memory Flask implementation per PRD.md and SCAFFOLD.yaml. No seeding, no disk persistence.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import Flask, jsonify, request

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"


def _parse_iso(s: str) -> datetime:
    """Parse an ISO8601 string; accepts trailing Z."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 at second precision with Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._now: datetime = _parse_iso(CLOCK_DEFAULT_ISO)

    def now(self) -> datetime:
        return self._now

    def set(self, iso: str) -> datetime:
        dt = _parse_iso(iso)
        self._now = dt
        return dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class DB:
    def __init__(self):
        self.stores: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}
        self.associates: dict[str, dict] = {}
        self.vehicles: dict[str, dict] = {}
        self.appraisals: dict[str, dict] = {}
        self.inspections: dict[str, dict] = {}
        self.line_items: dict[str, dict] = {}
        self.pricing_events: dict[str, dict] = {}
        self.transfer_requests: dict[str, dict] = {}
        self.sales: dict[str, dict] = {}
        self.financing_applications: dict[str, dict] = {}
        self.lender_offers: dict[str, dict] = {}
        self.return_requests: dict[str, dict] = {}
        self.auction_lots: dict[str, dict] = {}
        self.ledger_entries: dict[str, dict] = {}


db = DB()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = ("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
ERR_UNAUTHORIZED_ROLE = ("ERR_UNAUTHORIZED_ROLE", 403)
ERR_UNKNOWN_IDENTITY = ("ERR_UNKNOWN_IDENTITY", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_VALIDATION = ("ERR_VALIDATION", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 409)
ERR_INSPECTION_ALREADY_OPEN = ("ERR_INSPECTION_ALREADY_OPEN", 409)
ERR_LINE_ITEMS_UNRESOLVED = ("ERR_LINE_ITEMS_UNRESOLVED", 409)
ERR_VEHICLE_ALREADY_HELD = ("ERR_VEHICLE_ALREADY_HELD", 409)
ERR_VEHICLE_NOT_LISTED = ("ERR_VEHICLE_NOT_LISTED", 409)
ERR_VEHICLE_NO_LONGER_AVAILABLE = ("ERR_VEHICLE_NO_LONGER_AVAILABLE", 409)
ERR_APPRAISAL_EXPIRED = ("ERR_APPRAISAL_EXPIRED", 409)
ERR_APPRAISAL_CUSTOMER_MISMATCH = ("ERR_APPRAISAL_CUSTOMER_MISMATCH", 409)
ERR_APPRAISAL_NOT_ACTIVE = ("ERR_APPRAISAL_NOT_ACTIVE", 409)
ERR_RETURN_WINDOW_CLOSED = ("ERR_RETURN_WINDOW_CLOSED", 409)
ERR_FINANCING_NOT_ACCEPTED = ("ERR_FINANCING_NOT_ACCEPTED", 409)
ERR_OFFER_NOT_PRESENTED = ("ERR_OFFER_NOT_PRESENTED", 409)
ERR_FINANCING_DECLINED = ("ERR_FINANCING_DECLINED", 409)
ERR_AUCTION_ROUNDS_EXHAUSTED = ("ERR_AUCTION_ROUNDS_EXHAUSTED", 409)
ERR_HAMMER_BELOW_RESERVE_INVALID = ("ERR_HAMMER_BELOW_RESERVE_INVALID", 422)
ERR_WINDOW_CLOSED = ("ERR_WINDOW_CLOSED", 409)
ERR_CROSS_ENTITY_STATE = ("ERR_CROSS_ENTITY_STATE", 409)
ERR_AGGREGATE_RULE = ("ERR_AGGREGATE_RULE", 409)
ERR_FISCAL_RULE = ("ERR_FISCAL_RULE", 409)


def raise_err(spec, message: str):
    raise ApiError(spec[0], spec[1], message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def _request_id() -> str:
    return "req_" + uuid.uuid4().hex[:24]


def _now_iso() -> str:
    return _format_iso(CLOCK.now())


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit: int, offset: int, total_count: int, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

ROLE_TO_KIND = {
    "StoreManager": "MANAGER",
    "Appraiser": "APPRAISER",
    "ReconditioningInspector": "INSPECTOR",
    "SalesAssociate": "SALES",
    "FinanceManager": "FINANCE",
}

ENTITY_BACKED_ROLES = set(ROLE_TO_KIND.keys()) | {"Customer"}
OPAQUE_ROLES = {"PlatformAdmin", "AuctionManager"}
ALL_ROLES = ENTITY_BACKED_ROLES | OPAQUE_ROLES


def get_auth():
    """Returns (user_id, role) or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, "X-User-ID and X-User-Role headers required")
    if role not in ALL_ROLES:
        raise_err(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, f"unknown role {role}")
    return user_id, role


def resolve_identity(user_id: str, role: str):
    """Entity-backed identity resolution (priority 3). Returns backing entity dict or None."""
    if role in OPAQUE_ROLES:
        return None
    if role == "Customer":
        ent = db.customers.get(user_id)
        if ent is None:
            raise_err(ERR_UNKNOWN_IDENTITY, f"customer {user_id} not found")
        return ent
    # Associate-backed roles
    ent = db.associates.get(user_id)
    if ent is None:
        raise_err(ERR_UNKNOWN_IDENTITY, f"associate {user_id} not found")
    expected_kind = ROLE_TO_KIND[role]
    if ent.get("role_kind") != expected_kind:
        raise_err(ERR_UNKNOWN_IDENTITY, f"associate {user_id} does not have role_kind {expected_kind}")
    return ent


def require_roles(*allowed_roles):
    """Decorator: enforce auth presence (P1), role permission (P2), entity identity (P3)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed_roles:
                raise_err(ERR_UNAUTHORIZED_ROLE, f"role {role} not permitted for this endpoint")
            identity = resolve_identity(user_id, role)
            return fn(user_id=user_id, role=role, identity=identity, *args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _is_bool(x):
    return isinstance(x, bool)


def _require_fields(payload: dict, fields: list[str]):
    if not isinstance(payload, dict):
        raise_err(ERR_VALIDATION, "request body must be a JSON object")
    for f in fields:
        if f not in payload or payload[f] is None:
            raise_err(ERR_VALIDATION, f"missing required field {f}")


def _validate_enum(value, allowed: list[str], field: str):
    if value not in allowed:
        raise_err(ERR_VALIDATION, f"invalid {field}: {value}")


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------


def get_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(items: list[dict]) -> tuple:
    limit, offset = get_pagination()
    # Default sort: created_at ascending
    items_sorted = sorted(items, key=lambda x: x.get("created_at", ""))
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Common fields helpers
# ---------------------------------------------------------------------------


def mint_common(with_version: bool = True) -> dict:
    now = _now_iso()
    d = {
        "id": str(uuid.uuid4()),
        "created_at": now,
    }
    if with_version:
        d["updated_at"] = now
        d["version"] = 1
    return d


def touch(ent: dict):
    """Bump version and refresh updated_at for resources that carry version."""
    if "version" in ent:
        ent["version"] = int(ent["version"]) + 1
        ent["updated_at"] = _now_iso()


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------


def _round_half_up_int(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_half_up_4dp(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Lazy auto-transitions driven by the logical clock
# ---------------------------------------------------------------------------


def _lazy_transition_appraisal(ap: dict):
    if ap["status"] == "ACTIVE":
        vu = _parse_iso(ap["valid_until"])
        if CLOCK.now() >= vu:
            ap["status"] = "EXPIRED"
            touch(ap)


def _lazy_transition_transfer(tr: dict):
    if tr["status"] == "DELIVERED" and tr.get("hold_expires_at"):
        he = _parse_iso(tr["hold_expires_at"])
        if CLOCK.now() >= he:
            _transition_transfer_hold_expired(tr)


def _transition_transfer_hold_expired(tr: dict):
    tr["status"] = "HOLD_EXPIRED"
    touch(tr)
    veh = db.vehicles.get(tr["vehicle_id"])
    if veh is not None and veh.get("hold_status") == "TRANSFER_HOLD":
        veh["hold_status"] = None
        veh["hold_status"] = "NONE"
        touch(veh)


def _lazy_transition_financing_app(app: dict):
    if app["status"] == "OFFERS_PRESENTED":
        created = _parse_iso(app["created_at"])
        if CLOCK.now() > created + timedelta(days=3):
            app["status"] = "EXPIRED"
            touch(app)
            for of in db.lender_offers.values():
                if of["application_id"] == app["id"] and of["offer_status"] == "PRESENTED":
                    of["offer_status"] = "SUPERSEDED"


def _lazy_transition_all():
    for ap in db.appraisals.values():
        _lazy_transition_appraisal(ap)
    for tr in db.transfer_requests.values():
        _lazy_transition_transfer(tr)
    for app in db.financing_applications.values():
        _lazy_transition_financing_app(app)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def _serialize_vehicle(v: dict) -> dict:
    """Recompute days_in_inventory on read."""
    out = dict(v)
    acquired = _parse_iso(v["inventory_acquired_at"])
    delta = CLOCK.now() - acquired
    out["days_in_inventory"] = int(delta.total_seconds() // 86400)
    return out


def _serialize_appraisal(ap: dict) -> dict:
    _lazy_transition_appraisal(ap)
    return dict(ap)


def _serialize_transfer(tr: dict) -> dict:
    _lazy_transition_transfer(tr)
    return dict(tr)


def _serialize_financing_app(app: dict) -> dict:
    _lazy_transition_financing_app(app)
    return dict(app)


def _serialize_simple(ent: dict) -> dict:
    return dict(ent)


# ---------------------------------------------------------------------------
# Calculation: appraisal_offer_value
# ---------------------------------------------------------------------------

AGE_DEPRECIATION_CENTS = 80000
MILEAGE_DEPRECIATION_CENTS = 1500
RECON_HAIRCUT_NUM = 1
RECON_HAIRCUT_DEN = 2
MIN_OFFER_CENTS = 50000


def compute_provisional_offer(vehicle: dict) -> int:
    base = int(vehicle["book_value_cents"])
    current_year = CLOCK.now().year
    age_years = max(0, current_year - int(vehicle["model_year"]))
    mileage_over = max(0, int(vehicle["odometer_miles"]) - age_years * 12000)
    offer = Decimal(base)
    offer -= Decimal(age_years * AGE_DEPRECIATION_CENTS)
    offer -= Decimal((mileage_over // 1000) * MILEAGE_DEPRECIATION_CENTS)
    offer_int = _round_half_up_int(offer)
    if offer_int < MIN_OFFER_CENTS:
        offer_int = MIN_OFFER_CENTS
    return offer_int


def compute_final_offer(vehicle: dict, recon_cost_total_cents: int) -> int:
    prov = compute_provisional_offer(vehicle)
    haircut = Decimal(recon_cost_total_cents) * Decimal(RECON_HAIRCUT_NUM) / Decimal(RECON_HAIRCUT_DEN)
    offer = Decimal(prov) - haircut
    offer_int = _round_half_up_int(offer)
    if offer_int < MIN_OFFER_CENTS:
        offer_int = MIN_OFFER_CENTS
    return offer_int


# ---------------------------------------------------------------------------
# Calculation: reconditioning_disposition
# ---------------------------------------------------------------------------


def compute_disposition_and_grade(vehicle: dict, inspection: dict, store: dict) -> tuple[str, str | None, int, int]:
    """Returns (disposition, grade_or_None, threshold_cents, provisional_offer_cents)."""
    provisional = compute_provisional_offer(vehicle)
    pct = Decimal(str(store["retail_threshold_pct"]))
    threshold = int((Decimal(provisional) * pct).to_integral_value(rounding="ROUND_FLOOR"))
    est = int(inspection["estimated_repair_total_cents"])
    if est > threshold:
        return ("WHOLESALE", "WHOLESALE_ONLY", threshold, provisional)
    # RETAIL; compute grade
    if est == 0:
        grade = "A"
    elif est <= threshold // 2:
        grade = "B"
    else:
        grade = "C"
    return ("RETAIL", grade, threshold, provisional)


# ---------------------------------------------------------------------------
# Calculation: algorithmic_repricing
# ---------------------------------------------------------------------------

RETAIL_MARKUP_PCT = 12
TIER_1_DAYS, TIER_2_DAYS, TIER_3_DAYS = 30, 45, 60
TIER_1_PCT, TIER_2_PCT, TIER_3_PCT = 3, 5, 8


def compute_initial_list_price(final_offer_cents: int) -> int:
    p = Decimal(final_offer_cents) * Decimal(100 + RETAIL_MARKUP_PCT) / Decimal(100)
    return _round_half_up_int(p)


def compute_markdown(current_price: int, days_in_inventory: int) -> tuple[int, int]:
    """Returns (new_price, tier_pct). Tier pct may be 0 (no change)."""
    d = days_in_inventory
    if d < TIER_1_DAYS:
        tier_pct = 0
    elif d < TIER_2_DAYS:
        tier_pct = TIER_1_PCT
    elif d < TIER_3_DAYS:
        tier_pct = TIER_2_PCT
    else:
        tier_pct = TIER_3_PCT
    if tier_pct == 0:
        return current_price, 0
    new_price = Decimal(current_price) * Decimal(100 - tier_pct) / Decimal(100)
    return _round_half_up_int(new_price), tier_pct


# ---------------------------------------------------------------------------
# Calculation: transfer_shipping_fee
# ---------------------------------------------------------------------------

LANE_BASE_0 = 15000
LANE_BASE_1 = 45000
LANE_BASE_2 = 90000
EXPEDITE_NUM, EXPEDITE_DEN = 3, 2
ENCLOSED_CARRIER_SURCHARGE = 20000

_REGION_BAND = {
    ("WEST", "WEST"): 0, ("CENTRAL", "CENTRAL"): 0, ("EAST", "EAST"): 0,
    ("WEST", "CENTRAL"): 1, ("CENTRAL", "WEST"): 1,
    ("CENTRAL", "EAST"): 1, ("EAST", "CENTRAL"): 1,
    ("WEST", "EAST"): 2, ("EAST", "WEST"): 2,
}

_LANE_BASE_BY_BAND = {0: LANE_BASE_0, 1: LANE_BASE_1, 2: LANE_BASE_2}


def compute_shipping_fee(from_region: str, to_region: str, expedited: bool, model_year: int) -> int:
    band = _REGION_BAND[(from_region, to_region)]
    base = Decimal(_LANE_BASE_BY_BAND[band])
    if expedited:
        base = base * Decimal(EXPEDITE_NUM) / Decimal(EXPEDITE_DEN)
    fee = _round_half_up_int(base)
    current_year = CLOCK.now().year
    if int(model_year) >= current_year - 1:
        fee += ENCLOSED_CARRIER_SURCHARGE
    return fee


# ---------------------------------------------------------------------------
# Calculation: auction_reserve_price
# ---------------------------------------------------------------------------

WHOLESALE_BOOK_PCT = 85
RECON_RECOVERY_PCT = 50
RELIST_DECAY_PCT = 90
MIN_RESERVE_CENTS = 100000


def compute_reserve_standard(vehicle: dict) -> int:
    p = Decimal(int(vehicle["book_value_cents"])) * Decimal(WHOLESALE_BOOK_PCT) / Decimal(100)
    p_int = _round_half_up_int(p)
    recon_part = Decimal(int(vehicle["recon_cost_total_cents"])) * Decimal(RECON_RECOVERY_PCT) / Decimal(100)
    # recon recovery — the formula says "plus 50% of recon_cost_total_cents".
    # No explicit rounding pinned for this addend; treat as exact integer when divisible, else round half up.
    recon_int = _round_half_up_int(recon_part)
    reserve = p_int + recon_int
    if reserve < MIN_RESERVE_CENTS:
        reserve = MIN_RESERVE_CENTS
    return reserve


def compute_reserve_relist(prior_reserve: int) -> int:
    p = Decimal(int(prior_reserve)) * Decimal(RELIST_DECAY_PCT) / Decimal(100)
    reserve = _round_half_up_int(p)
    if reserve < MIN_RESERVE_CENTS:
        reserve = MIN_RESERVE_CENTS
    return reserve


# ---------------------------------------------------------------------------
# Calculation: financing_tier_scoring
# ---------------------------------------------------------------------------

DTI_CAP = Decimal("0.5")
TIER_1_MIN = Decimal("0.8000")
TIER_2_MIN = Decimal("0.6000")
TIER_3_MIN = Decimal("0.4000")

LENDER_APR_BPS = {
    "LENDER_A": {"TIER_1": 490, "TIER_2": 690, "TIER_3": 990},
    "LENDER_B": {"TIER_1": 515, "TIER_2": 740, "TIER_3": 1040},
    "LENDER_C": {"TIER_1": 540, "TIER_2": 780, "TIER_3": 1090},
}


def compute_approval_tier(credit_score: int, amount_due_cents: int, annual_income_cents: int) -> str:
    normalized_credit = (Decimal(int(credit_score)) - Decimal(300)) / Decimal(550)
    denom = max(1, int(annual_income_cents))
    dti = Decimal(int(amount_due_cents)) / Decimal(denom)
    normalized_dti = Decimal(1) - (dti / DTI_CAP)
    if normalized_dti < 0:
        normalized_dti = Decimal(0)
    score = Decimal("0.7") * normalized_credit + Decimal("0.3") * normalized_dti
    score = _round_half_up_4dp(score)
    if score >= TIER_1_MIN:
        return "TIER_1"
    if score >= TIER_2_MIN:
        return "TIER_2"
    if score >= TIER_3_MIN:
        return "TIER_3"
    return "DECLINED"


# ---------------------------------------------------------------------------
# Calculation: associate_compensation (volume bonus)
# ---------------------------------------------------------------------------

VOLUME_TIER_1, VOLUME_TIER_2, VOLUME_TIER_3 = 5, 10, 20
BONUS_TIER_1, BONUS_TIER_2, BONUS_TIER_3 = 50000, 150000, 400000


def maybe_accrue_volume_bonus(associate: dict, sale: dict):
    """On sale completion, count completed sales for the associate's store in this calendar month.
    If this completion crosses a tier boundary exactly (i.e. count == tier), post bonus entry."""
    completed_at = _parse_iso(sale["completed_at"])
    year, month = completed_at.year, completed_at.month
    store_id = associate["store_id"]
    assoc_id = associate["id"]
    count = 0
    for s in db.sales.values():
        if s.get("associate_id") != assoc_id:
            continue
        if s.get("status") not in ("COMPLETED", "RETURNED"):
            # returned sales still count; CANCELLED/PENDING_FINANCE do not
            continue
        cat = s.get("completed_at")
        if not cat:
            continue
        cdt = _parse_iso(cat)
        if cdt.year == year and cdt.month == month:
            # Bonus counts per-associate; the store restriction is implicit in the associate's home store.
            # PRD: "completed sales in month m at associate's store" — sales are at the selling store,
            # which the formula equates with the associate's home store.
            count += 1
    # Boundary rule: post the bonus only when the just-completed sale crosses the boundary (>= tier for the first time).
    tier_bonus = None
    if count == VOLUME_TIER_1:
        tier_bonus = BONUS_TIER_1
    elif count == VOLUME_TIER_2:
        tier_bonus = BONUS_TIER_2
    elif count == VOLUME_TIER_3:
        tier_bonus = BONUS_TIER_3
    if tier_bonus is not None:
        post_ledger_entry(
            entry_kind="COMMISSION_ACCRUAL",
            amount_cents=tier_bonus,
            ref_entity="Sale",
            ref_id=sale["id"],
            store_id=store_id,
        )


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def post_ledger_entry(entry_kind: str, amount_cents: int, ref_entity: str, ref_id: str, store_id: str):
    ent = mint_common(with_version=False)
    ent["entry_kind"] = entry_kind
    ent["amount_cents"] = int(amount_cents)
    ent["ref_entity"] = ref_entity
    ent["ref_id"] = ref_id
    ent["store_id"] = store_id
    db.ledger_entries[ent["id"]] = ent
    return ent


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _get_or_404(table: dict, key: str, what: str = "resource"):
    ent = table.get(key)
    if ent is None:
        raise_err(ERR_NOT_FOUND, f"{what} {key} not found")
    return ent


def _find_sourcing_appraisal(vehicle_id: str) -> dict | None:
    """Return the newest non-terminal appraisal on a vehicle."""
    candidates = [a for a in db.appraisals.values() if a["vehicle_id"] == vehicle_id and a["status"] in ("PENDING_INSPECTION", "ACTIVE")]
    if not candidates:
        return None
    candidates.sort(key=lambda a: a["created_at"])
    return candidates[-1]


def _find_latest_appraisal_for_offer(vehicle_id: str) -> dict | None:
    """Latest appraisal with a computed final_offer_cents — used for listing/markdown floor.
    Includes appraisals that have since transitioned to REDEEMED/EXPIRED, since the final
    offer was locked in at inspection completion."""
    candidates = [a for a in db.appraisals.values() if a["vehicle_id"] == vehicle_id and a.get("final_offer_cents") is not None]
    if not candidates:
        return None
    candidates.sort(key=lambda a: a["created_at"])
    return candidates[-1]


def _has_open_inspection(vehicle_id: str) -> bool:
    for ins in db.inspections.values():
        if ins["vehicle_id"] == vehicle_id and ins["status"] == "OPEN":
            return True
    return False


def _find_active_transfer_for_vehicle_and_customer(vehicle_id: str, customer_id: str) -> dict | None:
    for tr in db.transfer_requests.values():
        if tr["vehicle_id"] == vehicle_id and tr["customer_id"] == customer_id and tr["status"] == "DELIVERED":
            return tr
    return None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "method not allowed"))


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err)
    import traceback
    traceback.print_exc()
    return error_response(ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1], f"internal error: {err}"))


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_clock(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["to_iso8601"])
    iso = payload["to_iso8601"]
    try:
        dt = _parse_iso(iso)
    except Exception:
        raise_err(ERR_VALIDATION, "to_iso8601 is not a valid ISO 8601 timestamp")
    CLOCK.set(iso)
    _lazy_transition_all()
    return success_object({"current_utc": _format_iso(dt)}, status=200)


# ---------------------------------------------------------------------------
# Stores
# ---------------------------------------------------------------------------


@app.route("/v1/stores", methods=["POST"])
@require_roles("PlatformAdmin")
def create_store(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["store_code", "display_name", "region"])
    region = payload["region"]
    _validate_enum(region, ["WEST", "CENTRAL", "EAST"], "region")
    store_code = payload["store_code"]
    if not isinstance(store_code, str) or not store_code:
        raise_err(ERR_VALIDATION, "store_code must be a non-empty string")
    for s in db.stores.values():
        if s["store_code"] == store_code:
            raise_err(ERR_VALIDATION, f"store_code {store_code} already exists")
    display_name = payload["display_name"]
    if not isinstance(display_name, str) or not display_name:
        raise_err(ERR_VALIDATION, "display_name must be a non-empty string")
    retail_threshold_pct = payload.get("retail_threshold_pct", 0.20)
    if not isinstance(retail_threshold_pct, (int, float)) or isinstance(retail_threshold_pct, bool):
        raise_err(ERR_VALIDATION, "retail_threshold_pct must be a number")
    transfer_hold_days = payload.get("transfer_hold_days", 7)
    if not _is_int(transfer_hold_days) or transfer_hold_days < 0:
        raise_err(ERR_VALIDATION, "transfer_hold_days must be a non-negative integer")
    ent = mint_common()
    ent.update({
        "store_code": store_code,
        "display_name": display_name,
        "region": region,
        "retail_threshold_pct": retail_threshold_pct,
        "transfer_hold_days": transfer_hold_days,
        "status": "ACTIVE",
    })
    db.stores[ent["id"]] = ent
    return success_object(_serialize_simple(ent), status=201)


@app.route("/v1/stores", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Appraiser", "ReconditioningInspector", "SalesAssociate", "FinanceManager", "AuctionManager", "Customer")
def list_stores(user_id, role, identity):
    return paginate(list(db.stores.values()))


@app.route("/v1/stores/<store_id>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Appraiser", "ReconditioningInspector", "SalesAssociate", "FinanceManager", "AuctionManager", "Customer")
def get_store(store_id, user_id, role, identity):
    s = _get_or_404(db.stores, store_id, "store")
    return success_object(_serialize_simple(s))


@app.route("/v1/stores/<store_id>/ledger-entries", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "FinanceManager")
def list_store_ledger(store_id, user_id, role, identity):
    _get_or_404(db.stores, store_id, "store")
    kind = request.args.get("entry_kind")
    items = [le for le in db.ledger_entries.values() if le["store_id"] == store_id]
    if kind:
        items = [le for le in items if le["entry_kind"] == kind]
    return paginate(items)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------


@app.route("/v1/customers", methods=["POST"])
@require_roles("PlatformAdmin")
def create_customer(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["full_name", "email", "credit_score", "stated_annual_income_cents"])
    email = payload["email"]
    if not isinstance(email, str) or not email:
        raise_err(ERR_VALIDATION, "email must be a non-empty string")
    for c in db.customers.values():
        if c["email"] == email:
            raise_err(ERR_VALIDATION, f"email {email} already registered")
    cs = payload["credit_score"]
    if not _is_int(cs) or cs < 300 or cs > 850:
        raise_err(ERR_VALIDATION, "credit_score must be an integer between 300 and 850 inclusive")
    income = payload["stated_annual_income_cents"]
    if not _is_int(income) or income < 0:
        raise_err(ERR_VALIDATION, "stated_annual_income_cents must be a non-negative integer")
    full_name = payload["full_name"]
    if not isinstance(full_name, str) or not full_name:
        raise_err(ERR_VALIDATION, "full_name must be a non-empty string")
    ent = mint_common()
    ent.update({
        "full_name": full_name,
        "email": email,
        "credit_score": cs,
        "stated_annual_income_cents": income,
    })
    db.customers[ent["id"]] = ent
    return success_object(_serialize_simple(ent), status=201)


@app.route("/v1/customers", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "SalesAssociate", "FinanceManager")
def list_customers(user_id, role, identity):
    return paginate(list(db.customers.values()))


@app.route("/v1/customers/<cid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "SalesAssociate", "FinanceManager", "Customer")
def get_customer(cid, user_id, role, identity):
    c = _get_or_404(db.customers, cid, "customer")
    if role == "Customer" and user_id != cid:
        raise_err(ERR_UNAUTHORIZED_ROLE, "customers may read only their own record")
    return success_object(_serialize_simple(c))


# ---------------------------------------------------------------------------
# Associates
# ---------------------------------------------------------------------------


@app.route("/v1/associates", methods=["POST"])
@require_roles("PlatformAdmin")
def create_associate(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["display_name", "store_id", "role_kind"])
    store_id = payload["store_id"]
    store = db.stores.get(store_id)
    if store is None:
        raise_err(ERR_NOT_FOUND, f"store {store_id} not found")
    role_kind = payload["role_kind"]
    _validate_enum(role_kind, ["SALES", "APPRAISER", "INSPECTOR", "FINANCE", "MANAGER"], "role_kind")
    display_name = payload["display_name"]
    if not isinstance(display_name, str) or not display_name:
        raise_err(ERR_VALIDATION, "display_name must be a non-empty string")
    flat = payload.get("flat_commission_cents", 25000)
    if not _is_int(flat) or flat < 0:
        raise_err(ERR_VALIDATION, "flat_commission_cents must be a non-negative integer")
    ent = mint_common()
    ent.update({
        "display_name": display_name,
        "store_id": store_id,
        "role_kind": role_kind,
        "flat_commission_cents": flat,
        "status": "ACTIVE",
    })
    db.associates[ent["id"]] = ent
    return success_object(_serialize_simple(ent), status=201)


@app.route("/v1/associates", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager")
def list_associates(user_id, role, identity):
    items = list(db.associates.values())
    sid = request.args.get("store_id")
    rk = request.args.get("role_kind")
    if sid:
        items = [a for a in items if a["store_id"] == sid]
    if rk:
        items = [a for a in items if a["role_kind"] == rk]
    return paginate(items)


@app.route("/v1/associates/<aid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager")
def get_associate(aid, user_id, role, identity):
    a = _get_or_404(db.associates, aid, "associate")
    return success_object(_serialize_simple(a))


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------


@app.route("/v1/vehicles", methods=["POST"])
@require_roles("StoreManager")
def create_vehicle(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["vin", "make", "model", "model_year", "odometer_miles", "book_value_cents", "current_store_id"])
    vin = payload["vin"]
    if not isinstance(vin, str) or len(vin) != 17:
        raise_err(ERR_VALIDATION, "vin must be a 17-character string")
    for v in db.vehicles.values():
        if v["vin"] == vin:
            raise_err(ERR_VALIDATION, f"vin {vin} already exists")
    store_id = payload["current_store_id"]
    store = db.stores.get(store_id)
    if store is None:
        raise_err(ERR_NOT_FOUND, f"store {store_id} not found")
    if store["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"store {store_id} is CLOSED")
    model_year = payload["model_year"]
    if not _is_int(model_year) or model_year < 1990 or model_year > 2027:
        raise_err(ERR_VALIDATION, "model_year must be an integer between 1990 and 2027 inclusive")
    odo = payload["odometer_miles"]
    if not _is_int(odo) or odo < 0:
        raise_err(ERR_VALIDATION, "odometer_miles must be a non-negative integer")
    bv = payload["book_value_cents"]
    if not _is_int(bv) or bv <= 0:
        raise_err(ERR_VALIDATION, "book_value_cents must be a positive integer")
    make = payload["make"]
    if not isinstance(make, str) or not make:
        raise_err(ERR_VALIDATION, "make must be a non-empty string")
    model = payload["model"]
    if not isinstance(model, str) or not model:
        raise_err(ERR_VALIDATION, "model must be a non-empty string")
    ent = mint_common()
    ent.update({
        "vin": vin,
        "make": make,
        "model": model,
        "model_year": model_year,
        "odometer_miles": odo,
        "book_value_cents": bv,
        "current_store_id": store_id,
        "lifecycle_status": "INTAKE",
        "hold_status": "NONE",
        "condition_grade": "UNGRADED",
        "current_list_price_cents": None,
        "inventory_acquired_at": _now_iso(),
        "recon_cost_total_cents": 0,
    })
    db.vehicles[ent["id"]] = ent
    return success_object(_serialize_vehicle(ent), status=201)


@app.route("/v1/vehicles", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Appraiser", "ReconditioningInspector", "SalesAssociate", "FinanceManager", "AuctionManager", "Customer")
def list_vehicles(user_id, role, identity):
    items = list(db.vehicles.values())
    sid = request.args.get("current_store_id")
    ls = request.args.get("lifecycle_status")
    hs = request.args.get("hold_status")
    if sid:
        items = [v for v in items if v["current_store_id"] == sid]
    if ls:
        items = [v for v in items if v["lifecycle_status"] == ls]
    if hs:
        items = [v for v in items if v["hold_status"] == hs]
    items = [_serialize_vehicle(v) for v in items]
    return paginate(items)


@app.route("/v1/vehicles/<vid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Appraiser", "ReconditioningInspector", "SalesAssociate", "FinanceManager", "AuctionManager", "Customer")
def get_vehicle(vid, user_id, role, identity):
    v = _get_or_404(db.vehicles, vid, "vehicle")
    return success_object(_serialize_vehicle(v))


@app.route("/v1/vehicles/<vid>/list", methods=["POST"])
@require_roles("StoreManager")
def list_vehicle_for_retail(vid, user_id, role, identity):
    v = _get_or_404(db.vehicles, vid, "vehicle")
    if v["lifecycle_status"] != "RECON":
        raise_err(ERR_INVALID_STATE, f"vehicle must be in RECON, is {v['lifecycle_status']}")
    if v["hold_status"] != "NONE":
        raise_err(ERR_INVALID_STATE, f"vehicle hold_status must be NONE, is {v['hold_status']}")
    # Find the sourcing appraisal for initial price: latest ACTIVE with a final offer
    ap = _find_latest_appraisal_for_offer(vid)
    if ap is None or ap.get("final_offer_cents") is None:
        raise_err(ERR_INVALID_STATE, "vehicle has no active appraisal with a final offer")
    final_offer = int(ap["final_offer_cents"])
    price = compute_initial_list_price(final_offer)
    v["current_list_price_cents"] = price
    v["lifecycle_status"] = "RETAIL_LISTED"
    touch(v)
    # PricingEvent INITIAL_LISTING
    pe = mint_common(with_version=False)
    pe.update({
        "vehicle_id": vid,
        "trigger_kind": "INITIAL_LISTING",
        "old_price_cents": None,
        "new_price_cents": price,
        "days_in_inventory_at_event": _serialize_vehicle(v)["days_in_inventory"],
    })
    db.pricing_events[pe["id"]] = pe
    return success_object(_serialize_vehicle(v), status=200)


@app.route("/v1/vehicles/<vid>/pricing-events", methods=["POST"])
@require_roles("StoreManager")
def create_pricing_event(vid, user_id, role, identity):
    v = _get_or_404(db.vehicles, vid, "vehicle")
    if v["lifecycle_status"] != "RETAIL_LISTED":
        raise_err(ERR_INVALID_STATE, f"vehicle must be RETAIL_LISTED, is {v['lifecycle_status']}")
    if v["hold_status"] != "NONE":
        raise_err(ERR_INVALID_STATE, f"vehicle hold_status must be NONE, is {v['hold_status']}")
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["expected_vehicle_version"])
    evv = payload["expected_vehicle_version"]
    if not _is_int(evv):
        raise_err(ERR_VALIDATION, "expected_vehicle_version must be an integer")
    if evv != v["version"]:
        raise_err(ERR_STALE_VERSION, f"expected_vehicle_version {evv} != current version {v['version']}")
    days = _serialize_vehicle(v)["days_in_inventory"]
    old_price = int(v["current_list_price_cents"])
    new_price, tier_pct = compute_markdown(old_price, days)
    # Floor at final_offer
    ap = _find_latest_appraisal_for_offer(vid)
    floor_price = int(ap["final_offer_cents"]) if ap and ap.get("final_offer_cents") is not None else 0
    if new_price < floor_price:
        new_price = floor_price
    v["current_list_price_cents"] = new_price
    touch(v)
    pe = mint_common(with_version=False)
    pe.update({
        "vehicle_id": vid,
        "trigger_kind": "SCHEDULED_MARKDOWN",
        "old_price_cents": old_price,
        "new_price_cents": new_price,
        "days_in_inventory_at_event": days,
    })
    db.pricing_events[pe["id"]] = pe
    return success_object(_serialize_simple(pe), status=201)


@app.route("/v1/vehicles/<vid>/pricing-events", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "SalesAssociate")
def list_pricing_events(vid, user_id, role, identity):
    _get_or_404(db.vehicles, vid, "vehicle")
    items = [p for p in db.pricing_events.values() if p["vehicle_id"] == vid]
    return paginate(items)


@app.route("/v1/vehicles/<vid>/appraisals", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Appraiser", "SalesAssociate")
def list_vehicle_appraisals(vid, user_id, role, identity):
    _get_or_404(db.vehicles, vid, "vehicle")
    items = [_serialize_appraisal(a) for a in db.appraisals.values() if a["vehicle_id"] == vid]
    return paginate(items)


@app.route("/v1/vehicles/<vid>/inspections", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "ReconditioningInspector")
def list_vehicle_inspections(vid, user_id, role, identity):
    _get_or_404(db.vehicles, vid, "vehicle")
    items = [i for i in db.inspections.values() if i["vehicle_id"] == vid]
    return paginate(items)


@app.route("/v1/vehicles/<vid>/transfer-requests", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "SalesAssociate", "Customer")
def list_vehicle_transfers(vid, user_id, role, identity):
    _get_or_404(db.vehicles, vid, "vehicle")
    items = [_serialize_transfer(t) for t in db.transfer_requests.values() if t["vehicle_id"] == vid]
    return paginate(items)


@app.route("/v1/vehicles/<vid>/auction-lots", methods=["GET"])
@require_roles("PlatformAdmin", "AuctionManager", "StoreManager")
def list_vehicle_auction_lots(vid, user_id, role, identity):
    _get_or_404(db.vehicles, vid, "vehicle")
    items = [a for a in db.auction_lots.values() if a["vehicle_id"] == vid]
    return paginate(items)


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------


@app.route("/v1/appraisals", methods=["POST"])
@require_roles("Appraiser")
def create_appraisal(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["vehicle_id", "customer_id", "appraiser_id"])
    vehicle_id = payload["vehicle_id"]
    customer_id = payload["customer_id"]
    appraiser_id = payload["appraiser_id"]
    vehicle = _get_or_404(db.vehicles, vehicle_id, "vehicle")
    customer = _get_or_404(db.customers, customer_id, "customer")
    appraiser = _get_or_404(db.associates, appraiser_id, "associate")
    # The acting Appraiser role identity is the associate performing the appraisal.
    if appraiser_id != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "appraiser_id must equal the acting X-User-ID")
    if appraiser["role_kind"] != "APPRAISER" or appraiser["status"] != "ACTIVE":
        raise_err(ERR_VALIDATION, "appraiser must be an ACTIVE associate with role_kind APPRAISER")
    # Vehicle state
    if vehicle["lifecycle_status"] == "INTAKE":
        pass  # allowed
    elif vehicle["lifecycle_status"] == "APPRAISED":
        # Second appraisal only allowed when no non-terminal appraisal exists
        existing = _find_sourcing_appraisal(vehicle_id)
        if existing is not None:
            raise_err(ERR_CROSS_ENTITY_STATE, "vehicle already has a non-terminal appraisal")
    else:
        raise_err(ERR_INVALID_STATE, f"vehicle lifecycle_status must be INTAKE or APPRAISED, is {vehicle['lifecycle_status']}")
    # Compute provisional
    provisional = compute_provisional_offer(vehicle)
    ent = mint_common()
    ent.update({
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "appraiser_id": appraiser_id,
        "provisional_offer_cents": provisional,
        "final_offer_cents": None,
        "valid_from": None,
        "valid_until": None,
        "status": "PENDING_INSPECTION",
    })
    db.appraisals[ent["id"]] = ent
    # Vehicle INTAKE -> APPRAISED (or stays APPRAISED)
    if vehicle["lifecycle_status"] == "INTAKE":
        vehicle["lifecycle_status"] = "APPRAISED"
        touch(vehicle)
    return success_object(_serialize_appraisal(ent), status=201)


@app.route("/v1/appraisals", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Appraiser", "SalesAssociate")
def list_appraisals(user_id, role, identity):
    items = list(db.appraisals.values())
    cid = request.args.get("customer_id")
    aid = request.args.get("appraiser_id")
    st = request.args.get("status")
    if cid:
        items = [a for a in items if a["customer_id"] == cid]
    if aid:
        items = [a for a in items if a["appraiser_id"] == aid]
    if st:
        items = [a for a in items if a["status"] == st]
    items = [_serialize_appraisal(a) for a in items]
    return paginate(items)


@app.route("/v1/appraisals/<aid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Appraiser", "SalesAssociate", "Customer")
def get_appraisal(aid, user_id, role, identity):
    a = _get_or_404(db.appraisals, aid, "appraisal")
    return success_object(_serialize_appraisal(a))


@app.route("/v1/appraisals/<aid>/void", methods=["POST"])
@require_roles("Appraiser", "StoreManager")
def void_appraisal(aid, user_id, role, identity):
    ap = _get_or_404(db.appraisals, aid, "appraisal")
    if ap["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, f"appraisal must be ACTIVE, is {ap['status']}")
    if role == "Appraiser" and user_id != ap["appraiser_id"]:
        raise_err(ERR_UNAUTHORIZED_ROLE, "an Appraiser may void only their own offer")
    ap["status"] = "VOIDED"
    touch(ap)
    return success_object(_serialize_appraisal(ap), status=200)


# ---------------------------------------------------------------------------
# Inspections / line items
# ---------------------------------------------------------------------------


@app.route("/v1/vehicles/<vid>/inspections", methods=["POST"])
@require_roles("ReconditioningInspector")
def open_inspection(vid, user_id, role, identity):
    vehicle = _get_or_404(db.vehicles, vid, "vehicle")
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["inspector_id"])
    inspector_id = payload["inspector_id"]
    inspector = _get_or_404(db.associates, inspector_id, "associate")
    if inspector["role_kind"] != "INSPECTOR" or inspector["status"] != "ACTIVE":
        raise_err(ERR_VALIDATION, "inspector must be an ACTIVE associate with role_kind INSPECTOR")
    if inspector_id != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "inspector_id must equal the acting X-User-ID")
    if vehicle["lifecycle_status"] not in ("APPRAISED", "RETURNED"):
        raise_err(ERR_INVALID_STATE, f"vehicle lifecycle_status must be APPRAISED or RETURNED, is {vehicle['lifecycle_status']}")
    # For APPRAISED: standard path. For RETURNED: hold must be RETURN_REVIEW_HOLD.
    if vehicle["lifecycle_status"] == "RETURNED" and vehicle["hold_status"] != "RETURN_REVIEW_HOLD":
        raise_err(ERR_INVALID_STATE, "RETURNED vehicle must have hold_status RETURN_REVIEW_HOLD")
    # SoD
    sourcing = _find_sourcing_appraisal(vid)
    if sourcing is not None and sourcing["appraiser_id"] == inspector_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "inspector may not be the appraiser who sourced this vehicle")
    # Open inspection?
    if _has_open_inspection(vid):
        raise_err(ERR_INSPECTION_ALREADY_OPEN, "an OPEN inspection already exists for this vehicle")
    ent = mint_common()
    ent.update({
        "vehicle_id": vid,
        "inspector_id": inspector_id,
        "opened_at": _now_iso(),
        "estimated_repair_total_cents": 0,
        "disposition": "UNDECIDED",
        "status": "OPEN",
    })
    db.inspections[ent["id"]] = ent
    # Cascade
    if vehicle["lifecycle_status"] == "RETURNED":
        vehicle["hold_status"] = "NONE"
        vehicle["recon_cost_total_cents"] = 0
        vehicle["inventory_acquired_at"] = _now_iso()
        vehicle["lifecycle_status"] = "IN_INSPECTION"
    else:
        vehicle["lifecycle_status"] = "IN_INSPECTION"
        vehicle["recon_cost_total_cents"] = 0
    touch(vehicle)
    return success_object(_serialize_simple(ent), status=201)


@app.route("/v1/inspections", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager")
def list_inspections(user_id, role, identity):
    items = list(db.inspections.values())
    iid = request.args.get("inspector_id")
    st = request.args.get("status")
    if iid:
        items = [i for i in items if i["inspector_id"] == iid]
    if st:
        items = [i for i in items if i["status"] == st]
    return paginate(items)


@app.route("/v1/inspections/<iid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "ReconditioningInspector")
def get_inspection(iid, user_id, role, identity):
    ins = _get_or_404(db.inspections, iid, "inspection")
    return success_object(_serialize_simple(ins))


def _recompute_inspection_total(ins: dict):
    total = 0
    for li in db.line_items.values():
        if li["inspection_id"] == ins["id"] and li["line_status"] != "REJECTED":
            total += int(li["cost_cents"])
    ins["estimated_repair_total_cents"] = total


@app.route("/v1/inspections/<iid>/line-items", methods=["POST"])
@require_roles("ReconditioningInspector")
def add_line_item(iid, user_id, role, identity):
    ins = _get_or_404(db.inspections, iid, "inspection")
    if ins["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"inspection must be OPEN, is {ins['status']}")
    if ins["inspector_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the inspector who opened the inspection may add line items")
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["category", "cost_cents"])
    cat = payload["category"]
    _validate_enum(cat, ["MECHANICAL", "BODY", "COSMETIC", "SAFETY"], "category")
    cost = payload["cost_cents"]
    if not _is_int(cost) or cost <= 0:
        raise_err(ERR_VALIDATION, "cost_cents must be a positive integer")
    ent = mint_common(with_version=False)
    ent.update({
        "inspection_id": iid,
        "category": cat,
        "cost_cents": cost,
        "line_status": "PROPOSED",
    })
    db.line_items[ent["id"]] = ent
    _recompute_inspection_total(ins)
    touch(ins)
    return success_object(_serialize_simple(ent), status=201)


@app.route("/v1/inspections/<iid>/line-items", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "ReconditioningInspector")
def list_line_items(iid, user_id, role, identity):
    _get_or_404(db.inspections, iid, "inspection")
    items = [li for li in db.line_items.values() if li["inspection_id"] == iid]
    return paginate(items)


@app.route("/v1/inspections/<iid>/line-items/<lid>/approve", methods=["POST"])
@require_roles("ReconditioningInspector")
def approve_line_item(iid, lid, user_id, role, identity):
    ins = _get_or_404(db.inspections, iid, "inspection")
    li = db.line_items.get(lid)
    if li is None or li["inspection_id"] != iid:
        raise_err(ERR_NOT_FOUND, f"line item {lid} not found on inspection {iid}")
    if ins["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"inspection must be OPEN, is {ins['status']}")
    if li["line_status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, f"line item must be PROPOSED, is {li['line_status']}")
    li["line_status"] = "APPROVED"
    _recompute_inspection_total(ins)
    touch(ins)
    return success_object(_serialize_simple(li), status=200)


@app.route("/v1/inspections/<iid>/line-items/<lid>/reject", methods=["POST"])
@require_roles("ReconditioningInspector")
def reject_line_item(iid, lid, user_id, role, identity):
    ins = _get_or_404(db.inspections, iid, "inspection")
    li = db.line_items.get(lid)
    if li is None or li["inspection_id"] != iid:
        raise_err(ERR_NOT_FOUND, f"line item {lid} not found on inspection {iid}")
    if ins["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"inspection must be OPEN, is {ins['status']}")
    if li["line_status"] != "PROPOSED":
        raise_err(ERR_INVALID_STATE, f"line item must be PROPOSED, is {li['line_status']}")
    li["line_status"] = "REJECTED"
    _recompute_inspection_total(ins)
    touch(ins)
    return success_object(_serialize_simple(li), status=200)


@app.route("/v1/inspections/<iid>/complete", methods=["POST"])
@require_roles("ReconditioningInspector")
def complete_inspection(iid, user_id, role, identity):
    ins = _get_or_404(db.inspections, iid, "inspection")
    if ins["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"inspection must be OPEN, is {ins['status']}")
    if ins["inspector_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the inspector who opened the inspection may complete it")
    # All line items resolved
    for li in db.line_items.values():
        if li["inspection_id"] == iid and li["line_status"] == "PROPOSED":
            raise_err(ERR_LINE_ITEMS_UNRESOLVED, "inspection has unresolved PROPOSED line items")
    vehicle = _get_or_404(db.vehicles, ins["vehicle_id"], "vehicle")
    store = _get_or_404(db.stores, vehicle["current_store_id"], "store")
    _recompute_inspection_total(ins)
    disposition, grade, threshold, provisional = compute_disposition_and_grade(vehicle, ins, store)
    ins["disposition"] = disposition
    ins["status"] = "COMPLETED"
    touch(ins)
    est = int(ins["estimated_repair_total_cents"])
    # Cascade to vehicle
    if disposition == "RETAIL":
        vehicle["condition_grade"] = grade
        vehicle["recon_cost_total_cents"] = est
        vehicle["lifecycle_status"] = "RECON"
    else:
        vehicle["condition_grade"] = "WHOLESALE_ONLY"
        vehicle["recon_cost_total_cents"] = est
        vehicle["lifecycle_status"] = "WHOLESALE_PENDING"
    touch(vehicle)
    # Activate sourcing appraisal (the newest non-terminal on the vehicle)
    sourcing = _find_sourcing_appraisal(vehicle["id"])
    if sourcing is not None and sourcing["status"] == "PENDING_INSPECTION":
        final_offer = compute_final_offer(vehicle, est)
        sourcing["final_offer_cents"] = final_offer
        sourcing["status"] = "ACTIVE"
        sourcing["valid_from"] = _now_iso()
        vu = CLOCK.now() + timedelta(days=7)
        sourcing["valid_until"] = _format_iso(vu)
        touch(sourcing)
    return success_object(_serialize_simple(ins), status=200)


@app.route("/v1/inspections/<iid>/cancel", methods=["POST"])
@require_roles("StoreManager")
def cancel_inspection(iid, user_id, role, identity):
    ins = _get_or_404(db.inspections, iid, "inspection")
    if ins["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"inspection must be OPEN, is {ins['status']}")
    vehicle = _get_or_404(db.vehicles, ins["vehicle_id"], "vehicle")
    if vehicle["lifecycle_status"] != "IN_INSPECTION":
        raise_err(ERR_INVALID_STATE, f"vehicle must be IN_INSPECTION, is {vehicle['lifecycle_status']}")
    ins["status"] = "CANCELLED"
    touch(ins)
    vehicle["lifecycle_status"] = "APPRAISED"
    touch(vehicle)
    return success_object(_serialize_simple(ins), status=200)


# ---------------------------------------------------------------------------
# Transfer requests
# ---------------------------------------------------------------------------


@app.route("/v1/transfer-requests", methods=["POST"])
@require_roles("Customer")
def create_transfer_request(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["vehicle_id", "customer_id", "to_store_id", "expected_vehicle_version"])
    vehicle_id = payload["vehicle_id"]
    customer_id = payload["customer_id"]
    to_store_id = payload["to_store_id"]
    expedited = payload.get("expedited", False)
    if not _is_bool(expedited):
        raise_err(ERR_VALIDATION, "expedited must be a boolean")
    supersedes_request_id = payload.get("supersedes_request_id")
    expected_vehicle_version = payload["expected_vehicle_version"]
    if not _is_int(expected_vehicle_version):
        raise_err(ERR_VALIDATION, "expected_vehicle_version must be an integer")
    vehicle = _get_or_404(db.vehicles, vehicle_id, "vehicle")
    customer = _get_or_404(db.customers, customer_id, "customer")
    to_store = _get_or_404(db.stores, to_store_id, "store")
    if customer_id != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "customer_id must equal acting X-User-ID")
    if to_store_id == vehicle["current_store_id"]:
        raise_err(ERR_VALIDATION, "to_store must differ from vehicle's current store")
    if supersedes_request_id is not None:
        prior = _get_or_404(db.transfer_requests, supersedes_request_id, "transfer request")
        if prior["vehicle_id"] != vehicle_id:
            raise_err(ERR_VALIDATION, "supersedes_request_id must reference a request for the same vehicle")
        if prior["status"] != "CANCELLED":
            raise_err(ERR_VALIDATION, "superseded request must be CANCELLED")
    if vehicle["lifecycle_status"] != "RETAIL_LISTED":
        raise_err(ERR_VEHICLE_NOT_LISTED, f"vehicle is not RETAIL_LISTED (is {vehicle['lifecycle_status']})")
    if vehicle["hold_status"] != "NONE":
        raise_err(ERR_VEHICLE_ALREADY_HELD, "vehicle is already held")
    if expected_vehicle_version != vehicle["version"]:
        raise_err(ERR_STALE_VERSION, f"expected_vehicle_version {expected_vehicle_version} != current version {vehicle['version']}")
    from_store = _get_or_404(db.stores, vehicle["current_store_id"], "store")
    fee = compute_shipping_fee(from_store["region"], to_store["region"], expedited, vehicle["model_year"])
    ent = mint_common()
    ent.update({
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "from_store_id": vehicle["current_store_id"],
        "to_store_id": to_store_id,
        "expedited": expedited,
        "shipping_fee_cents": fee,
        "hold_expires_at": None,
        "supersedes_request_id": supersedes_request_id,
        "status": "REQUESTED",
    })
    db.transfer_requests[ent["id"]] = ent
    vehicle["hold_status"] = "TRANSFER_HOLD"
    touch(vehicle)
    return success_object(_serialize_transfer(ent), status=201)


@app.route("/v1/transfer-requests", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "SalesAssociate", "Customer")
def list_transfer_requests(user_id, role, identity):
    items = list(db.transfer_requests.values())
    cid = request.args.get("customer_id")
    fs = request.args.get("from_store_id")
    ts = request.args.get("to_store_id")
    sup = request.args.get("supersedes_request_id")
    st = request.args.get("status")
    if cid:
        items = [t for t in items if t["customer_id"] == cid]
    if fs:
        items = [t for t in items if t["from_store_id"] == fs]
    if ts:
        items = [t for t in items if t["to_store_id"] == ts]
    if sup:
        items = [t for t in items if t.get("supersedes_request_id") == sup]
    if st:
        items = [t for t in items if t["status"] == st]
    items = [_serialize_transfer(t) for t in items]
    return paginate(items)


@app.route("/v1/transfer-requests/<tid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "SalesAssociate", "Customer")
def get_transfer_request(tid, user_id, role, identity):
    tr = _get_or_404(db.transfer_requests, tid, "transfer request")
    return success_object(_serialize_transfer(tr))


@app.route("/v1/transfer-requests/<tid>/pay", methods=["POST"])
@require_roles("Customer")
def pay_transfer(tid, user_id, role, identity):
    tr = _get_or_404(db.transfer_requests, tid, "transfer request")
    if tr["customer_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the requesting customer may pay")
    if tr["status"] != "REQUESTED":
        raise_err(ERR_INVALID_STATE, f"transfer must be REQUESTED, is {tr['status']}")
    vehicle = _get_or_404(db.vehicles, tr["vehicle_id"], "vehicle")
    if vehicle["lifecycle_status"] != "RETAIL_LISTED":
        raise_err(ERR_VEHICLE_NO_LONGER_AVAILABLE, "vehicle is no longer RETAIL_LISTED")
    tr["status"] = "FEE_PAID"
    touch(tr)
    post_ledger_entry("TRANSFER_FEE", int(tr["shipping_fee_cents"]), "TransferRequest", tr["id"], tr["to_store_id"])
    return success_object(_serialize_transfer(tr), status=200)


@app.route("/v1/transfer-requests/<tid>/ship", methods=["POST"])
@require_roles("StoreManager")
def ship_transfer(tid, user_id, role, identity):
    tr = _get_or_404(db.transfer_requests, tid, "transfer request")
    if tr["status"] != "FEE_PAID":
        raise_err(ERR_INVALID_STATE, f"transfer must be FEE_PAID, is {tr['status']}")
    if identity is None or identity.get("store_id") != tr["from_store_id"]:
        raise_err(ERR_UNAUTHORIZED_ROLE, "shipping must be done by a StoreManager of the origin store")
    tr["status"] = "IN_TRANSIT"
    touch(tr)
    return success_object(_serialize_transfer(tr), status=200)


@app.route("/v1/transfer-requests/<tid>/deliver", methods=["POST"])
@require_roles("StoreManager")
def deliver_transfer(tid, user_id, role, identity):
    tr = _get_or_404(db.transfer_requests, tid, "transfer request")
    if tr["status"] != "IN_TRANSIT":
        raise_err(ERR_INVALID_STATE, f"transfer must be IN_TRANSIT, is {tr['status']}")
    if identity is None or identity.get("store_id") != tr["to_store_id"]:
        raise_err(ERR_UNAUTHORIZED_ROLE, "delivery must be confirmed by a StoreManager of the destination store")
    vehicle = _get_or_404(db.vehicles, tr["vehicle_id"], "vehicle")
    to_store = _get_or_404(db.stores, tr["to_store_id"], "store")
    vehicle["current_store_id"] = tr["to_store_id"]
    touch(vehicle)
    hold_expires = CLOCK.now() + timedelta(days=int(to_store["transfer_hold_days"]))
    tr["hold_expires_at"] = _format_iso(hold_expires)
    tr["status"] = "DELIVERED"
    touch(tr)
    return success_object(_serialize_transfer(tr), status=200)


@app.route("/v1/transfer-requests/<tid>/cancel", methods=["POST"])
@require_roles("Customer")
def cancel_transfer(tid, user_id, role, identity):
    tr = _get_or_404(db.transfer_requests, tid, "transfer request")
    if tr["customer_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the requesting customer may cancel")
    if tr["status"] not in ("REQUESTED", "FEE_PAID", "IN_TRANSIT"):
        raise_err(ERR_INVALID_STATE, f"transfer cannot be cancelled from {tr['status']}")
    vehicle = _get_or_404(db.vehicles, tr["vehicle_id"], "vehicle")
    prior_status = tr["status"]
    tr["status"] = "CANCELLED"
    touch(tr)
    if vehicle.get("hold_status") == "TRANSFER_HOLD":
        vehicle["hold_status"] = "NONE"
        touch(vehicle)
    if prior_status == "FEE_PAID":
        post_ledger_entry("TRANSFER_FEE_REFUND", -int(tr["shipping_fee_cents"]), "TransferRequest", tr["id"], tr["to_store_id"])
    elif prior_status == "IN_TRANSIT":
        half = _round_half_up_int(Decimal(int(tr["shipping_fee_cents"])) / Decimal(2))
        post_ledger_entry("TRANSFER_FEE_REFUND", -half, "TransferRequest", tr["id"], tr["to_store_id"])
    return success_object(_serialize_transfer(tr), status=200)


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------


@app.route("/v1/sales", methods=["POST"])
@require_roles("SalesAssociate")
def create_sale(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["vehicle_id", "customer_id", "associate_id"])
    vehicle_id = payload["vehicle_id"]
    customer_id = payload["customer_id"]
    associate_id = payload["associate_id"]
    trade_in_appraisal_id = payload.get("trade_in_appraisal_id")
    vehicle = _get_or_404(db.vehicles, vehicle_id, "vehicle")
    customer = _get_or_404(db.customers, customer_id, "customer")
    associate = _get_or_404(db.associates, associate_id, "associate")
    if associate_id != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "associate_id must equal acting X-User-ID")
    if associate["role_kind"] != "SALES" or associate["status"] != "ACTIVE":
        raise_err(ERR_VALIDATION, "associate must be an ACTIVE SALES associate")
    # State check — PRD §3.5: a sale against a vehicle not RETAIL_LISTED is
    # rejected with ERR_CROSS_ENTITY_STATE.
    if vehicle["lifecycle_status"] != "RETAIL_LISTED":
        raise_err(ERR_CROSS_ENTITY_STATE, f"vehicle is not RETAIL_LISTED (is {vehicle['lifecycle_status']})")
    if vehicle["hold_status"] != "NONE":
        # Allow if the hold belongs to this buyer's DELIVERED transfer request
        tr = _find_active_transfer_for_vehicle_and_customer(vehicle_id, customer_id)
        if tr is None:
            raise_err(ERR_CROSS_ENTITY_STATE, "vehicle is held for another customer's transfer")
        # else: allowed — completion will fulfil the transfer
    # Trade-in appraisal checks
    trade_in_credit = 0
    if trade_in_appraisal_id is not None:
        ap = _get_or_404(db.appraisals, trade_in_appraisal_id, "appraisal")
        _lazy_transition_appraisal(ap)
        if ap["status"] == "EXPIRED":
            raise_err(ERR_APPRAISAL_EXPIRED, "trade-in appraisal has expired")
        if ap["status"] != "ACTIVE":
            raise_err(ERR_APPRAISAL_NOT_ACTIVE, f"trade-in appraisal is {ap['status']}, not ACTIVE")
        if ap["customer_id"] != customer_id:
            raise_err(ERR_APPRAISAL_CUSTOMER_MISMATCH, "trade-in appraisal belongs to a different customer")
        trade_in_credit = int(ap["final_offer_cents"] or 0)
    sale_price = int(vehicle["current_list_price_cents"])
    amount_due = sale_price - trade_in_credit
    if amount_due < 0:
        amount_due = 0
    ent = mint_common()
    ent.update({
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "associate_id": associate_id,
        "store_id": vehicle["current_store_id"],
        "trade_in_appraisal_id": trade_in_appraisal_id,
        "sale_price_cents": sale_price,
        "trade_in_credit_cents": trade_in_credit,
        "amount_due_cents": amount_due,
        "completed_at": None,
        "status": "PENDING_FINANCE",
    })
    db.sales[ent["id"]] = ent
    return success_object(_serialize_simple(ent), status=201)


@app.route("/v1/sales", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "SalesAssociate", "FinanceManager")
def list_sales(user_id, role, identity):
    items = list(db.sales.values())
    vid = request.args.get("vehicle_id")
    cid = request.args.get("customer_id")
    aid = request.args.get("associate_id")
    sid = request.args.get("store_id")
    tid = request.args.get("trade_in_appraisal_id")
    st = request.args.get("status")
    if vid:
        items = [s for s in items if s["vehicle_id"] == vid]
    if cid:
        items = [s for s in items if s["customer_id"] == cid]
    if aid:
        items = [s for s in items if s["associate_id"] == aid]
    if sid:
        items = [s for s in items if s["store_id"] == sid]
    if tid:
        items = [s for s in items if s.get("trade_in_appraisal_id") == tid]
    if st:
        items = [s for s in items if s["status"] == st]
    return paginate(items)


@app.route("/v1/sales/<sid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "SalesAssociate", "FinanceManager", "Customer")
def get_sale(sid, user_id, role, identity):
    s = _get_or_404(db.sales, sid, "sale")
    if role == "Customer" and s["customer_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "customers may read only their own sale")
    return success_object(_serialize_simple(s))


@app.route("/v1/sales/<sid>/complete", methods=["POST"])
@require_roles("SalesAssociate")
def complete_sale(sid, user_id, role, identity):
    sale = _get_or_404(db.sales, sid, "sale")
    if sale["status"] != "PENDING_FINANCE":
        raise_err(ERR_INVALID_STATE, f"sale must be PENDING_FINANCE, is {sale['status']}")
    if sale["associate_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the selling associate may complete the sale")
    vehicle = _get_or_404(db.vehicles, sale["vehicle_id"], "vehicle")
    if vehicle["lifecycle_status"] != "RETAIL_LISTED":
        raise_err(ERR_INVALID_STATE, f"vehicle is not RETAIL_LISTED (is {vehicle['lifecycle_status']})")
    # Financing check
    fin_apps = [fa for fa in db.financing_applications.values() if fa["sale_id"] == sale["id"]]
    accepted_app = None
    for fa in fin_apps:
        _lazy_transition_financing_app(fa)
        if fa["status"] == "ACCEPTED":
            accepted_app = fa
    if fin_apps and accepted_app is None:
        raise_err(ERR_FINANCING_NOT_ACCEPTED, "sale has a financing application that is not ACCEPTED")
    # Hold handling
    fulfilling_transfer = None
    if vehicle["hold_status"] != "NONE":
        # Find this buyer's DELIVERED transfer request on this vehicle
        tr = _find_active_transfer_for_vehicle_and_customer(vehicle["id"], sale["customer_id"])
        if tr is None:
            raise_err(ERR_VEHICLE_ALREADY_HELD, "vehicle is held for another customer")
        _lazy_transition_transfer(tr)
        if tr["status"] == "HOLD_EXPIRED":
            raise_err(ERR_WINDOW_CLOSED, "transfer hold has expired")
        if tr["status"] != "DELIVERED":
            raise_err(ERR_INVALID_STATE, f"transfer request is {tr['status']}, not DELIVERED")
        he = _parse_iso(tr["hold_expires_at"])
        if CLOCK.now() >= he:
            _transition_transfer_hold_expired(tr)
            raise_err(ERR_WINDOW_CLOSED, "transfer hold has expired")
        fulfilling_transfer = tr
    # Recompute sale price from current list price
    sale["sale_price_cents"] = int(vehicle["current_list_price_cents"])
    sale["amount_due_cents"] = max(0, sale["sale_price_cents"] - int(sale.get("trade_in_credit_cents", 0)))
    sale["completed_at"] = _now_iso()
    sale["status"] = "COMPLETED"
    touch(sale)
    # Vehicle SOLD
    vehicle["lifecycle_status"] = "SOLD"
    vehicle["hold_status"] = "NONE"
    touch(vehicle)
    # Fulfil transfer if applicable
    if fulfilling_transfer is not None:
        fulfilling_transfer["status"] = "FULFILLED"
        touch(fulfilling_transfer)
    # Ledger entries
    post_ledger_entry("SALE_REVENUE", int(sale["sale_price_cents"]), "Sale", sale["id"], sale["store_id"])
    if sale.get("trade_in_appraisal_id"):
        ap = db.appraisals.get(sale["trade_in_appraisal_id"])
        if ap is not None:
            post_ledger_entry("TRADE_IN_PAYABLE", -int(sale["trade_in_credit_cents"]), "Sale", sale["id"], sale["store_id"])
            ap["status"] = "REDEEMED"
            touch(ap)
            # Trade-in vehicle enters INTAKE at the sale store
            tv = db.vehicles.get(ap["vehicle_id"])
            if tv is not None:
                tv["lifecycle_status"] = "INTAKE"
                tv["hold_status"] = "NONE"
                tv["current_store_id"] = sale["store_id"]
                tv["inventory_acquired_at"] = _now_iso()
                tv["current_list_price_cents"] = None
                tv["recon_cost_total_cents"] = 0
                tv["condition_grade"] = "UNGRADED"
                touch(tv)
    # Commission accrual
    assoc = db.associates.get(sale["associate_id"])
    if assoc is not None:
        post_ledger_entry("COMMISSION_ACCRUAL", int(assoc["flat_commission_cents"]), "Sale", sale["id"], sale["store_id"])
        maybe_accrue_volume_bonus(assoc, sale)
    return success_object(_serialize_simple(sale), status=200)


@app.route("/v1/sales/<sid>/cancel", methods=["POST"])
@require_roles("SalesAssociate")
def cancel_sale(sid, user_id, role, identity):
    sale = _get_or_404(db.sales, sid, "sale")
    if sale["status"] != "PENDING_FINANCE":
        raise_err(ERR_INVALID_STATE, f"sale must be PENDING_FINANCE, is {sale['status']}")
    if sale["associate_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the selling associate may cancel the sale")
    sale["status"] = "CANCELLED"
    touch(sale)
    for fa in db.financing_applications.values():
        if fa["sale_id"] == sale["id"] and fa["status"] in ("SUBMITTED", "OFFERS_PRESENTED"):
            fa["status"] = "WITHDRAWN"
            touch(fa)
            for of in db.lender_offers.values():
                if of["application_id"] == fa["id"] and of["offer_status"] == "PRESENTED":
                    of["offer_status"] = "SUPERSEDED"
    return success_object(_serialize_simple(sale), status=200)


# ---------------------------------------------------------------------------
# Financing
# ---------------------------------------------------------------------------


@app.route("/v1/sales/<sid>/financing-applications", methods=["POST"])
@require_roles("FinanceManager")
def submit_financing(sid, user_id, role, identity):
    sale = _get_or_404(db.sales, sid, "sale")
    if sale["status"] != "PENDING_FINANCE":
        raise_err(ERR_INVALID_STATE, f"sale must be PENDING_FINANCE, is {sale['status']}")
    # SoD: finance manager must not be the selling associate
    if sale["associate_id"] == user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "finance manager may not be the selling associate on the same sale")
    # Existing app?
    existing = [fa for fa in db.financing_applications.values() if fa["sale_id"] == sid and fa["status"] in ("SUBMITTED", "OFFERS_PRESENTED")]
    if existing:
        raise_err(ERR_INVALID_STATE, "sale already has an active financing application")
    customer = _get_or_404(db.customers, sale["customer_id"], "customer")
    requested = int(sale["amount_due_cents"])
    tier = compute_approval_tier(customer["credit_score"], requested, customer["stated_annual_income_cents"])
    ent = mint_common()
    ent.update({
        "sale_id": sid,
        "customer_id": sale["customer_id"],
        "requested_amount_cents": requested,
        "approval_tier": tier,
        "status": "SUBMITTED",
    })
    db.financing_applications[ent["id"]] = ent
    if tier != "DECLINED":
        ent["status"] = "OFFERS_PRESENTED"
        for lender_code in ("LENDER_A", "LENDER_B", "LENDER_C"):
            of = mint_common(with_version=False)
            of.update({
                "application_id": ent["id"],
                "lender_code": lender_code,
                "apr_bps": LENDER_APR_BPS[lender_code][tier],
                "max_amount_cents": requested,
                "offer_status": "PRESENTED",
            })
            db.lender_offers[of["id"]] = of
    return success_object(_serialize_financing_app(ent), status=201)


@app.route("/v1/sales/<sid>/financing-applications", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "FinanceManager", "Customer")
def list_sale_financing(sid, user_id, role, identity):
    _get_or_404(db.sales, sid, "sale")
    items = [_serialize_financing_app(fa) for fa in db.financing_applications.values() if fa["sale_id"] == sid]
    return paginate(items)


@app.route("/v1/financing-applications", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "FinanceManager")
def list_financing(user_id, role, identity):
    items = list(db.financing_applications.values())
    cid = request.args.get("customer_id")
    st = request.args.get("status")
    if cid:
        items = [f for f in items if f["customer_id"] == cid]
    if st:
        items = [f for f in items if f["status"] == st]
    items = [_serialize_financing_app(f) for f in items]
    return paginate(items)


@app.route("/v1/financing-applications/<fid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "FinanceManager", "Customer")
def get_financing(fid, user_id, role, identity):
    fa = _get_or_404(db.financing_applications, fid, "financing application")
    return success_object(_serialize_financing_app(fa))


@app.route("/v1/financing-applications/<fid>/offers", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "FinanceManager", "Customer")
def list_financing_offers(fid, user_id, role, identity):
    _get_or_404(db.financing_applications, fid, "financing application")
    items = [o for o in db.lender_offers.values() if o["application_id"] == fid]
    return paginate(items)


@app.route("/v1/financing-applications/<fid>/accept", methods=["POST"])
@require_roles("Customer")
def accept_financing(fid, user_id, role, identity):
    fa = _get_or_404(db.financing_applications, fid, "financing application")
    if fa["customer_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the application owner may accept")
    _lazy_transition_financing_app(fa)
    if fa["approval_tier"] == "DECLINED":
        raise_err(ERR_FINANCING_DECLINED, "application is DECLINED")
    if fa["status"] != "OFFERS_PRESENTED":
        raise_err(ERR_INVALID_STATE, f"application must be OFFERS_PRESENTED, is {fa['status']}")
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["lender_code"])
    lender_code = payload["lender_code"]
    _validate_enum(lender_code, ["LENDER_A", "LENDER_B", "LENDER_C"], "lender_code")
    chosen = None
    for of in db.lender_offers.values():
        if of["application_id"] == fid and of["lender_code"] == lender_code and of["offer_status"] == "PRESENTED":
            chosen = of
            break
    if chosen is None:
        raise_err(ERR_OFFER_NOT_PRESENTED, f"no PRESENTED offer for lender_code {lender_code}")
    chosen["offer_status"] = "ACCEPTED"
    for of in db.lender_offers.values():
        if of["application_id"] == fid and of["id"] != chosen["id"] and of["offer_status"] == "PRESENTED":
            of["offer_status"] = "SUPERSEDED"
    fa["status"] = "ACCEPTED"
    touch(fa)
    return success_object(_serialize_financing_app(fa), status=200)


@app.route("/v1/financing-applications/<fid>/withdraw", methods=["POST"])
@require_roles("Customer")
def withdraw_financing(fid, user_id, role, identity):
    fa = _get_or_404(db.financing_applications, fid, "financing application")
    if fa["customer_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the application owner may withdraw")
    _lazy_transition_financing_app(fa)
    if fa["status"] not in ("SUBMITTED", "OFFERS_PRESENTED"):
        raise_err(ERR_INVALID_STATE, f"application must be SUBMITTED or OFFERS_PRESENTED, is {fa['status']}")
    fa["status"] = "WITHDRAWN"
    touch(fa)
    for of in db.lender_offers.values():
        if of["application_id"] == fid and of["offer_status"] == "PRESENTED":
            of["offer_status"] = "SUPERSEDED"
    return success_object(_serialize_financing_app(fa), status=200)


# ---------------------------------------------------------------------------
# Returns
# ---------------------------------------------------------------------------

RETURN_WINDOW_DAYS = 7
RETURN_MILEAGE_CAP = 400
PER_MILE_CENTS = 50


@app.route("/v1/returns", methods=["POST"])
@require_roles("Customer")
def open_return(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["sale_id", "reason_code", "odometer_at_return"])
    sale_id = payload["sale_id"]
    sale = _get_or_404(db.sales, sale_id, "sale")
    if sale["customer_id"] != user_id:
        raise_err(ERR_UNAUTHORIZED_ROLE, "only the buyer may open a return")
    if sale["status"] != "COMPLETED":
        raise_err(ERR_INVALID_STATE, f"sale must be COMPLETED, is {sale['status']}")
    reason = payload["reason_code"]
    _validate_enum(reason, ["CHANGED_MIND", "MECHANICAL_DEFECT", "MISREPRESENTATION"], "reason_code")
    odo = payload["odometer_at_return"]
    if not _is_int(odo) or odo < 0:
        raise_err(ERR_VALIDATION, "odometer_at_return must be a non-negative integer")
    ent = mint_common()
    ent.update({
        "sale_id": sale_id,
        "reason_code": reason,
        "opened_at": _now_iso(),
        "odometer_at_return": odo,
        "refund_total_cents": None,
        "status": "OPEN",
    })
    db.return_requests[ent["id"]] = ent
    return success_object(_serialize_simple(ent), status=201)


@app.route("/v1/returns", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Customer")
def list_returns(user_id, role, identity):
    items = list(db.return_requests.values())
    sid = request.args.get("sale_id")
    st = request.args.get("status")
    if sid:
        items = [r for r in items if r["sale_id"] == sid]
    if st:
        items = [r for r in items if r["status"] == st]
    return paginate(items)


@app.route("/v1/returns/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "StoreManager", "Customer")
def get_return(rid, user_id, role, identity):
    r = _get_or_404(db.return_requests, rid, "return request")
    return success_object(_serialize_simple(r))


@app.route("/v1/returns/<rid>/approve", methods=["POST"])
@require_roles("StoreManager")
def approve_return(rid, user_id, role, identity):
    r = _get_or_404(db.return_requests, rid, "return request")
    if r["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"return must be OPEN, is {r['status']}")
    sale = _get_or_404(db.sales, r["sale_id"], "sale")
    if sale["status"] != "COMPLETED":
        raise_err(ERR_INVALID_STATE, f"sale must be COMPLETED, is {sale['status']}")
    opened = _parse_iso(r["opened_at"])
    completed = _parse_iso(sale["completed_at"])
    if opened > completed + timedelta(days=RETURN_WINDOW_DAYS):
        raise_err(ERR_RETURN_WINDOW_CLOSED, "return window has closed")
    r["status"] = "APPROVED"
    touch(r)
    return success_object(_serialize_simple(r), status=200)


@app.route("/v1/returns/<rid>/reject", methods=["POST"])
@require_roles("StoreManager")
def reject_return(rid, user_id, role, identity):
    r = _get_or_404(db.return_requests, rid, "return request")
    if r["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, f"return must be OPEN, is {r['status']}")
    r["status"] = "REJECTED"
    touch(r)
    return success_object(_serialize_simple(r), status=200)


@app.route("/v1/returns/<rid>/settle", methods=["POST"])
@require_roles("StoreManager")
def settle_return(rid, user_id, role, identity):
    r = _get_or_404(db.return_requests, rid, "return request")
    if r["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, f"return must be APPROVED, is {r['status']}")
    sale = _get_or_404(db.sales, r["sale_id"], "sale")
    if identity is None or identity.get("store_id") != sale["store_id"]:
        raise_err(ERR_UNAUTHORIZED_ROLE, "settlement must be performed by a StoreManager of the sale's store")
    vehicle = _get_or_404(db.vehicles, sale["vehicle_id"], "vehicle")
    # Waterfall
    gross = int(sale["amount_due_cents"])
    mileage_excess = max(0, int(r["odometer_at_return"]) - int(vehicle["odometer_miles"]) - RETURN_MILEAGE_CAP)
    mileage_deduction = mileage_excess * PER_MILE_CENTS
    refund_total = max(0, gross - mileage_deduction)
    # Bucket A: LENDER_REVERSAL (if financed and accepted)
    accepted_offer = None
    accepted_app = None
    for fa in db.financing_applications.values():
        if fa["sale_id"] == sale["id"] and fa["status"] == "ACCEPTED":
            accepted_app = fa
            break
    if accepted_app is not None:
        for of in db.lender_offers.values():
            if of["application_id"] == accepted_app["id"] and of["offer_status"] == "ACCEPTED":
                accepted_offer = of
                break
    remainder = refund_total
    if accepted_app is not None and accepted_offer is not None:
        principal = int(accepted_app["requested_amount_cents"])
        to_lender = min(remainder, principal)
        if to_lender > 0:
            post_ledger_entry("LENDER_REVERSAL", -to_lender, "ReturnRequest", r["id"], sale["store_id"])
            remainder -= to_lender
    # Bucket B: REFUND_PAYABLE
    if remainder > 0:
        post_ledger_entry("REFUND_PAYABLE", -remainder, "ReturnRequest", r["id"], sale["store_id"])
    # Bucket C: COMMISSION_CLAWBACK (unconditional)
    assoc = db.associates.get(sale["associate_id"])
    if assoc is not None:
        post_ledger_entry("COMMISSION_CLAWBACK", -int(assoc["flat_commission_cents"]), "ReturnRequest", r["id"], sale["store_id"])
    r["refund_total_cents"] = refund_total
    r["status"] = "SETTLED"
    touch(r)
    # Sale -> RETURNED
    sale["status"] = "RETURNED"
    touch(sale)
    # Vehicle SOLD -> RETURNED with RETURN_REVIEW_HOLD
    vehicle["lifecycle_status"] = "RETURNED"
    vehicle["hold_status"] = "RETURN_REVIEW_HOLD"
    touch(vehicle)
    # Trade-in appraisal reactivation
    if sale.get("trade_in_appraisal_id"):
        ap = db.appraisals.get(sale["trade_in_appraisal_id"])
        if ap is not None and ap["status"] == "REDEEMED":
            vu = _parse_iso(ap["valid_until"])
            tv = db.vehicles.get(ap["vehicle_id"])
            if CLOCK.now() < vu:
                ap["status"] = "ACTIVE"
                touch(ap)
                # Unwind re-acquisition: trade-in vehicle returns to customer (removed from inventory)
                if tv is not None and tv["lifecycle_status"] == "INTAKE":
                    tv["lifecycle_status"] = "DISPOSED"
                    tv["hold_status"] = "NONE"
                    touch(tv)
            else:
                ap["status"] = "EXPIRED"
                touch(ap)
    return success_object(_serialize_simple(r), status=200)


# ---------------------------------------------------------------------------
# Auction lots
# ---------------------------------------------------------------------------


@app.route("/v1/auction-lots", methods=["POST"])
@require_roles("AuctionManager")
def create_auction_lot(user_id, role, identity):
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["vehicle_id"])
    vehicle_id = payload["vehicle_id"]
    vehicle = _get_or_404(db.vehicles, vehicle_id, "vehicle")
    if vehicle["lifecycle_status"] != "WHOLESALE_PENDING":
        raise_err(ERR_INVALID_STATE, f"vehicle must be WHOLESALE_PENDING, is {vehicle['lifecycle_status']}")
    # No LISTED lot exists for the vehicle
    for lot in db.auction_lots.values():
        if lot["vehicle_id"] == vehicle_id and lot["status"] == "LISTED":
            raise_err(ERR_INVALID_STATE, "vehicle already has a LISTED auction lot")
    # Find prior lots
    prior_lots = [l for l in db.auction_lots.values() if l["vehicle_id"] == vehicle_id]
    prior_lots.sort(key=lambda l: l["created_at"])
    prior = prior_lots[-1] if prior_lots else None
    if prior is None:
        round_num = 1
        reserve = compute_reserve_standard(vehicle)
    else:
        if prior["status"] != "UNSOLD":
            raise_err(ERR_INVALID_STATE, f"prior lot must be UNSOLD to relist, is {prior['status']}")
        if int(prior["auction_round"]) >= 3:
            raise_err(ERR_AUCTION_ROUNDS_EXHAUSTED, "auction rounds exhausted (max 3)")
        round_num = int(prior["auction_round"]) + 1
        reserve = compute_reserve_relist(int(prior["reserve_price_cents"]))
    ent = mint_common()
    ent.update({
        "vehicle_id": vehicle_id,
        "reserve_price_cents": reserve,
        "hammer_price_cents": None,
        "auction_round": round_num,
        "status": "LISTED",
    })
    db.auction_lots[ent["id"]] = ent
    vehicle["lifecycle_status"] = "AT_AUCTION"
    touch(vehicle)
    return success_object(_serialize_simple(ent), status=201)


@app.route("/v1/auction-lots", methods=["GET"])
@require_roles("PlatformAdmin", "AuctionManager", "StoreManager")
def list_auction_lots(user_id, role, identity):
    items = list(db.auction_lots.values())
    st = request.args.get("status")
    if st:
        items = [l for l in items if l["status"] == st]
    return paginate(items)


@app.route("/v1/auction-lots/<lid>", methods=["GET"])
@require_roles("PlatformAdmin", "AuctionManager", "StoreManager")
def get_auction_lot(lid, user_id, role, identity):
    lot = _get_or_404(db.auction_lots, lid, "auction lot")
    return success_object(_serialize_simple(lot))


@app.route("/v1/auction-lots/<lid>/close", methods=["POST"])
@require_roles("AuctionManager")
def close_auction_lot(lid, user_id, role, identity):
    lot = _get_or_404(db.auction_lots, lid, "auction lot")
    if lot["status"] != "LISTED":
        raise_err(ERR_INVALID_STATE, f"lot must be LISTED, is {lot['status']}")
    payload = request.get_json(silent=True) or {}
    _require_fields(payload, ["hammer_price_cents"])
    hammer = payload["hammer_price_cents"]
    if not _is_int(hammer) or hammer <= 0:
        raise_err(ERR_HAMMER_BELOW_RESERVE_INVALID, "hammer_price_cents must be a positive integer")
    lot["hammer_price_cents"] = hammer
    vehicle = _get_or_404(db.vehicles, lot["vehicle_id"], "vehicle")
    if hammer >= int(lot["reserve_price_cents"]):
        lot["status"] = "SOLD"
        touch(lot)
        vehicle["lifecycle_status"] = "DISPOSED"
        touch(vehicle)
        post_ledger_entry("AUCTION_PROCEEDS", hammer, "AuctionLot", lot["id"], vehicle["current_store_id"])
    else:
        lot["status"] = "UNSOLD"
        touch(lot)
        vehicle["lifecycle_status"] = "WHOLESALE_PENDING"
        touch(vehicle)
    return success_object(_serialize_simple(lot), status=200)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
