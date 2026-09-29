"""Complaint cases, exposure recomputation and the remediation track."""

from flask import Blueprint

import auth
import calc
import cascades
import listing
import serialize
import validation as v
from auth import authorize, check_action_role, check_complaint_channel
from envelope import created, ok
from errors import ApiError
from store import db, add_days, base_row, touch
from validation import MISSING, as_enum, as_int, as_string, field, parse_body

bp = Blueprint("complaints", __name__)

SOURCES = ("NETWORK", "ATTORNEY_GENERAL", "CARDHOLDER")
ALLEGATION_TYPES = ("UNDISCLOSED_SURCHARGE", "DEBIT_SURCHARGED", "CAP_EXCEEDED",
                    "MISSING_RECEIPT_LINE", "PROHIBITED_JURISDICTION", "PRICE_POSTING_MISSING")
INVESTIGATION_STATES = ("OPEN", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED")
REMEDIATION_STATES = ("NONE", "PLAN_REQUIRED", "PLAN_SUBMITTED", "PLAN_ACCEPTED", "CLOSED")
INVESTIGATION_ACTIONS = ("REVIEW", "SUBSTANTIATE", "DISMISS")
REMEDIATION_ACTIONS = ("SUBMIT_PLAN", "ACCEPT_PLAN", "CLOSE")


@bp.post("/complaint-cases")
def file_complaint():
    actor = authorize(["NetworkAuditor", "StateRegulator"])
    body, malformed = parse_body()

    # Step 7: channel ownership, ahead of the request-shape step.
    raw_source = None if malformed else field(body, "source")
    check_complaint_channel(actor, raw_source if isinstance(raw_source, str) else None)

    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["program_id", "source", "allegation_type", "narrative"])
    program_id = as_string(body["program_id"], "program_id", 1)
    source = as_enum(body["source"], "source", SOURCES)
    allegation_type = as_enum(body["allegation_type"], "allegation_type", ALLEGATION_TYPES)
    narrative = as_string(body["narrative"], "narrative", 1, 2000)

    program = auth.get_program(program_id)

    received_at = db.now()
    row = base_row()
    row.update({
        "program_id": program["id"],
        "source": source,
        "allegation_type": allegation_type,
        "narrative": narrative,
        "filed_by_user_id": actor.user_id,
        "received_at": received_at,
        "response_due_at": add_days(received_at, calc.RESPONSE_WINDOW_DAYS[source]),
        "investigation_state": "OPEN",
        "remediation_state": "NONE",
        "reviewed_by_user_id": None,
        "plan_summary": None,
    })
    db.complaint_cases[row["id"]] = row

    # A merely open case already scores under the attorney-general method.
    calc.recompute_exposure(program, network=False, ag=True)

    return created(serialize.complaint_case(row))


@bp.get("/complaint-cases/<case_id>")
def read_complaint(case_id):
    authorize(auth.READ_ROLES)
    return ok(serialize.complaint_case(auth.get_complaint_case(case_id)))


@bp.get("/complaint-cases")
def list_complaints():
    authorize(auth.READ_ROLES)
    rows = listing.filtered(list(db.complaint_cases.values()), [
        (listing.arg("program_id"), "program_id"),
        (listing.enum_arg("source", SOURCES), "source"),
        (listing.enum_arg("investigation_state", INVESTIGATION_STATES), "investigation_state"),
        (listing.enum_arg("remediation_state", REMEDIATION_STATES), "remediation_state"),
    ])
    return listing.list_response(rows, serialize.complaint_case)


