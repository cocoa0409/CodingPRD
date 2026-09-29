"""Every read endpoint (PRD 2.3, 2.9, 4)."""

from flask import Blueprint

from db import db
from middleware import (ROLE_CONTROLLER, ROLE_MERCHANDISE_DIRECTOR,
                        ROLE_PRICING_ANALYST, ROLE_STORE_MANAGER,
                        ROLE_VENDOR_REP, endpoint)
from response import filter_date, filter_enum, filter_str, ok, ok_list, pagination
from serializers import (agreement_json, claim_json, disposition_json,
                         estimate_json, execution_json, exit_review_json,
                         item_json, plan_json, price_zone_json,
                         reservation_json, sales_week_json, season_json,
                         step_json, store_json)
from services import lookup

bp = Blueprint("reads", __name__)

EVERYONE = (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR,
            ROLE_STORE_MANAGER, ROLE_VENDOR_REP, ROLE_CONTROLLER)
COMMERCIAL = (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR,
              ROLE_VENDOR_REP, ROLE_CONTROLLER)
INTERNAL = (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR, ROLE_CONTROLLER)
OPERATIONS = (ROLE_PRICING_ANALYST, ROLE_MERCHANDISE_DIRECTOR,
              ROLE_STORE_MANAGER, ROLE_CONTROLLER)

CATEGORIES = ("APPAREL", "FOOTWEAR", "ACCESSORIES", "SEASONAL_DECOR")
SEASON_STATUSES = ("PLANNING", "ACTIVE", "EXIT_WINDOW", "CLOSED")
ZONE_TYPES = ("CHAIN", "REGION", "STORE")
STORE_STATUSES = ("OPEN", "REMODEL", "CLOSING")
LIFECYCLE_STAGES = ("NEW_ARRIVAL", "CORE", "AGING", "CLEARANCE",
                    "EXIT_PENDING", "DISPOSED")
MARKDOWN_STATES = ("FULL_PRICE", "PROMO_ACTIVE", "PERM_MARKED", "EXIT_PRICED",
                   "SETTLED")
ESTIMATE_STATUSES = ("DRAFT", "CERTIFIED", "SUPERSEDED")
CONFIDENCES = ("HIGH", "LOW")
PLAN_TYPES = ("PERMANENT", "PROMOTIONAL")
PLAN_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED",
                 "EXECUTING", "COMPLETED", "SUPERSEDED")
STEP_STATUSES = ("PLANNED", "SCHEDULED", "EXECUTED", "SUPERSEDED")
EXECUTION_SCOPES = ("CHAIN", "ZONE", "STORE")
EXECUTION_STATUSES = ("SCHEDULED", "APPLIED", "ROLLED_BACK")
SIGNAGE_STATUSES = ("PENDING", "POSTED", "NON_COMPLIANT", "VERIFIED")
RESERVATION_STATUSES = ("RESERVED", "COMMITTED", "RELEASED")
AGREEMENT_STATUSES = ("PROPOSED", "COUNTERED", "AGREED", "FUNDED", "EXPIRED")
CLAIM_STATUSES = ("SUBMITTED", "RECOGNIZED", "REJECTED", "REVERSED")
CHANNELS = ("SALVAGE", "JOBBER", "DONATION")
DISPOSITION_STATUSES = ("DRAFT", "APPROVED", "SETTLED", "CANCELLED")
REVIEW_TYPES = ("PRELIMINARY", "FINAL")


def _matches(row, filters):
    for field, wanted in filters.items():
        if wanted is None:
            continue
        if row.get(field) != wanted:
            return False
    return True


def _select(collection, filters, sort_key=None):
    rows = [r for r in getattr(db, collection).values() if _matches(r, filters)]
    if sort_key is None:
        return sorted(rows, key=lambda r: r["created_at"])
    return sorted(rows, key=sort_key)


# --------------------------------------------------------------------------
# Seasons
# --------------------------------------------------------------------------

@endpoint(bp, "/seasons", ["GET"], EVERYONE)
def list_seasons(user_id, role):
    limit, offset = pagination()
    filters = {
        "status": filter_enum("status", SEASON_STATUSES),
        "category": filter_enum("category", CATEGORIES),
    }
    rows = _select("seasons", filters,
                   sort_key=lambda r: (r["created_at"], r["code"]))
    return ok_list([season_json(r) for r in rows], limit, offset)


