"""Categories and categorization rules."""
from flask import Blueprint
import db
import services
from auth import require_role, require_company_scope, active_grant
from errors import (ok, ok_list, invalid_state, not_writable, feature_gated,
                    rule_not_pausable, rule_not_resumable, not_found,
                    forbidden_role, invalid_request)
from helpers import (body_json, req_str, req_int, get_or_404, paginate,
                     sort_by_created, enum_check, filter_items,
                     company_subscription, opt_bool)
import serializers

bp = Blueprint("rules", __name__, url_prefix="/api/companies/<company_id>")

MATCH_FIELDS = ("PAYEE_CONTAINS", "AMOUNT_EQUALS", "AMOUNT_GREATER_THAN")


def _sub(company_id):
    get_or_404("ClientCompany", company_id)
    sub = company_subscription(company_id)
    if sub is None:
        not_found("Subscription not found")
    return sub


def _gate_bank_rules(sub, company_id):
    plan = db.TABLES["SubscriptionPlan"].get(sub["plan_id"])
    if plan is None or not plan.get("feature_bank_rules"):
        sub["pending_upgrade_prompt"] = True
        db.touch(sub)
        feature_gated()


def _standard_plus(identity):
    if identity is None or identity.get("permission_level") in ("REPORTS_ONLY", "TIME_TRACKING"):
        forbidden_role()


@bp.post("/categories")
def create_category(company_id):
    role, identity = require_role(["CompanyUser"])
    sub = _sub(company_id)
    require_company_scope(identity, company_id)
    if sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    rec = {
        "company_id": company_id,
        "name": req_str(data, "name"),
        "tax_line": req_str(data, "tax_line"),
    }
    db.stamp_common(rec, kind_has_version=False)
    db.TABLES["Category"][rec["id"]] = rec
    return ok(serializers.serialize_category(rec), status=201)


@bp.get("/categories")
def list_categories(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [c for c in db.TABLES["Category"].values() if c["company_id"] == company_id]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_category(c) for c in page], limit, offset, total)


@bp.post("/categorization_rules")
def create_rule(company_id):
    role, identity = require_role(["CompanyUser", "AccountantUser"])
    sub = _sub(company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
        _standard_plus(identity)
    else:
        active_grant(identity, company_id, ("FULL_BOOKKEEPING",))
    if sub["lifecycle_status"] in ("CANCELLED_READ_ONLY", "CANCELLED_EXPIRED"):
        not_writable()
    _gate_bank_rules(sub, company_id)
    data = body_json()
    body_company = data.get("company_id")
    if body_company is not None and body_company != company_id:
        not_found("company_id in body does not match path")
    match_field = enum_check(req_str(data, "match_field"), MATCH_FIELDS, "match_field")
    assign_cat = req_str(data, "assign_category_id")
    cat = db.TABLES["Category"].get(assign_cat)
    if cat is None or cat["company_id"] != company_id:
        not_found("Category not found")
    rec = {
        "company_id": company_id,
        "rule_name": req_str(data, "rule_name"),
        "match_field": match_field,
        "match_value": req_str(data, "match_value"),
        "assign_category_id": assign_cat,
        "priority": req_int(data, "priority"),
        "auto_apply": opt_bool(data, "auto_apply", True),
        "rule_status": "ACTIVE",
    }
    db.stamp_common(rec)
    db.TABLES["CategorizationRule"][rec["id"]] = rec
    services.reeval_uncategorized_txns(company_id)
    return ok(serializers.serialize_rule(rec), status=201)


@bp.get("/categorization_rules")
def list_rules(company_id):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    get_or_404("ClientCompany", company_id)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    items = [r for r in db.TABLES["CategorizationRule"].values()
             if r["company_id"] == company_id]
    items = filter_items(items, [("rule_status", "rule_status")])
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([serializers.serialize_rule(r) for r in page], limit, offset, total)


def _get_rule(company_id, rid):
    get_or_404("ClientCompany", company_id)
    rec = get_or_404("CategorizationRule", rid)
    if rec["company_id"] != company_id:
        not_found("Rule not in company")
    return rec


@bp.get("/categorization_rules/<rid>")
def get_rule(company_id, rid):
    role, identity = require_role(["PlatformAdmin", "CompanyUser", "AccountantUser"])
    rec = _get_rule(company_id, rid)
    if role == "CompanyUser":
        require_company_scope(identity, company_id)
    return ok(serializers.serialize_rule(rec))


@bp.post("/categorization_rules/<rid>/pause")
def pause_rule(company_id, rid):
    role, identity = require_role(["CompanyUser"])
    _sub(company_id)
    require_company_scope(identity, company_id)
    _standard_plus(identity)
    rec = _get_rule(company_id, rid)
    if rec["rule_status"] != "ACTIVE":
        rule_not_pausable()
    rec["rule_status"] = "PAUSED"
    db.touch(rec)
    return ok(serializers.serialize_rule(rec))


@bp.post("/categorization_rules/<rid>/resume")
def resume_rule(company_id, rid):
    role, identity = require_role(["CompanyUser"])
    sub = _sub(company_id)
    require_company_scope(identity, company_id)
    _standard_plus(identity)
    rec = _get_rule(company_id, rid)
    plan = db.TABLES["SubscriptionPlan"].get(sub["plan_id"])
    if rec["rule_status"] != "PAUSED" or plan is None or not plan.get("feature_bank_rules"):
        rule_not_resumable()
    rec["rule_status"] = "ACTIVE"
    db.touch(rec)
    services.reeval_uncategorized_txns(company_id)
    return ok(serializers.serialize_rule(rec))


@bp.delete("/categorization_rules/<rid>")
def delete_rule(company_id, rid):
    role, identity = require_role(["CompanyUser"])
    _sub(company_id)
    require_company_scope(identity, company_id)
    _standard_plus(identity)
    rec = _get_rule(company_id, rid)
    if rec["rule_status"] not in ("ACTIVE", "PAUSED"):
        invalid_state("Rule not deletable")
    rec["rule_status"] = "DELETED"
    db.touch(rec)
    return ok(serializers.serialize_rule(rec))