@bp.post("/complaint-cases/<case_id>/investigation-actions")
def investigation_action(case_id):
    actor = authorize(["ComplianceOfficer", "NetworkAuditor", "StateRegulator"])
    body, malformed = parse_body()
    raw_action = None if malformed else field(body, "action")
    check_action_role("investigation", raw_action, actor)
    case = auth.get_complaint_case(case_id)
    check_complaint_channel(actor, case["source"])
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["action"])
    action = as_enum(body["action"], "action", INVESTIGATION_ACTIONS)
    note_raw = field(body, "note")
    if note_raw is not MISSING and note_raw is not None:
        as_string(note_raw, "note", 1, 2000)

    program = db.programs.get(case["program_id"])

    if action == "REVIEW":
        if case["investigation_state"] != "OPEN":
            raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                           "Only an OPEN case can be moved under review.")
        case["investigation_state"] = "UNDER_REVIEW"
        case["reviewed_by_user_id"] = actor.user_id
        touch(case)
        if program is not None:
            calc.recompute_exposure(program, network=False, ag=True)
    elif action == "SUBSTANTIATE":
        if case["investigation_state"] not in ("OPEN", "UNDER_REVIEW"):
            raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                           "Only an OPEN or UNDER_REVIEW case can be substantiated.")
        case["investigation_state"] = "SUBSTANTIATED"
        case["remediation_state"] = "PLAN_REQUIRED"
        touch(case)
        if program is not None:
            network_score, _ = calc.recompute_exposure(program, network=True, ag=True)
            if (network_score >= calc.REMEDIATION_EXPOSURE_THRESHOLD
                    and program["status"] == "ACTIVE"):
                cascades.remediation_cascade(program)
    else:
        if case["investigation_state"] not in ("OPEN", "UNDER_REVIEW"):
            raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                           "Only an OPEN or UNDER_REVIEW case can be dismissed.")
        case["investigation_state"] = "DISMISSED"
        touch(case)
        if program is not None:
            calc.recompute_exposure(program, network=True, ag=True)

    return ok(serialize.complaint_case(case))


@bp.post("/complaint-cases/<case_id>/remediation-actions")
def remediation_action(case_id):
    actor = authorize(["ComplianceOfficer", "NetworkAuditor", "StateRegulator"])
    body, malformed = parse_body()
    raw_action = None if malformed else field(body, "action")
    check_action_role("remediation", raw_action, actor)
    case = auth.get_complaint_case(case_id)
    check_complaint_channel(actor, case["source"])
    if malformed:
        raise v.bad("The request body must be a JSON object.")
    v.require_present(body, ["action"])
    action = as_enum(body["action"], "action", REMEDIATION_ACTIONS)
    plan_raw = field(body, "plan_summary")
    plan_summary = None
    if action == "SUBMIT_PLAN":
        if plan_raw is MISSING or plan_raw is None:
            raise v.bad("Field 'plan_summary' is required for SUBMIT_PLAN.")
        plan_summary = as_string(plan_raw, "plan_summary", 1, 2000)
    elif plan_raw is not MISSING and plan_raw is not None:
        as_string(plan_raw, "plan_summary", 1, 2000)

    if action == "SUBMIT_PLAN":
        if case["remediation_state"] != "PLAN_REQUIRED":
            raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                           "A remediation plan can only be submitted from PLAN_REQUIRED.")
        case["remediation_state"] = "PLAN_SUBMITTED"
        case["plan_summary"] = plan_summary
        touch(case)
    elif action == "ACCEPT_PLAN":
        if case["remediation_state"] != "PLAN_SUBMITTED":
            raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                           "A remediation plan can only be accepted from PLAN_SUBMITTED.")
        case["remediation_state"] = "PLAN_ACCEPTED"
        touch(case)
    else:
        if case["remediation_state"] != "PLAN_ACCEPTED":
            raise ApiError("ERR_INVALID_COMPLAINT_STATE",
                           "A case can only be closed from PLAN_ACCEPTED.")
        for refund in calc.case_refunds(case["id"]):
            if refund["state"] == "PENDING":
                raise ApiError("ERR_REMEDIATION_REFUNDS_PENDING",
                               "A refund of this case is still PENDING.")
        case["remediation_state"] = "CLOSED"
        touch(case)
        cascades.bubble_up_remediation_close(case)

    return ok(serialize.complaint_case(case))
