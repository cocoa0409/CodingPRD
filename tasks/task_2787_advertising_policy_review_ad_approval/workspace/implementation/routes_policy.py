"""Policy framework, advertiser accounts and reviewer registry endpoints.

Every handler evaluates its checks in the single global order fixed by
PRD 2.10: authentication, role, ownership scope, body shape, pagination, path
identifiers, body foreign keys, then the numbered business rules.
"""

from decimal import Decimal

from flask import Blueprint, request

import calc
import services as svc
from core import (D, MUTABLE_COMMON, ROLE_ADMIN, ROLE_ADVERTISER, ROLE_ANALYST,
                  ROLE_REVIEWER, authenticate, db, fail, new_row, now, ok, ok_list,
                  oldest_first, pagination, paginate, plus_hours, q2, touch)
from validate import (read_body, v_array, v_bool, v_country, v_datetime, v_decimal2,
                      v_enum, v_id, v_int, v_policy_code, v_string, el_country,
                      el_enum, body_or_empty)

bp = Blueprint("policy", __name__)

CATEGORY_CLASSES = ("PROHIBITED", "RESTRICTED", "REGULATED")
QUEUES = ("STANDARD", "REGULATED_CERT", "POLITICAL")
DISPOSITIONS = ("BLOCKED", "RESTRICTED_CERT_REQUIRED", "ALLOWED_WITH_DISCLAIMER", "ALLOWED")
ACTION_TYPES = ("WARNING", "RESTRICTION", "SUSPENSION")

VERIFICATION_AXES = {
    "IDENTITY": ("identity_status", ("PENDING", "VERIFIED", "FAILED")),
    "BUSINESS_STANDING": ("business_standing_status", ("PENDING", "VERIFIED", "FAILED")),
    "INDUSTRY_AUTHORIZATION": ("industry_authorization_status",
                               ("NOT_REQUIRED", "PENDING", "GRANTED", "DENIED")),
    "POLITICAL_ELIGIBILITY": ("political_eligibility_status",
                              ("NOT_REQUESTED", "PENDING", "ELIGIBLE", "INELIGIBLE")),
}


# ==========================================================================
# policy rules
# ==========================================================================
@bp.route("/policy-rules", methods=["POST"])
def create_policy_rule():
    authenticate(ROLE_ADMIN)
    data = read_body(
        ("code", "title", "category_class", "base_severity_weight",
         "requires_certification", "requires_disclaimer",
         "confidence_auto_disapprove_threshold", "confidence_manual_threshold",
         "review_sla_hours", "default_queue"),
        ("code", "title", "category_class", "base_severity_weight"))
    code = v_policy_code(data, "code")
    title = v_string(data, "title", 1, 160)
    category_class = v_enum(data, "category_class", CATEGORY_CLASSES)
    weight = v_decimal2(data, "base_severity_weight", "0.01", "20.00")
    requires_certification = v_bool(data, "requires_certification", False)
    requires_disclaimer = v_bool(data, "requires_disclaimer", False)
    auto_threshold = v_decimal2(data, "confidence_auto_disapprove_threshold",
                               "0.01", "1.00", D("0.90"))
    manual_threshold = v_decimal2(data, "confidence_manual_threshold",
                                 "0.01", "1.00", D("0.55"))
    sla_hours = v_int(data, "review_sla_hours", 1, 336, 48)
    default_queue = v_enum(data, "default_queue", QUEUES, required=False, default="STANDARD")
    # priority 31 (duplicate code) is judged ahead of priority 32 (threshold order)
    if calc.rule_by_code(code) is not None:
        fail("ERR_DUPLICATE_POLICY_CODE", 409)
    if not (auto_threshold > manual_threshold):
        fail("ERR_INVALID_THRESHOLD_ORDER", 422)
    row = new_row(MUTABLE_COMMON)
    row.update({
        "code": code,
        "title": title,
        "category_class": category_class,
        "base_severity_weight": q2(weight),
        "requires_certification": requires_certification,
        "requires_disclaimer": requires_disclaimer,
        "confidence_auto_disapprove_threshold": q2(auto_threshold),
        "confidence_manual_threshold": q2(manual_threshold),
        "review_sla_hours": sla_hours,
        "default_queue": default_queue,
        "country_override_count": 0,
    })
    db.policy_rules[row["id"]] = row
    return ok(svc.s_policy_rule(row), 201)


@bp.route("/policy-rules", methods=["GET"])
def list_policy_rules():
    authenticate()
    limit, offset = pagination()
    rows = list(db.policy_rules.values())
    category_class = request.args.get("category_class")
    if category_class is not None:
        rows = [r for r in rows if r["category_class"] == category_class]
    rows.sort(key=lambda r: r["code"])
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_policy_rule(r) for r in page], limit, offset, total)


@bp.route("/policy-rules/<rule_id>", methods=["GET"])
def read_policy_rule(rule_id):
    authenticate()
    return ok(svc.s_policy_rule(svc.get_policy_rule(rule_id)))


