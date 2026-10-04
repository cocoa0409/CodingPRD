"""Routes: employer partners and placements (career counseling)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services
from errors import ApiError
from middleware import authenticate, require_role
from response import ok_object, ok_list
from validation import (
    get_body, req_str, opt_str, req_enum, req_int, opt_int, req_dt,
    pagination_params,
)

bp = Blueprint("placements", __name__)

MILESTONE_FROM = {"DAY_30": "ACTIVE", "DAY_90": "MILESTONE_30", "DAY_180": "MILESTONE_90"}
MILESTONE_DAYS = {"DAY_30": 30, "DAY_90": 90, "DAY_180": 180}
MILESTONE_TO = {"DAY_30": "MILESTONE_30", "DAY_90": "MILESTONE_90", "DAY_180": "RETAINED"}


@bp.post("/veteran-services/employer-partners")
def create_employer_partner():
    uid, role = authenticate()
    body = get_body()
    name = req_str(body, "name")
    industry = req_str(body, "industry")
    open_requisitions = opt_int(body, "open_requisitions", default=0, minimum=0)
    require_role(role, ["CareerCounselor"])
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "name": name, "industry": industry, "open_requisitions": open_requisitions,
    }
    services.stamp_new(rec)
    db.STORE["employer_partners"][rec["id"]] = rec
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/employer-partners")
def list_employer_partners():
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["CareerCounselor"])
    items = sorted(db.STORE["employer_partners"].values(),
                   key=lambda e: (e["created_at"], e["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(e) for e in page], limit, offset, total)


@bp.post("/veteran-services/placements")
def create_placement():
    uid, role = authenticate()
    body = get_body()
    member_id = req_str(body, "member_id")
    employer_partner_id = req_str(body, "employer_partner_id")
    start_date = req_dt(body, "start_date")
    salary_cents = req_int(body, "salary_cents", minimum=0)
    require_role(role, ["CareerCounselor"])
    # Existence: body FKs in declared input order
    member = db.STORE["members"].get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "member does not exist", 404)
    employer = db.STORE["employer_partners"].get(employer_partner_id)
    if employer is None:
        raise ApiError("ERR_EMPLOYER_NOT_FOUND", "employer partner does not exist", 404)
    # Priority 10: member must hold an ACTIVE CAREER-track enrollment
    career_ok = False
    for e in db.STORE["enrollments"].values():
        if e["member_id"] != member_id or e["status"] != "ACTIVE":
            continue
        track = db.STORE["program_tracks"].get(e["program_track_id"])
        if track is not None and track["track_code"] == "CAREER":
            career_ok = True
            break
    if not career_ok:
        raise ApiError("ERR_NO_ACTIVE_CAREER_ENROLLMENT",
                       "member holds no ACTIVE CAREER-track enrollment", 409)
    # Priority 13: requisition availability
    if employer["open_requisitions"] < 1:
        raise ApiError("ERR_NO_OPEN_REQUISITIONS",
                       "employer partner has no open requisitions", 409)
    rec = {
        "id": db.new_id(), "_seq": db.next_seq(),
        "member_id": member_id, "employer_partner_id": employer_partner_id,
        "start_date": start_date, "salary_cents": salary_cents,
        "status": "ACTIVE", "separated_at": None,
    }
    services.stamp_new(rec)
    db.STORE["placements"][rec["id"]] = rec
    employer["open_requisitions"] -= 1
    services.bump(employer)
    return ok_object(services.serialize(rec), 201)


@bp.get("/veteran-services/placements")
def list_placements():
    uid, role = authenticate()
    limit, offset = pagination_params()
    require_role(role, ["CareerCounselor", "OutcomeAnalyst"])
    member_id = request.args.get("member_id")
    employer_partner_id = request.args.get("employer_partner_id")
    status = request.args.get("status")
    items = [p for p in db.STORE["placements"].values()
             if (member_id is None or p["member_id"] == member_id)
             and (employer_partner_id is None or p["employer_partner_id"] == employer_partner_id)
             and (status is None or p["status"] == status)]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([services.serialize(p) for p in page], limit, offset, total)


@bp.get("/veteran-services/placements/<placement_id>")
def get_placement(placement_id):
    uid, role = authenticate()
    require_role(role, ["CareerCounselor"])
    rec = db.STORE["placements"].get(placement_id)
    if rec is None:
        raise ApiError("ERR_PLACEMENT_NOT_FOUND", "placement does not exist", 404)
    return ok_object(services.serialize(rec))


@bp.post("/veteran-services/placements/<placement_id>/transition")
def transition_placement(placement_id):
    uid, role = authenticate()
    body = get_body()
    action = req_enum(body, "action", ("CONFIRM_MILESTONE", "SEPARATE"))
    milestone = None
    if action == "CONFIRM_MILESTONE":
        milestone = req_enum(body, "milestone", ("DAY_30", "DAY_90", "DAY_180"))
    opt_str(body, "separation_reason")  # accepted, not persisted on the resource
    require_role(role, ["CareerCounselor"])
    placement = db.STORE["placements"].get(placement_id)
    if placement is None:
        raise ApiError("ERR_PLACEMENT_NOT_FOUND", "placement does not exist", 404)
    if action == "CONFIRM_MILESTONE":
        # Priority 7: strict ladder order
        if placement["status"] != MILESTONE_FROM[milestone]:
            raise ApiError("ERR_INVALID_STATE",
                           "milestone confirmation is out of order", 409)
        # Priority 11: day gate (the exact day is allowed)
        if db.now() < placement["start_date"] + timedelta(days=MILESTONE_DAYS[milestone]):
            raise ApiError("ERR_MILESTONE_TOO_EARLY",
                           "the milestone day gate has not been reached", 422)
        # DAY_180 moves straight through MILESTONE_180 into RETAINED
        placement["status"] = MILESTONE_TO[milestone]
        services.bump(placement)
        return ok_object(services.serialize(placement))
    # SEPARATE
    if placement["status"] not in ("ACTIVE", "MILESTONE_30", "MILESTONE_90", "MILESTONE_180"):
        raise ApiError("ERR_INVALID_STATE",
                       "placement cannot be separated from its current state", 409)
    prior = placement["status"]
    placement["status"] = "SEPARATED"
    placement["separated_at"] = db.now()
    services.bump(placement)
    # calculations.requisition_restore: restore only before MILESTONE_90
    if prior in ("ACTIVE", "MILESTONE_30"):
        employer = db.STORE["employer_partners"].get(placement["employer_partner_id"])
        if employer is not None:
            employer["open_requisitions"] += 1
            services.bump(employer)
    return ok_object(services.serialize(placement))
