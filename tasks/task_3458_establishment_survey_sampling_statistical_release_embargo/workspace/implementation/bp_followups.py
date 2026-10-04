"""/survey/follow-up-cases: list, read, advance (PRD 3.4)."""
from flask import Blueprint, request

from authz import get_auth, require_role
from bp_programs import find_program_by_code
from burden import burden_apply, burden_would_fit
from envelope import ok, ok_list, paginate
from errors import (
    raise_err, ERR_VALIDATION, ERR_CASE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_CONTACT_TOO_SOON, ERR_CONTACT_ALREADY_VOIDED, ERR_NO_CONTACT_RECORDED,
    ERR_ESCALATION_TOO_EARLY, ERR_BURDEN_BUDGET_EXCEEDED,
)
from store import (
    DB, sorted_entities, touch, now,
    CONTACT_MIN_MINUTES, CONTACT_MAX_MINUTES, CONTACT_SPACING,
    ESCALATION_MIN_CONTACTS, ESCALATION_MIN_AGE, LIVE_CASE_STATUSES,
)
from validate import get_body, req_str, req_int

bp = Blueprint("followups", __name__)

ACTIONS = {"RECORD_CONTACT", "VOID_CONTACT", "ESCALATE", "CLOSE"}


@bp.get("/follow-up-cases")
def list_cases():
    get_auth()
    items = sorted_entities("cases")
    for param in ("enrollment_id", "cycle_id", "case_status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c[param] == value]
    page, pagination = paginate(items)
    return ok_list(page, pagination)


def _load_case(cid):
    case = DB["cases"].get(cid)
    if case is None:
        raise_err(ERR_CASE_NOT_FOUND, "follow-up case not found")
    return case


@bp.get("/follow-up-cases/<cid>")
def get_case(cid):
    get_auth()
    return ok(_load_case(cid))


def _nonvoided_contacts(case):
    return [c for c in case["contacts"] if not c["voided"]]


def _refresh_total(case):
    case["total_contact_minutes"] = sum(
        c["contact_minutes"] for c in case["contacts"] if not c["voided"])


def _record_contact(case, data):
    minutes = req_int(data, "contact_minutes",
                      minimum=CONTACT_MIN_MINUTES, maximum=CONTACT_MAX_MINUTES)
    channel = req_str(data, "channel")
    if case["case_status"] not in LIVE_CASE_STATUSES:
        raise_err(ERR_INVALID_STATE,
                  f"cannot record a contact on a case in {case['case_status']}")
    history = _nonvoided_contacts(case)
    if history:
        last = max(history, key=lambda c: c["seq"])
        if now() < last["contacted_at"] + CONTACT_SPACING:
            raise_err(ERR_CONTACT_TOO_SOON,
                      "less than 24h since the last non-voided contact")
    enrollment = DB["enrollments"].get(case["enrollment_id"])
    program = find_program_by_code(enrollment["program_code"]) if enrollment else None
    if enrollment is not None and program is not None:
        if not burden_would_fit(enrollment, program, minutes):
            raise_err(ERR_BURDEN_BUDGET_EXCEEDED,
                      "contact would exceed the annual burden budget")
    seq = max((c["seq"] for c in case["contacts"]), default=0) + 1
    case["contacts"].append({
        "seq": seq,
        "contact_minutes": minutes,
        "channel": channel,
        "contacted_at": now(),
        "voided": False,
    })
    if case["case_status"] == "OPEN":
        case["case_status"] = "IN_CONTACT"
    _refresh_total(case)
    touch(case)
    if enrollment is not None:
        burden_apply(enrollment, minutes)


def _void_contact(case, data):
    seq = req_int(data, "contact_seq")
    entry = next((c for c in case["contacts"] if c["seq"] == seq), None)
    if entry is None:
        raise_err(ERR_VALIDATION, f"no contact with seq {seq} on this case")
    if case["case_status"] not in LIVE_CASE_STATUSES:
        raise_err(ERR_INVALID_STATE,
                  f"cannot void a contact on a case in {case['case_status']}")
    if entry["voided"]:
        raise_err(ERR_CONTACT_ALREADY_VOIDED, "contact is already voided")
    entry["voided"] = True
    _refresh_total(case)
    touch(case)
    enrollment = DB["enrollments"].get(case["enrollment_id"])
    if enrollment is not None:
        burden_apply(enrollment, -entry["contact_minutes"])


def _escalate(case):
    if case["case_status"] != "IN_CONTACT":
        raise_err(ERR_INVALID_STATE,
                  f"cannot escalate a case in {case['case_status']}")
    if (len(_nonvoided_contacts(case)) < ESCALATION_MIN_CONTACTS
            or now() < case["opened_at"] + ESCALATION_MIN_AGE):
        raise_err(ERR_ESCALATION_TOO_EARLY,
                  "escalation requires >= 2 non-voided contacts and 7 days since opened_at")
    case["case_status"] = "ESCALATED"
    touch(case)


def _close(case, data):
    outcome = req_str(data, "outcome")
    if outcome not in ("REFUSED", "UNRESPONSIVE"):
        raise_err(ERR_VALIDATION, "outcome must be REFUSED or UNRESPONSIVE")
    status = case["case_status"]
    if outcome == "REFUSED":
        if status not in LIVE_CASE_STATUSES:
            raise_err(ERR_INVALID_STATE, f"cannot close a case in {status}")
        if not _nonvoided_contacts(case):
            raise_err(ERR_NO_CONTACT_RECORDED,
                      "closing as REFUSED requires at least one non-voided contact")
        case["case_status"] = "CLOSED_REFUSED"
    else:  # UNRESPONSIVE: terminal stage of pursuit, ESCALATED only
        if status != "ESCALATED":
            raise_err(ERR_INVALID_STATE,
                      f"cannot close as UNRESPONSIVE from {status}")
        case["case_status"] = "CLOSED_UNRESPONSIVE"
    touch(case)


@bp.post("/follow-up-cases/<cid>/advance")
def advance_case(cid):
    _user, role = get_auth()
    require_role(role, {"CollectionOfficer"})
    case = _load_case(cid)
    data = get_body()
    action = req_str(data, "action")
    if action not in ACTIONS:
        raise_err(ERR_VALIDATION, f"unknown case action '{action}'")
    if action == "RECORD_CONTACT":
        _record_contact(case, data)
    elif action == "VOID_CONTACT":
        _void_contact(case, data)
    elif action == "ESCALATE":
        _escalate(case)
    elif action == "CLOSE":
        _close(case, data)
    return ok(case)
