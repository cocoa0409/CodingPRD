"""Fuel-delivery custody, resource holds and the allocatable fuel pool."""

from flask import Blueprint, request

import calc
import constants as C
import middleware
import store
from errors import (
    ERR_ALREADY_TERMINAL, ERR_CONFIRM_TOO_EARLY, ERR_CUSTOMER_SOURCING_UNVERIFIED,
    ERR_DELIVERY_WINDOW_OVERLAP, ERR_FUEL_SOURCING_MODE_INVALID,
    ERR_INSUFFICIENT_DRAW_POSITION, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PPA_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_SITE_DEMAND_LIMIT,
    ERR_SITE_FROZEN, ERR_SITE_NOT_FOUND, ERR_STALE_VERSION, ApiError,
)
from fields import Body

bp = Blueprint("deliveries", __name__)

OPEN_STATES = ("DELIVERY_SCHEDULED", "DELIVERY_IN_TRANSIT")


def load_site(site_id):
    site = store.get_site(site_id)
    if site is None:
        raise ApiError(ERR_SITE_NOT_FOUND, "no site exists with that id", 404)
    return site


def load_delivery(site, delivery_id):
    delivery = store.get_delivery(delivery_id)
    if delivery is None or delivery.get("site_id") != site["id"]:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "no delivery exists at that site", 404)
    return delivery


def open_demands(site, exclude_id=None):
    return [d for d in store.site_deliveries(site["id"])
            if d.get("lifecycle_state") in OPEN_STATES and d.get("id") != exclude_id]


def select_ppa(site):
    """Candidate A: the earliest-created active contract at the site."""
    active = [p for p in store.by_created(store.site_ppas(site["id"]))
              if p.get("state") == "PPA_ACTIVE"]
    if active:
        return active[0]
    fallback = [p for p in store.by_created(store.site_ppas(site["id"]))
                if p.get("state") in ("PPA_DRAFT", "PPA_ACTIVE", "PPA_SUSPENDED")]
    return fallback[0] if fallback else None


def fill_candidates(delivery, site, volume):
    candidates = store.by_created(store.site_ppas(site["id"]))
    active = [p for p in candidates if p.get("state") == "PPA_ACTIVE"]
    selected = select_ppa(site)
    candidate_a = 0.0
    if active:
        candidate_a = float(volume) * float(active[0].get("contracted_efficiency_kwh_per_therm") or 0)
    others = [p for p in candidates if selected is None or p.get("id") != selected.get("id")]
    candidate_b = 0.0
    if others:
        smallest = min(others, key=lambda p: (int(p.get("contracted_kw") or 0), p.get("created_at") or ""))
        candidate_b = float(volume) * float(smallest.get("contracted_efficiency_kwh_per_therm") or 0)
    total_output = 0.0
    if selected is not None:
        total_output = float(volume) * float(selected.get("contracted_efficiency_kwh_per_therm") or 0)
    allocated_a = min(candidate_a, total_output)
    allocated_b = min(candidate_b, max(0.0, total_output - allocated_a))
    delivery["candidate_ppa_a_kwh"] = round(candidate_a, 4)
    delivery["candidate_ppa_b_kwh"] = round(candidate_b, 4)
    delivery["candidate_ppa_distance_km"] = C.CANDIDATE_PPA_DISTANCE_KM
    delivery["selected_ppa_id"] = selected["id"] if selected is not None else None
    delivery["allocated_ppa_a_kwh"] = round(allocated_a, 4)
    delivery["allocated_ppa_b_kwh"] = round(allocated_b, 4)
    delivery["active_candidate_demands_at_site"] = len(open_demands(site, delivery.get("id")))
    return selected


