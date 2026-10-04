"""Registries: candidates, jurisdictions, supervisors (PRD section 3.1)."""
from flask import Blueprint

from auth import get_body, require_candidate_identity, require_roles
from dates import parse_date
from envelope import ok
from errors import fail
from serializers import ser_candidate, ser_jurisdiction, ser_supervisor
from services import (credit_tier_for, credited_for, jurisdiction_by_code,
                      live_certificate_of, open_disciplinary_count,
                      verified_area_sums)
from store import db, new_id, stamp_new, today, touch

bp = Blueprint("registry", __name__)


def _get_candidate_or_404(candidate_id):
    cand = db["candidates"].get(candidate_id)
    if cand is None:
        fail("ERR_NOT_FOUND", "candidate not found")
    return cand


def _require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        fail("ERR_INVALID_REQUEST", "%s is required" % field)
    return v


# ------------------------------------------------------------- candidates

@bp.post("/candidates")
def create_candidate():
    require_roles("Anonymous")
    body = get_body()
    hjc = body.get("home_jurisdiction_code")
    # Tier 3: jurisdiction resolution (only meaningful when the value exists).
    if hjc is not None and jurisdiction_by_code(hjc) is None:
        fail("ERR_JURISDICTION_UNKNOWN", "home_jurisdiction_code does not resolve")
    # Tier 8: required fields and uniqueness.
    email = _require_str(body, "email")
    full_name = _require_str(body, "full_name")
    password = _require_str(body, "password")
    if hjc is None:
        fail("ERR_INVALID_REQUEST", "home_jurisdiction_code is required")
    for c in db["candidates"].values():
        if c["email"] == email:
            fail("ERR_INVALID_REQUEST", "email is already registered")
    rec = stamp_new({
        "id": new_id(),
        "email": email,
        "full_name": full_name,
        "password": password,  # stored, never returned
        "home_jurisdiction_code": hjc,
        "education_status": "NONE",
        "experience_status": "NOT_STARTED",
        "exam_status": "NOT_AUTHORIZED",
        "certificate_eligible": False,
        "record_standing": "CLEAR",
    })
    db["candidates"][rec["id"]] = rec
    return ok(ser_candidate(rec), 201)


@bp.get("/candidates/<cid>")
def get_candidate(cid):
    uid, role = require_roles("Candidate", "NcarbAdministrator", "BoardAdministrator")
    if role == "Candidate":
        require_candidate_identity(uid, cid)
    cand = _get_candidate_or_404(cid)
    return ok(ser_candidate(cand))


@bp.get("/candidates/<cid>/summary")
def get_candidate_summary(cid):
    uid, role = require_roles("Candidate", "NcarbAdministrator", "BoardAdministrator")
    if role == "Candidate":
        require_candidate_identity(uid, cid)
    cand = _get_candidate_or_404(cid)
    sums = verified_area_sums(cid)
    total = sum(sums.values())
    # Locked: VERIFIED credited_hours plus in-flight (SUBMITTED) reports at the
    # tier stamped at submission; DRAFT rows carry credit_pct 0 so add nothing.
    locked = total
    projected = total
    current = today()
    for r in db["reports"].values():
        if r["candidate_id"] != cid:
            continue
        if r["status"] == "SUBMITTED":
            locked += credited_for(r["hours"], r["credit_pct"])
        if r["status"] in ("DRAFT", "SUBMITTED"):
            # What-if: re-tier against the current date; too-old reports count 0.
            tier = credit_tier_for(current, parse_date(r["work_period_end"]))
            if tier is not None:
                projected += credited_for(r["hours"], tier)
    certs = sorted(
        (c for c in db["certificates"].values() if c["candidate_id"] == cid),
        key=lambda c: c["created_at"])
    live = live_certificate_of(cid)
    cert_for_status = live if live is not None else (certs[-1] if certs else None)
    return ok({
        "candidate_id": cid,
        "education_status": cand["education_status"],
        "experience_status": cand["experience_status"],
        "exam_status": cand["exam_status"],
        "record_standing": cand["record_standing"],
        "certificate_eligible": cand["certificate_eligible"],
        "total_credited_hours": total,
        "locked_credited_hours": locked,
        "projected_credited_hours": projected,
        "area_progress": sums,
        "certificate_status": cert_for_status["status"] if cert_for_status else None,
        "open_disciplinary_count": open_disciplinary_count(cid),
    })


# ----------------------------------------------------------- jurisdictions

