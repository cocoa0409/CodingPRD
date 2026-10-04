"""Recertification (PRD §3.6): OCC-guarded draft creation, CE entries, the
credit waterfall, deterministic audit selection, decisions and audit outcomes,
and the deny/fail reopen cycle."""

from flask import Blueprint, request

from db import STORE, base_entity, disciplinary_hold, now_dt, serialize, touch
from envelope import ok_list, ok_object, list_page
from errors import ApiError, raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, opt_str,
                        req_enum, req_int, req_number, req_str)
from services.ce import (audit_select, check_sufficiency, compute_recert_seq,
                         eligible_entries, waterfall)
from util import add_months, is_half_increment, num, parse_date

bp = Blueprint("recerts", __name__)


def recert_json(a):
    return serialize(a)


def _store_credited(app, credited):
    for k in ("national_credited_hours", "local_credited_hours",
              "individual_credited_hours", "total_credited_hours"):
        app[k] = num(credited[k])


def _recompute_draft_credited(app, level):
    entries = eligible_entries(app, ("RECORDED", "VERIFIED"))
    _store_credited(app, waterfall(app, level, entries))


def _extend_certification_anniversary(app, cert):
    """Anniversary-preserving extension: new expiry is measured from the pinned
    creation-time expiry, never from the approval date (PRD §3.6)."""
    cert["expires_on"] = add_months(app["cert_expires_on_at_creation"], 24)
    cert["lapse_deadline"] = add_months(cert["expires_on"], 48)
    cert["renewed_count"] += 1
    touch(cert)


@bp.post("/registry/recert-applications")
def create_recert():
    uid, _ = authn(["Candidate"])
    b = body()
    certification_id = req_str(b, "certification_id")
    model = req_enum(b, "model", ["NCCP", "HOURLY"])
    expected_version = req_int(b, "expected_certification_version")

    cert = STORE.certifications.get(certification_id)
    if not cert:
        raise_err("ERR_NOT_FOUND", "Certification %s does not exist" % certification_id)
    if cert["candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the owning candidate may open a recertification draft")
    if expected_version != cert["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_certification_version %s does not match current version %s"
                  % (expected_version, cert["version"]))
    if cert["status"] != "ACTIVE":
        raise_err("ERR_CERTIFICATION_NOT_ACTIVE",
                  "Certification is %s, not ACTIVE" % cert["status"])

    candidate = STORE.candidates.get(uid)
    if candidate and candidate["status"] == "BARRED":
        raise_err("ERR_PERMANENTLY_BARRED", "Candidate is BARRED")
    if disciplinary_hold(uid):
        raise_err("ERR_DISCIPLINARY_HOLD",
                  "Candidate is under a HOLD_NEW_APPLICATIONS interim action")

    existing_draft = None
    for a in STORE.recerts.values():
        if a["certification_id"] == certification_id:
            if a["status"] in ("SUBMITTED", "AUDIT_PENDING"):
                raise_err("ERR_RECERT_IN_PROGRESS_CONFLICT",
                          "Another application for this certification is %s" % a["status"])
            if a["status"] == "DRAFT":
                existing_draft = a
    if existing_draft is not None:
        existing_draft["status"] = "SUPERSEDED"
        touch(existing_draft)

    e = base_entity()
    e.update({
        "certification_id": certification_id,
        "candidate_id": uid,
        "model": model,
        "cycle_window_start": add_months(cert["expires_on"], -12),
        "cert_expires_on_at_creation": cert["expires_on"],
        "recert_seq": None,
        "audit_selected": None,
        "audit_reasons": [],
        "national_credited_hours": 0,
        "local_credited_hours": 0,
        "individual_credited_hours": 0,
        "total_credited_hours": 0,
        "status": "DRAFT",
        "submitted_at": None,
        "decided_at": None,
        "_ever_submitted": False,
    })
    STORE.recerts[e["id"]] = e
    # Opening a draft mutates the certification (invalidates stale OCC views).
    touch(cert)
    return ok_object(recert_json(e), 201)


@bp.get("/registry/recert-applications")
def list_recerts():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    certification_id = request.args.get("certification_id")
    status = request.args.get("status")
    items = []
    for a in STORE.recerts.values():
        if candidate_id is not None and a["candidate_id"] != candidate_id:
            continue
        if certification_id is not None and a["certification_id"] != certification_id:
            continue
        if status is not None and a["status"] != status:
            continue
        items.append(a)
    page, total, limit, offset = list_page(items)
    return ok_list([recert_json(a) for a in page], total, limit, offset)


