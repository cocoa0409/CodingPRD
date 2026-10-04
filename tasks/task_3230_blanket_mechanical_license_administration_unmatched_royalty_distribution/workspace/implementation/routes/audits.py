"""AuditEngagement endpoints."""
from flask import Blueprint, request

import db
from auth import require_roles
from errors import err
from lookups import get_sp, get_audit
from response import ok_list, ok_object
from util import body_json, make_record, touch, month_bounds

bp = Blueprint("audits", __name__)

MEMBER = ("MemberUser",)
ADMIN = ("MLCAdministrator",)
READ = ("MLCAdministrator", "MemberUser")


def audit_view(a):
    return {k: v for k, v in a.items() if not k.startswith("_")}


@bp.route("/mlc/service-providers/<sp_id>/audits", methods=["POST"])
@require_roles(*MEMBER)
def create_audit(sp_id, _user_id, _role):
    sp = get_sp(sp_id)
    body = body_json(required=("auditor_member_id", "scope_months"))
    auditor_id = body["auditor_member_id"]
    if auditor_id not in db.members:
        raise err("ERR_MEMBER_NOT_FOUND")
    scope = body["scope_months"]
    if not isinstance(scope, list) or not scope:
        raise err("ERR_INVALID_REQUEST", "scope_months must be a non-empty list")
    for m in scope:
        month_bounds(m)
    # Every scope month must be covered by an ACCEPTED or AUDIT_CONFIRMED report
    for m in scope:
        covered = any(
            r["service_provider_id"] == sp_id and r["reporting_month"] == m
            and r["status"] in ("ACCEPTED", "AUDIT_CONFIRMED")
            for r in db.usage_reports.values())
        if not covered:
            raise err("ERR_INVALID_REQUEST", f"scope month {m} not covered by an accepted report")
    if sp["audit_credits"] <= 0:
        raise err("ERR_AUDIT_CREDITS_EXHAUSTED")
    sp["audit_credits"] -= 1
    touch(sp)
    rec = make_record()
    rec.update({
        "service_provider_id": sp_id,
        "auditor_member_id": auditor_id,
        "scope_months": list(scope),
        "status": "OPEN",
        "findings_note": None,
        "adjustment_cents": 0,
    })
    db.audits[rec["id"]] = rec
    # Scoped ACCEPTED reports -> UNDER_AUDIT
    for r in db.usage_reports.values():
        if (r["service_provider_id"] == sp_id and r["reporting_month"] in scope
                and r["status"] == "ACCEPTED"):
            r["status"] = "UNDER_AUDIT"
            touch(r)
    return ok_object(audit_view(rec), 201)


@bp.route("/mlc/audits", methods=["GET"])
@require_roles(*READ)
def list_audits(_user_id, _role):
    items = sorted(db.audits.values(), key=lambda a: a["created_at"])
    auditor = request.args.get("auditor_member_id")
    if auditor:
        items = [a for a in items if a["auditor_member_id"] == auditor]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    return ok_list([audit_view(a) for a in items])


@bp.route("/mlc/audits/<audit_id>", methods=["GET"])
@require_roles(*READ)
def get_one_audit(audit_id, _user_id, _role):
    return ok_object(audit_view(get_audit(audit_id)))


@bp.route("/mlc/audits/<audit_id>/issue-findings", methods=["POST"])
@require_roles(*MEMBER)
def issue_findings(audit_id, _user_id, _role):
    a = get_audit(audit_id)
    body = body_json(required=("findings_note",))
    if a["status"] != "OPEN":
        raise err("ERR_INVALID_STATE")
    if a["auditor_member_id"] != _user_id:
        raise err("ERR_NOT_CLAIM_OWNER")
    a["findings_note"] = body["findings_note"]
    a["status"] = "FINDINGS_ISSUED"
    touch(a)
    return ok_object(audit_view(a))


