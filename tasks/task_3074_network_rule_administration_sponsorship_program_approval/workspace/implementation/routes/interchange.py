"""Interchange rates: draft, list, get, publish, retire, quote."""

from flask import Blueprint, request

import db
from errors import raise_err
from helpers import (
    REGIONS, base_record, get_json, get_or_404, is_digits, logical_now, paginate,
    parse_iso, req_enum, req_int, req_str, sort_by_created, touch,
)
from middleware import require_roles
from response import iso3, ok

bp = Blueprint("interchange", __name__)

TRANSACTION_TYPES = {"CARD_PRESENT", "CARD_NOT_PRESENT", "ECOM_TOKENIZED", "RECURRING"}
DATA_TIERS = {"STANDARD", "ENHANCED", "PREMIUM"}
REGION_SCOPES = REGIONS | {"GLOBAL"}
READ_ROLES = {"NetworkOperator", "PricingAnalyst", "Member"}
TIER_ORDER = ["PREMIUM", "ENHANCED", "STANDARD"]


@bp.post("/network/interchange-rates")
def create_rate():
    require_roles({"PricingAnalyst"})
    body = get_json()
    mcc = req_str(body, "merchant_category")
    transaction_type = req_enum(body, "transaction_type", TRANSACTION_TYPES)
    tier = req_enum(body, "data_quality_tier", DATA_TIERS)
    rate_bps = req_int(body, "rate_basis_points")
    fixed_fee = req_int(body, "fixed_fee_cents")
    region_scope = req_enum(body, "region_scope", REGION_SCOPES)
    if "effective_from" not in body:
        raise_err("ERR_INVALID_REQUEST", "effective_from is required")
    effective_dt = parse_iso(body["effective_from"], "effective_from")
    if not is_digits(mcc, 4):
        raise_err("ERR_VALIDATION", "merchant_category must be exactly 4 digits")
    rec = base_record()
    rec.update({
        "merchant_category": mcc,
        "transaction_type": transaction_type,
        "data_quality_tier": tier,
        "rate_basis_points": rate_bps,
        "fixed_fee_cents": fixed_fee,
        "region_scope": region_scope,
        "effective_from": iso3(effective_dt),
        "status": "DRAFT",
    })
    db.interchange_rates[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/network/interchange-rates")
def list_rates():
    require_roles(READ_ROLES)
    items = list(db.interchange_rates.values())
    mcc = request.args.get("merchant_category")
    tt = request.args.get("transaction_type")
    tier = request.args.get("data_quality_tier")
    region_scope = request.args.get("region_scope")
    status = request.args.get("status")
    if mcc is not None:
        items = [r for r in items if r["merchant_category"] == mcc]
    if tt is not None:
        items = [r for r in items if r["transaction_type"] == tt]
    if tier is not None:
        items = [r for r in items if r["data_quality_tier"] == tier]
    if region_scope is not None:
        items = [r for r in items if r["region_scope"] == region_scope]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return ok(page, 200, meta)


@bp.get("/network/interchange-rates/<rid>")
def get_rate(rid):
    require_roles(READ_ROLES)
    rec = get_or_404(db.interchange_rates, rid)
    return ok(rec, 200)


@bp.post("/network/interchange-rates/<rid>/publish")
def publish_rate(rid):
    require_roles({"PricingAnalyst"})
    rec = get_or_404(db.interchange_rates, rid)
    if rec["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "InterchangeRate is not DRAFT")
    if parse_iso(rec["effective_from"]) < logical_now():
        raise_err("ERR_WINDOW_EXPIRED", "effective_from is in the past")
    rec["status"] = "PUBLISHED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/interchange-rates/<rid>/retire")
def retire_rate(rid):
    require_roles({"PricingAnalyst"})
    rec = get_or_404(db.interchange_rates, rid)
    if rec["status"] != "PUBLISHED":
        raise_err("ERR_INVALID_STATE", "InterchangeRate is not PUBLISHED")
    rec["status"] = "RETIRED"
    touch(rec)
    return ok(rec, 200)


@bp.post("/network/interchange-rates/quote")
def quote_rate():
    require_roles(READ_ROLES)
    body = get_json()
    mcc = req_str(body, "mcc")
    transaction_type = req_enum(body, "transaction_type", TRANSACTION_TYPES)
    region = req_enum(body, "region", REGIONS)
    amount_cents = req_int(body, "amount_cents")
    token = body.get("token")
    avs_match = body.get("avs_match")
    as_of = body.get("as_of")

    if as_of is not None:
        eval_dt = parse_iso(as_of, "as_of")
    else:
        eval_dt = logical_now()

    # Data quality qualification
    if token and avs_match:
        qualified = "PREMIUM"
    elif avs_match:
        qualified = "ENHANCED"
    else:
        qualified = "STANDARD"

    # Downward fallback from the qualified tier
    start_idx = TIER_ORDER.index(qualified)
    winning = None
    winning_tier = None
    for tier in TIER_ORDER[start_idx:]:
        candidates = [
            r for r in db.interchange_rates.values()
            if r["status"] == "PUBLISHED"
            and parse_iso(r["effective_from"]) <= eval_dt
            and r["merchant_category"] == mcc
            and r["transaction_type"] == transaction_type
            and r["data_quality_tier"] == tier
            and r["region_scope"] in (region, "GLOBAL")
        ]
        if not candidates:
            continue
        # region-scoped preferred over GLOBAL; then latest effective_from;
        # then earliest created_at
        region_rows = [r for r in candidates if r["region_scope"] == region]
        pool = region_rows if region_rows else [r for r in candidates if r["region_scope"] == "GLOBAL"]
        pool.sort(key=lambda r: r["created_at"])  # earliest created_at first
        winning = max(pool, key=lambda r: parse_iso(r["effective_from"]))
        winning_tier = tier
        break

    if winning is None:
        raise_err("ERR_RATE_NOT_FOUND",
                  "No published effective interchange rate matches the qualified tier or any lower tier")

    fee_cents = (amount_cents * winning["rate_basis_points"]) // 10000 + winning["fixed_fee_cents"]
    return ok({
        "fee_cents": fee_cents,
        "qualified_tier": winning_tier,
        "rate_basis_points": winning["rate_basis_points"],
        "applied_rate_id": winning["id"],
    }, 200)
