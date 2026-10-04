"""BrandStandardsAudit endpoints -- two independent state dimensions
(PRD 2.7, 3.8).

POST /franchise/brand-standards-audits, GET /franchise/brand-standards-audits[/{id}]
POST /franchise/brand-standards-audits/{id}/conduct|publish|reopen|remediation-transitions
"""
from decimal import Decimal

from flask import Blueprint

import derived
from auth import guard
from config import (
    AUDIT_KINDS,
    AUDIT_REOPEN_HOURS,
    PASS_MIN,
    REMEDIATION_OPEN_SET,
    STANDARDS_REMEDIATION_HOURS,
)
from errors import ApiError
from fetch import get_agreement, get_audit, paged
from response import created, ok
from store import common_fields, db, hours_from, now_dt, parse_instant, touch
from validate import (
    body,
    opt_decimal,
    opt_id,
    opt_str,
    reject_unknown,
    req_decimal,
    req_enum,
    req_id,
    req_int,
    req_str,
)
from calculations import audit_outcome, standards_audit_score
from money import as_number, dec, round_tenth

bp = Blueprint("audits", __name__)

CREATE_INPUT = [
    "agreement_id", "audit_kind", "conducted_iso", "raw_score", "findings_count",
    "auditor_operator_id", "critical_findings_count",
]

REMEDIATION_ACTIONS = (
    "SUBMIT", "ACKNOWLEDGE", "RESOLVE", "REJECT", "ESCALATE", "DEFAULT",
)


def _started_audit(audit_id):
    audit = get_audit(audit_id)
    if audit.get("audit_status") == "SUPERSEDED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    return audit


def _require_audit_status(audit, allowed):
    if audit.get("audit_status") not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def _require_remediation_status(audit, allowed):
    if audit.get("remediation_status") not in allowed:
        raise ApiError("ERR_INVALID_STATE")


def _sync_agreement(agreement_id):
    agreement = db.agreements.get(agreement_id)
    if agreement is None:
        return None
    derived.refresh_agreement(agreement)
    touch(agreement)
    return agreement


@bp.post("/franchise/brand-standards-audits")
def schedule_audit():
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, CREATE_INPUT)
    agreement_id = req_id(b, "agreement_id")
    audit_kind = req_enum(b, "audit_kind", AUDIT_KINDS)
    conducted_iso = req_str(b, "conducted_iso")
    if parse_instant(conducted_iso) is None:
        raise ApiError("ERR_INVALID_REQUEST", "conducted_iso must be an ISO 8601 UTC instant.")
    raw_score = req_decimal(b, "raw_score", minimum=Decimal("0"), maximum=Decimal("100"))
    findings = req_int(b, "findings_count", minimum=0)
    critical = opt_int_default(b, "critical_findings_count", 0)
    auditor = opt_str(b, "auditor_operator_id", default=None, min_len=1)

    get_agreement(agreement_id)
    if critical > findings:
        raise ApiError("ERR_INVALID_REQUEST", "critical_findings_count may not exceed findings_count.")

    record = common_fields()
    record.update({
        "_kind": "BrandStandardsAudit",
        "agreement_id": agreement_id,
        "auditor_operator_id": auditor,
        "audit_kind": audit_kind,
        "conducted_iso": conducted_iso,
        "raw_score": as_number(raw_score),
        "findings_count": findings,
        "critical_findings_count": critical,
        "weighted_score": 0,
        "outcome": "FAIL",
        "audit_status": "SCHEDULED",
        "remediation_status": "NONE",
        "remediation_owner_operator_id": None,
        "remediation_verifier_operator_id": None,
        "verification_audit_id": None,
        "remediation_due_iso": None,
        "remediation_opened_clock_iso": None,
        "remediation_resolved_clock_iso": None,
    })
    db.audits[record["id"]] = record
    return created(record)


def opt_int_default(b, key, default):
    from validate import opt_int
    return opt_int(b, key, default=default, minimum=0)


@bp.get("/franchise/brand-standards-audits/<audit_id>")
def read_audit(audit_id):
    guard(["FranchiseAdmin", "ComplianceAuditor"])
    return ok(get_audit(audit_id))


