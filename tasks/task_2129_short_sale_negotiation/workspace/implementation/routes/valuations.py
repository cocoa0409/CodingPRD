"""Valuations, vendor scheduling, disputes and adjudication (PRD §3.6)."""
from flask import Blueprint

import calc
import constants as K
import services as S
import validation as V
from auth import require
from db import db
from envelope import collection, created, enum_filter, str_filter, success
from errors import fail
from serializers import dispute_out, valuation_out

bp = Blueprint("valuations", __name__)

VALUATION_READ_ROLES = (
    K.ROLE_NEGOTIATOR,
    K.ROLE_SERVICER_ANALYST,
    K.ROLE_BPO_VENDOR,
    K.ROLE_PLATFORM_ADMIN,
)
DISPUTE_READ_ROLES = (K.ROLE_NEGOTIATOR, K.ROLE_SERVICER_ANALYST, K.ROLE_PLATFORM_ADMIN)


@bp.post("/short-sale/cases/<case_id>/valuations")
def create_valuation(case_id):
    user_id = require(K.ROLE_SERVICER_ANALYST)
    case = S.need_case(case_id)
    data = V.body()

    # rung 6 — body reference existence
    raw_vendor = data.get("vendor_id")
    if isinstance(raw_vendor, str) and raw_vendor.strip():
        if db.get("vendors", raw_vendor) is None:
            fail("ERR_VENDOR_NOT_FOUND", "The vendor_id names no registered vendor firm.")

    # rung 7 — request shape
    vendor_id = V.req_string(data, "vendor_id")
    valuation_type = V.req_enum(data, "valuation_type", K.VALUATION_TYPES)
    effective_date = V.req_datetime(data, "effective_date")
    inspection_start = V.req_datetime(data, "inspection_start")
    inspection_end = V.req_datetime(data, "inspection_end")
    if inspection_end <= inspection_start:
        fail("ERR_INVALID_REQUEST", "inspection_end must fall strictly after inspection_start.")

    vendor = db.get("vendors", vendor_id)
    if vendor is None:
        fail("ERR_VENDOR_NOT_FOUND", "The vendor_id names no registered vendor firm.")

    # rung 9 — state admissibility
    S.require_case_actionable(case)

    # rung 12 — buffered slot conflict
    if S.vendor_slot_conflict(vendor_id, inspection_start, inspection_end):
        fail(
            "ERR_VENDOR_SCHEDULE_CONFLICT",
            "The requested inspection slot conflicts with one the vendor already holds.",
        )

    # rung 16 — aggregate daily capacity
    if S.vendor_same_day_count(vendor_id, inspection_start) >= vendor["daily_inspection_capacity"]:
        fail(
            "ERR_VENDOR_DAILY_CAPACITY_EXCEEDED",
            "The vendor has filled its inspection allowance for that date.",
        )

    valuation = {
        "id": db.new_id(),
        "case_id": case["id"],
        "vendor_id": vendor_id,
        "valuation_type": valuation_type,
        "effective_date": effective_date,
        "inspection_start": inspection_start,
        "inspection_end": inspection_end,
        "ordered_by_user_id": user_id,
        "value_cents": None,
        "recorded_at": None,
        "status": "ORDERED",
    }
    db.insert("valuations", valuation)
    return created(valuation_out(valuation))


@bp.get("/short-sale/valuations/<valuation_id>")
def get_valuation(valuation_id):
    require(*VALUATION_READ_ROLES)
    valuation = S.need_valuation(valuation_id)
    return success(valuation_out(valuation))


