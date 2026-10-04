"""Certifications: enrollment, exams, audit, expiry sweep."""
from datetime import timedelta
from flask import request

import errors as E
import middleware as mw
from db import db
from response import success_list, success_object
from services import calculations as calc
from routes.agreements import bp


def pub_cert(c):
    return {
        "id": c["id"], "employee_id": c["employee_id"], "program_code": c["program_code"],
        "status": c["status"], "exam_score": c["exam_score"],
        "exam_attempts": c["exam_attempts"], "proctor_anomaly": c["proctor_anomaly"],
        "proctor_inspector_id": c["proctor_inspector_id"],
        "audit_inspector_id": c["audit_inspector_id"],
        "certified_at": c["certified_at"], "expires_at": c["expires_at"],
        "created_at": c["created_at"], "updated_at": c["updated_at"], "version": c["version"],
    }


def get_cert(cid):
    c = db.certifications.get(cid)
    if c is None:
        raise E.err_not_found("certification not found")
    return c


def _cert_licensee(c):
    return db.employees[c["employee_id"]]["licensee_id"]


def _cert_scope(uid, role, c):
    if role == "LicenseeManager" and uid != _cert_licensee(c):
        raise E.err_forbidden()


@bp.post("/licensing/employees/<eid>/certifications")
def enroll(eid):
    uid, role = mw.auth()
    mw.require_role(role, ("LicenseeManager",))
    emp = db.employees.get(eid)
    if emp is None:
        raise E.err_not_found("employee not found")
    if uid != emp["licensee_id"]:
        raise E.err_forbidden()
    b = mw.body()
    program_code = mw.req_str(b, "program_code")
    rec = mw.make_resource({
        "employee_id": eid, "program_code": program_code, "status": "ENROLLED",
        "exam_score": None, "exam_attempts": 0, "proctor_anomaly": False,
        "proctor_inspector_id": None, "audit_inspector_id": None,
        "certified_at": None, "expires_at": None,
    })
    db.certifications[rec["id"]] = rec
    return success_object(pub_cert(rec), 201)


@bp.get("/licensing/certifications/<cid>")
def get_certification(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "BrandInspector"))
    c = get_cert(cid)
    _cert_scope(uid, role, c)
    return success_object(pub_cert(c))


@bp.get("/licensing/certifications")
def list_certifications():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin", "LicenseeManager", "BrandInspector"))
    items = list(db.certifications.values())
    if role == "LicenseeManager":
        items = [c for c in items if _cert_licensee(c) == uid]
    emp = request.args.get("employee_id")
    if emp is not None:
        items = [c for c in items if c["employee_id"] == emp]
    st = request.args.get("status")
    if st is not None:
        items = [c for c in items if c["status"] == st]
    page, limit, offset, total = mw.paginate(items)
    return success_list([pub_cert(x) for x in page], limit, offset, total)


@bp.post("/licensing/certifications/<cid>/record-exam")
def record_exam(cid):
    uid, role = mw.auth()
    mw.require_role(role, ("BrandInspector",))
    c = get_cert(cid)
    if c["status"] != "ENROLLED":
        raise E.err_invalid_cert_state()
    b = mw.body()
    score = mw.req_int(b, "exam_score", minimum=0, maximum=100)
    anomaly = mw.opt_bool(b, "proctor_anomaly", False)
    c["exam_score"] = score
    c["proctor_anomaly"] = anomaly
    c["proctor_inspector_id"] = uid
    c["exam_attempts"] += 1
    if calc.exam_passed(score, anomaly):
        c["status"] = "EXAM_PASSED"
    mw.touch(c)
    return success_object(pub_cert(c))


def _audit_common(cid, uid, role):
    mw.require_role(role, ("BrandInspector",))
    c = get_cert(cid)
    if c["status"] != "EXAM_PASSED":
        raise E.err_invalid_cert_state()
    if uid == c["proctor_inspector_id"]:
        raise E.err_sod("the auditing inspector must differ from the proctor")
    return c


def _has_active_agreement(licensee_id):
    return any(
        a["licensee_id"] == licensee_id and a["status"] == "ACTIVE"
        for a in db.license_agreements.values()
    )


@bp.post("/licensing/certifications/<cid>/audit-verify")
def audit_verify(cid):
    uid, role = mw.auth()
    c = _audit_common(cid, uid, role)
    emp = db.employees[c["employee_id"]]
    if not _has_active_agreement(emp["licensee_id"]):
        raise E.err_agreement_not_active(
            "audit-verify requires an ACTIVE agreement for the employee's licensee"
        )
    c["status"] = "CERTIFIED"
    c["audit_inspector_id"] = uid
    c["certified_at"] = mw.fmt_clock(db.clock)
    c["expires_at"] = mw.fmt_clock(db.clock + timedelta(days=calc.CERT_VALIDITY_DAYS))
    mw.touch(c)
    calc.recompute_posture_for_licensee_stores(emp["licensee_id"])
    return success_object(pub_cert(c))


@bp.post("/licensing/certifications/<cid>/audit-reject")
def audit_reject(cid):
    uid, role = mw.auth()
    c = _audit_common(cid, uid, role)
    b = mw.body()
    c["rejection_reason"] = mw.opt_str(b, "reason")
    c["status"] = "AUDIT_FAILED"
    c["audit_inspector_id"] = uid
    mw.touch(c)
    return success_object(pub_cert(c))


@bp.post("/licensing/certifications/sweep-expiry")
def sweep_certification_expiry():
    uid, role = mw.auth()
    mw.require_role(role, ("BrandProgramAdmin",))
    expired = []
    affected_licensees = set()
    for c in list(db.certifications.values()):
        if c["status"] != "CERTIFIED":
            continue
        expires = mw.parse_iso8601(c["expires_at"])
        if db.clock >= expires:
            c["status"] = "EXPIRED"
            mw.touch(c)
            expired.append(c)
            affected_licensees.add(db.employees[c["employee_id"]]["licensee_id"])
    for lic in affected_licensees:
        calc.recompute_posture_for_licensee_stores(lic)
    page, limit, offset, total = mw.paginate(expired)
    return success_list([pub_cert(x) for x in page], limit, offset, total)
