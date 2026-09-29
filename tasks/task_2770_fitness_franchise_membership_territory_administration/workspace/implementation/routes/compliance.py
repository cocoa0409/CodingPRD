"""Royalty self-reporting and facility inspections."""
from flask import Blueprint

import calc
import cascade
import config
import validate as v
from auth import guard, require_owner
from envelope import ok, created
from errors import ApiError
from helpers import ALL_ROLES, get_club, get_franchisee, get_inspection, get_report, paged
from store import (db, common_fields, clock_date, clock_date_str, parse_date, month_key,
                   month_last_day, touch)

bp = Blueprint("compliance", __name__)

ADMIN = ["BrandAdministrator"]
AUDITOR = ["ComplianceAuditor"]


# --------------------------------------------------------------------------
# royalty reports
# --------------------------------------------------------------------------
def _qualifying_agreements(franchisee_id, period_month):
    club_ids = {c["id"] for c in db.clubs.values() if c["franchisee_id"] == franchisee_id}
    cutoff = month_last_day(period_month)
    rows = []
    for agreement in db.agreements.values():
        if agreement["home_club_id"] not in club_ids:
            continue
        if agreement["agreement_status"] not in config.ENROLLED_AGREEMENT_STATES:
            continue
        if parse_date(agreement["signed_on"]) > cutoff:
            continue
        rows.append(agreement)
    return rows


@bp.post("/franchise/royalty-reports")
def create_report():
    uid, role = guard(["FranchiseOwner"])
    b = v.body()

    raw = b.get("franchisee_id")
    if isinstance(raw, str):
        require_owner(raw == uid)

    franchisee_id = v.req_id(b, "franchisee_id")
    period_month = v.req_month(b, "period_month")
    reported_member_count = v.req_int(b, "reported_member_count", minimum=0)

    franchisee = get_franchisee(franchisee_id)

    for existing in db.royalty_reports.values():
        if (existing["franchisee_id"] == franchisee_id
                and existing["period_month"] == period_month):
            raise ApiError("ERR_DUPLICATE_ROYALTY_PERIOD")

    if period_month >= month_key(clock_date()):
        raise ApiError("ERR_REPORT_PERIOD_NOT_CLOSED")

    qualifying = _qualifying_agreements(franchisee_id, period_month)
    verified_count = len(qualifying)
    verified_basis = sum(a["effective_monthly_dues_cents"] for a in qualifying)
    reported_basis = reported_member_count * config.BRAND_STANDARD_DUES_CENTS
    bps = franchisee["royalty_rate_bps"]
    variance = calc.variance_pct(reported_member_count, verified_count)

    record = common_fields()
    record.update({
        "franchisee_id": franchisee_id,
        "period_month": period_month,
        "reported_member_count": reported_member_count,
        "verified_member_count": verified_count,
        "reported_dues_basis_cents": reported_basis,
        "verified_dues_basis_cents": verified_basis,
        "reported_royalty_cents": calc.royalty_from_basis(reported_basis, bps),
        "royalty_due_cents": calc.royalty_from_basis(verified_basis, bps),
        "variance_pct": float(variance),
        "status": "SUBMITTED",
        "adjusted_royalty_cents": None,
        "adjudicated_by_user_id": None,
    })

    disputed = abs(variance) > config.ROYALTY_VARIANCE_TOLERANCE_PCT
    record["status"] = "DISPUTED" if disputed else "ACCEPTED"
    db.royalty_reports[record["id"]] = record

    cascade.recompute_franchisee(franchisee, bump="always" if disputed else "never")
    return created(record)


@bp.post("/franchise/royalty-reports/<rid>/adjudicate")
def adjudicate_report(rid):
    uid, role = guard(ADMIN)
    b = v.body()
    adjusted = v.req_money(b, "adjusted_royalty_cents")
    v.opt_str(b, "note")
    record = get_report(rid)

    if record["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_ROYALTY_STATE")

    low = min(record["royalty_due_cents"], record["reported_royalty_cents"])
    high = max(record["royalty_due_cents"], record["reported_royalty_cents"])
    if adjusted < low or adjusted > high:
        raise v.bad("Field 'adjusted_royalty_cents' must lie between royalty_due_cents and "
                    "reported_royalty_cents inclusive.")

    record["status"] = "ADJUSTED"
    record["adjusted_royalty_cents"] = adjusted
    record["adjudicated_by_user_id"] = uid
    touch(record)
    cascade.recompute_franchisee(db.franchisees.get(record["franchisee_id"]), bump="always")
    return ok(record)


@bp.get("/franchise/royalty-reports/<rid>")
def read_report(rid):
    guard(ALL_ROLES)
    return ok(get_report(rid))


@bp.get("/franchise/royalty-reports")
def list_reports():
    guard(ALL_ROLES)
    return paged(db.royalty_reports, "franchisee_id", "period_month", "status")