@bp.get("/registry/recert-applications/<rid>")
def get_recert(rid):
    authn(ALL_AUTHENTICATED_ROLES)
    a = STORE.recerts.get(rid)
    if not a:
        raise_err("ERR_NOT_FOUND", "RecertApplication %s does not exist" % rid)
    return ok_object(recert_json(a), 200)


@bp.post("/registry/recert-applications/<rid>/ce-entries")
def add_ce_entry(rid):
    uid, _ = authn(["Candidate"])
    b = body()
    component = req_enum(b, "component", ["NATIONAL", "LOCAL", "INDIVIDUAL"])
    hours = req_number(b, "hours")
    delivery_method = req_enum(b, "delivery_method", ["DISTRIBUTED", "IN_PERSON"])
    course_code = req_str(b, "course_code")
    course_date = parse_date(b.get("course_date"))
    provider_name = req_str(b, "provider_name")
    if float(hours) <= 0:
        raise_err("ERR_INVALID_REQUEST", "hours must be positive")
    if course_date is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'course_date' must be an ISO-8601 date")
    # Priority 3.5: the 0.5-increment check sits between shape and existence.
    if not is_half_increment(hours):
        raise_err("ERR_CE_HOURS_INCREMENT", "CE hours must be a positive multiple of 0.5")

    app = STORE.recerts.get(rid)
    if not app:
        raise_err("ERR_NOT_FOUND", "RecertApplication %s does not exist" % rid)
    if app["candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the owning candidate may add CE entries")
    if app["status"] != "DRAFT":
        raise_err("ERR_RECERT_NOT_DRAFT",
                  "Recertification application is %s, not DRAFT" % app["status"])

    if not (app["cycle_window_start"].date() <= course_date
            <= app["cert_expires_on_at_creation"].date()):
        raise_err("ERR_CE_ENTRY_OUTSIDE_CYCLE",
                  "course_date falls outside the pinned cycle window")

    for e in STORE.ce_entries.values():
        if e["recert_application_id"] == rid and e["course_code"] == course_code:
            raise_err("ERR_DUPLICATE_COURSE_IN_CYCLE",
                      "course_code %s already present on this application" % course_code)

    e = base_entity()
    e.update({
        "recert_application_id": rid,
        "component": component,
        "hours": hours,
        "delivery_method": delivery_method,
        "course_code": course_code,
        "course_date": course_date,
        "provider_name": provider_name,
        "status": "RECORDED",
        "reject_reason": None,
    })
    STORE.ce_entries[e["id"]] = e

    cert = STORE.certifications.get(app["certification_id"])
    level = STORE.levels.get(cert["level_id"]) if cert else None
    if level:
        _recompute_draft_credited(app, level)
        touch(app)
    return ok_object(serialize(e), 201)


@bp.get("/registry/recert-applications/<rid>/ce-entries")
def list_ce_entries(rid):
    authn(ALL_AUTHENTICATED_ROLES)
    app = STORE.recerts.get(rid)
    if not app:
        raise_err("ERR_NOT_FOUND", "RecertApplication %s does not exist" % rid)
    items = [e for e in STORE.ce_entries.values()
             if e["recert_application_id"] == rid]
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(e) for e in page], total, limit, offset)


@bp.post("/registry/recert-applications/<rid>/submit")
def submit_recert(rid):
    uid, _ = authn(["Candidate"])
    app = STORE.recerts.get(rid)
    if not app:
        raise_err("ERR_NOT_FOUND", "RecertApplication %s does not exist" % rid)
    if app["candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the owning candidate may submit")
    if app["status"] != "DRAFT":
        raise_err("ERR_RECERT_NOT_DRAFT",
                  "Recertification application is %s, not DRAFT" % app["status"])

    cert = STORE.certifications.get(app["certification_id"])
    if not cert or cert["status"] != "ACTIVE":
        raise_err("ERR_CERTIFICATION_NOT_ACTIVE",
                  "Certification must be ACTIVE at submission")
    now = now_dt()
    if not (app["cycle_window_start"] <= now <= app["cert_expires_on_at_creation"]):
        raise_err("ERR_RECERT_WINDOW_NOT_OPEN",
                  "Current time is outside the pinned cycle window")

    level = STORE.levels.get(cert["level_id"])
    entries = eligible_entries(app, ("RECORDED", "VERIFIED"))
    credited = waterfall(app, level, entries)
    _store_credited(app, credited)
    check_sufficiency(app, level, credited)

    seq = compute_recert_seq(app)
    selected, reasons = audit_select(app, app["candidate_id"], entries, seq, now)
    app["recert_seq"] = seq
    app["audit_selected"] = selected
    app["audit_reasons"] = reasons
    app["submitted_at"] = now
    app["status"] = "AUDIT_PENDING" if selected else "SUBMITTED"
    app["_ever_submitted"] = True
    touch(app)
    return ok_object(recert_json(app), 200)


