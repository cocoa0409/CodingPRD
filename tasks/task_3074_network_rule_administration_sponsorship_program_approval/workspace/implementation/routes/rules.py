"""Network rules: draft (with supersede OCC), list, get, publish (supersede
cascade), retire."""

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    REGIONS, base_record, get_json, get_or_404, logical_now, paginate, parse_iso,
    req_enum, req_str, sort_by_created, touch,
)
from middleware import require_roles
from response import iso3, ok

bp = Blueprint("rules", __name__)

READ_ROLES = {
    "NetworkOperator", "RulesAdministrator", "FraudAnalyst", "DisputeAnalyst",
    "PricingAnalyst", "SponsorshipManager", "CertificationEngineer", "SettlementOperator",
}
REGION_SCOPES = REGIONS | {"GLOBAL"}


def _validate_fine_schedule(schedule):
    if not isinstance(schedule, list) or len(schedule) == 0:
        raise_err("ERR_VALIDATION", "fine_schedule must be a non-empty array")
    for entry in schedule:
        if not isinstance(entry, dict):
            raise_err("ERR_VALIDATION", "fine_schedule entries must be objects")
        mn = entry.get("min_amount_minor")
        mx = entry.get("max_amount_minor")
        fine = entry.get("fine_cents")
        if isinstance(mn, bool) or not isinstance(mn, int) or mn < 1:
            raise_err("ERR_VALIDATION", "fine_schedule min_amount_minor must be a positive integer")
        if mx is not None and (isinstance(mx, bool) or not isinstance(mx, int)):
            raise_err("ERR_VALIDATION", "fine_schedule max_amount_minor must be an integer or null")
        if isinstance(fine, bool) or not isinstance(fine, int):
            raise_err("ERR_VALIDATION", "fine_schedule fine_cents must be an integer")


@bp.post("/network/rules")
def create_rule():
    require_roles({"RulesAdministrator"})
    body = get_json()
    rule_code = req_str(body, "rule_code")
    title = req_str(body, "title")
    body_text = req_str(body, "body")
    region_scope = req_enum(body, "region_scope", REGION_SCOPES)
    if "effective_from" not in body:
        raise_err("ERR_INVALID_REQUEST", "effective_from is required")
    effective_dt = parse_iso(body["effective_from"], "effective_from")
    fine_schedule = body.get("fine_schedule")
    regional_override_of = body.get("regional_override_of_rule_id")
    supersedes_rule_id = body.get("supersedes_rule_id")

    # Existence of body-referenced resources (priority 3), left-to-right
    if regional_override_of is not None:
        get_or_404(db.rules, regional_override_of)
    if supersedes_rule_id is not None:
        get_or_404(db.rules, supersedes_rule_id)

    # Structural constraints (priority 7)
    _validate_fine_schedule(fine_schedule)
    if regional_override_of is not None and region_scope == "GLOBAL":
        raise_err("ERR_VALIDATION",
                  "region_scope must not be GLOBAL when regional_override_of_rule_id is set")

    # OCC: expected_rule_version required when supersedes_rule_id supplied
    if supersedes_rule_id is not None:
        if "expected_rule_version" not in body:
            raise_err("ERR_INVALID_REQUEST", "expected_rule_version is required when supersedes_rule_id is supplied")
        expected = body["expected_rule_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise_err("ERR_INVALID_REQUEST", "expected_rule_version must be an integer")
        referenced = db.rules[supersedes_rule_id]
        if expected != referenced["version"]:
            raise_err("ERR_STALE_VERSION", "expected_rule_version does not match the referenced rule's current version")

    # Uniqueness (priority 10): rule_code + region_scope + effective_from among non-RETIRED
    eff_iso = iso3(effective_dt)
    for r in db.rules.values():
        if (r["status"] != "RETIRED" and r["rule_code"] == rule_code
                and r["region_scope"] == region_scope
                and r["effective_from"] == eff_iso):
            raise_err("ERR_DUPLICATE",
                      "A non-RETIRED rule with this rule_code, region_scope, and effective_from already exists")

    rec = base_record()
    rec.update({
        "rule_code": rule_code,
        "title": title,
        "body": body_text,
        "region_scope": region_scope,
        "regional_override_of_rule_id": regional_override_of,
        "effective_from": eff_iso,
        "status": "DRAFT",
        "fine_schedule": fine_schedule,
    })
    db.rules[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/rules")
def list_rules():
    require_roles(READ_ROLES)
    items = list(db.rules.values())
    rule_code = request.args.get("rule_code")
    region_scope = request.args.get("region_scope")
    status = request.args.get("status")
    override_of = request.args.get("regional_override_of_rule_id")
    if rule_code is not None:
        items = [r for r in items if r["rule_code"] == rule_code]
    if region_scope is not None:
        items = [r for r in items if r["region_scope"] == region_scope]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if override_of is not None:
        items = [r for r in items if r.get("regional_override_of_rule_id") == override_of]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/rules/<rid>")
def get_rule(rid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.rules, rid)
    return ok(rec, 200)


@bp.post("/network/rules/<rid>/publish")
def publish_rule(rid):
    require_roles({"RulesAdministrator"})
    rec = get_or_404(db.rules, rid)
    if rec["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Rule is not DRAFT")
    now = logical_now()
    eff = parse_iso(rec["effective_from"])
    if eff < now:
        raise_err("ERR_WINDOW_EXPIRED", "effective_from is in the past")
    # Supersede cascade: PUBLISHED rules with same rule_code, overlapping scope,
    # earlier effective_from -> SUPERSEDED
    for other in db.rules.values():
        if other["id"] == rec["id"] or other["status"] != "PUBLISHED":
            continue
        if other["rule_code"] != rec["rule_code"]:
            continue
        same_scope = other["region_scope"] == rec["region_scope"]
        both_global = other["region_scope"] == "GLOBAL" and rec["region_scope"] == "GLOBAL"
        if not (same_scope or both_global):
            continue
        if parse_iso(other["effective_from"]) < eff:
            other["status"] = "SUPERSEDED"
            touch(other)
    rec["status"] = "PUBLISHED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/rules/<rid>/retire")
def retire_rule(rid):
    require_roles({"RulesAdministrator"})
    rec = get_or_404(db.rules, rid)
    if rec["status"] != "PUBLISHED":
        raise_err("ERR_INVALID_STATE", "Rule is not PUBLISHED")
    rec["status"] = "RETIRED"
    touch(rec)
    return ok(rec, 200)
