"""Resuscitation Training Center Authorization & Card Issuance API.

In-memory only. Every boot starts with an empty store and the logical clock
at exactly 2026-09-01T00:00:00Z.
"""

import calendar
import os
import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = CLOCK_START


CLOCK = Clock()


def now_iso():
    """Current logical clock as ISO8601 with Z suffix (whole seconds)."""
    return CLOCK.now.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso_ms():
    """Timestamp for meta / created_at / updated_at: three fractional digits."""
    return CLOCK.now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{CLOCK.now.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO8601 timestamp (accepts trailing Z or +00:00, fractional)."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# In-memory data store
# ---------------------------------------------------------------------------

DB = {
    "training_centers": {},
    "training_sites": {},
    "instructors": {},
    "alignments": {},
    "monitorings": {},
    "teaching_evaluations": {},
    "guidelines_versions": {},
    "course_sessions": {},
    "roster_entries": {},
    "skills_evaluations": {},
    "cards": {},
    "quality_audits": {},
    "audit_findings": {},
    "card_verifications": {},
}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_missing_context():
    return ApiError(
        "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
        "X-User-ID and X-User-Role headers must be present and non-empty.",
        400,
    )


def err_permissions(msg="Caller role is not permitted for this endpoint."):
    return ApiError("ERR_INSUFFICIENT_PERMISSIONS", msg, 403)


def err_invalid(msg):
    return ApiError("ERR_INVALID_REQUEST", msg, 400)


NOT_FOUND_BY_ENTITY = {
    "training_center": "ERR_TRAINING_CENTER_NOT_FOUND",
    "training_site": "ERR_TRAINING_SITE_NOT_FOUND",
    "instructor": "ERR_INSTRUCTOR_NOT_FOUND",
    "alignment": "ERR_ALIGNMENT_NOT_FOUND",
    "guidelines_version": "ERR_GUIDELINES_VERSION_NOT_FOUND",
    "course_session": "ERR_SESSION_NOT_FOUND",
    "roster_entry": "ERR_ROSTER_ENTRY_NOT_FOUND",
    "card": "ERR_CARD_NOT_FOUND",
    "quality_audit": "ERR_AUDIT_NOT_FOUND",
}


def err_not_found(entity, msg=None):
    return ApiError(
        NOT_FOUND_BY_ENTITY.get(entity, "ERR_NOT_FOUND"),
        msg or f"{entity} not found.",
        404,
    )


@app.errorhandler(ApiError)
def handle_api_error(e):
    return _error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return _error_response(ApiError("ERR_NOT_FOUND", "Resource not found.", 404))


@app.errorhandler(405)
def handle_405(e):
    return _error_response(ApiError("ERR_NOT_FOUND", "Method not allowed.", 404))


@app.errorhandler(Exception)
def handle_exception(e):
    return _error_response(ApiError("ERR_INVALID_REQUEST", str(e), 400))


def _error_response(e):
    body = {
        "meta": {
            "api_request_id": "req_" + _random_alnum(20),
            "api_request_timestamp": now_iso_ms(),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


def _random_alnum(n):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------


def respond_obj(data, status=200):
    body = {
        "meta": {
            "api_request_id": "req_" + _random_alnum(20),
            "api_request_timestamp": now_iso_ms(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def respond_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": "req_" + _random_alnum(20),
            "api_request_timestamp": now_iso_ms(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")
    try:
        limit = int(limit) if limit is not None else 10
    except ValueError:
        raise err_invalid("limit must be an integer")
    try:
        offset = int(offset) if offset is not None else 0
    except ValueError:
        raise err_invalid("offset must be an integer")
    if limit < 1 or limit > 100:
        raise err_invalid("limit out of range [1, 100]")
    if offset < 0:
        raise err_invalid("offset must be >= 0")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    total = len(items)
    return respond_list(items[offset:offset + limit], limit, offset, total)


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

VALID_ROLES = {
    "NationalAdmin",
    "TCAdmin",
    "TCCoordinator",
    "Instructor",
    "TrainingFaculty",
    "QAAuditor",
    "Employer",
}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_missing_context()
    if role not in VALID_ROLES:
        raise err_permissions(f"Unknown role {role!r}.")
    return Caller(user_id, role)


def require_roles(caller, roles):
    if caller.role not in roles:
        raise err_permissions()


def require_faculty_identity(caller):
    """TrainingFaculty caller: X-User-ID must resolve to an Instructor with
    is_faculty == true and status CERTIFIED."""
    inst = DB["instructors"].get(caller.user_id)
    if inst is None:
        raise err_permissions("Faculty identity does not resolve to an instructor.")
    if not inst.get("is_faculty") or inst.get("status") != "CERTIFIED":
        raise err_permissions("Faculty identity requires is_faculty and CERTIFIED status.")
    return inst


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def common_fields(record):
    record["id"] = new_id()
    ts = now_iso_ms()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = now_iso_ms()
    record["version"] = record.get("version", 1) + 1


def get_or_404(store_key, entity, rid):
    rec = DB[store_key].get(rid)
    if rec is None:
        raise err_not_found(entity)
    return rec


def body():
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err_invalid(f"Missing required field: {f}")


def require_enum(data, field, allowed):
    if data[field] not in allowed:
        raise err_invalid(f"Invalid value for {field}: {data[field]!r}")


def require_int(data, field, minimum=None):
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid(f"{field} must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid(f"{field} must be >= {minimum}")


def end_of_month(dt):
    last_day = calendar.monthrange(dt.year, dt.month)[1]
    return dt.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def ser_center(c):
    return {
        "id": c["id"],
        "legal_name": c["legal_name"],
        "region": c["region"],
        "contact_email": c["contact_email"],
        "status": c["status"],
        "probation_started_at": c["probation_started_at"],
        "last_audit_opened_at": c["last_audit_opened_at"],
        "cards_issued_count": c["cards_issued_count"],
        "active_card_count": c["active_card_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_site(s):
    return {
        "id": s["id"],
        "training_center_id": s["training_center_id"],
        "name": s["name"],
        "street_address": s["street_address"],
        "city": s["city"],
        "state_code": s["state_code"],
        "capacity_students": s["capacity_students"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_instructor(i):
    return {
        "id": i["id"],
        "full_name": i["full_name"],
        "email": i["email"],
        "discipline": i["discipline"],
        "home_training_center_id": i["home_training_center_id"],
        "legacy_certified": i["legacy_certified"],
        "status": i["status"],
        "certified_since": i["certified_since"],
        "renewal_due_at": i["renewal_due_at"],
        "renewal_count": i["renewal_count"],
        "is_faculty": i["is_faculty"],
        "sessions_taught_count": i["sessions_taught_count"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_alignment(a):
    return {
        "id": a["id"],
        "training_center_id": a["training_center_id"],
        "instructor_id": a["instructor_id"],
        "as_faculty": a["as_faculty"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_monitoring(m):
    return {
        "id": m["id"],
        "instructor_id": m["instructor_id"],
        "monitoring_faculty_id": m["monitoring_faculty_id"],
        "monitored_at": m["monitored_at"],
        "course_type_observed": m["course_type_observed"],
        "outcome": m["outcome"],
        "created_at": m["created_at"],
    }


def ser_evaluation(e):
    return {
        "id": e["id"],
        "instructor_id": e["instructor_id"],
        "evaluator_faculty_id": e["evaluator_faculty_id"],
        "score": e["score"],
        "notes": e["notes"],
        "created_at": e["created_at"],
    }


def ser_guidelines(g):
    return {
        "id": g["id"],
        "code": g["code"],
        "title": g["title"],
        "published_at": g["published_at"],
        "transition_deadline_at": g["transition_deadline_at"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def curriculum_flag(session):
    g = DB["guidelines_versions"].get(session["guidelines_version_id"])
    return "CURRENT" if g and g["status"] == "ACTIVE" else "LEGACY"


def seats_available(session):
    enrolled = sum(
        1
        for r in DB["roster_entries"].values()
        if r["course_session_id"] == session["id"] and r["status"] == "ENROLLED"
    )
    return session["capacity"] - enrolled


def ser_session(s):
    return {
        "id": s["id"],
        "training_center_id": s["training_center_id"],
        "site_id": s["site_id"],
        "primary_instructor_id": s["primary_instructor_id"],
        "guidelines_version_id": s["guidelines_version_id"],
        "course_type": s["course_type"],
        "delivery_format": s["delivery_format"],
        "start_at": s["start_at"],
        "end_at": s["end_at"],
        "capacity": s["capacity"],
        "manikin_count": s["manikin_count"],
        "aed_trainer_count": s["aed_trainer_count"],
        "assisting_instructor_count": s["assisting_instructor_count"],
        "status": s["status"],
        "cancel_reason": s["cancel_reason"],
        "seats_available": seats_available(s),
        "curriculum_flag": curriculum_flag(s),
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_roster(r):
    return {
        "id": r["id"],
        "course_session_id": r["course_session_id"],
        "student_name": r["student_name"],
        "student_email": r["student_email"],
        "prior_card_id": r["prior_card_id"],
        "status": r["status"],
        "remediation_used": r["remediation_used"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_skills(e):
    return {
        "id": e["id"],
        "roster_entry_id": e["roster_entry_id"],
        "evaluated_by_instructor_id": e["evaluated_by_instructor_id"],
        "attempt_number": e["attempt_number"],
        "is_remediation_retest": e["is_remediation_retest"],
        "items": e["items"],
        "total_items": e["total_items"],
        "passed_items": e["passed_items"],
        "score_percent": e["score_percent"],
        "outcome": e["outcome"],
        "created_at": e["created_at"],
    }


def ser_card(c):
    return {
        "id": c["id"],
        "roster_entry_id": c["roster_entry_id"],
        "training_center_id": c["training_center_id"],
        "prior_card_id": c["prior_card_id"],
        "is_renewal": c["is_renewal"],
        "card_code": c["card_code"],
        "verification_token": c["verification_token"],
        "holder_email": c["holder_email"],
        "course_type": c["course_type"],
        "guidelines_version_code": c["guidelines_version_code"],
        "issued_at": c["issued_at"],
        "expires_at": c["expires_at"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_audit(a):
    return {
        "id": a["id"],
        "target_training_center_id": a["target_training_center_id"],
        "opened_by": a["opened_by"],
        "status": a["status"],
        "compliance_score": a["compliance_score"],
        "opened_at": a["opened_at"],
        "closed_at": a["closed_at"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_finding(f):
    return {
        "id": f["id"],
        "audit_id": f["audit_id"],
        "severity": f["severity"],
        "is_repeat_offense": f["is_repeat_offense"],
        "description": f["description"],
        "deduction_points": f["deduction_points"],
        "created_at": f["created_at"],
    }


def ser_verification(v):
    return {
        "id": v["id"],
        "card_id": v["card_id"],
        "verifier_reference": v["verifier_reference"],
        "verified_at": v["verified_at"],
        "result": v["result"],
        "card_expires_at": v["card_expires_at"],
        "created_at": v["created_at"],
    }


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------


def cancel_session(session, reason):
    """Cancel a session (cascade): ENROLLED roster -> CANCELLED; seats recompute."""
    session["status"] = "CANCELLED"
    session["cancel_reason"] = reason
    for r in DB["roster_entries"].values():
        if r["course_session_id"] == session["id"] and r["status"] == "ENROLLED":
            r["status"] = "CANCELLED"
            touch(r)
    touch(session)


def suspend_site(site, reason):
    """Site ALIGNED -> SUSPENDED; cascade to sessions."""
    site["status"] = "SUSPENDED"
    touch(site)
    for s in DB["course_sessions"].values():
        if s["site_id"] == site["id"] and s["status"] == "SCHEDULED":
            cancel_session(s, reason)


def suspend_center(center):
    """Center -> SUSPENDED with full site/session/roster cascade."""
    center["status"] = "SUSPENDED"
    touch(center)
    for site in DB["training_sites"].values():
        if site["training_center_id"] == center["id"] and site["status"] == "ALIGNED":
            suspend_site(site, "CENTER_SUSPENDED")


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------


@app.post("/aha/_clock/set_current_utc")
def set_clock():
    caller = get_caller()
    require_roles(caller, {"NationalAdmin"})
    data = body()
    require_fields(data, ["to_iso8601"])
    new_dt = parse_iso(data["to_iso8601"])
    if new_dt is None:
        raise err_invalid("to_iso8601 must be a valid ISO8601 timestamp")
    new_dt = new_dt.replace(microsecond=0)
    CLOCK.now = new_dt
    # Instructor expiry sweep: CERTIFIED with renewal_due_at strictly < clock
    for inst in DB["instructors"].values():
        if inst["status"] == "CERTIFIED" and inst["renewal_due_at"]:
            due = parse_iso(inst["renewal_due_at"])
            if due is not None and due < new_dt:
                inst["status"] = "EXPIRED"
                touch(inst)
    # Card expiry sweep: ACTIVE with expires_at strictly < clock
    for card in DB["cards"].values():
        if card["status"] == "ACTIVE" and card["expires_at"]:
            exp = parse_iso(card["expires_at"])
            if exp is not None and exp < new_dt:
                card["status"] = "EXPIRED"
                touch(card)
                center = DB["training_centers"].get(card["training_center_id"])
                if center is not None:
                    center["active_card_count"] = max(0, center["active_card_count"] - 1)
                    touch(center)
    return respond_obj({"current_utc": iso_z(new_dt)})


# ---------------------------------------------------------------------------
# Training Centers
# ---------------------------------------------------------------------------


@app.post("/aha/training-centers")
def create_center():
    caller = get_caller()
    require_roles(caller, {"NationalAdmin"})
    data = body()
    require_fields(data, ["legal_name", "region", "contact_email"])
    c = common_fields({})
    c.update(
        legal_name=data["legal_name"],
        region=data["region"],
        contact_email=data["contact_email"],
        status="PROVISIONAL",
        probation_started_at=None,
        last_audit_opened_at=None,
        cards_issued_count=0,
        active_card_count=0,
    )
    DB["training_centers"][c["id"]] = c
    return respond_obj(ser_center(c), 201)


@app.get("/aha/training-centers/<cid>")
def get_center(cid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    c = get_or_404("training_centers", "training_center", cid)
    return respond_obj(ser_center(c))


@app.post("/aha/training-centers/<cid>/activate")
def activate_center(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin"})
    c = get_or_404("training_centers", "training_center", cid)
    if c["status"] != "PROVISIONAL":
        if c["status"] == "REVOKED":
            raise ApiError("ERR_CENTER_REVOKED", "Center is REVOKED (terminal).", 409)
        raise ApiError("ERR_CENTER_NOT_ACTIVE", "Center is not PROVISIONAL.", 409)
    aligned = any(
        s["training_center_id"] == cid and s["status"] == "ALIGNED"
        for s in DB["training_sites"].values()
    )
    if not aligned:
        raise ApiError("ERR_NO_ALIGNED_SITE", "Center has no ALIGNED site.", 409)
    c["status"] = "ACTIVE"
    touch(c)
    return respond_obj(ser_center(c))


@app.post("/aha/training-centers/<cid>/reinstate")
def reinstate_center(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "QAAuditor"})
    c = get_or_404("training_centers", "training_center", cid)
    if c["status"] not in ("PROBATION", "SUSPENDED"):
        raise ApiError(
            "ERR_CENTER_NOT_ACTIVE",
            "Center must be PROBATION or SUSPENDED to reinstate.",
            409,
        )
    open_audit = any(
        a["target_training_center_id"] == cid and a["status"] == "OPEN"
        for a in DB["quality_audits"].values()
    )
    if open_audit:
        raise ApiError("ERR_AUDIT_STILL_OPEN", "An OPEN audit targets this center.", 409)
    if c["status"] == "PROBATION":
        c["status"] = "ACTIVE"
        c["probation_started_at"] = None
    else:  # SUSPENDED -> PROBATION
        c["status"] = "PROBATION"
        c["probation_started_at"] = now_iso()
    touch(c)
    return respond_obj(ser_center(c))


@app.post("/aha/training-centers/<cid>/suspend")
def suspend_center_endpoint(cid):
    caller = get_caller()
    require_roles(caller, {"QAAuditor"})
    c = get_or_404("training_centers", "training_center", cid)
    if c["status"] not in ("ACTIVE", "PROBATION"):
        if c["status"] == "REVOKED":
            raise ApiError("ERR_CENTER_REVOKED", "Center is REVOKED (terminal).", 409)
        raise ApiError(
            "ERR_CENTER_NOT_ACTIVE",
            "Center must be ACTIVE or PROBATION to suspend.",
            409,
        )
    suspend_center(c)
    return respond_obj(ser_center(c))


@app.post("/aha/training-centers/<cid>/revoke")
def revoke_center(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin"})
    c = get_or_404("training_centers", "training_center", cid)
    if c["status"] != "SUSPENDED":
        if c["status"] == "REVOKED":
            raise ApiError("ERR_CENTER_REVOKED", "Center is already REVOKED.", 409)
        raise ApiError("ERR_CENTER_NOT_ACTIVE", "Center must be SUSPENDED to revoke.", 409)
    c["status"] = "REVOKED"
    touch(c)
    for site in DB["training_sites"].values():
        if site["training_center_id"] == cid and site["status"] != "DECOMMISSIONED":
            site["status"] = "DECOMMISSIONED"
            touch(site)
    for a in DB["alignments"].values():
        if a["training_center_id"] == cid and a["status"] == "ACTIVE":
            a["status"] = "ENDED"
            touch(a)
    for s in DB["course_sessions"].values():
        if s["training_center_id"] == cid and s["status"] == "SCHEDULED":
            cancel_session(s, "CENTER_SUSPENDED")
    return respond_obj(ser_center(c))


# ---------------------------------------------------------------------------
# Training Sites
# ---------------------------------------------------------------------------


@app.post("/aha/training-centers/<cid>/sites")
def create_site(cid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    center = get_or_404("training_centers", "training_center", cid)
    data = body()
    require_fields(data, ["name", "street_address", "city", "state_code", "capacity_students"])
    require_int(data, "capacity_students", minimum=1)
    s = common_fields({})
    s.update(
        training_center_id=cid,
        name=data["name"],
        street_address=data["street_address"],
        city=data["city"],
        state_code=data["state_code"],
        capacity_students=data["capacity_students"],
        status="PENDING_ALIGNMENT",
    )
    DB["training_sites"][s["id"]] = s
    return respond_obj(ser_site(s), 201)


@app.get("/aha/training-centers/<cid>/sites")
def list_sites(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor"})
    get_or_404("training_centers", "training_center", cid)
    status = request.args.get("status")
    items = [
        ser_site(s)
        for s in sorted(
            DB["training_sites"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if s["training_center_id"] == cid and (status is None or s["status"] == status)
    ]
    return paginate(items)


@app.get("/aha/training-sites/<sid>")
def get_site(sid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor"})
    s = get_or_404("training_sites", "training_site", sid)
    return respond_obj(ser_site(s))


def center_has_faculty_oversight(cid):
    for a in DB["alignments"].values():
        if (
            a["training_center_id"] == cid
            and a["status"] == "ACTIVE"
            and a["as_faculty"]
        ):
            inst = DB["instructors"].get(a["instructor_id"])
            if inst and inst["status"] == "CERTIFIED":
                return True
    return False


@app.post("/aha/training-sites/<sid>/align")
def align_site(sid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    s = get_or_404("training_sites", "training_site", sid)
    data = body()
    require_fields(data, ["expected_training_center_version"])
    center = DB["training_centers"].get(s["training_center_id"])
    if center is None:
        raise err_not_found("training_center")
    if s["status"] != "PENDING_ALIGNMENT":
        raise ApiError(
            "ERR_SITE_NOT_ALIGNED", "Site must be PENDING_ALIGNMENT to align.", 409
        )
    # OCC
    if data["expected_training_center_version"] != center["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_training_center_version does not match center version.",
            412,
        )
    if center["status"] not in ("PROVISIONAL", "ACTIVE", "PROBATION"):
        raise ApiError(
            "ERR_CENTER_SUSPENDED",
            "Owning center is SUSPENDED or REVOKED.",
            409,
        )
    if not center_has_faculty_oversight(center["id"]):
        raise ApiError(
            "ERR_NO_FACULTY_OVERSIGHT",
            "Center lacks faculty oversight (no ACTIVE as_faculty alignment with CERTIFIED instructor).",
            409,
        )
    s["status"] = "ALIGNED"
    touch(s)
    touch(center)  # bumps center version
    return respond_obj(ser_site(s))


@app.post("/aha/training-sites/<sid>/suspend")
def suspend_site_endpoint(sid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin", "QAAuditor"})
    s = get_or_404("training_sites", "training_site", sid)
    if s["status"] != "ALIGNED":
        raise ApiError("ERR_SITE_NOT_ALIGNED", "Site must be ALIGNED to suspend.", 409)
    suspend_site(s, "SITE_SUSPENDED")
    return respond_obj(ser_site(s))


@app.post("/aha/training-sites/<sid>/reinstate")
def reinstate_site(sid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    s = get_or_404("training_sites", "training_site", sid)
    center = DB["training_centers"].get(s["training_center_id"])
    if center and center["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError(
            "ERR_CENTER_SUSPENDED", "Owning center is SUSPENDED or REVOKED.", 409
        )
    if s["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_SITE_SUSPENDED", "Site must be SUSPENDED to reinstate.", 409
        )
    s["status"] = "ALIGNED"
    touch(s)
    return respond_obj(ser_site(s))


@app.post("/aha/training-sites/<sid>/decommission")
def decommission_site(sid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    s = get_or_404("training_sites", "training_site", sid)
    if s["status"] != "ALIGNED":
        raise ApiError(
            "ERR_SITE_NOT_ALIGNED", "Site must be ALIGNED to decommission.", 409
        )
    busy = any(
        sess["site_id"] == sid and sess["status"] in ("SCHEDULED", "IN_PROGRESS")
        for sess in DB["course_sessions"].values()
    )
    if busy:
        raise ApiError(
            "ERR_SITE_HAS_SCHEDULED_SESSIONS",
            "Site has SCHEDULED or IN_PROGRESS sessions.",
            409,
        )
    s["status"] = "DECOMMISSIONED"
    touch(s)
    return respond_obj(ser_site(s))


# ---------------------------------------------------------------------------
# Instructors
# ---------------------------------------------------------------------------

DISCIPLINES = {"BLS", "ACLS", "PALS", "HEARTSAVER"}


@app.post("/aha/instructors")
def create_instructor():
    caller = get_caller()
    require_roles(caller, {"NationalAdmin"})
    data = body()
    require_fields(data, ["full_name", "email", "discipline", "home_training_center_id"])
    require_enum(data, "discipline", DISCIPLINES)
    if DB["training_centers"].get(data["home_training_center_id"]) is None:
        raise err_not_found("training_center", "home_training_center_id not found")
    legacy = data.get("legacy_certified", False)
    if not isinstance(legacy, bool):
        raise err_invalid("legacy_certified must be a boolean")
    i = common_fields({})
    i.update(
        full_name=data["full_name"],
        email=data["email"],
        discipline=data["discipline"],
        home_training_center_id=data["home_training_center_id"],
        legacy_certified=legacy,
        status="CANDIDATE",
        certified_since=None,
        renewal_due_at=None,
        renewal_count=0,
        is_faculty=False,
        sessions_taught_count=0,
    )
    if legacy:
        i["status"] = "CERTIFIED"
        i["certified_since"] = now_iso()
        i["renewal_due_at"] = iso_z(add_months(CLOCK.now, 24))
    DB["instructors"][i["id"]] = i
    return respond_obj(ser_instructor(i), 201)


@app.get("/aha/instructors/<iid>")
def get_instructor(iid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    i = get_or_404("instructors", "instructor", iid)
    return respond_obj(ser_instructor(i))


@app.get("/aha/training-centers/<cid>/instructors")
def list_center_instructors(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor"})
    get_or_404("training_centers", "training_center", cid)
    status = request.args.get("status")
    items = [
        ser_instructor(i)
        for i in sorted(
            DB["instructors"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if i["home_training_center_id"] == cid and (status is None or i["status"] == status)
    ]
    return paginate(items)


@app.post("/aha/instructors/<iid>/grant-faculty")
def grant_faculty(iid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin"})
    i = get_or_404("instructors", "instructor", iid)
    if i["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_CERTIFIED",
            "Instructor must be CERTIFIED to be granted faculty status.",
            409,
        )
    i["is_faculty"] = True
    touch(i)
    return respond_obj(ser_instructor(i))


MONITOR_COURSE_TYPES = {"BLS_PROVIDER", "ACLS_PROVIDER", "PALS_PROVIDER", "HEARTSAVER"}


@app.post("/aha/instructors/<iid>/monitor")
def monitor_instructor(iid):
    caller = get_caller()
    require_roles(caller, {"TrainingFaculty"})
    candidate = get_or_404("instructors", "instructor", iid)
    data = body()
    require_fields(data, ["monitored_at", "course_type_observed", "outcome"])
    require_enum(data, "course_type_observed", MONITOR_COURSE_TYPES)
    require_enum(data, "outcome", {"SATISFACTORY", "UNSATISFACTORY"})
    if parse_iso(data["monitored_at"]) is None:
        raise err_invalid("monitored_at must be a valid ISO8601 timestamp")
    # State precondition first
    if candidate["status"] != "CANDIDATE":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_CANDIDATE",
            "Instructor must be CANDIDATE for monitoring.",
            409,
        )
    # Faculty identity: is_faculty and CERTIFIED
    faculty = require_faculty_identity(caller)
    if caller.user_id == candidate["id"]:
        raise ApiError(
            "ERR_SELF_EVALUATION_FORBIDDEN",
            "Faculty may not monitor or evaluate themselves.",
            403,
        )
    if faculty["discipline"] != candidate["discipline"]:
        raise ApiError(
            "ERR_FACULTY_DISCIPLINE_MISMATCH",
            "Faculty discipline differs from candidate discipline.",
            409,
        )
    m = {
        "id": new_id(),
        "instructor_id": candidate["id"],
        "monitoring_faculty_id": caller.user_id,
        "monitored_at": data["monitored_at"],
        "course_type_observed": data["course_type_observed"],
        "outcome": data["outcome"],
        "created_at": now_iso_ms(),
    }
    DB["monitorings"][m["id"]] = m
    if data["outcome"] == "SATISFACTORY":
        candidate["status"] = "MONITORED"
        touch(candidate)
    return respond_obj(ser_monitoring(m), 201)


@app.get("/aha/instructors/<iid>/monitorings")
def list_monitorings(iid):
    caller = get_caller()
    require_roles(
        caller, {"NationalAdmin", "TCAdmin", "QAAuditor", "TrainingFaculty", "Instructor"}
    )
    get_or_404("instructors", "instructor", iid)
    items = [
        ser_monitoring(m)
        for m in sorted(
            DB["monitorings"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if m["instructor_id"] == iid
    ]
    return paginate(items)


@app.post("/aha/instructors/<iid>/teaching-evaluations")
def create_teaching_evaluation(iid):
    caller = get_caller()
    require_roles(caller, {"TrainingFaculty"})
    candidate = get_or_404("instructors", "instructor", iid)
    data = body()
    require_fields(data, ["score", "notes"])
    require_int(data, "score", minimum=1)
    if data["score"] > 5:
        raise err_invalid("score must be in 1..5")
    faculty = require_faculty_identity(caller)
    if caller.user_id == candidate["id"]:
        raise ApiError(
            "ERR_SELF_EVALUATION_FORBIDDEN",
            "Faculty may not monitor or evaluate themselves.",
            403,
        )
    if faculty["discipline"] != candidate["discipline"]:
        raise ApiError(
            "ERR_FACULTY_DISCIPLINE_MISMATCH",
            "Faculty discipline differs from candidate discipline.",
            409,
        )
    e = {
        "id": new_id(),
        "instructor_id": candidate["id"],
        "evaluator_faculty_id": caller.user_id,
        "score": data["score"],
        "notes": data["notes"],
        "created_at": now_iso_ms(),
    }
    DB["teaching_evaluations"][e["id"]] = e
    return respond_obj(ser_evaluation(e), 201)


@app.get("/aha/instructors/<iid>/teaching-evaluations")
def list_teaching_evaluations(iid):
    caller = get_caller()
    require_roles(
        caller, {"NationalAdmin", "TCAdmin", "QAAuditor", "TrainingFaculty", "Instructor"}
    )
    get_or_404("instructors", "instructor", iid)
    items = [
        ser_evaluation(e)
        for e in sorted(
            DB["teaching_evaluations"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if e["instructor_id"] == iid
    ]
    return paginate(items)


@app.post("/aha/instructors/<iid>/certify")
def certify_instructor(iid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    i = get_or_404("instructors", "instructor", iid)
    if i["status"] != "MONITORED":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_MONITORED",
            "Instructor must be MONITORED for certification.",
            409,
        )
    evals = [e for e in DB["teaching_evaluations"].values() if e["instructor_id"] == iid]
    if len(evals) < 2:
        raise ApiError(
            "ERR_INSUFFICIENT_TEACHING_EVALUATIONS",
            "Fewer than 2 teaching evaluations recorded.",
            409,
        )
    from decimal import Decimal, ROUND_HALF_UP

    total = sum(e["score"] for e in evals)
    avg = (Decimal(total) / Decimal(len(evals))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if avg < Decimal("4.00"):
        raise ApiError(
            "ERR_EVALUATION_AVERAGE_BELOW_THRESHOLD",
            "Certification evaluation average < 4.00.",
            409,
        )
    i["status"] = "CERTIFIED"
    i["certified_since"] = now_iso()
    i["renewal_due_at"] = iso_z(add_months(CLOCK.now, 24))
    touch(i)
    return respond_obj(ser_instructor(i))


@app.post("/aha/instructors/<iid>/renew")
def renew_instructor(iid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    i = get_or_404("instructors", "instructor", iid)
    if i["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_CERTIFIED",
            "Instructor must be CERTIFIED to renew.",
            409,
        )
    due = parse_iso(i["renewal_due_at"])
    window_open = (due - timedelta(days=90)) <= CLOCK.now <= due
    if not window_open:
        raise ApiError(
            "ERR_RENEWAL_WINDOW_CLOSED",
            "Current clock is outside the renewal window.",
            409,
        )
    window_start = add_months(CLOCK.now, -24)
    completed = sum(
        1
        for s in DB["course_sessions"].values()
        if s["primary_instructor_id"] == iid
        and s["status"] == "COMPLETED"
        and parse_iso(s["start_at"]) >= window_start
        and parse_iso(s["start_at"]) <= CLOCK.now
    )
    if completed < 2:
        raise ApiError(
            "ERR_RENEWAL_SESSION_SHORTFALL",
            "Fewer than 2 COMPLETED sessions taught in the trailing 24 months.",
            409,
        )
    i["renewal_due_at"] = iso_z(add_months(CLOCK.now, 24))
    i["renewal_count"] += 1
    touch(i)
    return respond_obj(ser_instructor(i))


@app.post("/aha/instructors/<iid>/suspend")
def suspend_instructor(iid):
    caller = get_caller()
    require_roles(caller, {"QAAuditor"})
    i = get_or_404("instructors", "instructor", iid)
    if i["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_CERTIFIED",
            "Instructor must be CERTIFIED to suspend.",
            409,
        )
    i["status"] = "SUSPENDED"
    touch(i)
    for s in DB["course_sessions"].values():
        if s["primary_instructor_id"] == iid and s["status"] == "SCHEDULED":
            cancel_session(s, "INSTRUCTOR_SUSPENDED")
    return respond_obj(ser_instructor(i))


@app.post("/aha/instructors/<iid>/reinstate")
def reinstate_instructor(iid):
    caller = get_caller()
    require_roles(caller, {"QAAuditor", "TCAdmin"})
    i = get_or_404("instructors", "instructor", iid)
    if i["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_SUSPENDED",
            "Instructor must be SUSPENDED to reinstate.",
            409,
        )
    i["status"] = "CERTIFIED"
    touch(i)
    return respond_obj(ser_instructor(i))


@app.post("/aha/instructors/<iid>/reset-candidacy")
def reset_candidacy(iid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    i = get_or_404("instructors", "instructor", iid)
    if i["status"] != "EXPIRED":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_EXPIRED",
            "Instructor must be EXPIRED to reset candidacy.",
            409,
        )
    i["status"] = "CANDIDATE"
    touch(i)
    return respond_obj(ser_instructor(i))


# ---------------------------------------------------------------------------
# Alignments
# ---------------------------------------------------------------------------


@app.post("/aha/training-centers/<cid>/alignments")
def create_alignment(cid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    center = get_or_404("training_centers", "training_center", cid)
    data = body()
    require_fields(data, ["instructor_id"])
    inst = DB["instructors"].get(data["instructor_id"])
    if inst is None:
        raise err_not_found("instructor")
    as_faculty = data.get("as_faculty", False)
    if not isinstance(as_faculty, bool):
        raise err_invalid("as_faculty must be a boolean")
    if inst["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_CERTIFIED",
            "Instructor must be CERTIFIED to align.",
            409,
        )
    dup = any(
        a["training_center_id"] == cid
        and a["instructor_id"] == inst["id"]
        and a["status"] == "ACTIVE"
        for a in DB["alignments"].values()
    )
    if dup:
        raise ApiError(
            "ERR_DUPLICATE_ACTIVE_ALIGNMENT",
            "An ACTIVE alignment already exists for this (training_center_id, instructor_id).",
            409,
        )
    a = common_fields({})
    a.update(
        training_center_id=cid,
        instructor_id=inst["id"],
        as_faculty=as_faculty,
        status="ACTIVE",
    )
    DB["alignments"][a["id"]] = a
    return respond_obj(ser_alignment(a), 201)


@app.get("/aha/training-centers/<cid>/alignments")
def list_center_alignments(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor"})
    get_or_404("training_centers", "training_center", cid)
    status = request.args.get("status")
    items = [
        ser_alignment(a)
        for a in sorted(
            DB["alignments"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if a["training_center_id"] == cid and (status is None or a["status"] == status)
    ]
    return paginate(items)


@app.get("/aha/instructors/<iid>/alignments")
def list_instructor_alignments(iid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    get_or_404("instructors", "instructor", iid)
    status = request.args.get("status")
    items = [
        ser_alignment(a)
        for a in sorted(
            DB["alignments"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if a["instructor_id"] == iid and (status is None or a["status"] == status)
    ]
    return paginate(items)


@app.post("/aha/alignments/<aid>/end")
def end_alignment(aid):
    caller = get_caller()
    require_roles(caller, {"TCAdmin"})
    a = get_or_404("alignments", "alignment", aid)
    if a["status"] != "ACTIVE":
        raise ApiError(
            "ERR_ALIGNMENT_NOT_ACTIVE", "Alignment must be ACTIVE to end.", 409
        )
    a["status"] = "ENDED"
    touch(a)
    return respond_obj(ser_alignment(a))


# ---------------------------------------------------------------------------
# Guidelines Versions
# ---------------------------------------------------------------------------


@app.post("/aha/guidelines-versions")
def create_guidelines():
    caller = get_caller()
    require_roles(caller, {"NationalAdmin"})
    data = body()
    require_fields(data, ["code", "title", "published_at", "transition_deadline_at"])
    if parse_iso(data["published_at"]) is None:
        raise err_invalid("published_at must be a valid ISO8601 timestamp")
    if parse_iso(data["transition_deadline_at"]) is None:
        raise err_invalid("transition_deadline_at must be a valid ISO8601 timestamp")
    if any(g["code"] == data["code"] for g in DB["guidelines_versions"].values()):
        raise ApiError(
            "ERR_GUIDELINES_VERSION_CONFLICT",
            "Guidelines version code must be unique.",
            409,
        )
    g = common_fields({})
    g.update(
        code=data["code"],
        title=data["title"],
        published_at=data["published_at"],
        transition_deadline_at=data["transition_deadline_at"],
        status="DRAFT",
    )
    DB["guidelines_versions"][g["id"]] = g
    return respond_obj(ser_guidelines(g), 201)


@app.get("/aha/guidelines-versions")
def list_guidelines():
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    status = request.args.get("status")
    items = [
        ser_guidelines(g)
        for g in sorted(
            DB["guidelines_versions"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if status is None or g["status"] == status
    ]
    return paginate(items)


@app.get("/aha/guidelines-versions/<gid>")
def get_guidelines(gid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    g = get_or_404("guidelines_versions", "guidelines_version", gid)
    return respond_obj(ser_guidelines(g))


@app.post("/aha/guidelines-versions/<gid>/activate")
def activate_guidelines(gid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin"})
    g = get_or_404("guidelines_versions", "guidelines_version", gid)
    if g["status"] != "DRAFT":
        raise ApiError(
            "ERR_GUIDELINES_VERSION_CONFLICT",
            "Guidelines version must be DRAFT to activate.",
            409,
        )
    # Supersede previously ACTIVE version
    old = next(
        (v for v in DB["guidelines_versions"].values() if v["status"] == "ACTIVE"), None
    )
    g["status"] = "ACTIVE"
    touch(g)
    if old is not None:
        old["status"] = "SUPERSEDED"
        touch(old)
        deadline = parse_iso(g["transition_deadline_at"])
        for s in DB["course_sessions"].values():
            if (
                s["guidelines_version_id"] == old["id"]
                and s["status"] == "SCHEDULED"
                and parse_iso(s["start_at"]) > deadline
            ):
                cancel_session(s, "GUIDELINES_TRANSITION")
    return respond_obj(ser_guidelines(g))


@app.get("/aha/guidelines-versions/<gid>/course-sessions")
def list_guidelines_sessions(gid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor"})
    get_or_404("guidelines_versions", "guidelines_version", gid)
    status = request.args.get("status")
    items = [
        ser_session(s)
        for s in sorted(
            DB["course_sessions"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if s["guidelines_version_id"] == gid and (status is None or s["status"] == status)
    ]
    return paginate(items)


# ---------------------------------------------------------------------------
# Course Sessions
# ---------------------------------------------------------------------------

COURSE_TYPES = {"BLS_PROVIDER", "ACLS_PROVIDER", "PALS_PROVIDER", "HEARTSAVER", "BLS_INSTRUCTOR"}
DELIVERY_FORMATS = {"CLASSROOM", "BLENDED_SKILLS_SESSION"}

COURSE_DISCIPLINE = {
    "BLS_PROVIDER": "BLS",
    "BLS_INSTRUCTOR": "BLS",
    "ACLS_PROVIDER": "ACLS",
    "PALS_PROVIDER": "PALS",
    "HEARTSAVER": "HEARTSAVER",
}

ADVANCED_COURSES = {"ACLS_PROVIDER", "PALS_PROVIDER"}


def ceil_div(a, b):
    return -(-a // b)


@app.post("/aha/course-sessions")
def create_session():
    caller = get_caller()
    require_roles(caller, {"TCCoordinator"})
    data = body()
    require_fields(
        data,
        [
            "training_center_id",
            "site_id",
            "primary_instructor_id",
            "guidelines_version_id",
            "course_type",
            "delivery_format",
            "start_at",
            "end_at",
            "capacity",
            "manikin_count",
            "aed_trainer_count",
        ],
    )
    require_enum(data, "course_type", COURSE_TYPES)
    require_enum(data, "delivery_format", DELIVERY_FORMATS)
    start_dt = parse_iso(data["start_at"])
    end_dt = parse_iso(data["end_at"])
    if start_dt is None or end_dt is None:
        raise err_invalid("start_at and end_at must be valid ISO8601 timestamps")
    if end_dt <= start_dt:
        raise err_invalid("end_at must be strictly after start_at")
    require_int(data, "capacity", minimum=1)
    require_int(data, "manikin_count", minimum=0)
    require_int(data, "aed_trainer_count", minimum=0)
    assisting = data.get("assisting_instructor_count", 0)
    if isinstance(assisting, bool) or not isinstance(assisting, int) or assisting < 0:
        raise err_invalid("assisting_instructor_count must be an integer >= 0")

    # Existence of body FKs in declaration order
    center = DB["training_centers"].get(data["training_center_id"])
    if center is None:
        raise err_not_found("training_center")
    site = DB["training_sites"].get(data["site_id"])
    if site is None:
        raise err_not_found("training_site")
    instructor = DB["instructors"].get(data["primary_instructor_id"])
    if instructor is None:
        raise err_not_found("instructor")
    guidelines = DB["guidelines_versions"].get(data["guidelines_version_id"])
    if guidelines is None:
        raise err_not_found("guidelines_version")

    # Business safety gates (priority 5), declared order
    if center["status"] in ("SUSPENDED", "REVOKED"):
        raise ApiError("ERR_CENTER_SUSPENDED", "Center is SUSPENDED or REVOKED.", 409)
    if center["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_NOT_ACTIVE", "Center must be ACTIVE.", 409)
    if site["status"] == "SUSPENDED":
        raise ApiError("ERR_SITE_SUSPENDED", "Site is SUSPENDED.", 409)
    if site["status"] != "ALIGNED":
        raise ApiError("ERR_SITE_NOT_ALIGNED", "Site must be ALIGNED.", 409)
    if instructor["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_CERTIFIED", "Instructor must be CERTIFIED.", 409
        )
    if data["course_type"] == "BLS_INSTRUCTOR" and not instructor["is_faculty"]:
        raise ApiError(
            "ERR_FACULTY_REQUIRED_FOR_INSTRUCTOR_COURSE",
            "BLS_INSTRUCTOR courses require an is_faculty primary instructor.",
            403,
        )
    if instructor["discipline"] != COURSE_DISCIPLINE[data["course_type"]]:
        raise ApiError(
            "ERR_INSTRUCTOR_DISCIPLINE_MISMATCH",
            "Instructor discipline does not match course type.",
            409,
        )

    # Structural constraints (priority 6)
    if data["capacity"] > site["capacity_students"]:
        raise ApiError(
            "ERR_CAPACITY_EXCEEDS_SITE",
            "Session capacity exceeds site capacity_students.",
            422,
        )
    cap = data["capacity"]
    if data["delivery_format"] == "CLASSROOM":
        req_manikins = ceil_div(cap, 3)
    else:
        req_manikins = ceil_div(cap, 6)
    req_aed = ceil_div(cap, 6)
    if data["course_type"] in ADVANCED_COURSES:
        req_aed = max(req_aed, ceil_div(cap, 4))
    req_instructors = 1 + max(0, ceil_div(cap - 6, 6))
    if (
        data["manikin_count"] < req_manikins
        or data["aed_trainer_count"] < req_aed
        or 1 + assisting < req_instructors
    ):
        raise ApiError(
            "ERR_EQUIPMENT_RATIO_VIOLATION",
            "manikin/AED/instructor ratios not met.",
            422,
        )

    # Temporal checks (priority 7)
    if guidelines["status"] != "ACTIVE":
        raise ApiError(
            "ERR_GUIDELINES_VERSION_NOT_ACTIVE",
            "Guidelines version must be ACTIVE at session creation.",
            409,
        )
    # Instructor double-booking: half-open [start_at, end_at) overlap
    for s in DB["course_sessions"].values():
        if (
            s["primary_instructor_id"] == instructor["id"]
            and s["status"] in ("SCHEDULED", "IN_PROGRESS")
        ):
            s_start = parse_iso(s["start_at"])
            s_end = parse_iso(s["end_at"])
            if start_dt < s_end and end_dt > s_start:
                raise ApiError(
                    "ERR_SESSION_OVERLAP_INSTRUCTOR",
                    "Primary instructor already leads an overlapping session.",
                    409,
                )
    # Site turnover buffer: gap < 60 minutes rejected; exactly 60 allowed
    for s in DB["course_sessions"].values():
        if s["site_id"] == site["id"] and s["status"] in ("SCHEDULED", "IN_PROGRESS"):
            s_start = parse_iso(s["start_at"])
            s_end = parse_iso(s["end_at"])
            gap = max((start_dt - s_end).total_seconds(), (s_start - end_dt).total_seconds())
            if gap < 3600:
                raise ApiError(
                    "ERR_SESSION_OVERLAP_SITE",
                    "Site has a session within the 60-minute turnover buffer.",
                    409,
                )

    # Referential checks (priority 8)
    if site["training_center_id"] != center["id"]:
        raise ApiError(
            "ERR_SITE_CENTER_MISMATCH",
            "site_id does not belong to training_center_id.",
            409,
        )
    aligned = any(
        a["training_center_id"] == center["id"]
        and a["instructor_id"] == instructor["id"]
        and a["status"] == "ACTIVE"
        for a in DB["alignments"].values()
    )
    if not aligned:
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_ALIGNED",
            "Primary instructor holds no ACTIVE alignment to the center.",
            409,
        )

    s = common_fields({})
    s.update(
        training_center_id=center["id"],
        site_id=site["id"],
        primary_instructor_id=instructor["id"],
        guidelines_version_id=guidelines["id"],
        course_type=data["course_type"],
        delivery_format=data["delivery_format"],
        start_at=data["start_at"],
        end_at=data["end_at"],
        capacity=cap,
        manikin_count=data["manikin_count"],
        aed_trainer_count=data["aed_trainer_count"],
        assisting_instructor_count=assisting,
        status="SCHEDULED",
        cancel_reason=None,
    )
    DB["course_sessions"][s["id"]] = s
    return respond_obj(ser_session(s), 201)


@app.get("/aha/course-sessions/<sid>")
def get_session(sid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    s = get_or_404("course_sessions", "course_session", sid)
    return respond_obj(ser_session(s))


def _list_sessions(filter_fn):
    status = request.args.get("status")
    items = [
        ser_session(s)
        for s in sorted(
            DB["course_sessions"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if filter_fn(s) and (status is None or s["status"] == status)
    ]
    return paginate(items)


@app.get("/aha/training-centers/<cid>/course-sessions")
def list_center_sessions(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor"})
    get_or_404("training_centers", "training_center", cid)
    return _list_sessions(lambda s: s["training_center_id"] == cid)


@app.get("/aha/training-sites/<sid>/course-sessions")
def list_site_sessions(sid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor"})
    get_or_404("training_sites", "training_site", sid)
    return _list_sessions(lambda s: s["site_id"] == sid)


@app.get("/aha/instructors/<iid>/course-sessions")
def list_instructor_sessions(iid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    get_or_404("instructors", "instructor", iid)
    return _list_sessions(lambda s: s["primary_instructor_id"] == iid)


@app.post("/aha/course-sessions/<sid>/start")
def start_session(sid):
    caller = get_caller()
    require_roles(caller, {"TCCoordinator", "Instructor"})
    s = get_or_404("course_sessions", "course_session", sid)
    if s["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_SESSION_NOT_SCHEDULED", "Session must be SCHEDULED to start.", 409
        )
    if caller.role == "Instructor" and caller.user_id != s["primary_instructor_id"]:
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_SESSION_LEAD",
            "X-User-ID does not equal the session's primary_instructor_id.",
            403,
        )
    s["status"] = "IN_PROGRESS"
    touch(s)
    return respond_obj(ser_session(s))


@app.post("/aha/course-sessions/<sid>/complete")
def complete_session(sid):
    caller = get_caller()
    require_roles(caller, {"Instructor"})
    s = get_or_404("course_sessions", "course_session", sid)
    if s["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_SESSION_NOT_IN_PROGRESS", "Session must be IN_PROGRESS to complete.", 409
        )
    if caller.user_id != s["primary_instructor_id"]:
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_SESSION_LEAD",
            "X-User-ID does not equal the session's primary_instructor_id.",
            403,
        )
    center = DB["training_centers"].get(s["training_center_id"])
    if center is None:
        raise err_not_found("training_center")
    if center["status"] == "PROBATION":
        raise ApiError(
            "ERR_CENTER_ON_PROBATION",
            "Center is PROBATION; card issuance at session completion is blocked.",
            409,
        )
    if center["status"] != "ACTIVE":
        raise ApiError("ERR_CENTER_NOT_ACTIVE", "Center must be ACTIVE.", 409)
    unresolved = any(
        r["course_session_id"] == sid and r["status"] == "ENROLLED"
        for r in DB["roster_entries"].values()
    )
    if unresolved:
        raise ApiError(
            "ERR_SESSION_HAS_UNRESOLVED_ROSTER",
            "Session still has ENROLLED roster entries.",
            409,
        )

    # Issue cards for PASSED roster entries
    guidelines = DB["guidelines_versions"].get(s["guidelines_version_id"])
    issued = 0
    for r in sorted(
        DB["roster_entries"].values(), key=lambda x: (x["created_at"], x["id"])
    ):
        if r["course_session_id"] == sid and r["status"] == "PASSED":
            card = _issue_card(s, r, center, guidelines)
            issued += 1
    s["status"] = "COMPLETED"
    touch(s)
    center["cards_issued_count"] += issued
    center["active_card_count"] += issued
    touch(center)
    instructor = DB["instructors"].get(s["primary_instructor_id"])
    if instructor is not None:
        instructor["sessions_taught_count"] += 1
        touch(instructor)
    return respond_obj(ser_session(s))


def _mint_card_code():
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "AHA-" + "".join(secrets.choice(alphabet) for _ in range(6)) + "-" + "".join(
            secrets.choice(alphabet) for _ in range(6)
        )
        if not any(c["card_code"] == code for c in DB["cards"].values()):
            return code


def _issue_card(session, roster_entry, center, guidelines):
    prior_card = None
    if roster_entry["prior_card_id"]:
        prior_card = DB["cards"].get(roster_entry["prior_card_id"])
    is_renewal = prior_card is not None
    issued_at = CLOCK.now.replace(microsecond=0)
    if is_renewal and parse_iso(prior_card["expires_at"]) > issued_at:
        expires = end_of_month(add_months(parse_iso(prior_card["expires_at"]), 24))
    else:
        expires = end_of_month(add_months(issued_at, 24))
    card = common_fields({})
    card.update(
        roster_entry_id=roster_entry["id"],
        training_center_id=center["id"],
        prior_card_id=roster_entry["prior_card_id"] if is_renewal else None,
        is_renewal=is_renewal,
        card_code=_mint_card_code(),
        verification_token=secrets.token_urlsafe(24),
        holder_email=roster_entry["student_email"],
        course_type=session["course_type"],
        guidelines_version_code=guidelines["code"] if guidelines else None,
        issued_at=iso_z(issued_at),
        expires_at=iso_z(expires),
        status="ACTIVE",
    )
    DB["cards"][card["id"]] = card
    return card


@app.post("/aha/course-sessions/<sid>/cancel")
def cancel_session_endpoint(sid):
    caller = get_caller()
    require_roles(caller, {"TCCoordinator"})
    s = get_or_404("course_sessions", "course_session", sid)
    if s["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError(
            "ERR_SESSION_NOT_SCHEDULED",
            "Session must be SCHEDULED or IN_PROGRESS to cancel.",
            409,
        )
    cancel_session(s, "MANUAL")
    return respond_obj(ser_session(s))


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


@app.post("/aha/course-sessions/<sid>/roster")
def add_roster(sid):
    caller = get_caller()
    require_roles(caller, {"TCCoordinator"})
    s = get_or_404("course_sessions", "course_session", sid)
    data = body()
    require_fields(data, ["student_name", "student_email"])
    if s["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_SESSION_NOT_SCHEDULED", "Session must be SCHEDULED for roster add.", 409
        )
    prior_card_id = data.get("prior_card_id")
    prior_card = None
    if prior_card_id is not None:
        prior_card = DB["cards"].get(prior_card_id)
        if prior_card is None:
            raise err_not_found("card")
        if prior_card["holder_email"] != data["student_email"]:
            raise ApiError(
                "ERR_PRIOR_CARD_HOLDER_MISMATCH",
                "prior_card_id holder_email differs from student_email.",
                409,
            )
    if seats_available(s) <= 0:
        raise ApiError("ERR_SESSION_FULL", "Session has no seats available.", 422)
    r = common_fields({})
    r.update(
        course_session_id=sid,
        student_name=data["student_name"],
        student_email=data["student_email"],
        prior_card_id=prior_card_id if prior_card is not None else None,
        status="ENROLLED",
        remediation_used=False,
    )
    DB["roster_entries"][r["id"]] = r
    return respond_obj(ser_roster(r), 201)


@app.get("/aha/course-sessions/<sid>/roster")
def list_roster(sid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    get_or_404("course_sessions", "course_session", sid)
    status = request.args.get("status")
    items = [
        ser_roster(r)
        for r in sorted(
            DB["roster_entries"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if r["course_session_id"] == sid and (status is None or r["status"] == status)
    ]
    return paginate(items)


@app.get("/aha/roster-entries/<rid>")
def get_roster_entry(rid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    r = get_or_404("roster_entries", "roster_entry", rid)
    return respond_obj(ser_roster(r))


@app.post("/aha/roster-entries/<rid>/cancel")
def cancel_roster_entry(rid):
    caller = get_caller()
    require_roles(caller, {"TCCoordinator"})
    r = get_or_404("roster_entries", "roster_entry", rid)
    if r["status"] != "ENROLLED":
        raise ApiError(
            "ERR_ROSTER_ENTRY_NOT_ENROLLED",
            "Roster entry must be ENROLLED to cancel.",
            409,
        )
    r["status"] = "CANCELLED"
    touch(r)
    return respond_obj(ser_roster(r))


# ---------------------------------------------------------------------------
# Skills Evaluations
# ---------------------------------------------------------------------------


@app.post("/aha/roster-entries/<rid>/skills-evaluations")
def create_skills_evaluation(rid):
    caller = get_caller()
    require_roles(caller, {"Instructor"})
    r = get_or_404("roster_entries", "roster_entry", rid)
    session = DB["course_sessions"].get(r["course_session_id"])
    if session is None:
        raise err_not_found("course_session")
    data = body()
    require_fields(data, ["items"])
    items = data["items"]
    if not isinstance(items, list) or len(items) == 0:
        raise err_invalid("items must be a non-empty array")
    for it in items:
        if not isinstance(it, dict):
            raise err_invalid("each item must be an object")
        if "item_code" not in it or not isinstance(it["item_code"], str):
            raise err_invalid("each item requires item_code")
        if not isinstance(it.get("critical"), bool) or not isinstance(it.get("passed"), bool):
            raise err_invalid("each item requires boolean critical and passed")
    if not any(it["critical"] for it in items):
        raise err_invalid("items must contain at least one critical item")

    if caller.user_id != session["primary_instructor_id"]:
        raise ApiError(
            "ERR_INSTRUCTOR_NOT_SESSION_LEAD",
            "X-User-ID does not equal the session's primary_instructor_id.",
            403,
        )
    if session["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_SESSION_NOT_IN_PROGRESS",
            "Skills evaluation requires the session to be IN_PROGRESS.",
            409,
        )
    if r["status"] != "ENROLLED":
        raise ApiError(
            "ERR_ROSTER_ENTRY_NOT_ENROLLED",
            "Roster entry must be ENROLLED.",
            409,
        )

    prior = [
        e
        for e in DB["skills_evaluations"].values()
        if e["roster_entry_id"] == rid
    ]
    attempt_number = len(prior) + 1
    if attempt_number > 2:
        raise ApiError(
            "ERR_REMEDIATION_LIMIT_EXCEEDED",
            "At most 2 skills evaluation attempts are permitted.",
            409,
        )
    if attempt_number == 2:
        first = sorted(prior, key=lambda x: (x["created_at"], x["id"]))[0]
        if first["outcome"] != "REMEDIATION_REQUIRED":
            raise ApiError(
                "ERR_REMEDIATION_LIMIT_EXCEEDED",
                "A second attempt requires a prior REMEDIATION_REQUIRED.",
                409,
            )
    is_retest = attempt_number == 2

    total_items = len(items)
    passed_items = sum(1 for it in items if it["passed"])
    critical_failed = any(it["critical"] and not it["passed"] for it in items)
    from decimal import Decimal, ROUND_HALF_UP

    score_percent = float(
        (Decimal(passed_items) * Decimal(100) / Decimal(total_items)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )
    threshold = 90.00 if is_retest else 84.00
    if not critical_failed and score_percent >= threshold:
        outcome = "PASS"
    else:
        outcome = "FAIL" if is_retest else "REMEDIATION_REQUIRED"

    e = {
        "id": new_id(),
        "roster_entry_id": rid,
        "evaluated_by_instructor_id": caller.user_id,
        "attempt_number": attempt_number,
        "is_remediation_retest": is_retest,
        "items": items,
        "total_items": total_items,
        "passed_items": passed_items,
        "score_percent": score_percent,
        "outcome": outcome,
        "created_at": now_iso_ms(),
    }
    DB["skills_evaluations"][e["id"]] = e

    if outcome == "PASS":
        r["status"] = "PASSED"
        if is_retest:
            r["remediation_used"] = True
        touch(r)
    elif outcome == "REMEDIATION_REQUIRED":
        r["remediation_used"] = True
        touch(r)
    else:  # FAIL
        r["status"] = "FAILED"
        touch(r)
    return respond_obj(ser_skills(e), 201)


@app.get("/aha/roster-entries/<rid>/skills-evaluations")
def list_roster_skills(rid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    get_or_404("roster_entries", "roster_entry", rid)
    items = [
        ser_skills(e)
        for e in sorted(
            DB["skills_evaluations"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if e["roster_entry_id"] == rid
    ]
    return paginate(items)


@app.get("/aha/instructors/<iid>/skills-evaluations")
def list_instructor_skills(iid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    get_or_404("instructors", "instructor", iid)
    items = [
        ser_skills(e)
        for e in sorted(
            DB["skills_evaluations"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if e["evaluated_by_instructor_id"] == iid
    ]
    return paginate(items)


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


@app.get("/aha/cards/<cid>")
def get_card(cid):
    caller = get_caller()
    require_roles(
        caller,
        {
            "NationalAdmin",
            "TCAdmin",
            "TCCoordinator",
            "QAAuditor",
            "Instructor",
            "TrainingFaculty",
            "Employer",
        },
    )
    c = get_or_404("cards", "card", cid)
    return respond_obj(ser_card(c))


@app.get("/aha/roster-entries/<rid>/cards")
def list_roster_cards(rid):
    caller = get_caller()
    require_roles(
        caller,
        {"NationalAdmin", "TCAdmin", "TCCoordinator", "QAAuditor", "Instructor", "TrainingFaculty"},
    )
    get_or_404("roster_entries", "roster_entry", rid)
    items = [
        ser_card(c)
        for c in sorted(DB["cards"].values(), key=lambda x: (x["created_at"], x["id"]))
        if c["roster_entry_id"] == rid
    ]
    return paginate(items)


@app.get("/aha/training-centers/<cid>/cards")
def list_center_cards(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "QAAuditor"})
    get_or_404("training_centers", "training_center", cid)
    status = request.args.get("status")
    items = [
        ser_card(c)
        for c in sorted(DB["cards"].values(), key=lambda x: (x["created_at"], x["id"]))
        if c["training_center_id"] == cid and (status is None or c["status"] == status)
    ]
    return paginate(items)


@app.get("/aha/cards/<cid>/renewals")
def list_card_renewals(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "QAAuditor"})
    get_or_404("cards", "card", cid)
    items = [
        ser_card(c)
        for c in sorted(DB["cards"].values(), key=lambda x: (x["created_at"], x["id"]))
        if c["prior_card_id"] == cid
    ]
    return paginate(items)


@app.post("/aha/cards/<cid>/revoke")
def revoke_card(cid):
    caller = get_caller()
    require_roles(caller, {"QAAuditor", "NationalAdmin"})
    c = get_or_404("cards", "card", cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_CARD_NOT_ACTIVE", "Card must be ACTIVE to revoke.", 409)
    c["status"] = "REVOKED"
    touch(c)
    center = DB["training_centers"].get(c["training_center_id"])
    if center is not None:
        center["active_card_count"] = max(0, center["active_card_count"] - 1)
        touch(center)
    return respond_obj(ser_card(c))


@app.get("/aha/cards/<cid>/roster-entries")
def list_card_roster_entries(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "QAAuditor"})
    get_or_404("cards", "card", cid)
    items = [
        ser_roster(r)
        for r in sorted(
            DB["roster_entries"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if r["prior_card_id"] == cid
    ]
    return paginate(items)


@app.get("/aha/cards/<cid>/verifications")
def list_card_verifications(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "QAAuditor", "Employer"})
    get_or_404("cards", "card", cid)
    items = [
        ser_verification(v)
        for v in sorted(
            DB["card_verifications"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if v["card_id"] == cid
    ]
    return paginate(items)


# ---------------------------------------------------------------------------
# Employer Verification
# ---------------------------------------------------------------------------


@app.post("/aha/card-verifications")
def create_card_verification():
    caller = get_caller()
    require_roles(caller, {"Employer", "NationalAdmin", "QAAuditor"})
    data = body()
    require_fields(data, ["card_code", "verification_token", "verifier_reference"])
    card = next(
        (c for c in DB["cards"].values() if c["card_code"] == data["card_code"]), None
    )
    if card is None:
        raise err_not_found("card", "card_code not found")
    if card["verification_token"] != data["verification_token"]:
        raise ApiError(
            "ERR_CARD_VERIFICATION_MISMATCH",
            "verification_token does not match the card.",
            409,
        )
    v = {
        "id": new_id(),
        "card_id": card["id"],
        "verifier_reference": data["verifier_reference"],
        "verified_at": now_iso(),
        "result": "VALID" if card["status"] == "ACTIVE" else card["status"],
        "card_expires_at": card["expires_at"],
        "created_at": now_iso_ms(),
    }
    DB["card_verifications"][v["id"]] = v
    return respond_obj(ser_verification(v), 201)


# ---------------------------------------------------------------------------
# Quality Audits
# ---------------------------------------------------------------------------


@app.post("/aha/quality-audits")
def create_audit():
    caller = get_caller()
    require_roles(caller, {"QAAuditor"})
    data = body()
    require_fields(data, ["target_training_center_id", "expected_training_center_version"])
    center = DB["training_centers"].get(data["target_training_center_id"])
    if center is None:
        raise err_not_found("training_center")
    if data["expected_training_center_version"] != center["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_training_center_version does not match center version.",
            412,
        )
    a = common_fields({})
    a.update(
        target_training_center_id=center["id"],
        opened_by=caller.user_id,
        status="OPEN",
        compliance_score=100,
        opened_at=now_iso(),
        closed_at=None,
    )
    DB["quality_audits"][a["id"]] = a
    center["last_audit_opened_at"] = now_iso()
    touch(center)
    return respond_obj(ser_audit(a), 201)


@app.get("/aha/quality-audits/<aid>")
def get_audit(aid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "QAAuditor"})
    a = get_or_404("quality_audits", "quality_audit", aid)
    return respond_obj(ser_audit(a))


@app.get("/aha/training-centers/<cid>/quality-audits")
def list_center_audits(cid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "QAAuditor"})
    get_or_404("training_centers", "training_center", cid)
    status = request.args.get("status")
    items = [
        ser_audit(a)
        for a in sorted(
            DB["quality_audits"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if a["target_training_center_id"] == cid and (status is None or a["status"] == status)
    ]
    return paginate(items)


SEVERITY_POINTS = {"OBSERVATION": 1.25, "MINOR": 4.5, "MAJOR": 12.5, "CRITICAL": 40}
REPEAT_MULTIPLIER = 1.5


@app.post("/aha/quality-audits/<aid>/findings")
def create_finding(aid):
    caller = get_caller()
    require_roles(caller, {"QAAuditor"})
    a = get_or_404("quality_audits", "quality_audit", aid)
    data = body()
    require_fields(data, ["severity", "description"])
    require_enum(data, "severity", SEVERITY_POINTS.keys())
    repeat = data.get("is_repeat_offense", False)
    if not isinstance(repeat, bool):
        raise err_invalid("is_repeat_offense must be a boolean")
    if a["status"] != "OPEN":
        raise ApiError(
            "ERR_AUDIT_NOT_OPEN", "Audit must be OPEN to append findings.", 409
        )
    from decimal import Decimal, ROUND_HALF_UP

    raw = Decimal(str(SEVERITY_POINTS[data["severity"]])) * (
        Decimal("1.5") if repeat else Decimal("1.0")
    )
    deduction = float(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    f = {
        "id": new_id(),
        "audit_id": aid,
        "severity": data["severity"],
        "is_repeat_offense": repeat,
        "description": data["description"],
        "deduction_points": deduction,
        "created_at": now_iso_ms(),
    }
    DB["audit_findings"][f["id"]] = f
    # Recompute compliance score: round-per-finding then sum
    total = Decimal("0")
    for ff in DB["audit_findings"].values():
        if ff["audit_id"] == aid:
            total += Decimal(str(ff["deduction_points"]))
    score = max(Decimal("0"), Decimal("100") - total)
    a["compliance_score"] = float(score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    touch(a)
    if data["severity"] == "CRITICAL":
        center = DB["training_centers"].get(a["target_training_center_id"])
        if center is not None and center["status"] in ("ACTIVE", "PROBATION"):
            suspend_center(center)
    return respond_obj(ser_finding(f), 201)


@app.get("/aha/quality-audits/<aid>/findings")
def list_findings(aid):
    caller = get_caller()
    require_roles(caller, {"NationalAdmin", "TCAdmin", "QAAuditor"})
    get_or_404("quality_audits", "quality_audit", aid)
    severity = request.args.get("severity")
    items = [
        ser_finding(f)
        for f in sorted(
            DB["audit_findings"].values(), key=lambda x: (x["created_at"], x["id"])
        )
        if f["audit_id"] == aid and (severity is None or f["severity"] == severity)
    ]
    return paginate(items)


@app.post("/aha/quality-audits/<aid>/close")
def close_audit(aid):
    caller = get_caller()
    require_roles(caller, {"QAAuditor"})
    a = get_or_404("quality_audits", "quality_audit", aid)
    data = body()
    require_fields(data, ["outcome"])
    require_enum(data, "outcome", {"CLEAN", "CORRECTIVE_ACTION"})
    if a["status"] != "OPEN":
        raise ApiError("ERR_AUDIT_NOT_OPEN", "Audit must be OPEN to close.", 409)
    if data["outcome"] == "CLEAN":
        has_critical = any(
            f["audit_id"] == aid and f["severity"] == "CRITICAL"
            for f in DB["audit_findings"].values()
        )
        if has_critical:
            raise ApiError(
                "ERR_AUDIT_HAS_OPEN_CRITICAL_FINDINGS",
                "Audit has CRITICAL findings and cannot close CLEAN.",
                409,
            )
        a["status"] = "CLOSED_CLEAN"
    else:
        a["status"] = "CLOSED_CORRECTIVE"
    a["closed_at"] = now_iso()
    touch(a)
    if data["outcome"] == "CORRECTIVE_ACTION":
        center = DB["training_centers"].get(a["target_training_center_id"])
        if center is not None and center["status"] == "ACTIVE":
            center["status"] = "PROBATION"
            center["probation_started_at"] = now_iso()
            touch(center)
    return respond_obj(ser_audit(a))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
