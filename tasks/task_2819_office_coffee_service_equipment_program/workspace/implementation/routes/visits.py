"""Route capacity, replenishment scheduling, completion and voiding (PRD 3.4, 3.5)."""
from flask import Blueprint, request

import calc
import cascade
import lookup
import serializers
import shape
from authz import (ROLE_ACCOUNT_MANAGER, ROLE_BILLING_SPECIALIST, ROLE_PROGRAM_ADMIN,
                  ROLE_ROUTE_TECHNICIAN, authenticate, require_route_owner)
from envelope import created, ok
from errors import ApiError
from routes.accounts import OPERATING_POSTURES
from routes.sites import SERVICEABLE_POSTURES
from store import bump, db, insert, now, ordered, snapshot, touch
from timeutil import UTC, is_minute_aligned, parse_date_only, weekday_name

bp = Blueprint("visits", __name__)


def _validate_window(route, window_start, window_end):
    """PRD 3.4: window_end strictly after window_start, both minute-aligned, and
    window_start on the route's own service_day in UTC."""
    if window_end <= window_start:
        raise ApiError("ERR_VISIT_WINDOW_INVALID",
                       "window_end must be strictly later than window_start.")
    if not is_minute_aligned(window_start) or not is_minute_aligned(window_end):
        raise ApiError("ERR_VISIT_WINDOW_INVALID", "Both instants must be minute-aligned.")
    if weekday_name(window_start) != route["service_day"]:
        raise ApiError("ERR_VISIT_WINDOW_INVALID",
                       "window_start must fall on the route's service day %s."
                       % route["service_day"])


def _check_capacity(route, window_start, planned_minutes, exclude_visit_id=None):
    service_date = window_start.astimezone(UTC).date()
    booked = calc.booked_minutes_on_date(route["id"], service_date,
                                         exclude_visit_id=exclude_visit_id)
    if booked + planned_minutes > route["capacity_minutes"]:
        raise ApiError("ERR_ROUTE_CAPACITY_EXCEEDED",
                       "The route's day capacity would be exceeded.")


@bp.post("/ocs/service-visits")
def create_service_visit():
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_PROGRAM_ADMIN))
    fields = shape.fields()
    site_id = fields.string("site_id", min_len=1)
    window_start = fields.instant("window_start")
    window_end = fields.instant("window_end")
    planned_minutes = fields.integer("planned_minutes", minimum=1, maximum=480)
    site = lookup.site(site_id)
    account = db.accounts.get(site["account_id"])
    if account is None or account["program_posture"] not in OPERATING_POSTURES:
        raise ApiError("ERR_ACCOUNT_NOT_OPERATING",
                       "The owning account does not accept new stops.")
    if site["service_posture"] not in SERVICEABLE_POSTURES:
        raise ApiError("ERR_SITE_NOT_SERVICEABLE",
                       "Site posture %s cannot be scheduled." % site["service_posture"])
    # The visit's route is copied from the site's own route and is never client-supplied.
    route = lookup.route(site["route_id"])
    _validate_window(route, window_start, window_end)
    if calc.route_window_conflict(route, window_start, window_end):
        raise ApiError("ERR_ROUTE_WINDOW_CONFLICT",
                       "The buffered window collides with another stop on this route.")
    if site["recommended_model_id"] is None:
        raise ApiError("ERR_SITE_NOT_PLANNED",
                       "The site must be planned before a stop is scheduled.")
    _check_capacity(route, window_start, planned_minutes)

    row = insert(db.service_visits, {
        "site_id": site_id,
        "route_id": route["id"],
        "window_start": window_start,
        "window_end": window_end,
        "planned_minutes": planned_minutes,
        "visit_status": "SCHEDULED",
        "lines": [],
        "shortfall_flag": False,
        "completed_at": None,
        "void_reason": None,
    })
    route["booked_minutes_total"] = route["booked_minutes_total"] + planned_minutes
    bump(route)
    return created(serializers.service_visit(row))


def _service_date_matches(visit, raw):
    wanted = parse_date_only(raw)
    if wanted is None:
        return False
    return visit["window_start"].astimezone(UTC).date() == wanted


@bp.get("/ocs/service-visits")
def list_service_visits():
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_PROGRAM_ADMIN, ROLE_BILLING_SPECIALIST,
                  ROLE_ROUTE_TECHNICIAN))
    rows = lookup.eq_filter(list(db.service_visits.values()), "site_id")
    rows = lookup.eq_filter(rows, "route_id")
    rows = lookup.eq_filter(rows, "visit_status")
    raw_date = request.args.get("service_date")
    if raw_date is not None:
        rows = [v for v in rows if _service_date_matches(v, raw_date)]
    return lookup.listing(rows, serializers.service_visit)


@bp.get("/ocs/service-visits/<visit_id>")
def read_service_visit(visit_id):
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_PROGRAM_ADMIN, ROLE_BILLING_SPECIALIST,
                  ROLE_ROUTE_TECHNICIAN))
    return ok(serializers.service_visit(lookup.service_visit(visit_id)))