@bp.route("/mlc/audits/<audit_id>/close", methods=["POST"])
@require_roles(*ADMIN)
def close_audit(audit_id, _user_id, _role):
    a = get_audit(audit_id)
    body = body_json(required=("adjustment_cents",))
    if a["status"] != "FINDINGS_ISSUED":
        raise err("ERR_INVALID_STATE")
    adj = body["adjustment_cents"]
    if not isinstance(adj, int):
        raise err("ERR_INVALID_REQUEST", "adjustment_cents must be an integer")
    sp = db.service_providers.get(a["service_provider_id"])
    scoped = sorted(
        (r for r in db.usage_reports.values()
         if r["service_provider_id"] == a["service_provider_id"]
         and r["reporting_month"] in a["scope_months"]
         and r["status"] == "UNDER_AUDIT"),
        key=lambda r: r["reporting_month"])
    cap = sum(r["total_usage_cents"] for r in scoped)
    if abs(adj) > cap:
        raise err("ERR_AUDIT_ADJUSTMENT_OUT_OF_RANGE")
    a["adjustment_cents"] = adj
    # Apply adjustment report-by-report in chronological order; a negative
    # delta absorbs into matched_usage_cents first, then unmatched, and any
    # still-unabsorbed remainder carries to the next report (PRD §3.8:
    # "Closure applies the adjustment report by report in chronological
    # reporting_month order"). total_usage_cents always stays equal to
    # matched + unmatched (PRD §2.9).
    remaining = adj
    for r in scoped:
        if remaining == 0:
            break
        d = remaining
        applied = 0
        if d < 0:
            absorb = min(r["matched_usage_cents"], -d)
            r["matched_usage_cents"] -= absorb
            applied -= absorb
            leftover = -d - absorb
            if leftover > 0:
                absorb2 = min(r["unmatched_usage_cents"], leftover)
                r["unmatched_usage_cents"] -= absorb2
                applied -= absorb2
        else:
            r["matched_usage_cents"] += d
            applied += d
        r["total_usage_cents"] = (
            r["matched_usage_cents"] + r["unmatched_usage_cents"])
        remaining = d - applied
        r["status"] = "AUDIT_CONFIRMED" if adj == 0 else "AMENDED"
        touch(r)
        # Queue the signed delta applied to this report as an ADJUSTMENT
        # posting on the auditor member
        if applied != 0:
            db.postings.append({
                "member_id": a["auditor_member_id"],
                "period_month": r["reporting_month"],
                "usage_line_id": None,
                "allocated_cents": applied,
                "line_type": "ADJUSTMENT",
            })
    # Mark any scoped reports not touched above
    for r in db.usage_reports.values():
        if (r["service_provider_id"] == a["service_provider_id"]
                and r["reporting_month"] in a["scope_months"]
                and r["status"] == "UNDER_AUDIT"):
            r["status"] = "AUDIT_CONFIRMED" if adj == 0 else "AMENDED"
            touch(r)
    a["status"] = "CLOSED"
    touch(a)
    if sp is not None and adj == 0:
        sp["audit_credits"] += 1
        touch(sp)
    return ok_object(audit_view(a))


@bp.route("/mlc/audits/<audit_id>/withdraw", methods=["POST"])
@require_roles(*MEMBER)
def withdraw_audit(audit_id, _user_id, _role):
    a = get_audit(audit_id)
    body_json()
    if a["status"] != "OPEN":
        raise err("ERR_INVALID_STATE")
    if a["auditor_member_id"] != _user_id:
        raise err("ERR_NOT_CLAIM_OWNER")
    a["status"] = "WITHDRAWN"
    touch(a)
    for r in db.usage_reports.values():
        if (r["service_provider_id"] == a["service_provider_id"]
                and r["reporting_month"] in a["scope_months"]
                and r["status"] == "UNDER_AUDIT"):
            r["status"] = "ACCEPTED"
            touch(r)
    sp = db.service_providers.get(a["service_provider_id"])
    if sp is not None:
        sp["audit_credits"] += 1
        touch(sp)
    return ok_object(audit_view(a))