@bp.get("/franchise/brand-standards-audits")
def list_audits():
    guard(["FranchiseAdmin", "ComplianceAuditor"])
    return paged(
        db.audits,
        "agreement_id", "verification_audit_id", "audit_status",
        "remediation_status", "audit_kind",
    )


@bp.post("/franchise/brand-standards-audits/<audit_id>/conduct")
def conduct_audit(audit_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["auditor_operator_id"])
    supplied = opt_str(b, "auditor_operator_id", default=None, min_len=1)
    audit = _started_audit(audit_id)
    _require_audit_status(audit, ["SCHEDULED"])
    if supplied is not None:
        audit["auditor_operator_id"] = supplied
    if not audit.get("auditor_operator_id"):
        raise ApiError("ERR_AUDITOR_REQUIRED")
    if int(audit.get("critical_findings_count") or 0) > int(audit.get("findings_count") or 0):
        raise ApiError("ERR_INVALID_REQUEST")
    score = standards_audit_score(audit)
    audit["weighted_score"] = as_number(score)
    audit["outcome"] = audit_outcome(score)
    audit["audit_status"] = "CONDUCTED"
    touch(audit)
    return ok(audit)


@bp.post("/franchise/brand-standards-audits/<audit_id>/publish")
def publish_audit(audit_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["expected_agreement_version"])
    expected_version = req_int(b, "expected_agreement_version", minimum=0)
    audit = _started_audit(audit_id)
    _require_audit_status(audit, ["CONDUCTED"])
    agreement = get_agreement(audit.get("agreement_id"))
    if expected_version != agreement.get("version"):
        raise ApiError("ERR_STALE_VERSION")

    due = parse_instant(agreement.get("audit_due_iso") or "") if agreement.get("audit_due_iso") else None
    conducted = parse_instant(audit.get("conducted_iso") or "")
    if due is not None and conducted is not None and not conducted < due:
        raise ApiError("ERR_AUDIT_CYCLE_EXCEEDED")

    audit["audit_status"] = "PUBLISHED"
    touch(audit)

    # Every earlier published audit for this agreement is superseded.
    for other in db.audits.values():
        if other["id"] == audit["id"]:
            continue
        if other.get("agreement_id") != agreement["id"]:
            continue
        if other.get("audit_status") == "PUBLISHED":
            other["audit_status"] = "SUPERSEDED"
            touch(other)

    if audit.get("outcome") == "FAIL":
        franchisee = db.franchisees.get(agreement.get("franchisee_id"))
        audit["remediation_status"] = "OPEN"
        audit["remediation_owner_operator_id"] = (franchisee or {}).get("principal_name")
        audit["remediation_opened_clock_iso"] = derived.now_iso()
        audit["remediation_due_iso"] = derived.iso_of(
            hours_from(now_dt(), STANDARDS_REMEDIATION_HOURS))
        touch(audit)

    _sync_agreement(agreement["id"])
    return ok(audit)


@bp.post("/franchise/brand-standards-audits/<audit_id>/reopen")
def reopen_audit(audit_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, [])
    audit = _started_audit(audit_id)
    _require_audit_status(audit, ["PUBLISHED"])
    conducted = parse_instant(audit.get("conducted_iso") or "")
    if conducted is None or not now_dt() < hours_from(conducted, AUDIT_REOPEN_HOURS):
        raise ApiError("ERR_REOPEN_WINDOW_CLOSED")
    audit["audit_status"] = "CONDUCTED"
    audit["remediation_status"] = "NONE"
    audit["remediation_opened_clock_iso"] = None
    audit["remediation_due_iso"] = None
    audit["verification_audit_id"] = None
    audit["remediation_resolved_clock_iso"] = None
    touch(audit)
    _sync_agreement(audit.get("agreement_id"))
    return ok(audit)


@bp.post("/franchise/brand-standards-audits/<audit_id>/remediation-transitions")
def remediation_transitions(audit_id):
    guard(["FranchiseAdmin"])
    b = body()
    reject_unknown(b, ["action", "verifier_operator_id", "verification_audit_id", "reason"])
    action = req_enum(b, "action", REMEDIATION_ACTIONS)
    verifier = opt_str(b, "verifier_operator_id", default=None, min_len=1)
    verification_audit_id = opt_id(b, "verification_audit_id")
    opt_str(b, "reason", default=None, min_len=1)
    audit = _started_audit(audit_id)

    if action == "SUBMIT":
        return _submit(audit, verification_audit_id)
    if action == "ACKNOWLEDGE":
        return _acknowledge(audit, verifier)
    if action == "ESCALATE":
        return _escalate(audit)
    if action == "RESOLVE":
        return _resolve(audit, verifier)
    if action == "REJECT":
        return _reject(audit, verifier)
    return _default(audit)


