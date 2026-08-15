"""InformalResolution endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE_TRANSITION, ERR_FORBIDDEN_ROLE,
    ERR_INFORMAL_RESOLUTION_PROHIBITED, ERR_FORMAL_COMPLAINT_REQUIRED,
    ERR_ACTIVE_INFORMAL_RESOLUTION_EXISTS, ERR_DUPLICATE_RESOURCE,
    ERR_PARTY_BINDING_MISMATCH,
)
from middleware import authorized, check_case_read_access, party_side_of, STAFF_READ_ROLES
from response import success_list, success_object
from services.core import (
    new_record, touch, public, bump_case, append_event, auto_notice, get_case,
    check_case_not_terminal, get_pagination, sort_items, apply_filters,
    check_not_case_party, check_segregation, LIVE_IR_STATES, APPOINTMENT_SIDES,
)
from util import clock_iso
from validate import (
    get_body, req_str, req_enum, req_bool, require_path, require_profile_fk,
    as_enum, as_bool,
)

bp = Blueprint("informal", __name__)

READ_ROLES = STAFF_READ_ROLES + ["Party"]


@bp.post("/cases/<cid>/informal-resolutions")
def propose_informal(cid):
    caller = authorized(["TitleIXCoordinator"])
    case = get_case(cid)
    check_case_not_terminal(case)
    body = get_body()
    # Tier 3: body FK existence.
    require_profile_fk(body, "facilitator_id")
    facilitator_id = body.get("facilitator_id")
    if isinstance(facilitator_id, str):
        # Tier 5: party bar, segregation, then the employee/student prohibition.
        check_not_case_party(case, facilitator_id)
        check_segregation(case, facilitator_id, for_function="facilitator")
        complainant = db["party_profiles"].get(case["complainant_id"])
        respondent = db["party_profiles"].get(case["respondent_id"])
        if respondent is not None and complainant is not None \
                and respondent.get("role_type") == "EMPLOYEE" \
                and complainant.get("role_type") == "STUDENT":
            raise_error(ERR_INFORMAL_RESOLUTION_PROHIBITED,
                        "employee-on-student allegations may never resolve informally")
        # Tier 7: one live informal resolution per case; signed complaint required.
        if any(ir["case_id"] == cid and ir["status"] in LIVE_IR_STATES
               for ir in db["informal_resolutions"].values()):
            raise_error(ERR_ACTIVE_INFORMAL_RESOLUTION_EXISTS,
                        "another informal resolution on this case is still live")
        if not case.get("formal_complaint_signed"):
            raise_error(ERR_FORMAL_COMPLAINT_REQUIRED,
                        "informal resolution requires a signed formal complaint")
    # The case-machine trigger exists only from INVESTIGATION/EVIDENCE_REVIEW;
    # evaluated after the tier-7 constraint gates.
    if case["status"] not in ("INVESTIGATION", "EVIDENCE_REVIEW"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"informal resolution cannot be proposed from {case['status']}")
    facilitator_id = req_str(body, "facilitator_id")

    rec = new_record("informal_resolutions", {
        "case_id": cid,
        "facilitator_id": facilitator_id,
        "complainant_consent_at": None,
        "respondent_consent_at": None,
        "agreed_terms": None,
        "status": "PROPOSED",
        "withdrawn_by_side": None,
    })
    case["status"] = "INFORMAL_RESOLUTION_IN_PROGRESS"
    bump_case(case)
    append_event(cid, "INFORMAL_PROPOSED", caller,
                 {"informal_resolution_id": rec["id"], "facilitator_id": facilitator_id})
    auto_notice(cid, "INFORMAL_PROPOSAL", "BOTH",
                "An informal resolution has been proposed for this case.")
    append_event(cid, "NOTICE_SENT", caller,
                 {"notice_type": "INFORMAL_PROPOSAL", "recipient_side": "BOTH"})
    return success_object(public(rec), 201)


@bp.get("/cases/<cid>/informal-resolutions")
def list_informal(cid):
    caller = authorized(READ_ROLES)
    case = get_case(cid)
    check_case_read_access(caller, case)
    items = [ir for ir in db["informal_resolutions"].values() if ir["case_id"] == cid]
    items = apply_filters(items, {"status": request.args.get("status")})
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.get("/informal-resolutions/<iid>")
def get_informal(iid):
    caller = authorized(READ_ROLES)
    ir = require_path("informal_resolutions", iid)
    case = get_case(ir["case_id"])
    check_case_read_access(caller, case)
    return success_object(public(ir))


@bp.get("/informal-resolutions")
def list_informal_filtered():
    authorized(["TitleIXCoordinator", "CaseAdministrator"])
    items = list(db["informal_resolutions"].values())
    items = apply_filters(items, {
        "facilitator_id": request.args.get("facilitator_id"),
        "status": request.args.get("status"),
    })
    items = sort_items(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public(r) for r in page], total, limit, offset)


@bp.post("/informal-resolutions/<iid>/consent")
def record_consent(iid):
    caller = authorized(["Party"])
    ir = require_path("informal_resolutions", iid)
    case = get_case(ir["case_id"])
    body = get_body()
    if ir["status"] not in ("PROPOSED", "IN_PROGRESS"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"informal resolution is {ir['status']}")
    side = as_enum(body, "party_side", APPOINTMENT_SIDES)
    consent_val = as_bool(body, "consent")
    if side is not None and consent_val is not None:
        # Tier 7: duplicate consent by the same party.
        if consent_val is True and ir.get(f"{side.lower()}_consent_at") is not None:
            raise_error(ERR_DUPLICATE_RESOURCE,
                        f"the {side} has already consented")
        # A decline exists only from PROPOSED; from IN_PROGRESS use withdraw.
        if consent_val is False and ir["status"] == "IN_PROGRESS":
            raise_error(ERR_INVALID_STATE_TRANSITION,
                        "consent decline is only available from PROPOSED")
        # Tier 8: party binding.
        actor_side = party_side_of(case, caller.user_id)
        if actor_side is None or side != actor_side:
            raise_error(ERR_PARTY_BINDING_MISMATCH,
                        "party_side does not match the acting party's binding on the case")
    # Tier 11: schema.
    party_side = req_enum(body, "party_side", APPOINTMENT_SIDES)
    consent = req_bool(body, "consent")

    now = clock_iso()
    if consent:
        ir[f"{party_side.lower()}_consent_at"] = now
        touch(ir)
        append_event(case["id"], "INFORMAL_CONSENT_RECORDED", caller,
                     {"informal_resolution_id": iid, "party_side": party_side})
        if ir.get("complainant_consent_at") is not None \
                and ir.get("respondent_consent_at") is not None \
                and ir["status"] == "PROPOSED":
            ir["status"] = "IN_PROGRESS"
            touch(ir)
        bump_case(case)
    else:
        ir["status"] = "TERMINATED"
        touch(ir)
        case["status"] = "INVESTIGATION"
        bump_case(case)
        append_event(case["id"], "INFORMAL_TERMINATED", caller,
                     {"informal_resolution_id": iid, "status": "TERMINATED"})
        append_event(case["id"], "CASE_RESUMED", caller, {"status": "INVESTIGATION"})
    return success_object(public(ir))


@bp.post("/informal-resolutions/<iid>/withdraw")
def withdraw_informal(iid):
    caller = authorized(["Party"])
    ir = require_path("informal_resolutions", iid)
    case = get_case(ir["case_id"])
    if ir["status"] not in ("PROPOSED", "IN_PROGRESS"):
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"informal resolution is {ir['status']}")
    # Tier 8: only a case party may withdraw.
    actor_side = party_side_of(case, caller.user_id)
    if actor_side is None:
        raise_error(ERR_PARTY_BINDING_MISMATCH,
                    "only the complainant or respondent may withdraw the resolution")
    ir["status"] = "WITHDRAWN"
    ir["withdrawn_by_side"] = actor_side
    touch(ir)
    case["status"] = "INVESTIGATION"
    bump_case(case)
    append_event(case["id"], "INFORMAL_WITHDRAWN", caller,
                 {"informal_resolution_id": iid, "withdrawn_by_side": actor_side})
    append_event(case["id"], "CASE_RESUMED", caller, {"status": "INVESTIGATION"})
    return success_object(public(ir))


@bp.post("/informal-resolutions/<iid>/resolve")
def resolve_informal(iid):
    caller = authorized(["TitleIXCoordinator"])
    ir = require_path("informal_resolutions", iid)
    case = get_case(ir["case_id"])
    if ir["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE_TRANSITION,
                    f"informal resolution is {ir['status']}, not IN_PROGRESS")
    if caller.user_id != case["coordinator_id"]:
        raise_error(ERR_FORBIDDEN_ROLE,
                    "only the case's coordinator may record the resolution")
    body = get_body()
    agreed_terms = req_str(body, "agreed_terms")
    now = clock_iso()
    ir["agreed_terms"] = agreed_terms
    ir["status"] = "RESOLVED"
    touch(ir)
    case["status"] = "RESOLVED_INFORMAL"
    case["closed_at"] = now
    bump_case(case)
    append_event(case["id"], "INFORMAL_RESOLVED", caller,
                 {"informal_resolution_id": iid, "status": "RESOLVED"})
    append_event(case["id"], "CASE_CLOSED", caller, {"status": "RESOLVED_INFORMAL"})
    return success_object(public(ir))
