"""Food safety audits, corrective action and escalation -- PRD 3.9."""

from flask import Blueprint

import db
from core import LOCK, logical_today
from errors import ApiError
from middleware import (ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                        ROLE_QUALITY_AUDITOR, authorize, body, current_user_id,
                        req_date, req_enum, req_str)
from response import created, ok
from routes.base import (audit_or_404, finding_or_404, fk_lookup, filters,
                         kiosk_or_404, paginate)
from services import calc, domain

bp = Blueprint("audits", __name__)

SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
FINDING_TERMINAL = ("CORRECTED", "VERIFIED", "WAIVED")


def _scope_audit(actor, audit):
    if not actor.is_manager:
        return
    kiosk = db.kiosks.get(audit["kiosk_id"])
    store = domain.store_of_kiosk(kiosk) if kiosk is not None else None
    if store is None or store["id"] != actor.user_id:
        raise ApiError("ERR_OWNERSHIP_MISMATCH")


def _audit_kiosk(audit):
    return db.kiosks.get(audit["kiosk_id"])


@bp.post("/audits")
def schedule_audit():
    authorize(ROLE_QUALITY_AUDITOR)
    payload = body()
    kiosk = fk_lookup(payload, "kiosk_id", kiosk_or_404)
    req_str(payload, "kiosk_id")
    scheduled_for = req_date(payload, "scheduled_for")
    with LOCK:
        row = db.new_row(db.food_safety_audits, {
            "kiosk_id": kiosk["id"],
            "scheduled_for": scheduled_for,
            "status": "SCHEDULED",
            "opened_by_user_id": None,
            "verified_by_user_id": None,
            "round_count": 0,
            "critical_finding_count": 0,
            "open_finding_count": 0,
            "score": 100,
            "closure_outcome": None,
        })
    return created(db.public(row))


@bp.get("/audits/<audit_id>")
def get_audit(audit_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_QUALITY_AUDITOR)
    audit = audit_or_404(audit_id)
    _scope_audit(actor, audit)
    return ok(db.public(audit))


@bp.get("/audits")
def list_audits():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_QUALITY_AUDITOR)
    rows = list(db.food_safety_audits.values())
    if actor.is_manager:
        rows = [a for a in rows
                if (domain.store_of_kiosk(db.kiosks.get(a["kiosk_id"]))
                    or {}).get("id") == actor.user_id]
    rows = filters(rows, {"kiosk_id": "kiosk_id", "status": "status"})
    return paginate(rows)


@bp.post("/audits/<audit_id>/start")
def start_audit(audit_id):
    authorize(ROLE_QUALITY_AUDITOR)
    audit = audit_or_404(audit_id)
    with LOCK:
        if audit["status"] != "SCHEDULED":
            raise ApiError("ERR_AUDIT_INVALID_STATE")
        if logical_today() < audit["scheduled_for"]:
            raise ApiError("ERR_AUDIT_NOT_YET_DUE")
        audit["status"] = "IN_PROGRESS"
        audit["opened_by_user_id"] = current_user_id()
        db.touch(audit)
    return ok(db.public(audit))


@bp.post("/audits/<audit_id>/findings")
def record_finding(audit_id):
    authorize(ROLE_QUALITY_AUDITOR)
    audit = audit_or_404(audit_id)
    payload = body()
    severity = req_enum(payload, "severity", SEVERITIES)
    finding_code = req_str(payload, "finding_code")
    description = req_str(payload, "description")
    with LOCK:
        if audit["status"] != "IN_PROGRESS":
            raise ApiError("ERR_AUDIT_INVALID_STATE")
        row = db.new_row(db.audit_findings, {
            "audit_id": audit["id"],
            "severity": severity,
            "finding_code": finding_code,
            "description": description,
            "status": "OPEN",
            "risk_points": calc.FINDING_RISK_POINTS[severity],
            "correction_note": None,
            "waiver_rationale": None,
        })
        db.apply_changes(audit, {
            "open_finding_count": audit["open_finding_count"] + 1,
        })
        kiosk = _audit_kiosk(audit)
        if kiosk is not None and severity == "CRITICAL":
            domain.refresh_open_critical_count(kiosk)
    return created(db.public(row))


@bp.get("/audits/<audit_id>/findings")
def list_findings(audit_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_QUALITY_AUDITOR)
    audit = audit_or_404(audit_id)
    _scope_audit(actor, audit)
    rows = domain.findings_of_audit(audit["id"])
    rows = filters(rows, {"severity": "severity", "status": "status"})
    return paginate(rows)


@bp.post("/audits/<audit_id>/submit")
def submit_audit(audit_id):
    authorize(ROLE_QUALITY_AUDITOR)
    audit = audit_or_404(audit_id)
    with LOCK:
        if audit["status"] != "IN_PROGRESS":
            raise ApiError("ERR_AUDIT_INVALID_STATE")
        findings = domain.findings_of_audit(audit["id"])
        changes = {
            "critical_finding_count": len([f for f in findings
                                           if f["severity"] == "CRITICAL"]),
            "open_finding_count": len([f for f in findings
                                       if f["status"] == "OPEN"]),
            "score": calc.audit_score(findings),
        }
        kiosk = _audit_kiosk(audit)
        if not findings:
            changes["status"] = "CLOSED"
            changes["closure_outcome"] = "PASS"
            db.apply_changes(audit, changes)
            if kiosk is not None:
                db.apply_changes(kiosk, {
                    "consecutive_clean_audits":
                        kiosk["consecutive_clean_audits"] + 1,
                })
                domain.rederive_kiosk(kiosk)
        else:
            changes["status"] = "CORRECTIVE_ACTION_PENDING"
            db.apply_changes(audit, changes)
            forced = any(f["severity"] == "CRITICAL" for f in findings)
            if kiosk is not None:
                db.apply_changes(kiosk, {"consecutive_clean_audits": 0})
                domain.rederive_kiosk(kiosk, force_lockdown=forced)
    return ok(db.public(audit))