@bp.post("/registry/recert-applications/<rid>/decision")
def decide_recert(rid):
    authn(["RegistryAdmin"])
    b = body()
    outcome = req_enum(b, "outcome", ["APPROVED", "DENIED"])
    app = STORE.recerts.get(rid)
    if not app:
        raise_err("ERR_NOT_FOUND", "RecertApplication %s does not exist" % rid)
    if app["status"] != "SUBMITTED":
        raise_err("ERR_RECERT_NOT_SUBMITTED",
                  "Recertification application is %s, not SUBMITTED" % app["status"])
    if outcome == "APPROVED":
        cert = STORE.certifications.get(app["certification_id"])
        if not cert or cert["status"] != "ACTIVE":
            raise_err("ERR_CERTIFICATION_NOT_ACTIVE",
                      "Certification must be ACTIVE at decision time")
        _extend_certification_anniversary(app, cert)
    app["status"] = outcome
    app["decided_at"] = now_dt()
    touch(app)
    return ok_object(recert_json(app), 200)


@bp.post("/registry/recert-applications/<rid>/audit-outcome")
def audit_outcome(rid):
    authn(["RegistryAdmin"])
    b = body()
    verdicts = b.get("entry_verdicts")
    if not isinstance(verdicts, list):
        raise_err("ERR_INVALID_REQUEST", "Field 'entry_verdicts' is required and must be an array")
    app = STORE.recerts.get(rid)
    if not app:
        raise_err("ERR_NOT_FOUND", "RecertApplication %s does not exist" % rid)
    if app["status"] != "AUDIT_PENDING":
        raise_err("ERR_RECERT_NOT_AUDIT_PENDING",
                  "Recertification application is %s, not AUDIT_PENDING" % app["status"])

    cert = STORE.certifications.get(app["certification_id"])
    if not cert or cert["status"] != "ACTIVE":
        raise_err("ERR_CERTIFICATION_NOT_ACTIVE",
                  "Certification must be ACTIVE at decision time")

    for i, v in enumerate(verdicts):
        if not isinstance(v, dict):
            raise_err("ERR_INVALID_REQUEST", "entry_verdicts[%d] must be an object" % i)
        entry_id = v.get("entry_id", v.get("id"))
        verdict = v.get("verdict", v.get("outcome"))
        if not isinstance(entry_id, str) or verdict not in ("VERIFIED", "REJECTED"):
            raise_err("ERR_INVALID_REQUEST",
                      "entry_verdicts[%d] needs an entry_id and a verdict of VERIFIED|REJECTED" % i)
        entry = STORE.ce_entries.get(entry_id)
        if not entry or entry["recert_application_id"] != rid:
            raise_err("ERR_NOT_FOUND", "CECreditEntry %s does not exist on this application" % entry_id)
        if entry["status"] != "RECORDED":
            continue
        entry["status"] = verdict
        entry["reject_reason"] = (v.get("reject_reason") or v.get("reason")) if verdict == "REJECTED" else None
        touch(entry)

    level = STORE.levels.get(cert["level_id"])
    entries = eligible_entries(app, ("VERIFIED",))
    credited = waterfall(app, level, entries)
    _store_credited(app, credited)

    app["decided_at"] = now_dt()
    try:
        check_sufficiency(app, level, credited)
    except ApiError:
        app["status"] = "AUDIT_FAILED"
        touch(app)
        return ok_object(recert_json(app), 200)
    _extend_certification_anniversary(app, cert)
    app["status"] = "APPROVED"
    touch(app)
    return ok_object(recert_json(app), 200)


@bp.post("/registry/recert-applications/<rid>/reopen")
def reopen_recert(rid):
    uid, _ = authn(["Candidate"])
    app = STORE.recerts.get(rid)
    if not app:
        raise_err("ERR_NOT_FOUND", "RecertApplication %s does not exist" % rid)
    if app["candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the owning candidate may reopen")
    if app["status"] not in ("DENIED", "AUDIT_FAILED"):
        raise_err("ERR_RECERT_NOT_REOPENABLE",
                  "Recertification application is %s, not DENIED or AUDIT_FAILED" % app["status"])
    app["status"] = "DRAFT"
    touch(app)
    cert = STORE.certifications.get(app["certification_id"])
    level = STORE.levels.get(cert["level_id"]) if cert else None
    if level:
        _recompute_draft_credited(app, level)
    return ok_object(recert_json(app), 200)
