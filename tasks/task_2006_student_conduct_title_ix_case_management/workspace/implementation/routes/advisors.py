"""AdvisorAppointment endpoints (PRD 3.4): party-selected and
university-appointed advisors, replacement cascade, withdrawal."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_ADVISOR_INELIGIBLE,
    ERR_DUPLICATE_ADVISOR, ERR_NO_ADVISOR_AVAILABLE, ERR_PARTY_BINDING_MISMATCH,
)
from middleware import authorized, check_case_read_access, party_side_of, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    all_officials, APPOINTMENT_SIDES,
)
from validate import get_body, req_enum, req_str, require_path, require_profile_fk, as_enum

bp = Blueprint("advisors", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party", "Advisor"]


def _opposing_party_id(case, party_side):
    return case["respondent_id"] if party_side == "COMPLAINANT" else case["complainant_id"]


def _check_advisor_eligible(case, party_side, advisor_id):
    """Tier 5: advisor must not be the opposing party nor any case official."""
    if advisor_id == _opposing_party_id(case, party_side):
        raise_error(ERR_ADVISOR_INELIGIBLE,
                    "the advisor must not be the opposing party of the same case")
    if advisor_id in all_officials(case):
        raise_error(ERR_ADVISOR_INELIGIBLE,
                    "the advisor must not hold an official function on this case")


def _replace_existing(case, party_side, new_rec, caller):
    """Replacement cascade: prior ACTIVE appointment for (case, side) -> REPLACED."""
    for a in db["advisor_appointments"].values():
        if a["case_id"] == case["id"] and a["party_side"] == party_side \
                and a["status"] == "ACTIVE" and a["id"] != new_rec["id"]:
            a["status"] = "REPLACED"
            a["replaced_by_appointment_id"] = new_rec["id"]
            touch(a)
            append_event(case["id"], "ADVISOR_REPLACED", caller,
                         {"appointment_id": a["id"],
                          "replaced_by_appointment_id": new_rec["id"]}, system=True)


@bp.post("/cases/<cid>/advisor-appointments")
def appoint_party_selected(cid):
    caller = authorized(["Party", "TitleIXCoordinator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    # Tier 3: body FK existence.
    require_profile_fk(body, "advisor_id")
    party_side = as_enum(body, "party_side", APPOINTMENT_SIDES)
    advisor_id = body.get("advisor_id")
    if party_side is not None and isinstance(advisor_id, str):
        # Tier 5: advisor eligibility.
        _check_advisor_eligible(case, party_side, advisor_id)
        # Tier 7: same-advisor re-appointment is a no-op rejection.
        if any(a["case_id"] == cid and a["party_side"] == party_side
               and a["status"] == "ACTIVE" and a["advisor_id"] == advisor_id
               for a in db["advisor_appointments"].values()):
            raise_error(ERR_DUPLICATE_ADVISOR,
                        "this advisor already holds an ACTIVE appointment for that side")
        # Tier 8: a Party may appoint only for their own side.
        if caller.role == "Party":
            actor_side = party_side_of(case, caller.user_id)
            if actor_side is None or actor_side != party_side:
                raise_error(ERR_PARTY_BINDING_MISMATCH,
                            "a Party may appoint an advisor only for their own side")
    # Tier 11: schema.
    party_side = req_enum(body, "party_side", APPOINTMENT_SIDES)
    advisor_id = req_str(body, "advisor_id")

    rec = new_record("advisor_appointments", {
        "case_id": cid,
        "party_side": party_side,
        "advisor_id": advisor_id,
        "source": "PARTY_SELECTED",
        "status": "ACTIVE",
        "replaced_by_appointment_id": None,
    })
    append_event(cid, "ADVISOR_APPOINTED", caller,
                 {"appointment_id": rec["id"], "advisor_id": advisor_id,
                  "party_side": party_side, "source": "PARTY_SELECTED"})
    _replace_existing(case, party_side, rec, caller)
    bump_case(case)
    return success_object(public(rec), 201)


@bp.post("/cases/<cid>/advisor-appointments/appoint-university")
def appoint_university(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    party_side = as_enum(body, "party_side", APPOINTMENT_SIDES)
    if party_side is not None:
        # Tier 7: deterministic selector; empty pool is rejected.
        officials = all_officials(case)
        parties = {case["complainant_id"], case["respondent_id"]}
        pool = [
            p for p in db["party_profiles"].values()
            if p.get("advisor_eligible") is True
            and p["id"] not in officials
            and p["id"] not in parties
        ]
        if not pool:
            raise_error(ERR_NO_ADVISOR_AVAILABLE,
                        "no advisor-eligible profile is available for this case")

        def _rank(profile):
            active_count = sum(
                1 for a in db["advisor_appointments"].values()
                if a["advisor_id"] == profile["id"] and a["status"] == "ACTIVE"
            )
            return (active_count, profile["created_at"], profile["_seq"])

        pool.sort(key=_rank)
        selected = pool[0]
    # Tier 11: schema.
    party_side = req_enum(body, "party_side", APPOINTMENT_SIDES)

    rec = new_record("advisor_appointments", {
        "case_id": cid,
        "party_side": party_side,
        "advisor_id": selected["id"],
        "source": "UNIVERSITY_APPOINTED",
        "status": "ACTIVE",
        "replaced_by_appointment_id": None,
    })
    append_event(cid, "ADVISOR_APPOINTED", caller,
                 {"appointment_id": rec["id"], "advisor_id": selected["id"],
                  "party_side": party_side, "source": "UNIVERSITY_APPOINTED"})
    _replace_existing(case, party_side, rec, caller)
    bump_case(case)
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/advisor-appointments")
def list_appointments(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [a for a in db["advisor_appointments"].values() if a["case_id"] == cid]
    items = apply_filters(items, {
        "party_side": request.args.get("party_side"),
        "status": request.args.get("status"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/advisor-appointments/<aid>")
def get_appointment(aid):
    caller = authorized(READ_ROLES)
    rec = require_path("advisor_appointments", aid)
    case = get_case(rec["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(rec))


@bp.get("/advisor-appointments")
def list_appointments_filtered():
    authorized(["TitleIXCoordinator", "CaseAdministrator"])
    items = list(db["advisor_appointments"].values())
    items = apply_filters(items, {
        "advisor_id": request.args.get("advisor_id"),
        "replaced_by_appointment_id": request.args.get("replaced_by_appointment_id"),
        "status": request.args.get("status"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.post("/advisor-appointments/<aid>/withdraw")
def withdraw_appointment(aid):
    caller = authorized(["Advisor", "Party", "TitleIXCoordinator"])
    rec = require_path("advisor_appointments", aid)
    case = get_case(rec["case_id"])
    if rec["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"appointment is {rec['status']}, not ACTIVE")
    # Tier 8 party binding: the appointed advisor, the served party, or the
    # case coordinator may withdraw.
    served_party_id = case["complainant_id"] if rec["party_side"] == "COMPLAINANT" \
        else case["respondent_id"]
    allowed = (
        caller.user_id == rec["advisor_id"]
        or caller.user_id == served_party_id
        or caller.user_id == case["coordinator_id"]
    )
    if not allowed:
        raise_error(ERR_PARTY_BINDING_MISMATCH,
                    "only the appointed advisor, the served party, or the case coordinator may withdraw")
    rec["status"] = "WITHDRAWN"
    touch(rec)
    bump_case(case)
    append_event(case["id"], "ADVISOR_WITHDRAWN", caller,
                 {"appointment_id": aid, "status": "WITHDRAWN"})
    return success_object(public(rec))
