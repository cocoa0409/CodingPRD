"""Audit and corrective-action endpoints."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from db import db, serialize
from util import (ApiError, bump, get_json, iso_ms, now_logical, ok, paginate,
                  parse_dt, sort_by_created, new_common)
from routes.shops import require_roles, get_cycle_or_404

bp = Blueprint("audits", __name__)

ROLES_READ = {"NetworkAdmin", "NetworkAuditor", "ShopManager"}
ACTIVE_AUDIT_STATES = {"SCHEDULED", "IN_PROGRESS", "FINDINGS_ISSUED", "VERIFICATION"}


def get_audit_or_404(audit_id):
    audit = db.audits.get(audit_id)
    if not audit:
        raise ApiError("ERR_NOT_FOUND", 404, "Audit not found")
    return audit


def get_action_or_404(action_id):
    action = db.corrective_actions.get(action_id)
    if not action:
        raise ApiError("ERR_NOT_FOUND", 404, "Corrective action not found")
    return action


def _refresh_audit_points(audit):
    pts = sum(calc.SEVERITY_POINTS[a["finding_severity"]]
              for a in db.corrective_actions.values()
              if a["audit_id"] == audit["id"])
    if audit.get("severity_points") != pts:
        audit["severity_points"] = pts
        bump(audit)


def _maybe_hide_shop_for_verification(audit):
    cycle = db.cycles.get(audit["cycle_id"])
    if cycle:
        shop = db.shops.get(cycle["shop_id"])
        if shop:
            import sweep
            sweep.recompute_locator_hidden(shop)


@bp.post("/network/certification-cycles/<cycle_id>/audits")
def schedule_audit(cycle_id):
    require_roles("NetworkAuditor")
    cycle = get_cycle_or_404(cycle_id)
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Cycle must be OPEN to schedule an audit")
    shop_id = cycle["shop_id"]
    if any(a["cycle_id"] == cycle["id"] and a["status"] in ACTIVE_AUDIT_STATES
           for a in db.audits.values()):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "An active audit already exists for this cycle")
    body = get_json()
    start = parse_dt(body.get("scheduled_start"), "scheduled_start")
    end = parse_dt(body.get("scheduled_end"), "scheduled_end")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "scheduled_end must be after scheduled_start")
    for a in db.audits.values():
        if a["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if db.cycles.get(a["cycle_id"], {}).get("shop_id") != shop_id:
            continue
        a_start = parse_dt(a["scheduled_start"], "scheduled_start")
        a_end = parse_dt(a["scheduled_end"], "scheduled_end")
        if start < a_end and a_start < end:
            raise ApiError("ERR_AUDIT_OVERLAP", 409,
                           "Audit window intersects another active audit of the shop")
    audit = new_common()
    audit.update({
        "cycle_id": cycle["id"],
        "auditor_user_id": request.headers.get("X-User-ID"),
        "scheduled_start": iso_ms(start),
        "scheduled_end": iso_ms(end),
        "round_number": 1,
        "status": "SCHEDULED",
        "severity_points": 0,
        "grade": None,
    })
    db.audits[audit["id"]] = audit
    cycle["status"] = "AUDIT_SCHEDULED"
    bump(cycle)
    return ok(serialize(audit), 201)


@bp.get("/network/certification-cycles/<cycle_id>/audits")
def list_cycle_audits(cycle_id):
    require_roles(*ROLES_READ)
    get_cycle_or_404(cycle_id)
    items = sort_by_created([a for a in db.audits.values()
                             if a["cycle_id"] == cycle_id])
    page, meta = paginate(items)
    return ok([serialize(a) for a in page], 200, meta)


@bp.get("/network/audits/<audit_id>")
def get_audit(audit_id):
    require_roles(*ROLES_READ)
    return ok(serialize(get_audit_or_404(audit_id)))


@bp.post("/network/audits/<audit_id>/begin")
def begin_audit(audit_id):
    require_roles("NetworkAuditor")
    audit = get_audit_or_404(audit_id)
    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit is not SCHEDULED")
    if audit["auditor_user_id"] != request.headers.get("X-User-ID"):
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Only the scheduling auditor may begin this audit")
    now = now_logical()
    start = parse_dt(audit["scheduled_start"], "scheduled_start")
    end = parse_dt(audit["scheduled_end"], "scheduled_end")
    if not (start <= now < end):
        raise ApiError("ERR_AUDIT_WINDOW_MISSED", 422,
                       "Logical clock is outside the scheduled audit window")
    audit["status"] = "IN_PROGRESS"
    bump(audit)
    cycle = db.cycles.get(audit["cycle_id"])
    if cycle and cycle["status"] == "AUDIT_SCHEDULED":
        cycle["status"] = "UNDER_AUDIT"
        bump(cycle)
    return ok(serialize(audit))


@bp.post("/network/audits/<audit_id>/cancel")
def cancel_audit(audit_id):
    require_roles("NetworkAuditor")
    audit = get_audit_or_404(audit_id)
    if audit["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit is not SCHEDULED")
    audit["status"] = "CANCELLED"
    bump(audit)
    cycle = db.cycles.get(audit["cycle_id"])
    if cycle and cycle["status"] == "AUDIT_SCHEDULED":
        cycle["status"] = "OPEN"
        bump(cycle)
    return ok(serialize(audit))


@bp.post("/network/audits/<audit_id>/issue-findings")
def issue_findings(audit_id):
    require_roles("NetworkAuditor")
    audit = get_audit_or_404(audit_id)
    if audit["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", 409, "Audit is not IN_PROGRESS")
    body = get_json()
    findings = body.get("findings", [])
    if not isinstance(findings, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "findings must be an array")
    cycle = db.cycles.get(audit["cycle_id"])
    now = now_logical()

    if len(findings) == 0:
        audit["grade"] = "A"
        audit["severity_points"] = 0
        audit["status"] = "PASSED"
        bump(audit)
        if cycle and cycle["status"] == "UNDER_AUDIT":
            cycle["status"] = "CLOSED_PASS"
            shop = db.shops.get(cycle["shop_id"])
            if shop:
                cycle["audit_snapshot_score"] = calc.compute_compliance_score(shop)
            bump(cycle)
            if shop:
                from sweep import apply_pass_posture
                apply_pass_posture(shop, cycle, "A")
        return ok(serialize(audit))

    # Validate all findings before mutating anything (atomicity).
    parsed = []
    for f in findings:
        if not isinstance(f, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "each finding must be an object")
        att_id = f.get("attestation_id")
        severity = f.get("finding_severity", f.get("severity"))
        att = db.attestations.get(att_id) if isinstance(att_id, str) else None
        if not att:
            raise ApiError("ERR_NOT_FOUND", 404, "Attestation not found")
        if severity not in calc.SEVERITY_POINTS:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "finding_severity must be MINOR, MAJOR, or CRITICAL")
        parsed.append((att, severity))

    issuer = request.headers.get("X-User-ID")
    for att, severity in parsed:
        att["status"] = "LAPSED"
        att["lapse_reason"] = "AUDIT_FINDING"
        bump(att)
        action = new_common()
        action.update({
            "audit_id": audit["id"],
            "attestation_id": att["id"],
            "finding_severity": severity,
            "due_at": iso_ms(now + timedelta(
                days=calc.CORRECTIVE_ACTION_DAYS[severity])),
            "status": "OPEN",
            "issued_by_user_id": issuer,
            "verified_by_user_id": None,
        })
        db.corrective_actions[action["id"]] = action
        # Opening a corrective action moves the attestation LAPSED -> UNDER_CORRECTION.
        att["status"] = "UNDER_CORRECTION"
        bump(att)
    _refresh_audit_points(audit)
    audit["status"] = "FINDINGS_ISSUED"
    bump(audit)
    if cycle and cycle["status"] == "UNDER_AUDIT":
        cycle["status"] = "CORRECTIVE_ACTION"
        bump(cycle)
    shop = db.shops.get(cycle["shop_id"]) if cycle else None
    if shop:
        calc.recompute_shop_score(shop)
    return ok(serialize(audit))


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------
@bp.get("/network/audits/<audit_id>/corrective-actions")
def list_audit_actions(audit_id):
    require_roles(*ROLES_READ)
    get_audit_or_404(audit_id)
    items = sort_by_created([a for a in db.corrective_actions.values()
                             if a["audit_id"] == audit_id])
    page, meta = paginate(items)
    return ok([serialize(a) for a in page], 200, meta)


@bp.get("/network/corrective-actions")
def list_actions():
    require_roles("NetworkAdmin", "NetworkAuditor")
    attestation_id = request.args.get("attestation_id")
    status = request.args.get("status")
    items = list(db.corrective_actions.values())
    if attestation_id is not None:
        items = [a for a in items if a["attestation_id"] == attestation_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok([serialize(a) for a in page], 200, meta)


@bp.get("/network/corrective-actions/<action_id>")
def get_action(action_id):
    require_roles(*ROLES_READ)
    return ok(serialize(get_action_or_404(action_id)))


@bp.post("/network/corrective-actions/<action_id>/submit")
def submit_action(action_id):
    require_roles("ShopManager")
    action = get_action_or_404(action_id)
    att = db.attestations.get(action["attestation_id"])
    if not att:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced attestation not found")
    if request.headers.get("X-User-ID") != att["shop_id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "ShopManager may only submit for their own shop")
    if action["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "Corrective action is not OPEN")
    body = get_json()
    evidence_uri = body.get("evidence_uri")
    if now_logical() > parse_dt(action["due_at"], "due_at"):
        raise ApiError("ERR_CORRECTIVE_OVERDUE", 422,
                       "Corrective action is past due_at")
    if not isinstance(evidence_uri, str) or not evidence_uri:
        raise ApiError("ERR_INVALID_REQUEST", 400, "evidence_uri is required")
    action["status"] = "SUBMITTED"
    bump(action)
    audit = db.audits.get(action["audit_id"])
    # §3.3: when the last OPEN action of the audit is submitted so that every
    # action is SUBMITTED or VERIFIED, the audit moves FINDINGS_ISSUED ->
    # VERIFICATION. The REJECTED branch of verify already returns the audit
    # to FINDINGS_ISSUED; submitting the last remaining OPEN action of an
    # audit that has REJECTED (but no other OPEN) actions must therefore
    # re-enter VERIFICATION, since the rejected action cannot be acted on
    # again — only OPEN actions block the transition.
    if audit and audit["status"] == "FINDINGS_ISSUED":
        if not any(a["status"] == "OPEN"
                   for a in db.corrective_actions.values()
                   if a["audit_id"] == audit["id"]):
            audit["status"] = "VERIFICATION"
            bump(audit)
            _maybe_hide_shop_for_verification(audit)
    return ok(serialize(action))


@bp.post("/network/corrective-actions/<action_id>/verify")
def verify_action(action_id):
    require_roles("NetworkAuditor")
    action = get_action_or_404(action_id)
    if action["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Corrective action is not SUBMITTED")
    body = get_json()
    verdict = body.get("verdict")
    verifier = request.headers.get("X-User-ID")
    if verifier == action["issued_by_user_id"]:
        raise ApiError("ERR_SELF_VERIFICATION", 422,
                       "Verifier must differ from the issuing auditor")
    if verdict not in ("VERIFIED", "REJECTED"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "verdict must be VERIFIED or REJECTED")
    audit = db.audits.get(action["audit_id"])
    att = db.attestations.get(action["attestation_id"])

    if verdict == "VERIFIED":
        action["status"] = "VERIFIED"
        action["verified_by_user_id"] = verifier
        bump(action)
        if att and att["status"] == "UNDER_CORRECTION":
            att["status"] = "ACTIVE"
            att["lapse_reason"] = None
            bump(att)
            shop = db.shops.get(att["shop_id"])
            if shop:
                calc.recompute_shop_score(shop)
        if audit and audit["status"] == "VERIFICATION":
            # REJECTED actions are superseded by their OPEN replacements and
            # no longer participate in the all-verified check (§3.3: "the
            # last non-verified action").
            if all(a["status"] == "VERIFIED"
                   for a in db.corrective_actions.values()
                   if a["audit_id"] == audit["id"] and a["status"] != "REJECTED"):
                grade, sp, _ = calc.grade_for_audit(audit)
                audit["grade"] = grade
                audit["severity_points"] = sp
                audit["status"] = "PASSED"
                bump(audit)
                _maybe_hide_shop_for_verification(audit)
    else:  # REJECTED
        action["status"] = "REJECTED"
        action["verified_by_user_id"] = verifier
        bump(action)
        fresh = new_common()
        fresh.update({
            "audit_id": action["audit_id"],
            "attestation_id": action["attestation_id"],
            "finding_severity": action["finding_severity"],
            "due_at": iso_ms(now_logical() + timedelta(
                days=calc.CORRECTIVE_ACTION_DAYS[action["finding_severity"]])),
            "status": "OPEN",
            "issued_by_user_id": action["issued_by_user_id"],
            "verified_by_user_id": None,
        })
        db.corrective_actions[fresh["id"]] = fresh
        if audit:
            audit["round_number"] = audit.get("round_number", 1) + 1
            if audit["status"] == "VERIFICATION":
                audit["status"] = "FINDINGS_ISSUED"
            bump(audit)
            _refresh_audit_points(audit)
    return ok(serialize(action))