# --------------------------------------------------------------------------
# facility inspections
# --------------------------------------------------------------------------
@bp.post("/franchise/inspections")
def create_inspection():
    guard(["ComplianceAuditor", "BrandAdministrator"])
    b = v.body()
    club_id = v.req_id(b, "club_id")
    inspection_date = v.req_date(b, "inspection_date")

    get_club(club_id)

    if parse_date(inspection_date) > clock_date():
        raise v.bad("Field 'inspection_date' may not be later than the current logical date.")

    record = common_fields()
    record.update({
        "club_id": club_id,
        "inspection_date": inspection_date,
        "equipment_condition_pts": None,
        "cleanliness_pts": None,
        "safety_pts": None,
        "equipment_age_months_max": None,
        "refresh_cycle_months_applied": None,
        "refresh_pts": None,
        "score": None,
        "variant_applied": None,
        "status": "SCHEDULED",
        "scored_by_user_id": None,
        "waived_by_user_id": None,
        "waiver_reason": None,
    })
    db.inspections[record["id"]] = record
    return created(record)


@bp.post("/franchise/inspections/<iid>/score")
def score_inspection(iid):
    uid, role = guard(AUDITOR)
    b = v.body()
    equipment = v.req_int(b, "equipment_condition_pts", minimum=0, maximum=100)
    cleanliness = v.req_int(b, "cleanliness_pts", minimum=0, maximum=100)
    safety = v.req_int(b, "safety_pts", minimum=0, maximum=100)
    age = v.req_int(b, "equipment_age_months_max", minimum=0, maximum=240)
    record = get_inspection(iid)

    if record["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE")

    club = get_club(record["club_id"])
    if club["status"] not in ("PRE_OPENING", "OPEN", "SUSPENDED"):
        raise ApiError("ERR_CLUB_NOT_OPERATIONAL")

    variant, cycle = calc.refresh_variant(club)
    refresh_pts = calc.refresh_points(age, cycle)
    score = calc.inspection_score(equipment, cleanliness, safety, refresh_pts)

    record["equipment_condition_pts"] = equipment
    record["cleanliness_pts"] = cleanliness
    record["safety_pts"] = safety
    record["equipment_age_months_max"] = age
    record["refresh_cycle_months_applied"] = cycle
    record["refresh_pts"] = refresh_pts
    record["score"] = score
    record["variant_applied"] = variant
    record["scored_by_user_id"] = uid
    record["status"] = "CLOSED" if score >= config.REMEDIATION_SCORE_THRESHOLD \
        else "REMEDIATION_REQUIRED"

    prior_status = club["status"]
    club["last_inspection_score"] = score
    club["equipment_compliance_state"] = calc.compliance_state_for(score)
    if club["equipment_compliance_state"] == "NON_COMPLIANT" and prior_status == "OPEN":
        club["status"] = "SUSPENDED"
    elif prior_status == "SUSPENDED" and score >= config.REMEDIATION_SCORE_THRESHOLD:
        club["status"] = "OPEN"

    touch(record)
    touch(club)
    cascade.recompute_franchisee(cascade.franchisee_of_club(club), bump="always")
    return ok(record)


@bp.post("/franchise/inspections/<iid>/waive-remediation")
def waive_remediation(iid):
    uid, role = guard(AUDITOR)
    b = v.body()
    reason = v.req_str(b, "reason")
    record = get_inspection(iid)

    if record["scored_by_user_id"] is not None and record["scored_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if (record["status"] != "REMEDIATION_REQUIRED" or record["score"] is None
            or record["score"] >= config.REMEDIATION_SCORE_THRESHOLD):
        raise ApiError("ERR_REMEDIATION_NOT_REQUIRED")

    record["status"] = "REMEDIATION_WAIVED"
    record["waived_by_user_id"] = uid
    record["waiver_reason"] = reason

    club = get_club(record["club_id"])
    club["equipment_compliance_state"] = "WATCH"
    if club["status"] == "SUSPENDED":
        club["status"] = "OPEN"

    touch(record)
    touch(club)
    cascade.recompute_franchisee(cascade.franchisee_of_club(club), bump="never")
    return ok(record)


@bp.post("/franchise/inspections/<iid>/close")
def close_inspection(iid):
    guard(ADMIN)
    b = v.body()
    v.opt_str(b, "note")
    record = get_inspection(iid)

    if record["status"] not in ("REMEDIATION_REQUIRED", "REMEDIATION_WAIVED"):
        raise ApiError("ERR_INVALID_INSPECTION_STATE")

    record["status"] = "CLOSED"
    touch(record)
    return ok(record)


@bp.get("/franchise/inspections/<iid>")
def read_inspection(iid):
    guard(ALL_ROLES)
    return ok(get_inspection(iid))


@bp.get("/franchise/inspections")
def list_inspections():
    guard(ALL_ROLES)
    return paged(db.inspections, "club_id", "status", "variant_applied")