def windows_overlap(site, start_raw, end_raw, exclude_id=None):
    if not start_raw or not end_raw:
        return False
    start = store.parse_dt(start_raw)
    end = store.parse_dt(end_raw)
    for other in store.site_deliveries(site["id"]):
        if other.get("id") == exclude_id:
            continue
        if other.get("lifecycle_state") not in OPEN_STATES:
            continue
        if not other.get("hold_window_start_iso8601") or not other.get("hold_window_end_iso8601"):
            continue
        other_start = store.parse_dt(other["hold_window_start_iso8601"])
        other_end = store.parse_dt(other["hold_window_end_iso8601"])
        if start <= other_end and other_start <= end:
            return True
    return False


def check_attesting(site, customer_id):
    if not customer_id:
        return
    customer = store.get_customer(customer_id)
    if customer is None or customer.get("status") != "CUSTOMER_ACTIVE":
        raise ApiError(ERR_CUSTOMER_SOURCING_UNVERIFIED,
                       "the attesting customer is not active", 422)
    if not any(p.get("fuel_responsibility") == "CUSTOMER_SOURCED_GAS"
               for p in store.site_ppas(site["id"])):
        raise ApiError(ERR_CUSTOMER_SOURCING_UNVERIFIED,
                       "no contract at this site sources its own gas", 422)


def check_sourcing_config(sourcing_mode, index_rate, hedged):
    if sourcing_mode == "INDEXED_BLEND" and index_rate is None:
        raise ApiError(ERR_FUEL_SOURCING_MODE_INVALID,
                       "the indexed blend requires an index leg", 422)
    if sourcing_mode == "FIXED_PRICE_BLEND" and float(hedged if hedged is not None else 0) != 1.0:
        raise ApiError(ERR_FUEL_SOURCING_MODE_INVALID,
                       "the fixed-price blend requires a fully hedged fraction", 422)


@bp.route("/power/sites/<site_id>/fuel-deliveries", methods=["POST"])
def create_delivery(site_id):
    middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/fuel-deliveries"))
    site = load_site(site_id)
    body = Body(request.get_json(silent=True))
    sourcing = body.opt("sourcing_mode", "string", enum=C.SOURCING_MODES)
    volume = body.req("volume_therms", "number")
    index_rate = body.opt("index_rate_cents_per_therm", "number")
    fixed_price = body.opt("fixed_price_cents_per_therm", "number", default=0)
    hedged = body.opt("hedged_fraction", "number", default=0)
    attesting = body.opt("attesting_customer_id", "string")
    delivered_at = body.req("delivered_at", "string")
    confirm_after = body.req("confirm_after_iso8601", "string")
    window_start = body.opt("hold_window_start_iso8601", "string")
    window_end = body.opt("hold_window_end_iso8601", "string")
    expected_version = body.req("expected_site_version", "integer")

    if (window_start is None) != (window_end is None):
        raise ApiError(ERR_INVALID_REQUEST,
                       "the window boundaries are supplied together or not at all", 400)

    if volume is not None and len(open_demands(site)) >= C.MAX_ACTIVE_DEMANDS_PER_SITE:
        raise ApiError(ERR_SITE_DEMAND_LIMIT, "the site is at its commitment ceiling", 422)
    if volume is not None and float(volume) > float(site.get("draw_position_therms") or 0):
        raise ApiError(ERR_INSUFFICIENT_DRAW_POSITION, "the volume exceeds the draw position", 422)
    if attesting is not None:
        check_attesting(site, attesting)
    if windows_overlap(site, window_start, window_end):
        raise ApiError(ERR_DELIVERY_WINDOW_OVERLAP,
                       "the window overlaps an open delivery window", 422)
    if expected_version is not None and int(expected_version) != int(site.get("version") or 0):
        raise ApiError(ERR_STALE_VERSION, "the observed site version is stale", 412)
    body.raise_if_invalid()
    check_sourcing_config(sourcing, index_rate, hedged)

    delivery = {
        "site_id": site["id"],
        "sourcing_mode": sourcing,
        "volume_therms": volume,
        "index_rate_cents_per_therm": index_rate,
        "fixed_price_cents_per_therm": fixed_price,
        "hedged_fraction": hedged,
        "attesting_customer_id": attesting,
        "delivered_at": delivered_at,
        "confirm_after_iso8601": confirm_after,
        "lifecycle_state": "DELIVERY_SCHEDULED",
        "effective_commodity_rate_cents_per_therm": 0.0,
        "candidate_ppa_a_kwh": 0.0,
        "candidate_ppa_b_kwh": 0.0,
        "candidate_ppa_distance_km": 0.0,
        "selected_ppa_id": None,
        "allocated_ppa_a_kwh": 0.0,
        "allocated_ppa_b_kwh": 0.0,
        "active_candidate_demands_at_site": 0,
        "hold_window_start_iso8601": window_start,
        "hold_window_end_iso8601": window_end,
        "fuel_basis_rate_cents_per_therm": 0.0,
    }
    store.create(store.fuel_deliveries, delivery)
    delivery["effective_commodity_rate_cents_per_therm"] = calc.effective_commodity_rate(delivery, site)
    fill_candidates(delivery, site, volume)
    site["draw_position_therms"] = float(site.get("draw_position_therms") or 0) - float(volume)
    calc.recompute_site(site)
    store.touch(site)
    return middleware.ok(delivery, status=201)


