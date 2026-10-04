"""Disciplinary cases and due process (PRD §3.9): interim actions bite at
creation; the rehearing loop; sanctions deferred to FINAL; cascades fire on
finalization."""

from flask import Blueprint, request

from db import (APPEAL_WINDOW_DAYS, RESPONSE_WINDOW_DAYS, STORE, base_entity,
                now_dt, serialize, touch)
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, opt_enum,
                        opt_list, req_enum, req_int, req_str)
from services.cascade import apply_sanction_cascade
from util import add_days

bp = Blueprint("cases", __name__)

VIOLATION_TYPES = ["EXAM_SECURITY", "FALSIFIED_EDUCATION", "CRIMINAL_CONDUCT"]
INTERIM_ACTIONS = ["NONE", "SUSPEND_CERTIFICATION", "HOLD_NEW_APPLICATIONS"]
SANCTION_TYPES = ["NONE", "WARNING", "SUSPENSION_12M", "REVOCATION", "PERMANENT_BAR"]


@bp.post("/registry/disciplinary-cases")
def open_case():
    uid, _ = authn(["RegistryAdmin", "StateOfficial"])
    b = body()
    subject_candidate_id = req_str(b, "subject_candidate_id")
    violation_type = req_enum(b, "violation_type", VIOLATION_TYPES)
    description = req_str(b, "description")
    interim_action = opt_enum(b, "interim_action", INTERIM_ACTIONS, "NONE")
    implicated_attempts = opt_list(b, "implicated_attempt_ids", []) or []
    implicated_records = opt_list(b, "implicated_completion_record_ids", []) or []

    if subject_candidate_id not in STORE.candidates:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % subject_candidate_id)
    for aid in implicated_attempts:
        if aid not in STORE.attempts:
            raise_err("ERR_NOT_FOUND", "CognitiveExamAttempt %s does not exist" % aid)
    for rid in implicated_records:
        if rid not in STORE.completions:
            raise_err("ERR_NOT_FOUND", "ProgramCompletionRecord %s does not exist" % rid)

    e = base_entity()
    e.update({
        "subject_candidate_id": subject_candidate_id,
        "violation_type": violation_type,
        "description": description,
        "opened_by_user_id": uid,
        "interim_action": interim_action,
        "implicated_attempt_ids": list(implicated_attempts),
        "implicated_completion_record_ids": list(implicated_records),
        "hearing_officer_user_id": None,
        "sanction_type": None,
        "findings": None,
        "response_deadline": None,
        "appeal_deadline": None,
        "decided_at": None,
        "finalized_at": None,
        "rehearing_count": 0,
        "status": "OPENED",
    })
    STORE.cases[e["id"]] = e

    # Interim actions apply immediately at creation.
    if interim_action == "SUSPEND_CERTIFICATION":
        for cert in STORE.certifications.values():
            if (cert["candidate_id"] == subject_candidate_id
                    and cert["status"] == "ACTIVE"):
                cert["pre_sanction_status"] = "ACTIVE"
                cert["status"] = "SUSPENDED"
                cert["_suspended_by_case_id"] = e["id"]
                touch(cert)

    return ok_object(serialize(e), 201)


@bp.get("/registry/disciplinary-cases")
def list_cases():
    authn(ALL_AUTHENTICATED_ROLES)
    subject = request.args.get("subject_candidate_id")
    status = request.args.get("status")
    implicated_attempt = request.args.get("implicated_attempt_ids")
    implicated_record = request.args.get("implicated_completion_record_ids")
    items = []
    for c in STORE.cases.values():
        if subject is not None and c["subject_candidate_id"] != subject:
            continue
        if status is not None and c["status"] != status:
            continue
        if implicated_attempt is not None and implicated_attempt not in (c.get("implicated_attempt_ids") or []):
            continue
        if implicated_record is not None and implicated_record not in (c.get("implicated_completion_record_ids") or []):
            continue
        items.append(c)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(c) for c in page], total, limit, offset)


@bp.get("/registry/disciplinary-cases/<cid>")
def get_case(cid):
    authn(ALL_AUTHENTICATED_ROLES)
    c = STORE.cases.get(cid)
    if not c:
        raise_err("ERR_NOT_FOUND", "DisciplinaryCase %s does not exist" % cid)
    return ok_object(serialize(c), 200)


def _stage_gate(case, allowed):
    if case["status"] not in allowed:
        raise_err("ERR_CASE_STAGE_MISMATCH",
                  "Case is %s; this action requires %s"
                  % (case["status"], " or ".join(allowed)))