@bp.post("/ocs/service-visits/<visit_id>/reschedule")
def reschedule_service_visit(visit_id):
    authenticate((ROLE_ACCOUNT_MANAGER, ROLE_PROGRAM_ADMIN))
    fields = shape.fields()
    window_start = fields.instant("window_start")
    window_end = fields.instant("window_end")
    visit = lookup.service_visit(visit_id)
    if visit["visit_status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_STATE_INVALID",
                       "Visit state %s cannot be rescheduled." % visit["visit_status"])
    route = lookup.route(visit["route_id"])
    _validate_window(route, window_start, window_end)
    if calc.route_window_conflict(route, window_start, window_end,
                                  exclude_visit_id=visit["id"]):
        raise ApiError("ERR_ROUTE_WINDOW_CONFLICT",
                       "The buffered window collides with another stop on this route.")
    _check_capacity(route, window_start, visit["planned_minutes"],
                    exclude_visit_id=visit["id"])
    visit["window_start"] = window_start
    visit["window_end"] = window_end
    # planned_minutes is unchanged, so booked_minutes_total is unchanged.
    bump(visit)
    return ok(serializers.service_visit(visit))


@bp.post("/ocs/service-visits/<visit_id>/lines")
def append_visit_line(visit_id):
    actor = authenticate((ROLE_ROUTE_TECHNICIAN,))
    fields = shape.fields()
    product_id = fields.string("product_id", min_len=1)
    requested_units = fields.integer("requested_units")
    visit = lookup.service_visit(visit_id)
    lookup.product_item(product_id)
    require_route_owner(actor, visit["route_id"])
    if visit["visit_status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_STATE_INVALID",
                       "Visit state %s does not accept lines." % visit["visit_status"])
    if calc.par_line_for(visit["site_id"], product_id) is None:
        raise ApiError("ERR_PRODUCT_NOT_STOCKED",
                       "The product is not stocked at this site.")
    if any(line["product_id"] == product_id for line in visit["lines"]):
        raise ApiError("ERR_DUPLICATE_VISIT_LINE",
                       "This visit already carries a line for that product.")
    visit["lines"].append({
        "product_id": product_id,
        "requested_units": requested_units,
        "delivered_units": None,
        "consumed_units": None,
        "effective_unit_price_micros": None,
        "resulting_on_hand_units": None,
    })
    bump(visit)
    return ok(serializers.service_visit(visit))


def _parse_delivered_lines(fields):
    """delivered_lines is an array of { product_id, delivered_units }."""
    raw = fields.array("delivered_lines")
    parsed = []
    for index, element in enumerate(raw):
        if not isinstance(element, dict):
            raise ApiError("ERR_VALIDATION",
                           "delivered_lines[%d] must be an object." % index)
        product_id = element.get("product_id")
        delivered_units = element.get("delivered_units")
        if not isinstance(product_id, str) or not product_id:
            raise ApiError("ERR_VALIDATION",
                           "delivered_lines[%d].product_id must be a string." % index)
        if not shape.is_int(delivered_units):
            raise ApiError("ERR_VALIDATION",
                           "delivered_lines[%d].delivered_units must be an integer."
                           % index)
        parsed.append((product_id, delivered_units))
    return parsed


@bp.post("/ocs/service-visits/<visit_id>/complete")
def complete_service_visit(visit_id):
    actor = authenticate((ROLE_ROUTE_TECHNICIAN,))
    fields = shape.fields()
    delivered = _parse_delivered_lines(fields)
    visit = lookup.service_visit(visit_id)
    require_route_owner(actor, visit["route_id"])
    site = db.sites.get(visit["site_id"])
    if site is None or site["service_posture"] not in SERVICEABLE_POSTURES:
        raise ApiError("ERR_SITE_NOT_SERVICEABLE",
                       "The site is not serviceable.")
    if visit["visit_status"] != "SCHEDULED":
        raise ApiError("ERR_VISIT_STATE_INVALID",
                       "Visit state %s cannot be completed." % visit["visit_status"])
    if now() < visit["window_start"]:
        raise ApiError("ERR_VISIT_NOT_YET_STARTED", "The visit's window has not opened.")

    requested = {line["product_id"]: line["requested_units"] for line in visit["lines"]}
    reported = {}
    for product_id, delivered_units in delivered:
        if product_id not in requested:
            raise ApiError("ERR_DELIVERED_EXCEEDS_REQUESTED",
                           "Product %s is absent from the visit's lines." % product_id)
        if delivered_units < 0 or delivered_units > requested[product_id]:
            raise ApiError("ERR_DELIVERED_EXCEEDS_REQUESTED",
                           "Delivered units must be between 0 and the requested units.")
        reported[product_id] = delivered_units

    account = db.accounts.get(site["account_id"])
    site_before = snapshot(site)

    # Consumption is debited before the delivery is credited, in ascending order of
    # the referenced par line's created_at.
    ordered_lines = sorted(
        visit["lines"],
        key=lambda line: _par_sort_key(visit["site_id"], line["product_id"]),
    )
    for line in ordered_lines:
        par = calc.par_line_for(visit["site_id"], line["product_id"])
        product = db.product_items.get(line["product_id"])
        delivered_units = reported.get(line["product_id"], 0)
        consumed_units = calc.consumption_debit(par, visit["window_start"]) if par else 0
        line["consumed_units"] = consumed_units
        line["delivered_units"] = delivered_units
        line["effective_unit_price_micros"] = (
            calc.effective_unit_price_micros(product, account)
            if product is not None and account is not None else 0)
        if par is not None:
            # Cascade hop one - the shelf ledger.
            par["cumulative_consumed_units"] += consumed_units
            par["cumulative_delivered_units"] += delivered_units
            par["on_hand_units"] = (par["cumulative_delivered_units"]
                                    - par["cumulative_consumed_units"])
            par["last_service_at"] = visit["window_start"]
            par["stock_status"] = calc.stock_status(par["on_hand_units"],
                                                   par["reorder_point_units"])
            bump(par)
            line["resulting_on_hand_units"] = par["on_hand_units"]
        else:
            line["resulting_on_hand_units"] = 0

    shortfall = any((line["delivered_units"] or 0) < line["requested_units"]
                    for line in visit["lines"])
    visit["shortfall_flag"] = shortfall
    if shortfall:
        site["consecutive_shortfall_visit_count"] += 1
    else:
        site["consecutive_shortfall_visit_count"] = 0
    visit["completed_at"] = now()
    visit["visit_status"] = "COMPLETED"
    bump(visit)
    # Cascade hops two, three and four.
    cascade.apply_site_posture(site, before=site_before)
    return ok(serializers.service_visit(visit))