@bp.route("/power/sites/<site_id>/fuel-deliveries", methods=["GET"])
def list_deliveries(site_id):
    middleware.authenticate(request.headers, ("GET", "/power/sites/{id}/fuel-deliveries"))
    site = load_site(site_id)
    rows = store.by_created(store.site_deliveries(site["id"]))
    for key in ("lifecycle_state", "attesting_customer_id", "selected_ppa_id"):
        wanted = request.args.get(key)
        if wanted:
            rows = [d for d in rows if d.get(key) == wanted]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/sites/<site_id>/fuel-deliveries/<delivery_id>", methods=["GET"])
def get_delivery(site_id, delivery_id):
    middleware.authenticate(request.headers, ("GET", "/power/sites/{id}/fuel-deliveries/{id}"))
    site = load_site(site_id)
    return middleware.ok(load_delivery(site, delivery_id))


@bp.route("/power/sites/<site_id>/fuel-deliveries/<delivery_id>/dispatch", methods=["POST"])
def dispatch_delivery(site_id, delivery_id):
    middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/fuel-deliveries/{id}/dispatch"))
    site = load_site(site_id)
    delivery = load_delivery(site, delivery_id)
    if delivery.get("lifecycle_state") != "DELIVERY_SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "the delivery is not scheduled", 409)
    if site.get("status") != "SITE_ACTIVE":
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)
    in_transit = [d for d in store.site_deliveries(site["id"])
                  if d.get("lifecycle_state") == "DELIVERY_IN_TRANSIT"]
    if len(in_transit) >= C.MAX_ACTIVE_DEMANDS_PER_SITE:
        raise ApiError(ERR_SITE_DEMAND_LIMIT, "the site is at its commitment ceiling", 422)
    delivery["lifecycle_state"] = "DELIVERY_IN_TRANSIT"
    store.touch(delivery)
    store.touch(site)
    return middleware.ok(delivery)