@endpoint(bp, "/seasons/<season_id>", ["GET"], EVERYONE)
def get_season(user_id, role, season_id):
    return ok(season_json(lookup.season(season_id)))


@endpoint(bp, "/seasons/<season_id>/allowance-agreements", ["GET"], COMMERCIAL)
def list_season_agreements(user_id, role, season_id):
    limit, offset = pagination()
    filters = {
        "status": filter_enum("status", AGREEMENT_STATUSES),
        "vendor_code": filter_str("vendor_code"),
    }
    season = lookup.season(season_id)
    filters["season_id"] = season["id"]
    rows = _select("agreements", filters)
    return ok_list([agreement_json(r) for r in rows], limit, offset)


@endpoint(bp, "/seasons/<season_id>/exit-reviews", ["GET"], INTERNAL)
def list_season_exit_reviews(user_id, role, season_id):
    limit, offset = pagination()
    filters = {"review_type": filter_enum("review_type", REVIEW_TYPES)}
    season = lookup.season(season_id)
    filters["season_id"] = season["id"]
    rows = _select("exit_reviews", filters)
    return ok_list([exit_review_json(r) for r in rows], limit, offset)


@endpoint(bp, "/exit-reviews", ["GET"], INTERNAL)
def list_exit_reviews(user_id, role):
    limit, offset = pagination()
    filters = {
        "season_id": filter_str("season_id"),
        "review_type": filter_enum("review_type", REVIEW_TYPES),
    }
    rows = _select("exit_reviews", filters,
                   sort_key=lambda r: (r["generated_at"], r["created_at"]))
    return ok_list([exit_review_json(r) for r in rows], limit, offset)


@endpoint(bp, "/exit-reviews/<exit_review_id>", ["GET"], INTERNAL)
def get_exit_review(user_id, role, exit_review_id):
    return ok(exit_review_json(lookup.exit_review(exit_review_id)))


# --------------------------------------------------------------------------
# Price zones and stores
# --------------------------------------------------------------------------

@endpoint(bp, "/price-zones", ["GET"], OPERATIONS)
def list_price_zones(user_id, role):
    limit, offset = pagination()
    filters = {
        "zone_type": filter_enum("zone_type", ZONE_TYPES),
        "parent_zone_id": filter_str("parent_zone_id"),
        "region_code": filter_str("region_code"),
    }
    rows = _select("price_zones", filters)
    return ok_list([price_zone_json(r) for r in rows], limit, offset)


@endpoint(bp, "/price-zones/<price_zone_id>", ["GET"], OPERATIONS)
def get_price_zone(user_id, role, price_zone_id):
    return ok(price_zone_json(lookup.price_zone(price_zone_id)))


@endpoint(bp, "/stores", ["GET"], OPERATIONS)
def list_stores(user_id, role):
    limit, offset = pagination()
    filters = {
        "price_zone_id": filter_str("price_zone_id"),
        "status": filter_enum("status", STORE_STATUSES),
        "region_code": filter_str("region_code"),
    }
    rows = _select("stores", filters)
    return ok_list([store_json(r) for r in rows], limit, offset)


@endpoint(bp, "/stores/<store_id>", ["GET"], OPERATIONS)
def get_store(user_id, role, store_id):
    return ok(store_json(lookup.store(store_id)))


# --------------------------------------------------------------------------
# Items, sales weeks and elasticity estimates
# --------------------------------------------------------------------------

@endpoint(bp, "/items", ["GET"], EVERYONE)
def list_items(user_id, role):
    limit, offset = pagination()
    filters = {
        "season_id": filter_str("season_id"),
        "cluster_code": filter_str("cluster_code"),
        "lifecycle_stage": filter_enum("lifecycle_stage", LIFECYCLE_STAGES),
        "markdown_state": filter_enum("markdown_state", MARKDOWN_STATES),
        "vendor_code": filter_str("vendor_code"),
        "category": filter_enum("category", CATEGORIES),
    }
    rows = _select("items", filters)
    return ok_list([item_json(r) for r in rows], limit, offset)


@endpoint(bp, "/items/<item_id>", ["GET"], EVERYONE)
def get_item(user_id, role, item_id):
    return ok(item_json(lookup.item(item_id)))