@bp.get("/short-sale/valuations")
def list_valuations():
    require(*VALUATION_READ_ROLES)
    case_id = str_filter("case_id")
    vendor_id = str_filter("vendor_id")
    status = enum_filter("status", K.VALUATION_STATUSES)
    rows = db.all("valuations")
    if case_id is not None:
        rows = [r for r in rows if r["case_id"] == case_id]
    if vendor_id is not None:
        rows = [r for r in rows if r["vendor_id"] == vendor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(rows, valuation_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/valuations/<valuation_id>/record-value")
def record_value(valuation_id):
    user_id = require(K.ROLE_BPO_VENDOR)
    valuation = S.need_valuation(valuation_id)

    # rung 3 — ownership binding
    if user_id != valuation["vendor_id"]:
        fail("ERR_ACTOR_NOT_OWNER", "Only the vendor named on the valuation may record its value.")

    data = V.body()
    value_cents = V.req_int(data, "value_cents", minimum=1)

    # rung 9 — state admissibility
    if valuation["status"] != "ORDERED":
        fail("ERR_VALUATION_NOT_ACTIONABLE", "Only an ORDERED valuation may record a value.")

    valuation["value_cents"] = value_cents
    valuation["recorded_at"] = db.now()
    valuation["status"] = "RECEIVED"

    case = db.get("cases", valuation["case_id"])
    S.recompute_case_value(case)

    return success(valuation_out(valuation))


# ---------------------------------------------------------------------------
# disputes
# ---------------------------------------------------------------------------
@bp.post("/short-sale/valuations/<valuation_id>/disputes")
def create_dispute(valuation_id):
    user_id = require(K.ROLE_NEGOTIATOR, K.ROLE_SERVICER_ANALYST)
    valuation = S.need_valuation(valuation_id)
    data = V.body()
    claimed_value_cents = V.req_int(data, "claimed_value_cents", minimum=1)
    comparable_count = V.req_int(data, "comparable_count", minimum=0)
    rationale = V.req_string(data, "rationale")

    # rung 9 — state admissibility
    if valuation["status"] not in ("RECEIVED", "REVISED"):
        fail(
            "ERR_VALUATION_NOT_ACTIONABLE",
            "A dispute may only be filed against a RECEIVED or REVISED valuation.",
        )

    variance = calc.variance_pct(claimed_value_cents, valuation["value_cents"])

    # rung 25 — dispute variance floor
    if variance < K.DISPUTE_MIN_VARIANCE_PCT:
        fail("ERR_DISPUTE_VARIANCE_TOO_SMALL", "The filed variance is below the minimum.")

    # rung 26 — dispute evidence floor
    if comparable_count < K.DISPUTE_MIN_COMPARABLES:
        fail("ERR_DISPUTE_EVIDENCE_INSUFFICIENT", "Too few comparable sales attached.")

    dispute = {
        "id": db.new_id(),
        "valuation_id": valuation["id"],
        "claimed_value_cents": claimed_value_cents,
        "comparable_count": comparable_count,
        "rationale": rationale,
        "filed_by_user_id": user_id,
        "variance_pct": variance,
        "resolved_value_cents": None,
        "adjudicated_by_user_id": None,
        "status": "OPEN",
    }
    db.insert("disputes", dispute)
    valuation["status"] = "DISPUTED"
    return created(dispute_out(dispute))


@bp.get("/short-sale/valuations/<valuation_id>/disputes")
def list_disputes(valuation_id):
    require(*DISPUTE_READ_ROLES)
    valuation = S.need_valuation(valuation_id)
    status = enum_filter("status", K.DISPUTE_STATUSES)
    rows = S.valuation_disputes(valuation["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return collection(rows, dispute_out, sort_key=lambda r: r["_seq"])


@bp.post("/short-sale/disputes/<dispute_id>/adjudicate")
def adjudicate(dispute_id):
    user_id = require(K.ROLE_SERVICER_ANALYST)
    dispute = S.need_dispute(dispute_id)
    valuation = db.get("valuations", dispute["valuation_id"])

    # rung 4 — segregation of duties
    if user_id == valuation["ordered_by_user_id"]:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The analyst who ordered the valuation may not adjudicate its disputes.",
        )

    data = V.body()
    resolution = V.req_enum(data, "resolution", K.DISPUTE_RESOLUTIONS)
    V.opt_string(data, "note")

    # rung 9 — state admissibility
    if dispute["status"] != "OPEN":
        fail("ERR_DISPUTE_NOT_OPEN", "Only an OPEN dispute may be adjudicated.")

    case = db.get("cases", valuation["case_id"])

    # CASCADE-A hop 1
    resolved = calc.resolved_value(
        resolution, dispute["claimed_value_cents"], valuation["value_cents"]
    )
    dispute["resolved_value_cents"] = resolved
    dispute["adjudicated_by_user_id"] = user_id
    dispute["status"] = resolution

    if resolution == "DENIED":
        # divergent branch: the value is untouched and the valuation locks
        valuation["status"] = "FINAL"
    else:
        # hop 2
        valuation["value_cents"] = resolved
        valuation["status"] = "REVISED"
        # hops 3 -> 4 -> 5
        S.cascade_a_propagate(case)

    return success(dispute_out(dispute))