@bp.route("/policy-rules/<rule_id>/country-overrides", methods=["POST"])
def create_country_override(rule_id):
    authenticate(ROLE_ADMIN)
    data = read_body(
        ("policy_rule_id", "country_code", "disposition", "requires_license",
         "requires_disclaimer", "severity_multiplier"),
        ("country_code", "disposition"))
    country_code = v_country(data, "country_code")
    disposition = v_enum(data, "disposition", DISPOSITIONS)
    requires_license = v_bool(data, "requires_license", False)
    requires_disclaimer = v_bool(data, "requires_disclaimer", False)
    multiplier = v_decimal2(data, "severity_multiplier", "0.50", "3.00", D("1.00"))
    body_rule_id = v_id(data, "policy_rule_id", required=False)
    rule = svc.get_policy_rule(rule_id)
    if body_rule_id is not None and body_rule_id not in db.policy_rules:
        fail("ERR_POLICY_RULE_NOT_FOUND", 404)
    # priority 31: at most one variation per (rule, country) pair
    if calc.override_for(rule, country_code) is not None:
        fail("ERR_DUPLICATE_POLICY_CODE", 409)
    row = new_row(MUTABLE_COMMON)
    row.update({
        "policy_rule_id": rule["id"],
        "country_code": country_code,
        "disposition": disposition,
        "requires_license": requires_license,
        "requires_disclaimer": requires_disclaimer,
        "severity_multiplier": q2(multiplier),
    })
    db.country_overrides[row["id"]] = row
    rule["country_override_count"] += 1
    touch(rule)
    return ok(svc.s_country_override(row), 201)


@bp.route("/policy-rules/<rule_id>/country-overrides", methods=["GET"])
def list_country_overrides(rule_id):
    authenticate()
    limit, offset = pagination()
    rule = svc.get_policy_rule(rule_id)
    rows = [r for r in db.country_overrides.values() if r["policy_rule_id"] == rule["id"]]
    rows.sort(key=lambda r: r["country_code"])
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_country_override(r) for r in page], limit, offset, total)


@bp.route("/policy-rules/<rule_id>/classifier-decisions", methods=["GET"])
def list_rule_classifier_decisions(rule_id):
    authenticate(ROLE_ADMIN, ROLE_REVIEWER, ROLE_ANALYST)
    limit, offset = pagination()
    rule = svc.get_policy_rule(rule_id)
    rows = [d for d in db.classifier_decisions.values() if d["policy_rule_id"] == rule["id"]]
    page, total = paginate(oldest_first(rows), limit, offset)
    return ok_list([svc.s_classifier_decision(r) for r in page], limit, offset, total)


# ==========================================================================
# advertisers
# ==========================================================================
@bp.route("/advertisers", methods=["POST"])
def create_advertiser():
    authenticate(ROLE_ADMIN)
    data = read_body(("legal_name", "country_code", "industry_code"),
                     ("legal_name", "country_code", "industry_code"))
    legal_name = v_string(data, "legal_name", 1, 200)
    country_code = v_country(data, "country_code")
    industry_code = v_string(data, "industry_code", 1, 40)
    row = new_row(MUTABLE_COMMON)
    row.update({
        "legal_name": legal_name,
        "country_code": country_code,
        "industry_code": industry_code,
        "identity_status": "PENDING",
        "business_standing_status": "PENDING",
        "industry_authorization_status": "NOT_REQUIRED",
        "political_eligibility_status": "NOT_REQUESTED",
        "account_status": "ACTIVE",
        "violation_points_raw": Decimal("0.00"),
        "violation_points_decayed": Decimal("0.00"),
        "severity_index": Decimal("0.00"),
        "ledger_entry_count": 0,
    })
    db.advertisers[row["id"]] = row
    return ok(svc.s_advertiser(row), 201)


@bp.route("/advertisers/<advertiser_id>", methods=["GET"])
def read_advertiser(advertiser_id):
    authenticate()
    return ok(svc.s_advertiser(svc.get_advertiser(advertiser_id)))


@bp.route("/advertisers/<advertiser_id>/verifications", methods=["POST"])
def record_verification(advertiser_id):
    authenticate(ROLE_ADMIN)
    data = read_body(("dimension", "outcome", "evidence_ref"), ("dimension", "outcome"))
    dimension = v_enum(data, "dimension", tuple(VERIFICATION_AXES.keys()))
    field, permitted = VERIFICATION_AXES[dimension]
    # an outcome outside the addressed axis's enumeration is a shape failure
    outcome = v_enum(data, "outcome", permitted)
    v_string(data, "evidence_ref", 1, 2000, required=False, nullable=True)
    advertiser = svc.get_advertiser(advertiser_id)
    advertiser[field] = outcome
    touch(advertiser)
    return ok(svc.s_advertiser(advertiser))