def _submit(audit, verification_audit_id):
    _require_remediation_status(audit, ["OPEN"])
    if verification_audit_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "verification_audit_id is required to submit.")
    candidate = db.audits.get(verification_audit_id)
    if candidate is None or candidate.get("agreement_id") != audit.get("agreement_id") \
            or candidate["id"] == audit["id"]:
        raise ApiError("ERR_VERIFICATION_AUDIT_NOT_FOUND")
    due = parse_instant(audit.get("remediation_due_iso") or "")
    conducted = parse_instant(candidate.get("conducted_iso") or "")
    if due is not None and conducted is not None and conducted > due:
        raise ApiError("ERR_REMEDIATION_WINDOW_CLOSED")
    audit["verification_audit_id"] = verification_audit_id
    audit["remediation_status"] = "SUBMITTED"
    touch(audit)
    _sync_agreement(audit.get("agreement_id"))
    return ok(audit)


def _acknowledge(audit, verifier):
    _require_remediation_status(audit, ["SUBMITTED"])
    if verifier is None:
        raise ApiError("ERR_INVALID_REQUEST", "verifier_operator_id is required.")
    if verifier == audit.get("remediation_owner_operator_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    audit["remediation_verifier_operator_id"] = verifier
    audit["remediation_status"] = "RE_VERIFICATION"
    touch(audit)
    _sync_agreement(audit.get("agreement_id"))
    return ok(audit)


def _escalate(audit):
    if audit.get("remediation_status") == "DEFAULTED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    _require_remediation_status(audit, ["OPEN", "SUBMITTED"])
    due = parse_instant(audit.get("remediation_due_iso") or "")
    if due is None or now_dt() < due:
        raise ApiError("ERR_REMEDIATION_NOT_OVERDUE")
    audit["remediation_status"] = "ESCALATED"
    touch(audit)
    agreement = _sync_agreement(audit.get("agreement_id"))
    if agreement is not None:
        agreement["standards_status"] = "REMEDIATION_REQUIRED"
    return ok(audit)


def _resolve(audit, verifier):
    _require_remediation_status(audit, ["RE_VERIFICATION"])
    if verifier is not None and verifier == audit.get("remediation_owner_operator_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    stored_verifier = verifier or audit.get("remediation_verifier_operator_id")
    if stored_verifier is not None and stored_verifier == audit.get("remediation_owner_operator_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    verification = db.audits.get(audit.get("verification_audit_id"))
    score = dec((verification or {}).get("weighted_score"))
    if score < dec(PASS_MIN):
        raise ApiError("ERR_REMEDIATION_FAILED")
    if verifier is not None:
        audit["remediation_verifier_operator_id"] = verifier
    audit["remediation_status"] = "RESOLVED"
    audit["remediation_resolved_clock_iso"] = derived.now_iso()
    touch(audit)
    _sync_agreement(audit.get("agreement_id"))
    return ok(audit)


def _reject(audit, verifier):
    _require_remediation_status(audit, ["RE_VERIFICATION"])
    if verifier is not None and verifier == audit.get("remediation_owner_operator_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    audit["verification_audit_id"] = None
    audit["remediation_status"] = "OPEN"
    touch(audit)
    _sync_agreement(audit.get("agreement_id"))
    return ok(audit)


def _default(audit):
    _require_remediation_status(audit, ["ESCALATED"])
    audit["remediation_status"] = "DEFAULTED"
    touch(audit)
    agreement = _sync_agreement(audit.get("agreement_id"))
    if agreement is not None:
        agreement["standards_status"] = "DEFAULT"
        franchisee = db.franchisees.get(agreement.get("franchisee_id"))
        if franchisee is not None:
            franchisee["status"] = "SUSPENDED"
            touch(franchisee)
    return ok(audit)