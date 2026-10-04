"""AlterationRequest endpoints (PRD section 3.6)."""
from flask import Blueprint, request

from calc import alteration_amortization
from dates import month_str, parse_date
from envelope import success
from errors import ApiError
from middleware import (ALL_ROLES, agency_scope, body, is_int, paginate,
                        require_auth)
from store import DB, bump, make_entity, pub, sorted_items

bp = Blueprint("alterations", __name__)


def _get_alt(aid):
    a = DB["alterations"].get(aid)
    if not a:
        raise ApiError("ERR_NOT_FOUND", 404, "AlterationRequest not found")
    return a


def _amortization_months(work_end, oa_end):
    """Months from the month after work_end month through the OA end month,
    inclusive."""
    ny, nm = (work_end.year + 1, 1) if work_end.month == 12 else (work_end.year, work_end.month + 1)
    return (oa_end.year - ny) * 12 + (oa_end.month - nm) + 1


@bp.route("/leasing/occupancy-agreements/<oid>/alteration-requests", methods=["POST"])
def create_alteration(oid):
    uid, role = require_auth(["AgencyManager"])
    oa = DB["oas"].get(oid)
    if not oa:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    # priority 3: agency scope
    agency_scope(uid, role, oa["agency_id"])
    b = body()
    # priority 5: shape
    if not isinstance(b.get("title"), str) or b["title"] == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "title is required")
    if not isinstance(b.get("description"), str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "description is required")
    if not is_int(b.get("scope_sf")) or b["scope_sf"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "scope_sf must be an integer > 0")
    # priority 7: OA must be ACTIVE
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "Alterations may only be requested against an ACTIVE OA")
    e = make_entity()
    e.update({
        "oa_id": oid,
        "title": b["title"],
        "description": b["description"],
        "scope_sf": b["scope_sf"],
        "status": "REQUESTED",
        "estimated_cost_cents": None,
        "work_start_date": None,
        "work_end_date": None,
        "funding_method": None,
        "completion_date": None,
        "amortization_months": None,
        "monthly_amort_cents": None,
        "amortization_start_month": None,
        "amortization_balance_cents": None,
        "lump_charge_status": "NONE",
    })
    DB["alterations"][e["id"]] = e
    return success(pub(e), 201)


@bp.route("/leasing/occupancy-agreements/<oid>/alteration-requests", methods=["GET"])
def list_alterations(oid):
    require_auth(ALL_ROLES)
    if oid not in DB["oas"]:
        raise ApiError("ERR_NOT_FOUND", 404, "OccupancyAgreement not found")
    items = [a for a in DB["alterations"].values() if a["oa_id"] == oid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, pagination = paginate(sorted_items(items))
    return success([pub(a) for a in page], 200, pagination)


@bp.route("/leasing/alteration-requests/<aid>/estimate", methods=["POST"])
def estimate_alteration(aid):
    require_auth(["GSAPropertyManager"])
    alt = _get_alt(aid)
    b = body()
    # priority 5: shape
    if not is_int(b.get("estimated_cost_cents")) or b["estimated_cost_cents"] <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "estimated_cost_cents must be an integer > 0")
    ws = parse_date(b.get("work_start_date"))
    we = parse_date(b.get("work_end_date"))
    if ws is None or we is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "work_start_date and work_end_date must be ISO dates")
    if we < ws:
        raise ApiError("ERR_INVALID_REQUEST", 400, "work_end_date must be on or after work_start_date")
    # priority 6: state
    if alt["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a REQUESTED alteration can be estimated")
    # priority 7: OA must be ACTIVE
    oa = DB["oas"][alt["oa_id"]]
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "The occupancy agreement is not ACTIVE")
    # priority 9: >= 14 clear days to every other non-CANCELLED window on this OA
    for other in DB["alterations"].values():
        if other["oa_id"] != alt["oa_id"] or other["id"] == alt["id"]:
            continue
        if other["status"] == "CANCELLED":
            continue
        os_ = parse_date(other.get("work_start_date"))
        oe = parse_date(other.get("work_end_date"))
        if not os_ or not oe:
            continue
        if os_ > we:
            gap = (os_ - we).days
        elif ws > oe:
            gap = (ws - oe).days
        else:
            gap = -1  # overlapping windows
        if gap < 14:
            raise ApiError("ERR_ALTERATION_WINDOW_CONFLICT", 409,
                           "Work window leaves fewer than 14 clear days to another alteration window")
    alt["estimated_cost_cents"] = b["estimated_cost_cents"]
    alt["work_start_date"] = b["work_start_date"]
    alt["work_end_date"] = b["work_end_date"]
    alt["status"] = "ESTIMATED"
    bump(alt)
    return success(pub(alt))