@endpoint(bp, "/items/<item_id>/sales-weeks", ["GET"], INTERNAL)
def list_item_sales_weeks(user_id, role, item_id):
    limit, offset = pagination()
    filters = {"week_ending_date": filter_date("week_ending_date")}
    item = lookup.item(item_id)
    filters["item_id"] = item["id"]
    rows = _select("sales_weeks", filters,
                   sort_key=lambda r: (r["week_ending_date"], r["created_at"]))
    return ok_list([sales_week_json(r) for r in rows], limit, offset)


@endpoint(bp, "/sales-weeks", ["GET"], INTERNAL)
def list_sales_weeks(user_id, role):
    limit, offset = pagination()
    filters = {
        "item_id": filter_str("item_id"),
        "week_ending_date": filter_date("week_ending_date"),
    }
    rows = _select("sales_weeks", filters,
                   sort_key=lambda r: (r["week_ending_date"], r["created_at"]))
    return ok_list([sales_week_json(r) for r in rows], limit, offset)


@endpoint(bp, "/sales-weeks/<sales_week_id>", ["GET"], INTERNAL)
def get_sales_week(user_id, role, sales_week_id):
    return ok(sales_week_json(lookup.sales_week(sales_week_id)))


@endpoint(bp, "/items/<item_id>/elasticity-estimates", ["GET"], INTERNAL)
def list_item_estimates(user_id, role, item_id):
    limit, offset = pagination()
    filters = {
        "status": filter_enum("status", ESTIMATE_STATUSES),
        "confidence": filter_enum("confidence", CONFIDENCES),
    }
    item = lookup.item(item_id)
    filters["item_id"] = item["id"]
    rows = _select("estimates", filters)
    return ok_list([estimate_json(r) for r in rows], limit, offset)


@endpoint(bp, "/elasticity-estimates", ["GET"], INTERNAL)
def list_estimates(user_id, role):
    limit, offset = pagination()
    filters = {
        "item_id": filter_str("item_id"),
        "status": filter_enum("status", ESTIMATE_STATUSES),
        "confidence": filter_enum("confidence", CONFIDENCES),
    }
    rows = _select("estimates", filters)
    return ok_list([estimate_json(r) for r in rows], limit, offset)


@endpoint(bp, "/elasticity-estimates/<estimate_id>", ["GET"], INTERNAL)
def get_estimate(user_id, role, estimate_id):
    return ok(estimate_json(lookup.estimate(estimate_id)))


# --------------------------------------------------------------------------
# Plans and ladder rungs
# --------------------------------------------------------------------------

@endpoint(bp, "/markdown-plans", ["GET"], COMMERCIAL)
def list_plans(user_id, role):
    limit, offset = pagination()
    filters = {
        "season_id": filter_str("season_id"),
        "item_id": filter_str("item_id"),
        "elasticity_estimate_id": filter_str("elasticity_estimate_id"),
        "superseded_by_plan_id": filter_str("superseded_by_plan_id"),
        "plan_type": filter_enum("plan_type", PLAN_TYPES),
        "status": filter_enum("status", PLAN_STATUSES),
    }
    rows = _select("plans", filters)
    return ok_list([plan_json(r) for r in rows], limit, offset)


@endpoint(bp, "/markdown-plans/<markdown_plan_id>", ["GET"], COMMERCIAL)
def get_plan(user_id, role, markdown_plan_id):
    return ok(plan_json(lookup.plan(markdown_plan_id)))


@endpoint(bp, "/markdown-plans/<markdown_plan_id>/steps", ["GET"], OPERATIONS)
def list_plan_steps(user_id, role, markdown_plan_id):
    limit, offset = pagination()
    filters = {"status": filter_enum("status", STEP_STATUSES)}
    plan = lookup.plan(markdown_plan_id)
    filters["markdown_plan_id"] = plan["id"]
    rows = _select("steps", filters,
                   sort_key=lambda r: (r["step_index"], r["created_at"]))
    return ok_list([step_json(r) for r in rows], limit, offset)


@endpoint(bp, "/markdown-steps", ["GET"], OPERATIONS)
def list_steps(user_id, role):
    limit, offset = pagination()
    filters = {
        "markdown_plan_id": filter_str("markdown_plan_id"),
        "status": filter_enum("status", STEP_STATUSES),
    }
    rows = _select("steps", filters,
                   sort_key=lambda r: (r["step_index"], r["created_at"]))
    return ok_list([step_json(r) for r in rows], limit, offset)


