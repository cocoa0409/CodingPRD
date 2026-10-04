"""RecordsSchedule endpoints (PRD §3.1).

POST /records/schedules                 RecordsOfficer, 201
GET  /records/schedules                 all roles except Anonymous
GET  /records/schedules/{id}            all roles except Anonymous
POST /records/schedules/{id}/submit     RecordsOfficer (DRAFT or RETURNED)
POST /records/schedules/{id}/appraise   AppraisalArchivist
POST /records/schedules/{id}/decide     ChiefArchivist (SoD vs appraiser)
"""
from flask import Blueprint, request

import constants as C
from envelope import ok_list, ok_object
from errors import err
from helpers import bump, get_agency, get_schedule
from store import DB, new_id, ts3
from validation import (
    body_fk,
    get_auth,
    get_body,
    list_page,
    opt_str,
    req_enum,
    req_str,
    require_ownership,
    require_role,
)

bp = Blueprint("schedules", __name__)


@bp.post("/records/schedules")
def create_schedule():
    uid, role = get_auth()                        # rung 1
    require_role(role, ["RecordsOfficer"])        # rung 2
    body = get_body()
    agency_id = body_fk(body, "agency_id")        # rung 4 (body FK order)
    get_agency(agency_id)
    require_ownership(uid, agency_id)             # rung 5
    # rung 12 (uniqueness) before rung 15 (shape)
    sn_raw = body.get("schedule_number")
    if isinstance(sn_raw, str) and any(
        s["agency_id"] == agency_id and s["schedule_number"] == sn_raw
        for s in DB.schedules.values()
    ):
        raise err(
            "ERR_SCHEDULE_NUMBER_EXISTS",
            "schedule_number already exists for this agency",
        )
    # rung 15 shape
    schedule_number = req_str(body, "schedule_number")
    title = req_str(body, "title")
    records_domain = req_enum(body, "records_domain", C.RECORDS_DOMAINS)
    disposition = req_enum(body, "disposition", C.DISPOSITIONS)
    classification_default = req_enum(
        body, "classification_default", C.CLASSIFICATIONS
    )
    lag_raw = body.get("transfer_lag_years")
    if disposition == "PERMANENT":
        # required iff PERMANENT; integer within 0..50 inclusive
        if (
            isinstance(lag_raw, bool)
            or not isinstance(lag_raw, int)
            or not (C.TRANSFER_LAG_MIN <= lag_raw <= C.TRANSFER_LAG_MAX)
        ):
            raise err(
                "ERR_INVALID_REQUEST",
                "transfer_lag_years is required for PERMANENT schedules and "
                "must be an integer between 0 and 50 inclusive",
            )
        transfer_lag_years = lag_raw
    else:
        if lag_raw is not None:
            raise err(
                "ERR_INVALID_REQUEST",
                "transfer_lag_years must be null unless disposition is PERMANENT",
            )
        transfer_lag_years = None
    now = ts3(DB.now())
    schedule = {
        "id": new_id(),
        "agency_id": agency_id,
        "schedule_number": schedule_number,
        "title": title,
        "records_domain": records_domain,
        "disposition": disposition,
        "transfer_lag_years": transfer_lag_years,
        "classification_default": classification_default,
        "status": "DRAFT",
        "appraiser_id": None,
        "appraisal_recommendation": None,
        "decided_by": None,
        "decision_note": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.schedules[schedule["id"]] = schedule
    return ok_object(schedule, 201)


@bp.get("/records/schedules")
def list_schedules():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in ("agency_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.schedules.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/schedules/<schedule_id>")
def get_one_schedule(schedule_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_schedule(schedule_id))


@bp.post("/records/schedules/<schedule_id>/submit")
def submit_schedule(schedule_id):
    uid, role = get_auth()
    require_role(role, ["RecordsOfficer"])
    s = get_schedule(schedule_id)                 # rung 3
    require_ownership(uid, s["agency_id"])        # rung 5
    if s["status"] not in ("DRAFT", "RETURNED"):  # rung 8
        raise err(
            "ERR_INVALID_STATE",
            "submit requires status DRAFT or RETURNED",
        )
    if s["status"] == "RETURNED":
        # revision cycle: resubmission clears the prior round's markings
        s["appraiser_id"] = None
        s["appraisal_recommendation"] = None
        s["decided_by"] = None
        s["decision_note"] = None
    s["status"] = "SUBMITTED"
    bump(s)
    return ok_object(s)


@bp.post("/records/schedules/<schedule_id>/appraise")
def appraise_schedule(schedule_id):
    uid, role = get_auth()
    require_role(role, ["AppraisalArchivist"])
    s = get_schedule(schedule_id)                 # rung 3
    if s["status"] != "SUBMITTED":                # rung 8
        raise err("ERR_INVALID_STATE", "appraise requires status SUBMITTED")
    recommendation = req_enum(                    # rung 15
        body=get_body(),
        name="appraisal_recommendation",
        values=C.APPRAISAL_RECOMMENDATIONS,
    )
    s["status"] = "APPRAISED"
    s["appraiser_id"] = uid
    s["appraisal_recommendation"] = recommendation
    bump(s)
    return ok_object(s)


@bp.post("/records/schedules/<schedule_id>/decide")
def decide_schedule(schedule_id):
    uid, role = get_auth()
    require_role(role, ["ChiefArchivist"])
    s = get_schedule(schedule_id)                 # rung 3
    if s["status"] != "APPRAISED":                # rung 8
        raise err("ERR_SCHEDULE_NOT_APPRAISED", "decide requires status APPRAISED")
    if uid == s["appraiser_id"]:                  # rung 11 segregation of duties
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "the appraiser of a schedule may not decide it",
        )
    body = get_body()                             # rung 15
    decision = req_enum(body, "decision", C.SCHEDULE_DECISIONS)
    decision_note = opt_str(body, "decision_note")
    s["status"] = "APPROVED" if decision == "APPROVE" else "RETURNED"
    s["decided_by"] = uid
    s["decision_note"] = decision_note
    bump(s)
    return ok_object(s)