def _finding_of_audit(audit, finding_id):
    finding = finding_or_404(finding_id)
    if finding["audit_id"] != audit["id"]:
        raise ApiError("ERR_AUDIT_RECORD_NOT_FOUND")
    return finding


@bp.post("/audits/<audit_id>/findings/<finding_id>/correct")
def correct_finding(audit_id, finding_id):
    actor = authorize(ROLE_HOST_STORE_MANAGER)
    audit = audit_or_404(audit_id)
    _scope_audit(actor, audit)
    finding = _finding_of_audit(audit, finding_id)
    payload = body()
    note = req_str(payload, "correction_note")
    with LOCK:
        if audit["status"] != "CORRECTIVE_ACTION_PENDING":
            raise ApiError("ERR_AUDIT_INVALID_STATE")
        if finding["status"] != "OPEN":
            raise ApiError("ERR_FINDING_INVALID_STATE")
        finding["status"] = "CORRECTED"
        finding["correction_note"] = note
        db.touch(finding)
        # A CORRECTED finding keeps its risk points: paperwork alone never
        # lifts the kiosk's posture (PRD 3.9).
        db.apply_changes(audit, {
            "open_finding_count": max(0, audit["open_finding_count"] - 1),
        })
    return ok(db.public(finding))


@bp.post("/audits/<audit_id>/findings/<finding_id>/waive")
def waive_finding(audit_id, finding_id):
    authorize(ROLE_QUALITY_AUDITOR)
    audit = audit_or_404(audit_id)
    finding = _finding_of_audit(audit, finding_id)
    payload = body()
    rationale = req_str(payload, "waiver_rationale")
    with LOCK:
        if audit["status"] != "CORRECTIVE_ACTION_PENDING":
            raise ApiError("ERR_AUDIT_INVALID_STATE")
        if finding["status"] != "OPEN":
            raise ApiError("ERR_FINDING_INVALID_STATE")
        if finding["severity"] != "MINOR":
            raise ApiError("ERR_FINDING_NOT_WAIVABLE")
        finding["status"] = "WAIVED"
        finding["waiver_rationale"] = rationale
        db.touch(finding)
        db.apply_changes(audit, {
            "open_finding_count": max(0, audit["open_finding_count"] - 1),
        })
        kiosk = _audit_kiosk(audit)
        if kiosk is not None:
            domain.rederive_kiosk(kiosk)
    return ok(db.public(finding))


@bp.post("/audits/<audit_id>/request-reverification")
def request_reverification(audit_id):
    actor = authorize(ROLE_HOST_STORE_MANAGER)
    audit = audit_or_404(audit_id)
    _scope_audit(actor, audit)
    with LOCK:
        if audit["status"] == "ESCALATED_CLOSURE":
            raise ApiError("ERR_CORRECTIVE_ROUNDS_EXHAUSTED")
        if audit["status"] != "CORRECTIVE_ACTION_PENDING":
            raise ApiError("ERR_AUDIT_INVALID_STATE")
        findings = domain.findings_of_audit(audit["id"])
        if any(f["status"] not in ("CORRECTED", "WAIVED") for f in findings):
            raise ApiError("ERR_OPEN_FINDINGS_BLOCK_REVERIFICATION")
        db.apply_changes(audit, {
            "status": "REVERIFICATION",
            "round_count": audit["round_count"] + 1,
        })
    return ok(db.public(audit))


@bp.post("/audits/<audit_id>/verify")
def verify_audit(audit_id):
    authorize(ROLE_QUALITY_AUDITOR)
    audit = audit_or_404(audit_id)
    payload = body()
    outcome = req_enum(payload, "outcome", ("PASS", "FAIL"))
    req_str(payload, "verification_note")
    with LOCK:
        if audit["status"] != "REVERIFICATION":
            raise ApiError("ERR_AUDIT_INVALID_STATE")
        if current_user_id() == audit["opened_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        findings = domain.findings_of_audit(audit["id"])
        corrected = [f for f in findings if f["status"] == "CORRECTED"]
        kiosk = _audit_kiosk(audit)

        if outcome == "PASS":
            for finding in corrected:
                finding["status"] = "VERIFIED"
                db.touch(finding)
            db.apply_changes(audit, {
                "status": "CLOSED",
                "closure_outcome": "PASS_AFTER_CORRECTION",
                "verified_by_user_id": current_user_id(),
            })
            domain.refresh_audit_counts(audit)
            if kiosk is not None:
                domain.rederive_kiosk(kiosk)
        elif audit["round_count"] < calc.AUDIT_MAX_ROUND_COUNT:
            for finding in corrected:
                finding["status"] = "OPEN"
                finding["correction_note"] = None
                db.touch(finding)
            db.apply_changes(audit, {
                "status": "CORRECTIVE_ACTION_PENDING",
                "open_finding_count": audit["open_finding_count"]
                + len(corrected),
            })
            if kiosk is not None:
                domain.rederive_kiosk(kiosk)
        else:
            db.apply_changes(audit, {
                "status": "ESCALATED_CLOSURE",
                "closure_outcome": "ESCALATED",
                "verified_by_user_id": current_user_id(),
            })
            if kiosk is not None and kiosk["operational_state"] == "OPERATING":
                domain.suspend_kiosk(kiosk, "AUDIT_ESCALATION",
                                     force_lockdown=True)
            elif kiosk is not None:
                domain.rederive_kiosk(kiosk, force_lockdown=True)
    return ok(db.public(audit))
