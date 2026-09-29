"""Panel defence firms, the panel selector and assignment lifecycle (PRD 3.7)."""
from flask import Blueprint

import constants as C
from auth import claim as fetch_claim, counsel_assignment, counsel_firm, endpoint
from envelope import created, listing, ok, pagination
from errors import ApiError
from routes import common
from store import all_of, db, new_record, touch
from val import ZERO, body, r2, v_enum, v_enum_list, v_int, v_money, v_str, v_str_list
from services import counsel as counsel_svc

bp = Blueprint("counsel", __name__, url_prefix=C.API_PREFIX)


@bp.post("/counsel-firms")
@endpoint([C.R_APPROVER])
def create_firm():
    payload = body()
    firm_name = v_str(payload, "firm_name")
    venues = v_enum_list(payload, "admitted_venue_codes", C.VENUE_CODES)
    specialties = v_enum_list(payload, "allegation_specialties", C.ALLEGATION_CATEGORIES)
    rate = v_money(
        payload, "blended_hourly_rate", minimum=ZERO, exclusive_minimum=True
    )
    quality_score = v_int(payload, "quality_score", minimum=0, maximum=100)
    capacity = v_int(
        payload, "max_concurrent_assignments", required=False, default=5, minimum=1
    )
    conflicts = v_str_list(payload, "conflict_insured_ids", required=False, default=[])

    record = new_record(
        {
            "firm_name": firm_name,
            "admitted_venue_codes": venues,
            "allegation_specialties": specialties,
            "blended_hourly_rate": rate,
            "quality_score": quality_score,
            "max_concurrent_assignments": capacity,
            "conflict_insured_ids": conflicts,
            "panel_status": "ACTIVE",
            "panel_status_reason": None,
            "open_assignment_count": 0,
            "billed_expense_total": r2(ZERO),
        }
    )
    db.counsel_firms[record["id"]] = record
    return created(record)


@bp.get("/counsel-firms/<record_id>")
@endpoint(C.CARRIER_ROLES)
def get_firm(record_id):
    return ok(counsel_firm(record_id))


@bp.get("/counsel-firms")
@endpoint(C.CARRIER_ROLES)
def list_firms():
    limit, offset = pagination()
    records = all_of(db.counsel_firms)
    records = common.eq(records, "panel_status", common.arg("panel_status"))
    records = common.contains(records, "admitted_venue_codes", common.arg("venue_code"))
    records = common.contains(
        records, "allegation_specialties", common.arg("allegation_category")
    )
    return listing(records, limit, offset)


@bp.post("/counsel-firms/<record_id>/panel-status")
@endpoint([C.R_APPROVER])
def change_panel_status(record_id):
    payload = body()
    panel_status = v_enum(payload, "panel_status", C.PANEL_STATUSES)
    reason = v_str(payload, "reason")

    firm = counsel_firm(record_id)
    firm["panel_status"] = panel_status
    firm["panel_status_reason"] = reason
    touch(firm)
    if panel_status == "REMOVED":
        counsel_svc.unwind_removed_firm(firm)
    return ok(firm)


@bp.post("/claims/<record_id>/counsel-assignments")
@endpoint([C.R_ADJUSTER])
def assign_counsel(record_id):
    claim = fetch_claim(record_id)

    if claim["claim_status"] not in ("INVESTIGATION", "LITIGATION"):
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if claim["coverage_status"] == "DENIED":
        raise ApiError("ERR_COVERAGE_DENIED_NO_DEFENSE")
    if counsel_svc.live_assignment(claim["id"]) is not None:
        raise ApiError("ERR_COUNSEL_ALREADY_ASSIGNED")

    ranked = counsel_svc.eligible_pool(claim)
    if not ranked:
        raise ApiError("ERR_NO_ELIGIBLE_COUNSEL")

    firm = ranked[0]
    record = new_record(
        {
            "claim_id": claim["id"],
            "counsel_firm_id": firm["id"],
            "assignment_status": "ASSIGNED",
            "assigned_at": db.logical_now(),
            "candidate_pool_size": len(ranked),
            "selection_rank_snapshot": 1,
            "billed_expense_amount": r2(ZERO),
            "decline_reason": None,
            "closed_at": None,
        }
    )
    db.counsel_assignments[record["id"]] = record
    firm["open_assignment_count"] = int(firm["open_assignment_count"]) + 1
    touch(firm)
    claim["counsel_reassignment_required"] = False
    touch(claim)
    return created(record)


@bp.get("/counsel-assignments/<record_id>")
@endpoint(C.CARRIER_ROLES)
def get_assignment(record_id):
    return ok(counsel_assignment(record_id))


@bp.get("/counsel-assignments")
@endpoint(C.CARRIER_ROLES)
def list_assignments():
    limit, offset = pagination()
    records = all_of(db.counsel_assignments)
    records = common.eq(records, "claim_id", common.arg("claim_id"))
    records = common.eq(records, "counsel_firm_id", common.arg("counsel_firm_id"))
    records = common.eq(records, "assignment_status", common.arg("assignment_status"))
    return listing(records, limit, offset)


@bp.post("/counsel-assignments/<record_id>/decline")
@endpoint([C.R_ADJUSTER])
def decline_assignment(record_id):
    payload = body()
    reason = v_enum(payload, "decline_reason", C.DECLINE_REASONS)

    assignment = counsel_assignment(record_id)
    if assignment["assignment_status"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_STATE_INVALID")

    assignment["assignment_status"] = "DECLINED"
    assignment["decline_reason"] = reason
    assignment["closed_at"] = db.logical_now()
    touch(assignment)

    firm = db.counsel_firms.get(assignment["counsel_firm_id"])
    if firm is not None:
        counsel_svc.release_capacity(firm)
    claim = db.claims.get(assignment["claim_id"])
    if claim is not None:
        counsel_svc.exclude_firm_from_claim(claim, assignment["counsel_firm_id"])
        claim["counsel_reassignment_required"] = True
        touch(claim)
    return ok(assignment)