@bp.route("/power/sites/<site_id>/fuel-deliveries/<delivery_id>/confirm", methods=["POST"])
def confirm_delivery(site_id, delivery_id):
    middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/fuel-deliveries/{id}/confirm"))
    site = load_site(site_id)
    delivery = load_delivery(site, delivery_id)
    if delivery.get("lifecycle_state") != "DELIVERY_IN_TRANSIT":
        raise ApiError(ERR_INVALID_STATE, "the delivery is not in transit", 409)
    if store.clock() < store.parse_dt(delivery["confirm_after_iso8601"]):
        raise ApiError(ERR_CONFIRM_TOO_EARLY, "the confirmation gate has not passed", 422)
    if float(delivery.get("volume_therms") or 0) > float(site.get("draw_position_therms") or 0):
        raise ApiError(ERR_INSUFFICIENT_DRAW_POSITION, "the volume exceeds the draw position", 422)
    if delivery.get("attesting_customer_id"):
        check_attesting(site, delivery.get("attesting_customer_id"))

    rate = calc.effective_commodity_rate(delivery, site, frozen=True)
    delivery["lifecycle_state"] = "DELIVERY_CONFIRMED"
    delivery["fuel_basis_rate_cents_per_therm"] = rate
    delivery["effective_commodity_rate_cents_per_therm"] = rate
    store.touch(delivery)

    site["current_avoided_fuel_cost_cents_per_therm"] = calc.r4f(
        min(calc.D(rate), calc.D(site.get("gas_commodity_rate_cents_per_therm") or 0)
            * calc.D(C.SOURCED_INDEX_CEILING_MULTIPLE)))
    site["draw_position_therms"] = float(site.get("draw_position_therms") or 0)
    store.touch(site)

    selected = None
    if delivery.get("selected_ppa_id"):
        selected = store.get_ppa(delivery["selected_ppa_id"])
    if selected is not None:
        first_line = None
        for line in store.by_created(store.ppa_lines(selected["id"])):
            first_line = line
            break
        charge_amount = calc.r2(calc.D(delivery.get("volume_therms") or 0) * calc.D(rate))
        store.create(store.accruals, {
            "ppa_id": selected["id"],
            "site_id": site["id"],
            "source_settlement_line_id": first_line["id"] if first_line else None,
            "accrual_type": "CHARGE_ACCRUAL",
            "amount_cents": charge_amount,
            "lifecycle_state": "ACCRUAL_OPEN",
            "signed_amount_cents": charge_amount,
            "applied_allowance_id": None,
            "period_anchor_iso8601": delivery.get("delivered_at"),
        })
        shortfall = calc.availability_shortfall_kwh(selected, site)
        capacity_amount = calc.r2(calc.D(shortfall)
                                  * calc.D(selected.get("availability_penalty_cents_per_kwh") or 0))
        store.create(store.accruals, {
            "ppa_id": selected["id"],
            "site_id": site["id"],
            "source_settlement_line_id": None,
            "accrual_type": "CAPACITY_ACCRUAL",
            "amount_cents": capacity_amount,
            "lifecycle_state": "ACCRUAL_OPEN",
            "signed_amount_cents": capacity_amount,
            "applied_allowance_id": None,
            "period_anchor_iso8601": delivery.get("delivered_at"),
        })
        calc.recompute_ppa(selected)
    calc.recompute_site(site)
    return middleware.ok(delivery)


@bp.route("/power/sites/<site_id>/fuel-deliveries/<delivery_id>/cancel", methods=["POST"])
def cancel_delivery(site_id, delivery_id):
    middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/fuel-deliveries/{id}/cancel"))
    site = load_site(site_id)
    delivery = load_delivery(site, delivery_id)
    state = delivery.get("lifecycle_state")
    if state in ("DELIVERY_CANCELLED", "DELIVERY_SETTLED"):
        raise ApiError(ERR_ALREADY_TERMINAL, "the delivery is already terminal", 409)
    if state == "DELIVERY_IN_TRANSIT":
        if store.clock() >= store.parse_dt(delivery["confirm_after_iso8601"]):
            raise ApiError(ERR_INVALID_STATE, "the cancellation gate has closed", 409)
    elif state != "DELIVERY_SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "the delivery cannot be cancelled", 409)

    delivery["lifecycle_state"] = "DELIVERY_CANCELLED"
    store.touch(delivery)
    site["draw_position_therms"] = float(site.get("draw_position_therms") or 0) \
        + float(delivery.get("volume_therms") or 0)
    if int(site.get("active_ppa_count") or 0) == 0:
        site["lifecycle_state"] = "RESOURCE_AVAILABLE"
    calc.recompute_site(site)
    store.touch(site)
    return middleware.ok(delivery)


