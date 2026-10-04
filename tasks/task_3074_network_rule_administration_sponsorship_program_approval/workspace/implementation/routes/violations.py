"""Rule violations: cite, list, get, assess, appeal, confirm, waive."""

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    base_record, exists_or_404, get_json, get_or_404, logical_now, paginate,
    parse_iso, req_enum, req_int, req_str, sort_by_created, touch,
)
from middleware import require_roles
from response import ok

bp = Blueprint("violations", __name__)

SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
SEVERITY_MULTIPLIER = {"MINOR": 1, "MAJOR": 2, "CRITICAL": 3}


@bp.post("/network/rule-violations")
def create_violation():
    user_id, _ = require_roles({"RulesAdministrator"})
    body = get_json()
    rule_id = req_str(body, "rule_id")
    subject_member_id = req_str(body, "subject_member_id")
    severity = req_enum(body, "severity", SEVERITIES)
    amount = req_int(body, "transaction_amount_minor")

    rule = exists_or_404(db.rules, rule_id, "rule")
    exists_or_404(db.members, subject_member_id, "subject member")

    now = logical_now()
    if rule["status"] != "PUBLISHED" or parse_iso(rule["effective_from"]) > now:
        raise_err("ERR_RULE_NOT_EFFECTIVE",
                  "Cited rule must be PUBLISHED and effective at the current logical time")

    rec = base_record()
    rec.update({
        "rule_id": rule_id,
        "subject_member_id": subject_member_id,
        "severity": severity,
        "transaction_amount_minor": amount,
        "status": "CITED",
        "fine_cents": None,
        "assessed_by_id": None,
        "cited_by_id": user_id,
    })
    db.violations[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/rule-violations")
def list_violations():
    require_roles({"NetworkOperator", "RulesAdministrator"})
    items = list(db.violations.values())
    subject = request.args.get("subject_member_id")
    rule_id = request.args.get("rule_id")
    status = request.args.get("status")
    if subject is not None:
        items = [v for v in items if v["subject_member_id"] == subject]
    if rule_id is not None:
        items = [v for v in items if v["rule_id"] == rule_id]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/rule-violations/<vid>")
def get_violation(vid):
    require_roles({"NetworkOperator", "RulesAdministrator", "Member"})
    rec = get_or_404(db.violations, vid)
    return ok(rec, 200)


def _select_fine(violation):
    """Compute fine_cents: regional override schedule if applicable, tier
    selection, then severity multiplier."""
    rule = db.rules[violation["rule_id"]]
    subject = db.members[violation["subject_member_id"]]
    now = logical_now()
    schedule = rule["fine_schedule"]
    # Regional override: published regional rule overriding this GLOBAL rule,
    # matching the subject member's region, effective at assessment time
    if rule["region_scope"] == "GLOBAL":
        for other in db.rules.values():
            if (other.get("regional_override_of_rule_id") == rule["id"]
                    and other["region_scope"] == subject["region"]
                    and other["status"] == "PUBLISHED"
                    and parse_iso(other["effective_from"]) <= now):
                schedule = other["fine_schedule"]
                break
    amount = violation["transaction_amount_minor"]
    selected = None
    for entry in sorted(schedule, key=lambda e: e["min_amount_minor"]):
        mn = entry["min_amount_minor"]
        mx = entry.get("max_amount_minor")
        if amount >= mn and (mx is None or amount <= mx):
            selected = entry
    if selected is None:
        raise_err("ERR_VALIDATION", "No fine tier matches the transaction amount")
    return selected["fine_cents"] * SEVERITY_MULTIPLIER[violation["severity"]]


@bp.post("/network/rule-violations/<vid>/assess")
def assess_violation(vid):
    user_id, _ = require_roles({"RulesAdministrator"})
    rec = get_or_404(db.violations, vid)
    if rec["status"] != "CITED":
        raise_err("ERR_INVALID_STATE", "Violation is not CITED")
    if user_id == rec["cited_by_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "Assessor must differ from the citing administrator")
    rec["fine_cents"] = _select_fine(rec)
    rec["assessed_by_id"] = user_id
    rec["status"] = "ASSESSED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/rule-violations/<vid>/appeal")
def appeal_violation(vid):
    user_id, _ = require_roles({"Member"})
    rec = get_or_404(db.violations, vid)
    if user_id != rec["subject_member_id"]:
        raise_err("ERR_IDENTITY_MISMATCH", "Only the subject member may appeal this violation")
    if rec["status"] != "ASSESSED":
        raise_err("ERR_INVALID_STATE", "Violation is not ASSESSED")
    rec["status"] = "APPEALED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/rule-violations/<vid>/confirm")
def confirm_violation(vid):
    user_id, _ = require_roles({"RulesAdministrator"})
    rec = get_or_404(db.violations, vid)
    if rec["status"] not in ("ASSESSED", "APPEALED"):
        raise_err("ERR_INVALID_STATE", "Violation is not ASSESSED or APPEALED")
    if user_id == rec["assessed_by_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "Confirmer must differ from the assessing administrator")
    rec["status"] = "CONFIRMED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/rule-violations/<vid>/waive")
def waive_violation(vid):
    user_id, _ = require_roles({"RulesAdministrator"})
    rec = get_or_404(db.violations, vid)
    if rec["status"] not in ("ASSESSED", "APPEALED"):
        raise_err("ERR_INVALID_STATE", "Violation is not ASSESSED or APPEALED")
    if user_id == rec["assessed_by_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES", "Waiver must differ from the assessing administrator")
    rec["fine_cents"] = 0
    rec["status"] = "WAIVED"
    touch(rec)
    return ok(rec, 200)