@bp.post("/jurisdictions")
def create_jurisdiction():
    require_roles("NcarbAdministrator")
    body = get_body()
    code = _require_str(body, "code")
    name = _require_str(body, "name")
    opt_bool = {}
    for f in ("requires_supplemental_exam", "ce_carry_over_allowed"):
        if f in body and body[f] is not None:
            if not isinstance(body[f], bool):
                fail("ERR_INVALID_REQUEST", "%s must be a boolean" % f)
            opt_bool[f] = body[f]
    opt_int = {}
    for f in ("min_total_experience_hours", "ce_hours_required",
              "ce_hsw_hours_required"):
        if f in body and body[f] is not None:
            v = body[f]
            if not isinstance(v, int) or isinstance(v, bool):
                fail("ERR_INVALID_REQUEST", "%s must be an integer" % f)
            opt_int[f] = v
    if jurisdiction_by_code(code) is not None:
        fail("ERR_JURISDICTION_CODE_EXISTS", "jurisdiction code already registered")
    rec = stamp_new({
        "id": new_id(),
        "code": code,
        "name": name,
        "requires_supplemental_exam": opt_bool.get("requires_supplemental_exam", False),
        "min_total_experience_hours": opt_int.get("min_total_experience_hours", 3740),
        "ce_hours_required": opt_int.get("ce_hours_required", 24),
        "ce_hsw_hours_required": opt_int.get("ce_hsw_hours_required", 12),
        "ce_carry_over_allowed": opt_bool.get("ce_carry_over_allowed", False),
    })
    db["jurisdictions"][rec["id"]] = rec
    return ok(ser_jurisdiction(rec), 201)


@bp.patch("/jurisdictions/<jid>")
def update_jurisdiction(jid):
    require_roles("NcarbAdministrator")
    j = db["jurisdictions"].get(jid)
    if j is None:
        fail("ERR_NOT_FOUND", "jurisdiction not found")
    body = get_body()
    expected = body.get("expected_jurisdiction_version")
    if expected is None:
        fail("ERR_INVALID_REQUEST", "expected_jurisdiction_version is required")
    if expected != j["version"]:
        fail("ERR_STALE_VERSION", "jurisdiction version does not match")
    if "name" in body and body["name"] is not None:
        if not isinstance(body["name"], str) or not body["name"].strip():
            fail("ERR_INVALID_REQUEST", "name must be a non-empty string")
        j["name"] = body["name"]
    for f in ("requires_supplemental_exam", "ce_carry_over_allowed"):
        if f in body and body[f] is not None:
            if not isinstance(body[f], bool):
                fail("ERR_INVALID_REQUEST", "%s must be a boolean" % f)
            j[f] = body[f]
    for f in ("min_total_experience_hours", "ce_hours_required",
              "ce_hsw_hours_required"):
        if f in body and body[f] is not None:
            v = body[f]
            if not isinstance(v, int) or isinstance(v, bool):
                fail("ERR_INVALID_REQUEST", "%s must be an integer" % f)
            j[f] = v
    touch(j)
    return ok(ser_jurisdiction(j))


# ------------------------------------------------------------ supervisors

@bp.post("/supervisors")
def create_supervisor():
    require_roles("NcarbAdministrator")
    body = get_body()
    jc = body.get("jurisdiction_code")
    if jc is not None and jurisdiction_by_code(jc) is None:
        fail("ERR_JURISDICTION_UNKNOWN", "jurisdiction_code does not resolve")
    full_name = _require_str(body, "full_name")
    license_number = _require_str(body, "license_number")
    if jc is None:
        fail("ERR_INVALID_REQUEST", "jurisdiction_code is required")
    license_status = body.get("license_status", "ACTIVE")
    if license_status not in ("ACTIVE", "INACTIVE"):
        fail("ERR_INVALID_REQUEST", "license_status must be ACTIVE or INACTIVE")
    for s in db["supervisors"].values():
        if s["license_number"] == license_number:
            fail("ERR_INVALID_REQUEST", "license_number is already registered")
    rec = stamp_new({
        "id": new_id(),
        "full_name": full_name,
        "license_number": license_number,
        "jurisdiction_code": jc,
        "license_status": license_status,
    })
    db["supervisors"][rec["id"]] = rec
    return ok(ser_supervisor(rec), 201)


@bp.patch("/supervisors/<sid>")
def update_supervisor(sid):
    require_roles("NcarbAdministrator")
    s = db["supervisors"].get(sid)
    if s is None:
        fail("ERR_NOT_FOUND", "supervisor not found")
    body = get_body()
    expected = body.get("expected_supervisor_version")
    if expected is None:
        fail("ERR_INVALID_REQUEST", "expected_supervisor_version is required")
    if expected != s["version"]:
        fail("ERR_STALE_VERSION", "supervisor version does not match")
    if "full_name" in body and body["full_name"] is not None:
        if not isinstance(body["full_name"], str) or not body["full_name"].strip():
            fail("ERR_INVALID_REQUEST", "full_name must be a non-empty string")
        s["full_name"] = body["full_name"]
    if "license_status" in body and body["license_status"] is not None:
        if body["license_status"] not in ("ACTIVE", "INACTIVE"):
            fail("ERR_INVALID_REQUEST", "license_status must be ACTIVE or INACTIVE")
        s["license_status"] = body["license_status"]
    if "jurisdiction_code" in body and body["jurisdiction_code"] is not None:
        if jurisdiction_by_code(body["jurisdiction_code"]) is None:
            fail("ERR_JURISDICTION_UNKNOWN", "jurisdiction_code does not resolve")
        s["jurisdiction_code"] = body["jurisdiction_code"]
    touch(s)
    return ok(ser_supervisor(s))