@bp.route("/advertisers/<advertiser_id>/enforcement-actions", methods=["POST"])
def create_manual_enforcement_action(advertiser_id):
    authenticate(ROLE_ADMIN)
    data = read_body(
        ("advertiser_id", "action_type", "trigger_reason", "effective_until",
         "prior_action_id", "expected_advertiser_version"),
        ("action_type", "trigger_reason", "expected_advertiser_version"))
    action_type = v_enum(data, "action_type", ACTION_TYPES)
    trigger_reason = v_string(data, "trigger_reason", 1, 300)
    effective_until = v_datetime(data, "effective_until", required=False)
    prior_action_id = v_id(data, "prior_action_id", required=False)
    expected_version = v_int(data, "expected_advertiser_version", 0, None)
    if expected_version is None:
        fail("ERR_INVALID_REQUEST", 400, "expected_advertiser_version is required.")
    body_advertiser_id = v_id(data, "advertiser_id", required=False)
    advertiser = svc.get_advertiser(advertiser_id)
    if body_advertiser_id is not None and body_advertiser_id not in db.advertisers:
        fail("ERR_ADVERTISER_NOT_FOUND", 404)
    if prior_action_id is not None:
        svc.get_enforcement_action(prior_action_id)
    # priority 10: version pinning (PRD 2.7)
    if expected_version != advertiser["version"]:
        fail("ERR_STALE_ADVERTISER_VERSION", 412)
    # priority 25: the cooldown blackout runs from effective_from through
    # effective_until extended by 72 hours, inclusive, over every status
    effective_from = now()
    for action in calc.actions_of(advertiser["id"]):
        blackout_end = plus_hours(action["effective_until"],
                                  calc.ENFORCEMENT_COOLDOWN_HOURS)
        if action["effective_from"] <= effective_from <= blackout_end:
            fail("ERR_ENFORCEMENT_COOLDOWN_CONFLICT", 409)
    row = svc.create_enforcement_action(
        advertiser, action_type, "MANUAL", trigger_reason,
        advertiser["severity_index"], effective_until=effective_until,
        prior_action_id=prior_action_id, source_notice_id=None)
    return ok(svc.s_enforcement_action(row), 201)


@bp.route("/advertisers/<advertiser_id>/political-archive-entries", methods=["GET"])
def list_advertiser_archive_entries(advertiser_id):
    authenticate()
    limit, offset = pagination()
    advertiser = svc.get_advertiser(advertiser_id)
    rows = [e for e in db.political_archive_entries.values()
            if e["advertiser_id"] == advertiser["id"]]
    rows.sort(key=lambda e: (e["archived_at"], e["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_political_archive_entry(r) for r in page], limit, offset, total)


@bp.route("/advertisers/<advertiser_id>/violation-ledger-entries", methods=["GET"])
def list_advertiser_ledger_entries(advertiser_id):
    authenticate()
    limit, offset = pagination()
    advertiser = svc.get_advertiser(advertiser_id)
    rows = calc.ledger_of(advertiser["id"])
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.s_violation_ledger_entry(r) for r in page], limit, offset, total)


# ==========================================================================
# reviewers
# ==========================================================================
@bp.route("/reviewers", methods=["POST"])
def create_reviewer():
    authenticate(ROLE_ADMIN)
    data = read_body(
        ("display_name", "queue_specialties", "country_authorizations",
         "max_concurrent_claims", "status"),
        ("display_name", "queue_specialties", "country_authorizations"))
    display_name = v_string(data, "display_name", 1, 120)
    specialties = v_array(data, "queue_specialties", element=el_enum(QUEUES))
    authorizations = v_array(data, "country_authorizations", element=el_country)
    ceiling = v_int(data, "max_concurrent_claims", 1, 10, 3)
    status = v_enum(data, "status", ("ACTIVE", "OFFLINE"), required=False, default="ACTIVE")
    row = new_row(MUTABLE_COMMON)
    row.update({
        "display_name": display_name,
        "queue_specialties": list(specialties),
        "country_authorizations": list(authorizations),
        "max_concurrent_claims": ceiling,
        "claimed_task_count": 0,
        "status": status,
    })
    db.reviewers[row["id"]] = row
    return ok(svc.s_reviewer(row), 201)


@bp.route("/reviewers/<reviewer_id>", methods=["GET"])
def read_reviewer(reviewer_id):
    authenticate(ROLE_ADMIN, ROLE_REVIEWER, ROLE_ANALYST)
    return ok(svc.s_reviewer(svc.get_reviewer(reviewer_id)))


@bp.route("/reviewers/<reviewer_id>", methods=["PATCH"])
def update_reviewer(reviewer_id):
    authenticate(ROLE_ADMIN)
    data = read_body(("status", "max_concurrent_claims", "queue_specialties",
                      "country_authorizations"))
    status = v_enum(data, "status", ("ACTIVE", "OFFLINE"), required=False)
    ceiling = v_int(data, "max_concurrent_claims", 1, 10)
    specialties = v_array(data, "queue_specialties", required=False,
                          element=el_enum(QUEUES))
    authorizations = v_array(data, "country_authorizations", required=False,
                             element=el_country)
    reviewer = svc.get_reviewer(reviewer_id)
    if status is not None:
        reviewer["status"] = status
    if ceiling is not None:
        reviewer["max_concurrent_claims"] = ceiling
    if specialties is not None:
        reviewer["queue_specialties"] = list(specialties)
    if authorizations is not None:
        reviewer["country_authorizations"] = list(authorizations)
    touch(reviewer)
    return ok(svc.s_reviewer(reviewer))