@bp.route("/leasing/alteration-requests/<aid>/approve", methods=["POST"])
def approve_alteration(aid):
    uid, role = require_auth(["AgencyManager"])
    alt = _get_alt(aid)
    oa = DB["oas"][alt["oa_id"]]
    agency_scope(uid, role, oa["agency_id"])
    b = body()
    if b.get("funding_method") not in ("LUMP_SUM", "AMORTIZED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "funding_method must be LUMP_SUM or AMORTIZED")
    if alt["status"] != "ESTIMATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an ESTIMATED alteration can be approved")
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "The occupancy agreement is not ACTIVE")
    if b["funding_method"] == "AMORTIZED":
        # priority 12: at least 12 amortization months between the month
        # after work_end month and the OA end month
        if _amortization_months(parse_date(alt["work_end_date"]), parse_date(oa["end_date"])) < 12:
            raise ApiError("ERR_AMORTIZATION_WINDOW_TOO_SHORT", 422,
                           "Fewer than 12 amortization months remain before the OA end")
    alt["funding_method"] = b["funding_method"]
    if b["funding_method"] == "LUMP_SUM":
        alt["lump_charge_status"] = "PENDING"
    alt["status"] = "APPROVED"
    bump(alt)
    return success(pub(alt))


@bp.route("/leasing/alteration-requests/<aid>/revise", methods=["POST"])
def revise_alteration(aid):
    uid, role = require_auth(["AgencyManager"])
    alt = _get_alt(aid)
    oa = DB["oas"][alt["oa_id"]]
    agency_scope(uid, role, oa["agency_id"])
    b = body()
    if not is_int(b.get("expected_alteration_version")):
        raise ApiError("ERR_INVALID_REQUEST", 400, "expected_alteration_version is required")
    if b.get("description") is not None and not isinstance(b["description"], str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "description must be a string")
    if b.get("scope_sf") is not None and (not is_int(b["scope_sf"]) or b["scope_sf"] <= 0):
        raise ApiError("ERR_INVALID_REQUEST", 400, "scope_sf must be an integer > 0")
    if alt["status"] != "ESTIMATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an ESTIMATED alteration can be revised")
    if b["expected_alteration_version"] != alt["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "The alteration's version has advanced; re-read and rebase")
    if b.get("description") is not None:
        alt["description"] = b["description"]
    if b.get("scope_sf") is not None:
        alt["scope_sf"] = b["scope_sf"]
    # the revision clears the pending estimate
    alt["estimated_cost_cents"] = None
    alt["work_start_date"] = None
    alt["work_end_date"] = None
    alt["status"] = "REQUESTED"
    bump(alt)
    return success(pub(alt))


@bp.route("/leasing/alteration-requests/<aid>/complete", methods=["POST"])
def complete_alteration(aid):
    require_auth(["GSAPropertyManager"])
    alt = _get_alt(aid)
    b = body()
    cd = parse_date(b.get("completion_date"))
    if cd is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "completion_date must be an ISO date")
    if alt["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only an APPROVED alteration can be completed")
    oa = DB["oas"][alt["oa_id"]]
    if oa["status"] != "ACTIVE":
        raise ApiError("ERR_OA_NOT_ACTIVE", 409, "The occupancy agreement is not ACTIVE")
    alt["completion_date"] = b["completion_date"]
    if alt["funding_method"] == "AMORTIZED":
        oe = parse_date(oa["end_date"])
        ny, nm = (cd.year + 1, 1) if cd.month == 12 else (cd.year, cd.month + 1)
        n = (oe.year - ny) * 12 + (oe.month - nm) + 1
        monthly, balance = alteration_amortization(alt["estimated_cost_cents"], n)
        alt["amortization_months"] = n
        alt["monthly_amort_cents"] = monthly
        alt["amortization_start_month"] = month_str(ny, nm)
        alt["amortization_balance_cents"] = balance
    alt["status"] = "COMPLETED"
    bump(alt)
    return success(pub(alt))


@bp.route("/leasing/alteration-requests/<aid>/cancel", methods=["POST"])
def cancel_alteration(aid):
    uid, role = require_auth(["AgencyManager"])
    alt = _get_alt(aid)
    oa = DB["oas"][alt["oa_id"]]
    agency_scope(uid, role, oa["agency_id"])
    if alt["status"] not in ("REQUESTED", "ESTIMATED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a non-terminal alteration can be cancelled")
    if alt["status"] == "APPROVED" and alt["lump_charge_status"] == "PENDING":
        alt["lump_charge_status"] = "REVERSED"
    alt["status"] = "CANCELLED"
    bump(alt)
    return success(pub(alt))
