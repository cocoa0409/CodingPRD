"""Break-room sites, demand modelling and par planning (PRD 3.2)."""
from datetime import timedelta

from flask import Blueprint

import calc
import cascade
import lookup
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                  ROLE_ROUTE_TECHNICIAN, authenticate)
from envelope import created, ok
from errors import ApiError
from routes.accounts import OPERATING_POSTURES
from store import bump, db, insert, now, ordered, snapshot, touch

bp = Blueprint("sites", __name__)

CONSUMPTION_MODELS = ("HEADCOUNT_MODEL", "TRAILING_USAGE")
BREW_STYLES = ("DRIP", "SINGLE_CUP", "ESPRESSO")
SERVICEABLE_POSTURES = ("ACTIVE", "ESCALATED")


@bp.post("/ocs/sites")
def create_site():
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    account_id = fields.string("account_id", min_len=1)
    route_id = fields.string("route_id", min_len=1)
    site_name = fields.string("site_name", min_len=1, max_len=200)
    headcount = fields.integer("headcount", minimum=1)
    days_per_week = fields.integer("days_per_week", minimum=1, maximum=7)
    consumption_model = fields.enum("consumption_model", CONSUMPTION_MODELS)
    service_minutes = fields.integer("service_minutes_estimate", minimum=1, maximum=480)
    # Body foreign keys resolve in the order the fields are declared (PRD 2.9).
    account = lookup.account(account_id)
    lookup.route(route_id)
    if account["program_posture"] not in OPERATING_POSTURES:
        raise ApiError("ERR_ACCOUNT_NOT_OPERATING",
                       "Account posture %s does not accept new sites."
                       % account["program_posture"])
    row = insert(db.sites, {
        "account_id": account_id,
        "route_id": route_id,
        "site_name": site_name,
        "headcount": headcount,
        "days_per_week": days_per_week,
        "consumption_model": consumption_model,
        "brew_style": None,
        "service_minutes_estimate": service_minutes,
        "service_posture": "ACTIVE",
        "forecast_cups_per_week": 0,
        "required_peak_cups_per_hour": 0,
        "recommended_model_id": None,
        "consecutive_shortfall_visit_count": 0,
        "escalation_score": 0.0,
    })
    return created(serializers.site(row))


@bp.get("/ocs/sites")
def list_sites():
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                  ROLE_ROUTE_TECHNICIAN))
    rows = lookup.eq_filter(list(db.sites.values()), "account_id")
    rows = lookup.eq_filter(rows, "route_id")
    rows = lookup.eq_filter(rows, "service_posture")
    return lookup.listing(rows, serializers.site)


@bp.get("/ocs/sites/<site_id>")
def read_site(site_id):
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                  ROLE_ROUTE_TECHNICIAN))
    return ok(serializers.site(lookup.site(site_id)))


@bp.patch("/ocs/sites/<site_id>")
def update_site(site_id):
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    headcount = fields.integer("headcount", required=False, minimum=1)
    days_per_week = fields.integer("days_per_week", required=False, minimum=1, maximum=7)
    consumption_model = fields.enum("consumption_model", CONSUMPTION_MODELS,
                                    required=False)
    route_id = fields.string("route_id", required=False, min_len=1)
    site = lookup.site(site_id)
    if route_id is not None:
        lookup.route(route_id)
    before = snapshot(site)
    # Revising demand attributes deliberately does NOT re-run the forecast.
    if headcount is not None:
        site["headcount"] = headcount
    if days_per_week is not None:
        site["days_per_week"] = days_per_week
    if consumption_model is not None:
        site["consumption_model"] = consumption_model
    if route_id is not None:
        site["route_id"] = route_id
    touch(site, before)
    return ok(serializers.site(site))