@bp.route("/power/sites/<site_id>/resource-holds", methods=["POST"])
def create_resource_hold(site_id):
    middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/resource-holds"))
    site = load_site(site_id)
    body = Body(request.get_json(silent=True))
    requested = body.req("requested_therms", "number")
    window_start = body.req("window_start_iso8601", "string")
    window_end = body.req("window_end_iso8601", "string")
    if site.get("status") != "SITE_ACTIVE":
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)
    if requested is not None and len(open_demands(site)) >= C.MAX_ACTIVE_DEMANDS_PER_SITE:
        raise ApiError(ERR_SITE_DEMAND_LIMIT, "the site is at its commitment ceiling", 422)
    if requested is not None and float(requested) > float(site.get("draw_position_therms") or 0):
        raise ApiError(ERR_INSUFFICIENT_DRAW_POSITION, "the volume exceeds the draw position", 422)
    if windows_overlap(site, window_start, window_end):
        raise ApiError(ERR_DELIVERY_WINDOW_OVERLAP,
                       "the window overlaps an open delivery window", 422)
    body.raise_if_invalid()

    delivery = {
        "site_id": site["id"],
        "sourcing_mode": "FIXED_PRICE_BLEND",
        "volume_therms": requested,
        "index_rate_cents_per_therm": None,
        "fixed_price_cents_per_therm": 0,
        "hedged_fraction": 1,
        "attesting_customer_id": None,
        "delivered_at": store.now_iso(),
        "confirm_after_iso8601": store.now_iso(),
        "lifecycle_state": "DELIVERY_SCHEDULED",
        "effective_commodity_rate_cents_per_therm": 0.0,
        "candidate_ppa_a_kwh": 0.0,
        "candidate_ppa_b_kwh": 0.0,
        "candidate_ppa_distance_km": 0.0,
        "selected_ppa_id": None,
        "allocated_ppa_a_kwh": 0.0,
        "allocated_ppa_b_kwh": 0.0,
        "active_candidate_demands_at_site": 0,
        "hold_window_start_iso8601": window_start,
        "hold_window_end_iso8601": window_end,
        "fuel_basis_rate_cents_per_therm": 0.0,
    }
    store.create(store.fuel_deliveries, delivery)
    delivery["effective_commodity_rate_cents_per_therm"] = calc.effective_commodity_rate(delivery, site)
    fill_candidates(delivery, site, requested)
    site["draw_position_therms"] = float(site.get("draw_position_therms") or 0) - float(requested)
    site["lifecycle_state"] = "RESOURCE_DRAWING"
    calc.recompute_site(site)
    store.touch(site)
    return middleware.ok(delivery, status=201)


@bp.route("/power/sites/<site_id>/release-resource-hold", methods=["POST"])
def release_resource_hold(site_id):
    middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/release-resource-hold"))
    site = load_site(site_id)
    body = Body(request.get_json(silent=True))
    delivery_id = body.req("delivery_id", "string")
    body.raise_now()
    delivery = store.get_delivery(delivery_id)
    if delivery is None or delivery.get("site_id") != site["id"]:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "no delivery exists at that site", 404)
    if delivery.get("lifecycle_state") != "DELIVERY_SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "the hold is not open", 409)
    delivery["lifecycle_state"] = "DELIVERY_CANCELLED"
    store.touch(delivery)
    site["draw_position_therms"] = float(site.get("draw_position_therms") or 0) \
        + float(delivery.get("volume_therms") or 0)
    if int(site.get("active_ppa_count") or 0) == 0:
        site["lifecycle_state"] = "RESOURCE_AVAILABLE"
    calc.recompute_site(site)
    store.touch(site)
    return middleware.ok(site)


@bp.route("/power/ppas/<ppa_id>/fuel-deliveries", methods=["GET"])
def list_ppa_deliveries(ppa_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/fuel-deliveries"))
    ppa = store.get_ppa(ppa_id)
    if ppa is None:
        raise ApiError(ERR_PPA_NOT_FOUND, "no contract exists with that id", 404)
    rows = store.by_created([d for d in store.fuel_deliveries.values()
                             if d.get("selected_ppa_id") == ppa["id"]])
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)