@endpoint(bp, "/markdown-steps/<markdown_step_id>", ["GET"], OPERATIONS)
def get_step(user_id, role, markdown_step_id):
    return ok(step_json(lookup.step(markdown_step_id)))


# --------------------------------------------------------------------------
# Zone executions, reservations, agreements, claims, dispositions
# --------------------------------------------------------------------------

@endpoint(bp, "/zone-executions", ["GET"], OPERATIONS)
def list_executions(user_id, role):
    limit, offset = pagination()
    filters = {
        "markdown_plan_id": filter_str("markdown_plan_id"),
        "markdown_step_id": filter_str("markdown_step_id"),
        "price_zone_id": filter_str("price_zone_id"),
        "store_id": filter_str("store_id"),
        "execution_scope": filter_enum("execution_scope", EXECUTION_SCOPES),
        "status": filter_enum("status", EXECUTION_STATUSES),
        "signage_status": filter_enum("signage_status", SIGNAGE_STATUSES),
    }
    rows = _select("executions", filters)
    return ok_list([execution_json(r) for r in rows], limit, offset)


@endpoint(bp, "/zone-executions/<zone_execution_id>", ["GET"], OPERATIONS)
def get_execution(user_id, role, zone_execution_id):
    return ok(execution_json(lookup.execution(zone_execution_id)))


@endpoint(bp, "/clearance-reservations", ["GET"], OPERATIONS)
def list_reservations(user_id, role):
    limit, offset = pagination()
    filters = {
        "season_id": filter_str("season_id"),
        "store_id": filter_str("store_id"),
        "markdown_plan_id": filter_str("markdown_plan_id"),
        "status": filter_enum("status", RESERVATION_STATUSES),
    }
    rows = _select("reservations", filters)
    return ok_list([reservation_json(r) for r in rows], limit, offset)


@endpoint(bp, "/clearance-reservations/<reservation_id>", ["GET"], OPERATIONS)
def get_reservation(user_id, role, reservation_id):
    return ok(reservation_json(lookup.reservation(reservation_id)))


@endpoint(bp, "/allowance-agreements", ["GET"], COMMERCIAL)
def list_agreements(user_id, role):
    limit, offset = pagination()
    filters = {
        "season_id": filter_str("season_id"),
        "vendor_code": filter_str("vendor_code"),
        "item_category_scope": filter_enum("item_category_scope", CATEGORIES),
        "status": filter_enum("status", AGREEMENT_STATUSES),
    }
    rows = _select("agreements", filters)
    return ok_list([agreement_json(r) for r in rows], limit, offset)


@endpoint(bp, "/allowance-agreements/<agreement_id>", ["GET"], COMMERCIAL)
def get_agreement(user_id, role, agreement_id):
    return ok(agreement_json(lookup.agreement(agreement_id)))


@endpoint(bp, "/vendor-claims", ["GET"], COMMERCIAL)
def list_claims(user_id, role):
    limit, offset = pagination()
    filters = {
        "allowance_agreement_id": filter_str("allowance_agreement_id"),
        "markdown_plan_id": filter_str("markdown_plan_id"),
        "status": filter_enum("status", CLAIM_STATUSES),
    }
    rows = _select("claims", filters)
    return ok_list([claim_json(r) for r in rows], limit, offset)


@endpoint(bp, "/vendor-claims/<claim_id>", ["GET"], COMMERCIAL)
def get_claim(user_id, role, claim_id):
    return ok(claim_json(lookup.claim(claim_id)))


@endpoint(bp, "/disposition-orders", ["GET"], INTERNAL)
def list_dispositions(user_id, role):
    limit, offset = pagination()
    filters = {
        "season_id": filter_str("season_id"),
        "item_id": filter_str("item_id"),
        "channel": filter_enum("channel", CHANNELS),
        "status": filter_enum("status", DISPOSITION_STATUSES),
    }
    rows = _select("dispositions", filters)
    return ok_list([disposition_json(r) for r in rows], limit, offset)


@endpoint(bp, "/disposition-orders/<disposition_order_id>", ["GET"], INTERNAL)
def get_disposition(user_id, role, disposition_order_id):
    return ok(disposition_json(lookup.disposition(disposition_order_id)))
