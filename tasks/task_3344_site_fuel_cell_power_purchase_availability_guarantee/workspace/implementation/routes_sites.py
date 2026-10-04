"""Site endpoints: registration, evaluation, posture and transfer."""

from flask import Blueprint, request

import calc
import constants as C
import middleware
import settle_calc
import store
import transitions
from errors import (
    ERR_CREDIT_TIER_INELIGIBLE, ERR_INVALID_STATE,
    ERR_PPA_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_SITE_NOT_FOUND,
    ERR_TRANSFER_BLOCKED, ApiError,
)
from fields import Body

bp = Blueprint("sites", __name__)

SITE_INPUTS = [
    "name", "utility_territory", "grid_tariff_rate_cents_per_kwh",
    "grid_outage_events_per_year", "grid_annual_outage_hours",
    "gas_commodity_rate_cents_per_therm", "expected_annual_site_load_kwh",
    "tax_rate_pct", "allowed_downtime_hours_per_year", "clearance_zone_capacity",
    "footprint_sqm", "standby_charge_cents_per_kw_month",
    "interconnect_exit_fee_cents_per_kw",
]


def load_site(site_id):
    site = store.get_site(site_id)
    if site is None:
        raise ApiError(ERR_SITE_NOT_FOUND, "no site exists with that id", 404)
    return site


def load_ppa_of_site(site, ppa_id):
    ppa = store.get_ppa(ppa_id)
    if ppa is None or ppa.get("site_id") != site["id"]:
        raise ApiError(ERR_PPA_NOT_FOUND, "no contract exists at that site", 404)
    return ppa


@bp.route("/power/sites", methods=["POST"])
def create_site():
    middleware.authenticate(request.headers, ("POST", "/power/sites"))
    body = Body(request.get_json(silent=True))
    site = {
        "name": body.req("name", "string"),
        "utility_territory": body.req("utility_territory", "string"),
        "grid_tariff_rate_cents_per_kwh": body.req("grid_tariff_rate_cents_per_kwh", "number"),
        "grid_outage_events_per_year": body.req("grid_outage_events_per_year", "integer"),
        "grid_annual_outage_hours": body.req("grid_annual_outage_hours", "number"),
        "gas_commodity_rate_cents_per_therm": body.req("gas_commodity_rate_cents_per_therm", "number"),
        "expected_annual_site_load_kwh": body.req("expected_annual_site_load_kwh", "integer"),
        "tax_rate_pct": body.req("tax_rate_pct", "number"),
        "allowed_downtime_hours_per_year": body.req("allowed_downtime_hours_per_year", "number"),
        "clearance_zone_capacity": body.req("clearance_zone_capacity", "number"),
        "footprint_sqm": body.req("footprint_sqm", "number"),
        "standby_charge_cents_per_kw_month": body.req("standby_charge_cents_per_kw_month", "number"),
        "interconnect_exit_fee_cents_per_kw": body.req("interconnect_exit_fee_cents_per_kw", "number"),
        "status": "SITE_ACTIVE",
        "lifecycle_state": "RESOURCE_AVAILABLE",
        "active_ppa_count": 0,
        "lifetime_customer_billable_cents": 0,
        "lifetime_availability_credit_cents": 0,
        "lifetime_settled_kwh": 0,
        "total_contracted_kw": 0,
        "contracted_purchase_cents": 0,
        "committed_feedstock_therms": 0,
        "initial_fuel_inventory_therms": C.INITIAL_FUEL_INVENTORY_THERMS,
        "draw_position_therms": C.INITIAL_FUEL_INVENTORY_THERMS,
        "current_avoided_fuel_cost_cents_per_therm": 0,
        "lifetime_settle_reconcile_count": 0,
        "reserved_capacity_hold_count": 0,
        "clearance_zone_used": 0,
    }
    body.raise_if_invalid()
    store.create(store.sites, site)
    calc.recompute_site(site)
    return middleware.ok(site, status=201)


@bp.route("/power/sites", methods=["GET"])
def list_sites():
    middleware.authenticate(request.headers, ("GET", "/power/sites"))
    rows = store.by_created(list(store.sites.values()))
    status = request.args.get("status")
    if status:
        rows = [s for s in rows if s.get("status") == status]
    lifecycle = request.args.get("lifecycle_state")
    if lifecycle:
        rows = [s for s in rows if s.get("lifecycle_state") == lifecycle]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/sites/<site_id>", methods=["GET"])
def get_site(site_id):
    middleware.authenticate(request.headers, ("GET", "/power/sites/{id}"))
    return middleware.ok(load_site(site_id))