@bp.post("/registry/disciplinary-cases/<cid>/issue-notice")
def issue_notice(cid):
    authn(["RegistryAdmin"])
    case = STORE.cases.get(cid)
    if not case:
        raise_err("ERR_NOT_FOUND", "DisciplinaryCase %s does not exist" % cid)
    _stage_gate(case, ["OPENED"])
    case["status"] = "NOTICE_ISSUED"
    case["response_deadline"] = add_days(now_dt(), RESPONSE_WINDOW_DAYS)
    touch(case)
    return ok_object(serialize(case), 200)


@bp.post("/registry/disciplinary-cases/<cid>/response")
def record_response(cid):
    uid, _ = authn(["Candidate"])
    case = STORE.cases.get(cid)
    if not case:
        raise_err("ERR_NOT_FOUND", "DisciplinaryCase %s does not exist" % cid)
    if case["subject_candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the subject candidate may respond")
    _stage_gate(case, ["NOTICE_ISSUED"])
    case["status"] = "UNDER_REVIEW"
    touch(case)
    return ok_object(serialize(case), 200)


@bp.post("/registry/disciplinary-cases/<cid>/schedule-hearing")
def schedule_hearing(cid):
    uid, _ = authn(["HearingOfficer"])
    case = STORE.cases.get(cid)
    if not case:
        raise_err("ERR_NOT_FOUND", "DisciplinaryCase %s does not exist" % cid)
    _stage_gate(case, ["UNDER_REVIEW", "REHEARING"])
    if uid == case["opened_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The hearing officer must differ from the case opener")
    case["hearing_officer_user_id"] = uid
    case["status"] = "HEARING_SCHEDULED"
    touch(case)
    return ok_object(serialize(case), 200)


@bp.post("/registry/disciplinary-cases/<cid>/decide")
def decide_case(cid):
    uid, _ = authn(["HearingOfficer"])
    b = body()
    sanction_type = req_enum(b, "sanction_type", SANCTION_TYPES)
    findings = req_str(b, "findings")
    expected_version = req_int(b, "expected_case_version")
    case = STORE.cases.get(cid)
    if not case:
        raise_err("ERR_NOT_FOUND", "DisciplinaryCase %s does not exist" % cid)
    if expected_version != case["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_case_version %s does not match current version %s"
                  % (expected_version, case["version"]))
    _stage_gate(case, ["HEARING_SCHEDULED"])
    if uid == case["opened_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The hearing officer must differ from the case opener")
    now = now_dt()
    case["sanction_type"] = sanction_type
    case["findings"] = findings
    case["decided_at"] = now
    case["appeal_deadline"] = add_days(now, APPEAL_WINDOW_DAYS)
    case["status"] = "DECIDED"
    touch(case)
    return ok_object(serialize(case), 200)


@bp.post("/registry/disciplinary-cases/<cid>/appeal")
def appeal_case(cid):
    uid, _ = authn(["Candidate"])
    b = body()
    grounds = b.get("appeal_grounds")
    if grounds is not None and not isinstance(grounds, str):
        raise_err("ERR_INVALID_REQUEST", "Field 'appeal_grounds' must be a string")
    case = STORE.cases.get(cid)
    if not case:
        raise_err("ERR_NOT_FOUND", "DisciplinaryCase %s does not exist" % cid)
    if case["subject_candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the subject candidate may appeal")
    # A late appeal observes FINAL (the sweep finalizes expired DECIDED cases),
    # so the stage check below catches it.
    _stage_gate(case, ["DECIDED"])
    case["status"] = "APPEAL_PENDING"
    touch(case)
    return ok_object(serialize(case), 200)


@bp.post("/registry/disciplinary-cases/<cid>/appeal-decision")
def appeal_decision(cid):
    authn(["RegistryAdmin"])
    b = body()
    outcome = req_enum(b, "outcome", ["AFFIRMED", "OVERTURNED"])
    case = STORE.cases.get(cid)
    if not case:
        raise_err("ERR_NOT_FOUND", "DisciplinaryCase %s does not exist" % cid)
    _stage_gate(case, ["APPEAL_PENDING"])
    if outcome == "AFFIRMED":
        case["status"] = "FINAL"
        case["finalized_at"] = now_dt()
        touch(case)
        apply_sanction_cascade(case)
    else:
        # OVERTURNED: rehearing cycle; no sanction has been applied, so no
        # compensation is required — just clear the decision fields.
        case["status"] = "REHEARING"
        case["sanction_type"] = None
        case["findings"] = None
        case["decided_at"] = None
        case["appeal_deadline"] = None
        case["rehearing_count"] += 1
        touch(case)
    return ok_object(serialize(case), 200)
