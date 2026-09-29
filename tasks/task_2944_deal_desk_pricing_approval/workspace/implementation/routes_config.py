"""Desk policy, approval matrix, catalogue and account endpoints (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import clock
import common
import db
import response
import validation
from auth import require_roles
from errors import fail
from validation import validate, json_body

bp = Blueprint("config", __name__)

ALL = auth.ALL_ROLES

POLICY_SPEC = {
    "name": {"type": "string", "required": True},
    "margin_floor_pct": {"type": "number", "required": True, "gt": Decimal(0), "lt": Decimal(1)},
    "absolute_margin_floor_pct": {"type": "number", "required": True, "gt": Decimal(0), "lt": Decimal(1)},
    "quote_validity_days": {"type": "integer", "required": True, "ge": 1},
    "standard_payment_terms_days": {"type": "integer", "required": True, "ge": 1},
    "uplift_rate_per_30_days": {"type": "number", "required": True, "ge": Decimal(0), "lt": Decimal(1)},
    "max_stack_discount_pct": {"type": "number", "required": True, "gt": Decimal(0), "lt": Decimal(1)},
    "volume_rebate_tier1_min_cents": {"type": "integer", "required": True, "ge": 0},
    "volume_rebate_tier1_pct": {"type": "number", "required": True, "ge": Decimal(0), "lt": Decimal(1)},
    "volume_rebate_tier2_min_cents": {"type": "integer", "required": True, "ge": 0},
    "volume_rebate_tier2_pct": {"type": "number", "required": True, "ge": Decimal(0), "lt": Decimal(1)},
    "surge_window_days": {"type": "integer", "required": True, "ge": 1},
    "surge_sla_multiplier": {"type": "number", "required": True, "gt": Decimal(0)},
    "price_hold_cooldown_days": {"type": "integer", "required": True, "ge": 0},
    "exception_allowance_cents": {"type": "integer", "required": True, "ge": 0},
    "terms_review_risk_threshold": {"type": "number", "required": True, "ge": Decimal(0), "le": Decimal(100)},
    "terms_cfo_risk_threshold": {"type": "number", "required": True, "ge": Decimal(0), "le": Decimal(100)},
}


@bp.post("/desk-policies")
@require_roles("PlatformAdmin")
def create_desk_policy():
    body = validate(json_body(), POLICY_SPEC)
    if not body["absolute_margin_floor_pct"] < body["margin_floor_pct"]:
        fail(
            "ERR_INVALID_REQUEST",
            "absolute_margin_floor_pct must be strictly below margin_floor_pct.",
        )
    if not body["volume_rebate_tier2_min_cents"] > body["volume_rebate_tier1_min_cents"]:
        fail(
            "ERR_INVALID_REQUEST",
            "volume_rebate_tier2_min_cents must exceed volume_rebate_tier1_min_cents.",
        )
    if not body["volume_rebate_tier2_pct"] > body["volume_rebate_tier1_pct"]:
        fail(
            "ERR_INVALID_REQUEST",
            "volume_rebate_tier2_pct must exceed volume_rebate_tier1_pct.",
        )
    record = dict(body)
    record["status"] = "DRAFT"
    record["activated_at"] = None
    record["superseded_at"] = None
    db.insert("desk_policies", record)
    return response.created(record)


@bp.get("/desk-policies/<policy_id>")
@require_roles(ALL)
def read_desk_policy(policy_id):
    return response.ok(common.must_get("desk_policies", policy_id))


def _coverage_valid(tiers):
    """Bands sorted by tier_level must tile [0, 1] with no gap or overlap."""
    if not tiers:
        return False
    if calc.dec(tiers[0]["min_discount_pct"]) != Decimal(0):
        return False
    previous = None
    for tier in tiers:
        if previous is not None:
            if calc.dec(tier["min_discount_pct"]) != calc.dec(previous["max_discount_pct"]):
                return False
        previous = tier
    return calc.dec(tiers[-1]["max_discount_pct"]) == Decimal(1)


@bp.post("/desk-policies/<policy_id>/activate")
@require_roles("PlatformAdmin")
def activate_desk_policy(policy_id):
    policy = common.must_get("desk_policies", policy_id)
    validate(json_body(), {})
    if not _coverage_valid(db.tiers_of_policy(policy_id)):
        fail(
            "ERR_APPROVAL_TIER_COVERAGE_INVALID",
            "The approval matrix must cover 0.0 to 1.0 contiguously.",
        )
    if policy["status"] != "DRAFT":
        fail("ERR_DESK_POLICY_NOT_DRAFT")

    instant = clock.now()
    policy["status"] = "ACTIVE"
    policy["activated_at"] = instant
    db.touch(policy)

    previous = None
    for row in db.sorted_records(db.all_records("desk_policies")):
        if row["id"] != policy_id and row["status"] == "ACTIVE":
            previous = row
            break
    if previous is not None:
        previous["status"] = "SUPERSEDED"
        previous["superseded_at"] = instant
        db.touch(previous)
        for quote in db.sorted_records(db.all_records("quotes")):
            if quote["desk_policy_id"] != previous["id"]:
                continue
            if quote["status"] != "PENDING_APPROVAL":
                continue
            quote["policy_revalidation_required"] = True
            db.touch(quote)
    return response.ok(policy)


TIER_SPEC = {
    "desk_policy_id": {"type": "string", "required": True},
    "tier_level": {"type": "integer", "required": True, "ge": 1, "le": 4},
    "min_discount_pct": {"type": "number", "required": True, "ge": Decimal(0), "lt": Decimal(1)},
    "max_discount_pct": {"type": "number", "required": True, "gt": Decimal(0), "le": Decimal(1)},
    "required_role": {
        "type": "enum",
        "required": True,
        "values": ("DealDeskAnalyst", "SalesDirector", "VPSales", "CFO"),
    },
    "sla_hours": {"type": "integer", "required": True, "ge": 1},
    "max_delegation_levels": {"type": "integer", "required": True, "ge": 0, "le": 1},
}


@bp.post("/approval-tiers")
@require_roles("PlatformAdmin")
def create_approval_tier():
    body = validate(json_body(), TIER_SPEC)
    if not body["max_discount_pct"] > body["min_discount_pct"]:
        fail("ERR_INVALID_REQUEST", "max_discount_pct must exceed min_discount_pct.")
    if db.policy(body["desk_policy_id"]) is None:
        fail("ERR_DESK_POLICY_NOT_FOUND")
    for existing in db.tiers_of_policy(body["desk_policy_id"]):
        if existing["tier_level"] == body["tier_level"]:
            fail("ERR_APPROVAL_TIER_OVERLAP", "That tier_level is already configured.")
        lower = calc.dec(existing["min_discount_pct"])
        upper = calc.dec(existing["max_discount_pct"])
        if body["min_discount_pct"] < upper and lower < body["max_discount_pct"]:
            fail("ERR_APPROVAL_TIER_OVERLAP", "The discount range overlaps an existing band.")
    record = dict(body)
    db.insert("approval_tiers", record, versioned=False)
    return response.created(record)


@bp.get("/desk-policies/<policy_id>/approval-tiers")
@require_roles(ALL)
def list_approval_tiers(policy_id):
    common.must_get("desk_policies", policy_id)
    rows = db.tiers_of_policy(policy_id)
    window, total, limit, offset = validation.paginate(rows)
    return response.listing(window, total, limit, offset)


PRODUCT_SPEC = {
    "sku": {"type": "string", "required": True},
    "name": {"type": "string", "required": True},
    "product_type": {
        "type": "enum",
        "required": True,
        "values": ("SUBSCRIPTION_LICENSE", "USAGE_METERED", "PROFESSIONAL_SERVICES", "SUPPORT_PLAN"),
    },
    "list_unit_price_cents": {"type": "integer", "required": True, "gt": 0},
    "unit_cost_cents": {"type": "integer", "required": True, "ge": 0},
    "rev_rec_category": {
        "type": "enum",
        "required": True,
        "values": ("RATABLE", "POINT_IN_TIME", "USAGE_AS_INCURRED"),
    },
    "min_term_months": {"type": "integer", "required": True, "ge": 1},
}


@bp.post("/products")
@require_roles("PlatformAdmin")
def create_product():
    body = validate(json_body(), PRODUCT_SPEC)
    if not body["unit_cost_cents"] < body["list_unit_price_cents"]:
        fail("ERR_INVALID_REQUEST", "unit_cost_cents must be below list_unit_price_cents.")
    for existing in db.all_records("products"):
        if existing["sku"] == body["sku"]:
            fail("ERR_DUPLICATE_PRODUCT_SKU")
    record = dict(body)
    db.insert("products", record)
    return response.created(record)


@bp.get("/products/<product_id>")
@require_roles(ALL)
def read_product(product_id):
    return response.ok(common.must_get("products", product_id))


VOLUME_TIER_SPEC = {
    "product_id": {"type": "string", "required": True},
    "tier_level": {"type": "integer", "required": True, "ge": 1},
    "min_quantity": {"type": "integer", "required": True, "ge": 1},
    "max_quantity": {"type": "integer", "ge": 1},
    "tier_discount_pct": {"type": "number", "required": True, "ge": Decimal(0), "lt": Decimal(1)},
}


@bp.post("/volume-tiers")
@require_roles("PlatformAdmin")
def create_volume_tier():
    body = validate(json_body(), VOLUME_TIER_SPEC)
    max_quantity = body.get("max_quantity")
    if max_quantity is not None and max_quantity < body["min_quantity"]:
        fail("ERR_INVALID_REQUEST", "max_quantity must be at or above min_quantity.")
    if db.product(body["product_id"]) is None:
        fail("ERR_PRODUCT_NOT_FOUND")
    upper = max_quantity if max_quantity is not None else None
    for existing in db.bands_of_product(body["product_id"]):
        if existing["tier_level"] == body["tier_level"]:
            fail("ERR_VOLUME_TIER_OVERLAP", "That tier_level is already configured.")
        if existing.get("max_quantity") is None and upper is None:
            fail("ERR_VOLUME_TIER_OVERLAP", "Only one unbounded band is allowed per product.")
        other_upper = existing.get("max_quantity")
        starts_after = other_upper is not None and body["min_quantity"] > other_upper
        ends_before = upper is not None and upper < existing["min_quantity"]
        if not (starts_after or ends_before):
            fail("ERR_VOLUME_TIER_OVERLAP", "The quantity range overlaps an existing band.")
    record = dict(body)
    record["max_quantity"] = max_quantity
    db.insert("volume_tiers", record, versioned=False)
    return response.created(record)


@bp.get("/products/<product_id>/volume-tiers")
@require_roles(ALL)
def list_volume_tiers(product_id):
    common.must_get("products", product_id)
    rows = db.bands_of_product(product_id)
    window, total, limit, offset = validation.paginate(rows)
    return response.listing(window, total, limit, offset)


BUNDLE_RULE_SPEC = {
    "anchor_product_id": {"type": "string", "required": True},
    "attached_product_id": {"type": "string", "required": True},
    "bundle_discount_pct": {"type": "number", "required": True, "gt": Decimal(0), "lt": Decimal(1)},
    "min_attach_quantity_ratio": {"type": "number", "required": True, "gt": Decimal(0)},
}


@bp.post("/bundle-rules")
@require_roles("PlatformAdmin")
def create_bundle_rule():
    body = validate(json_body(), BUNDLE_RULE_SPEC)
    if db.product(body["anchor_product_id"]) is None:
        fail("ERR_PRODUCT_NOT_FOUND")
    if db.product(body["attached_product_id"]) is None:
        fail("ERR_PRODUCT_NOT_FOUND")
    if body["anchor_product_id"] == body["attached_product_id"]:
        fail("ERR_DUPLICATE_BUNDLE_RULE", "A rule may not name the same product twice.")
    for existing in db.all_records("bundle_rules"):
        if (existing["anchor_product_id"] == body["anchor_product_id"]
                and existing["attached_product_id"] == body["attached_product_id"]):
            fail("ERR_DUPLICATE_BUNDLE_RULE")
    record = dict(body)
    db.insert("bundle_rules", record, versioned=False)
    return response.created(record)


@bp.get("/products/<product_id>/bundle-rules")
@require_roles(ALL)
def list_bundle_rules(product_id):
    common.must_get("products", product_id)
    rows = [
        r for r in db.all_records("bundle_rules")
        if r["anchor_product_id"] == product_id or r["attached_product_id"] == product_id
    ]
    window, total, limit, offset = validation.paginate(db.sorted_records(rows))
    return response.listing(window, total, limit, offset)


@bp.get("/products/<product_id>/quote-lines")
@require_roles(ALL)
def list_product_quote_lines(product_id):
    common.must_get("products", product_id)
    rows = [r for r in db.all_records("quote_lines") if r["product_id"] == product_id]
    window, total, limit, offset = validation.paginate(db.sorted_records(rows))
    return response.listing(window, total, limit, offset)


@bp.get("/products/<product_id>/price-holds")
@require_roles(ALL)
def list_product_price_holds(product_id):
    common.must_get("products", product_id)
    rows = [
        r for r in db.all_records("nonstandard_terms")
        if r["term_category"] == "PRICE_HOLD_RENEWAL" and r.get("hold_product_id") == product_id
    ]
    rows.sort(key=lambda r: (r["hold_start_date"], r["_seq"]))
    window, total, limit, offset = validation.paginate(rows)
    return response.listing(window, total, limit, offset)


ACCOUNT_SPEC = {
    "name": {"type": "string", "required": True},
    "segment": {
        "type": "enum",
        "required": True,
        "values": ("ENTERPRISE", "MID_MARKET", "SMB"),
    },
    "region": {"type": "string", "required": True},
    "existing_arr_cents": {"type": "integer", "ge": 0},
}


@bp.post("/accounts")
@require_roles("PlatformAdmin", "DealDeskAnalyst")
def create_account():
    body = validate(json_body(), ACCOUNT_SPEC)
    record = {
        "name": body["name"],
        "segment": body["segment"],
        "region": body["region"],
        "existing_arr_cents": body.get("existing_arr_cents", 0),
        "credit_status": "CLEAR",
        "credit_note": None,
        "booked_arr_cents": 0,
        "exception_allowance_used_cents": 0,
    }
    db.insert("accounts", record)
    return response.created(record)


@bp.get("/accounts/<account_id>")
@require_roles(ALL)
def read_account(account_id):
    return response.ok(common.must_get("accounts", account_id))


CREDIT_SPEC = {
    "credit_status": {
        "type": "enum",
        "required": True,
        "values": ("CLEAR", "WATCH", "HOLD"),
    },
    "credit_note": {"type": "string"},
}


@bp.post("/accounts/<account_id>/credit-decisions")
@require_roles("PlatformAdmin", "CFO")
def create_credit_decision(account_id):
    account = common.must_get("accounts", account_id)
    body = validate(json_body(), CREDIT_SPEC)
    account["credit_status"] = body["credit_status"]
    account["credit_note"] = body.get("credit_note")
    db.touch(account)
    return response.ok(account)
