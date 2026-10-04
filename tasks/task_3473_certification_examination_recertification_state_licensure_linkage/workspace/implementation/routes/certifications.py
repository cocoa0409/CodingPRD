"""Certification issuance (PRD §3.5): explicit basis references, freshness
windows, one ACTIVE certification per candidate+level."""

from flask import Blueprint, request

from db import (STORE, base_entity, now_dt, program_accredited_at_completion,
                serialize, within_validity_window)
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import ALL_AUTHENTICATED_ROLES, authn, body, req_str
from util import add_months

bp = Blueprint("certifications", __name__)


@bp.post("/registry/certifications/issue")
def issue_certification():
    authn(["RegistryAdmin"])
    b = body()
    candidate_id = req_str(b, "candidate_id")
    level_id = req_str(b, "level_id")
    exam_application_id = req_str(b, "exam_application_id")
    attempt_id = req_str(b, "attempt_id")
    psychomotor_id = req_str(b, "psychomotor_id")

    candidate = STORE.candidates.get(candidate_id)
    if not candidate:
        raise_err("ERR_NOT_FOUND", "Candidate %s does not exist" % candidate_id)
    if level_id not in STORE.levels:
        raise_err("ERR_NOT_FOUND", "LevelDefinition %s does not exist" % level_id)
    app = STORE.exam_apps.get(exam_application_id)
    if not app:
        raise_err("ERR_NOT_FOUND", "ExamApplication %s does not exist" % exam_application_id)
    attempt = STORE.attempts.get(attempt_id)
    if not attempt:
        raise_err("ERR_NOT_FOUND", "CognitiveExamAttempt %s does not exist" % attempt_id)
    pv = STORE.psychomotors.get(psychomotor_id)
    if not pv:
        raise_err("ERR_NOT_FOUND", "PsychomotorVerification %s does not exist" % psychomotor_id)

    # Compliance gates.
    if candidate["status"] == "BARRED":
        raise_err("ERR_PERMANENTLY_BARRED", "Candidate is BARRED")
    record = STORE.completions.get(app["completion_record_id"])
    if record and not program_accredited_at_completion(record):
        raise_err("ERR_PROGRAM_NOT_ACCREDITED_AT_COMPLETION",
                  "Program accreditation at the completion date was not ACCREDITED or PROVISIONAL")

    # Cross-record consistency: every reference must agree on candidate and
    # level, and each basis record must carry the required status.
    if app["candidate_id"] != candidate_id or app["level_id"] != level_id:
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Exam application belongs to a different candidate or level")
    if app["status"] != "APPROVED":
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Exam application is not APPROVED")
    att = STORE.atts.get(attempt["att_id"])
    if not att or att["exam_application_id"] != app["id"]:
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Attempt was not scheduled against this application's ATT")
    if (attempt["candidate_id"] != candidate_id or attempt["level_id"] != level_id
            or attempt["status"] != "SCORED_PASS"):
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Attempt is not a SCORED_PASS for this candidate and level")
    if (pv["candidate_id"] != candidate_id or pv["level_id"] != level_id
            or pv["status"] != "VERIFIED"):
        raise_err("ERR_CROSS_REFERENCE_MISMATCH",
                  "Psychomotor verification is not VERIFIED for this candidate and level")

    # Temporal gates: education validity + credential freshness.
    if not record or record["status"] != "VERIFIED" or not within_validity_window(record):
        raise_err("ERR_EDUCATION_VALIDITY_EXPIRED",
                  "Completion record is not VERIFIED and inside its 24-month validity window")
    now = now_dt()
    if attempt["delivered_at"] is None or now > add_months(attempt["delivered_at"], 24):
        raise_err("ERR_CREDENTIAL_STALE",
                  "The cognitive pass was delivered more than 24 months ago")
    if pv["verified_at"] is None or now > add_months(pv["verified_at"], 24):
        raise_err("ERR_CREDENTIAL_STALE",
                  "The psychomotor verification is more than 24 months old")

    # One ACTIVE certification per candidate+level.
    for c in STORE.certifications.values():
        if (c["candidate_id"] == candidate_id and c["level_id"] == level_id
                and c["status"] == "ACTIVE"):
            raise_err("ERR_DUPLICATE_ACTIVE_CERTIFICATION",
                      "An ACTIVE certification already exists for this candidate and level")

    e = base_entity()
    expires = add_months(now, 24)
    e.update({
        "candidate_id": candidate_id,
        "level_id": level_id,
        "basis_completion_record_id": app["completion_record_id"],
        "basis_attempt_id": attempt_id,
        "basis_psychomotor_id": psychomotor_id,
        "issued_on": now,
        "expires_on": expires,
        "lapse_deadline": add_months(expires, 48),
        "renewed_count": 0,
        "status": "ACTIVE",
        "suspension_ends": None,
        "pre_sanction_status": None,
        "revoked_by_case_id": None,
        "_suspended_by_case_id": None,
    })
    STORE.certifications[e["id"]] = e
    return ok_object(serialize(e), 201)


@bp.get("/registry/certifications")
def list_certifications():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    level_id = request.args.get("level_id")
    status = request.args.get("status")
    basis_completion = request.args.get("basis_completion_record_id")
    basis_attempt = request.args.get("basis_attempt_id")
    basis_psychomotor = request.args.get("basis_psychomotor_id")
    revoked_by = request.args.get("revoked_by_case_id")
    items = []
    for c in STORE.certifications.values():
        if candidate_id is not None and c["candidate_id"] != candidate_id:
            continue
        if level_id is not None and c["level_id"] != level_id:
            continue
        if status is not None and c["status"] != status:
            continue
        if basis_completion is not None and c["basis_completion_record_id"] != basis_completion:
            continue
        if basis_attempt is not None and c["basis_attempt_id"] != basis_attempt:
            continue
        if basis_psychomotor is not None and c["basis_psychomotor_id"] != basis_psychomotor:
            continue
        if revoked_by is not None and c.get("revoked_by_case_id") != revoked_by:
            continue
        items.append(c)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(c) for c in page], total, limit, offset)


@bp.get("/registry/certifications/<cid>")
def get_certification(cid):
    authn(ALL_AUTHENTICATED_ROLES)
    c = STORE.certifications.get(cid)
    if not c:
        raise_err("ERR_NOT_FOUND", "Certification %s does not exist" % cid)
    return ok_object(serialize(c), 200)