@bp.route("/power/sites/<site_id>/ppas", methods=["GET"])
def list_site_ppas(site_id):
    middleware.authenticate(request.headers, ("GET", "/power/sites/{id}/ppas"))
    site = load_site(site_id)
    rows = store.by_created(store.site_ppas(site["id"]))
    state = request.args.get("state")
    if state:
        rows = [p for p in rows if p.get("state") == state]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/sites/<site_id>/evaluate", methods=["POST"])
def evaluate_site(site_id):
    middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/evaluate"))
    site = load_site(site_id)
    capacity = calc.site_exit_capacity(site)
    standby = calc.r2(capacity * (site.get("standby_charge_cents_per_kw_month") or 0)
                      * C.DEFAULT_STANDBY_MONTHS)
    exit_fee = calc.r2(capacity * (site.get("interconnect_exit_fee_cents_per_kw") or 0))
    fixed_consideration = calc.r2((site.get("committed_feedstock_therms") or 0)
                                  * (site.get("gas_commodity_rate_cents_per_therm") or 0))
    candidates = store.by_created(store.site_ppas(site["id"]))
    escalated = calc.current_escalated_rate(candidates[0]) if candidates else 0.0
    for ppa in candidates:
        calc.recompute_ppa(ppa)
    calc.recompute_site(site)
    store.touch(site)
    payload = {
        "standby_charge_cents": standby,
        "exit_fee_cents": exit_fee,
        "fixed_consideration_cents": fixed_consideration,
        "escalated_rate_cents_per_kwh": escalated,
        "fixed_consideration_status": "IN_SERVICE",
        "site_id": site["id"],
        "site_version": site["version"],
    }
    return middleware.ok(payload)


@bp.route("/power/sites/<site_id>/freeze", methods=["POST"])
def freeze_site(site_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/freeze"))
    site = load_site(site_id)
    if site.get("status") != "SITE_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "site is not active", 409)
    if not any(p.get("state") == "PPA_ACTIVE" for p in store.site_ppas(site["id"])):
        raise ApiError(ERR_INVALID_STATE, "site has no active contracts", 409)
    body = Body(request.get_json(silent=True))
    reason = body.req("reason", "string", enum=C.FREEZE_REASONS)
    body.raise_if_invalid()
    transitions.freeze(site, reason, role)
    return middleware.ok(site)


@bp.route("/power/sites/<site_id>/unfreeze", methods=["POST"])
def unfreeze_site(site_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/unfreeze"))
    site = load_site(site_id)
    transitions.unfreeze(site, role)
    return middleware.ok(site)


@bp.route("/power/sites/<site_id>/transfer-ppa", methods=["POST"])
def transfer_ppa(site_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/sites/{id}/transfer-ppa"))
    site = load_site(site_id)
    body = Body(request.get_json(silent=True))
    ppa_id = body.req("ppa_id", "string")
    accepting_id = body.req("accepting_customer_id", "string")
    transfer_basis = body.opt("transfer_basis", "string", enum=C.PPA_BASES)
    body.raise_now()
    ppa = load_ppa_of_site(site, ppa_id)
    accepting = store.get_customer(accepting_id)
    if accepting is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "no customer exists with that id", 404)
    if ppa.get("transfer_stage") == "TRANSFER_BLOCKED":
        raise ApiError(ERR_TRANSFER_BLOCKED, "contract is blocked from moving", 409)
    previous = store.get_customer(ppa.get("customer_id"))
    if previous is not None and previous.get("credit_tier") == "CREDIT_SUBSTANDARD" \
            and not previous.get("hold_armed"):
        raise ApiError(ERR_CREDIT_TIER_INELIGIBLE,
                       "a substandard customer may only transfer with an armed hold", 422)

    valuation = settle_calc.transfer_valuation(ppa, site)
    ppa["customer_id"] = accepting["id"]
    ppa["contract_basis"] = transfer_basis or "PPA_BASIS_TRANSFERRED"
    ppa["customer_earned_output_tokens"] = int(ppa.get("customer_earned_output_tokens") or 0) \
        + C.TRANSFER_TOKEN_GRANT
    calc.recompute_ppa(ppa)
    calc.recompute_customer(accepting)
    if previous is not None:
        calc.recompute_customer(previous)
        store.touch(previous)
    store.touch(ppa)
    store.touch(site)
    store.touch(accepting)
    payload = dict(ppa)
    payload["transfer_valuation"] = valuation
    for key, value in valuation.items():
        payload.setdefault(key, value)
    return middleware.ok(payload)
