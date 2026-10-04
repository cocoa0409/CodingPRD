"""Audits (PRD 3.2).

POST /farm-network/farms/{id}/audits   (NetworkManager, 201)
GET  /farm-network/farms/{id}/audits   (NM, Auditor, QM, 200)
GET  /farm-network/audits/{id}         (NM, Auditor, QM, 200)
POST /farm-network/audits/{id}/complete  (Auditor, 200)
"""
from datetime import timedelta

from flask import Blueprint, request

import constants as C
import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok, ok_list
from serialize import audit_out
from validation import get_body, f_enum, f_datetime, f_str, pagination

bp = Blueprint("audits", __name__, url_prefix="/farm-network")

_READ_ROLES = ("NetworkManager", "Auditor", "QualityManager")


@bp.route("/farms/<fid>/audits", methods=["POST"])
def schedule_audit(fid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager",))
    farm = domain.get_farm_or_404(fid)
    data = get_body()
    audit_type = f_enum(data, "audit_type", C.AUDIT_TYPES)
    sched_raw, sched = f_datetime(data, "scheduled_for")
    if farm["status"] == "REMOVED":
        raise ApiError("ERR_FARM_TERMINAL", 409, "farm is REMOVED")
    # Minimum 30-day gap against every non-CANCELLED audit of the farm, in
    # either direction (priority 11); exactly 30 days is allowed.
    gap_seconds = C.MIN_AUDIT_GAP_DAYS * 86400
    for a in store.audits.values():
        if a["farm_id"] != farm["id"] or a["status"] == "CANCELLED":
            continue
        if abs((sched - a["_scheduled_dt"]).total_seconds()) < gap_seconds:
            raise ApiError("ERR_AUDIT_TOO_SOON", 422,
                           "audit must be at least %d days from every other audit of the farm"
                           % C.MIN_AUDIT_GAP_DAYS)
    ts = now()
    audit = {
        "id": domain.new_id(),
        "farm_id": farm["id"],
        "audit_type": audit_type,
        "scheduled_for": sched_raw,
        "status": "SCHEDULED",
        "auditor_user_id": None,
        "non_conformities_count": 0,
        "completed_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_scheduled_dt": sched,
        "_seq": store.next_seq(),
    }
    store.audits[audit["id"]] = audit
    return ok(audit_out(audit), 201)


@bp.route("/farms/<fid>/audits", methods=["GET"])
def list_audits(fid):
    uid, role = authenticate()
    authorize(role, _READ_ROLES)
    farm = domain.get_farm_or_404(fid)
    limit, offset = pagination()
    status = request.args.get("status")
    audit_type = request.args.get("audit_type")
    rows = [a for a in store.audits.values() if a["farm_id"] == farm["id"]]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    if audit_type is not None:
        rows = [a for a in rows if a["audit_type"] == audit_type]
    page, total = domain.sorted_page(rows, limit, offset)
    return ok_list([audit_out(a) for a in page], limit, offset, total)


@bp.route("/audits/<aid>", methods=["GET"])
def get_audit(aid):
    uid, role = authenticate()
    authorize(role, _READ_ROLES)
    return ok(audit_out(domain.get_audit_or_404(aid)))


def _parse_findings(data):
    """Validate the optional findings list; each entry carries a severity and
    a non-empty description."""
    findings = data.get("findings")
    if findings is None:
        return []
    if not isinstance(findings, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "findings must be a list")
    parsed = []
    for entry in findings:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "each finding must be an object")
        sev = f_enum(entry, "severity", C.CA_SEVERITIES)
        desc = f_str(entry, "description")
        parsed.append((sev, desc))
    return parsed


def _open_corrective_action(audit, severity, description, ts):
    """One OPEN corrective action per finding; due_at = completed_at +
    CA_DUE_DAYS[severity] (PRD 3.3)."""
    ca = {
        "id": domain.new_id(),
        "audit_id": audit["id"],
        "severity": severity,
        "description": description,
        "status": "OPEN",
        "due_at": ts + timedelta(days=C.CA_DUE_DAYS[severity]),
        "evidence_notes": None,
        "verified_by_user_id": None,
        "closed_at": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.corrective_actions[ca["id"]] = ca
    return ca


@bp.route("/audits/<aid>/complete", methods=["POST"])
def complete_audit(aid):
    uid, role = authenticate()
    authorize(role, ("Auditor",))
    audit = domain.get_audit_or_404(aid)
    data = get_body()
    outcome = f_enum(data, "outcome", C.AUDIT_OUTCOMES)
    findings = _parse_findings(data)
    if outcome == "PASSED" and findings:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "findings must be empty or omitted when outcome is PASSED")
    if outcome == "CORRECTIVE_ACTION_REQUIRED" and not findings:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "findings must contain at least one entry for CORRECTIVE_ACTION_REQUIRED")
    # State legality (priority 7) before the temporal window (priority 11).
    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_AUDIT_NOT_SCHEDULED", 409, "audit is not SCHEDULED")
    ts = now()
    early_edge = audit["_scheduled_dt"] - timedelta(days=C.AUDIT_WINDOW_EARLY_DAYS)
    late_edge = audit["_scheduled_dt"] + timedelta(days=C.AUDIT_WINDOW_LATE_DAYS)
    if ts < early_edge or ts > late_edge:
        raise ApiError("ERR_AUDIT_WINDOW_MISSED", 422,
                       "completion must fall within [scheduled_for - 3d, scheduled_for + 7d]")
    audit["status"] = outcome
    audit["auditor_user_id"] = uid
    audit["completed_at"] = ts
    audit["version"] += 1
    audit["updated_at"] = ts
    farm = store.farms.get(audit["farm_id"])
    if outcome == "PASSED":
        if farm is not None:
            farm["last_passed_audit_at"] = ts
            farm["version"] += 1
            farm["updated_at"] = ts
    else:
        # FAILED and CORRECTIVE_ACTION_REQUIRED record the finding count and
        # open one corrective action per finding.
        audit["non_conformities_count"] = len(findings)
        for sev, desc in findings:
            _open_corrective_action(audit, sev, desc, ts)
        if outcome == "FAILED" and farm is not None and farm["status"] == "ACTIVE":
            farm["status"] = "PROBATION"
            farm["version"] += 1
            farm["updated_at"] = ts
    return ok(audit_out(audit))