def _par_sort_key(site_id, product_id):
    par = calc.par_line_for(site_id, product_id)
    if par is None:
        return (1, None, 0)
    return (0, par["created_at"], par["_seq"])


def _covering_invoice(site, window_start):
    """Once money has gone out the door on a period, that period's history is frozen."""
    for invoice in db.invoices.values():
        if invoice["account_id"] != site["account_id"]:
            continue
        if invoice["invoice_status"] == "VOID":
            continue
        if invoice["period_start"] <= window_start <= invoice["period_end"]:
            return invoice
    return None


def _recompute_shortfall_streak(site):
    completed = [v for v in calc.site_visits(site["id"])
                 if v["visit_status"] == "COMPLETED"]
    completed.sort(key=lambda v: (v["completed_at"] or v["window_start"], v["_seq"]))
    streak = 0
    for visit in completed:
        if visit["shortfall_flag"]:
            streak += 1
        else:
            streak = 0
    return streak


def _revert_last_service_at(site_id, par, product_id):
    """Reverts to the window_start of the most recent remaining COMPLETED visit that
    touched that line, or to the par line's own created_at when none remains."""
    candidates = [
        v for v in calc.site_visits(site_id)
        if v["visit_status"] == "COMPLETED"
        and any(line["product_id"] == product_id for line in v["lines"])
    ]
    if not candidates:
        return par["created_at"]
    candidates.sort(key=lambda v: (v["window_start"], v["_seq"]))
    return candidates[-1]["window_start"]


@bp.post("/ocs/service-visits/<visit_id>/void")
def void_service_visit(visit_id):
    authenticate((ROLE_PROGRAM_ADMIN,))
    fields = shape.fields()
    void_reason = fields.string("void_reason", min_len=1)
    visit = lookup.service_visit(visit_id)
    if visit["visit_status"] != "COMPLETED":
        raise ApiError("ERR_VISIT_STATE_INVALID",
                       "Visit state %s cannot be voided." % visit["visit_status"])
    site = db.sites.get(visit["site_id"])
    if site is not None and _covering_invoice(site, visit["window_start"]) is not None:
        raise ApiError("ERR_VISIT_STATE_INVALID",
                       "An invoice already covers this visit's window.")

    visit["void_reason"] = void_reason
    visit["visit_status"] = "VOIDED"
    bump(visit)

    for line in visit["lines"]:
        par = calc.par_line_for(visit["site_id"], line["product_id"])
        if par is None:
            continue
        par["cumulative_delivered_units"] -= (line["delivered_units"] or 0)
        par["cumulative_consumed_units"] -= (line["consumed_units"] or 0)
        par["on_hand_units"] = (par["cumulative_delivered_units"]
                               - par["cumulative_consumed_units"])
        par["last_service_at"] = _revert_last_service_at(visit["site_id"], par,
                                                         line["product_id"])
        par["stock_status"] = calc.stock_status(par["on_hand_units"],
                                               par["reorder_point_units"])
        bump(par)

    route = db.routes.get(visit["route_id"])
    if route is not None:
        route["booked_minutes_total"] = route["booked_minutes_total"] - visit["planned_minutes"]
        bump(route)

    if site is not None:
        site_before = snapshot(site)
        site["consecutive_shortfall_visit_count"] = _recompute_shortfall_streak(site)
        cascade.apply_site_posture(site, before=site_before)
    return ok(serializers.service_visit(visit))