@bp.post("/ocs/sites/<site_id>/evaluate-service-posture")
def evaluate_service_posture(site_id):
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST))
    site = lookup.site(site_id)
    # The site's version increments by 1 only when the posture actually changed.
    cascade.apply_site_posture(site, version_only_on_posture_change=True)
    return ok(serializers.site(site))


def _observed_delivery_by_product(site_id):
    """TRAILING_USAGE observation window: the 28 days ending at the current instant,
    inclusive of both endpoints. Voided and cancelled visits contribute nothing."""
    current = now()
    start = current - timedelta(days=calc.TRAILING_WINDOW_DAYS)
    observed = {}
    any_visit = False
    for visit in calc.site_visits(site_id):
        if visit["visit_status"] != "COMPLETED":
            continue
        if not (start <= visit["window_start"] <= current):
            continue
        any_visit = True
        for line in visit["lines"]:
            delivered = line.get("delivered_units") or 0
            observed[line["product_id"]] = observed.get(line["product_id"], 0) + delivered
    return observed, any_visit


def _write_forecast_par_line(site, product, par_units, reorder_units):
    existing = calc.par_line_for(site["id"], product["id"])
    if existing is not None:
        if existing["source"] == "MANUAL":
            return  # MANUAL lines are never touched by planning.
        existing["par_units"] = par_units
        existing["reorder_point_units"] = reorder_units
        # stock_status is always derived, never supplied, so a rewritten reorder
        # point re-derives it against the shelf quantity already on the line.
        existing["stock_status"] = calc.stock_status(existing["on_hand_units"],
                                                    reorder_units)
        bump(existing)
        return
    insert(db.par_levels, {
        "site_id": site["id"],
        "product_id": product["id"],
        "par_units": par_units,
        "reorder_point_units": reorder_units,
        "source": "FORECAST",
        "on_hand_units": 0,
        "cumulative_delivered_units": 0,
        "cumulative_consumed_units": 0,
        "last_service_at": now(),
        "stock_status": "STOCKOUT",
    })


@bp.post("/ocs/sites/<site_id>/size-and-plan")
def size_and_plan(site_id):
    authenticate((ROLE_ACCOUNT_MANAGER,))
    fields = shape.fields()
    brew_style = fields.enum("brew_style", BREW_STYLES)
    site = lookup.site(site_id)
    if site["service_posture"] not in SERVICEABLE_POSTURES:
        raise ApiError("ERR_SITE_NOT_SERVICEABLE",
                       "Site posture %s cannot be planned." % site["service_posture"])

    # The weekly cup forecast is computed identically under both variants.
    cups = calc.forecast_cups_per_week(site["headcount"], site["days_per_week"], brew_style)
    peak = calc.required_peak_cups_per_hour(cups, site["days_per_week"])

    # Feasibility gates, in ladder order: model fit (37) then trailing usage (38).
    recommended_model_id = calc.select_recommended_model(site["headcount"], peak)
    if recommended_model_id is None:
        raise ApiError("ERR_NO_MODEL_FITS_HEADCOUNT",
                       "No brewer model fits this site's headcount and peak throughput.")

    observed = None
    if site["consumption_model"] == "TRAILING_USAGE":
        observed, any_visit = _observed_delivery_by_product(site["id"])
        if not any_visit:
            raise ApiError("ERR_NO_TRAILING_USAGE",
                           "The site has no completed visit inside the trailing window.")

    site["brew_style"] = brew_style
    site["forecast_cups_per_week"] = cups
    site["required_peak_cups_per_hour"] = peak
    site["recommended_model_id"] = recommended_model_id

    # One FORECAST par line per catalog product, at this site.
    for product in ordered(list(db.product_items.values())):
        if observed is None:
            par_units = calc.headcount_par_units(cups, product["category"])
        else:
            par_units = calc.trailing_par_units(observed.get(product["id"], 0))
        _write_forecast_par_line(site, product, par_units,
                                 calc.reorder_point_units(par_units))

    bump(site)
    return ok(serializers.site(site))
