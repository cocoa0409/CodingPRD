"""Contract endpoints: drafting, activation and the exit/renewal lifecycle."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import constants as C
import middleware
import store
import transitions
from errors import (
    ERR_CUSTOMER_NOT_FOUND, ERR_EFFICIENCY_INVALID, ERR_ESCALATOR_OUT_OF_RANGE,
    ERR_EXIT_WINDOW_CONFLICT, ERR_FOOTPRINT_EXCEEDED, ERR_INVALID_STATE,
    ERR_PPA_NOT_FOUND, ERR_SITE_FROZEN, ERR_SITE_NOT_FOUND,
    ERR_TERM_COMMITMENT_INVALID, ERR_TRANSFER_BLOCKED, ApiError,
)
from fields import Body

bp = Blueprint("ppas", __name__)


def load_ppa(ppa_id):
    ppa = store.get_ppa(ppa_id)
    if ppa is None:
        raise ApiError(ERR_PPA_NOT_FOUND, "no contract exists with that id", 404)
    return ppa


def load_site(site_id):
    site = store.get_site(site_id)
    if site is None:
        raise ApiError(ERR_SITE_NOT_FOUND, "no site exists with that id", 404)
    return site


def load_customer(customer_id):
    customer = store.get_customer(customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "no customer exists with that id", 404)
    return customer


def clearance_ok(site, extra_radius=0.0):
    capacity = float(site.get("clearance_zone_capacity") or 0)
    return calc.site_clearance_used(site) + float(extra_radius) <= capacity


def footprint_ok(site, extra_kw=0):
    capacity = float(site.get("footprint_sqm") or 0) * C.KW_PER_SQM
    return calc.site_contracted_capacity(site) + int(extra_kw) <= capacity


@bp.route("/power/ppas", methods=["POST"])
def create_ppa():
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/ppas"))
    body = Body(request.get_json(silent=True))
    site_id = body.req("site_id", "string")
    customer_id = body.req("customer_id", "string")
    body.raise_now()
    site = load_site(site_id)
    customer = load_customer(customer_id)

    term_years = body.req("term_years", "integer")
    contracted_kw = body.req("contracted_kw", "integer")
    efficiency = body.req("contracted_efficiency_kwh_per_therm", "number")
    annual_kwh = body.req("contracted_annual_kwh", "integer")
    tariff_base = body.req("tariff_base_cents_per_kwh", "number")
    escalator = body.req("escalator_pct", "number")
    fuel_adder = body.req("fuel_adder_cents_per_therm", "number")
    availability = body.req("guaranteed_availability_pct", "number")
    guaranteed_delivery = body.req("guaranteed_delivery_kwh", "integer")
    cure_days = body.req("customer_cure_deadline_days", "integer")
    fuel_responsibility = body.req("fuel_responsibility", "string", enum=C.FUEL_RESPONSIBILITIES)
    loss_floor = body.req("loss_floor_cents", "integer")
    reserve_pre = body.opt("capacity_reserve_pre_cents", "integer",
                           default=C.CAPACITY_RESERVE_PRE_DEFAULT_CENTS)

    if term_years is not None and term_years not in C.COMMITTED_TERMS:
        raise ApiError(ERR_TERM_COMMITMENT_INVALID, "term is not a committed term", 422)
    if contracted_kw is not None and contracted_kw <= 0:
        raise ApiError(ERR_EFFICIENCY_INVALID, "contracted capacity must be positive", 422)
    if efficiency is not None and efficiency <= 0:
        raise ApiError(ERR_EFFICIENCY_INVALID, "contracted efficiency must be positive", 422)
    if escalator is not None and (escalator < 0 or escalator > C.ESCALATOR_MAX_PCT):
        raise ApiError(ERR_ESCALATOR_OUT_OF_RANGE, "escalator is outside its interval", 422)
    body.raise_if_invalid()

    ppa = {
        "site_id": site["id"],
        "customer_id": customer["id"],
        "term_years": term_years,
        "contracted_kw": contracted_kw,
        "contracted_efficiency_kwh_per_therm": efficiency,
        "contracted_annual_kwh": annual_kwh,
        "tariff_base_cents_per_kwh": tariff_base,
        "escalator_pct": escalator,
        "fuel_adder_cents_per_therm": fuel_adder,
        "guaranteed_availability_pct": availability,
        "guaranteed_delivery_kwh": guaranteed_delivery,
        "customer_cure_deadline_days": cure_days,
        "fuel_responsibility": fuel_responsibility,
        "state": "PPA_DRAFT",
        "state_entered_at": store.now_iso(),
        "effective_tariff_cents_per_kwh": tariff_base,
        "purchase_price_cents_per_kwh": tariff_base,
        "availability_penalty_cents_per_kwh": calc.availability_penalty_rate(site),
        "effective_fuel_adder_cents_per_therm": calc.effective_fuel_adder(
            {"fuel_adder_cents_per_therm": fuel_adder}),
        "annual_customer_cost_cents": 0,
        "exit_fee_cents": 0,
        "realized_guarantee_credit_cents": 0,
        "lifetime_settled_kwh": 0,
        "lifetime_settled_cents": 0,
        "committed_kwh_remaining": 0,
        "customer_earned_ppa_tokens": 0,
        "customer_spent_ppa_tokens": 0,
        "customer_earned_output_tokens": 0,
        "customer_spent_output_tokens": 0,
        "contract_basis": "PPA_BASIS_AS_BUILT",
        "transfer_stage": "TRANSFER_NONE",
        "originating_ppa_id": None,
        "assigned_service_plan_id": None,
        "output_guarantee_reserve_cents": 0,
        "capacity_guarantee_reserve_cents": 0,
        "capacity_reserve_pre_cents": reserve_pre,
        "capacity_reserve_credits_cents": 0,
        "loss_floor_cents": loss_floor,
    }
    store.create(store.ppas, ppa)
    calc.recompute_ppa(ppa)
    calc.recompute_site(site)
    calc.recompute_customer(customer)
    store.touch(site)
    store.touch(customer)
    return middleware.ok(ppa, status=201)


@bp.route("/power/ppas", methods=["GET"])
def list_ppas():
    middleware.authenticate(request.headers, ("GET", "/power/ppas"))
    rows = store.by_created(list(store.ppas.values()))
    for key in ("site_id", "customer_id", "state", "assigned_service_plan_id", "originating_ppa_id"):
        wanted = request.args.get(key)
        if wanted:
            rows = [p for p in rows if p.get(key) == wanted]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/ppas/<ppa_id>", methods=["GET"])
def get_ppa(ppa_id):
    role, user_id = middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}"))
    ppa = load_ppa(ppa_id)
    if role == "Customer" and ppa.get("customer_id") != user_id:
        raise ApiError("ERR_UNAUTHORIZED", "customer may only read its own contracts", 403)
    return middleware.ok(ppa)


@bp.route("/power/ppas/<ppa_id>/transfers", methods=["GET"])
def list_transfers(ppa_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/transfers"))
    ppa = load_ppa(ppa_id)
    rows = store.by_created([p for p in store.ppas.values()
                             if p.get("originating_ppa_id") == ppa["id"]])
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/ppas/<ppa_id>/activate", methods=["POST"])
def activate_ppa(ppa_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/activate"))
    ppa = load_ppa(ppa_id)
    site = load_site(ppa["site_id"])
    customer = load_customer(ppa["customer_id"])
    if site.get("status") == "SITE_SUSPENDED":
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)
    if customer.get("status") != "CUSTOMER_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "customer is not active", 409)
    if ppa.get("state") != "PPA_DRAFT":
        raise ApiError(ERR_INVALID_STATE, "contract is not a draft", 409)
    if not clearance_ok(site):
        raise ApiError(ERR_FOOTPRINT_EXCEEDED, "clearance zone is exhausted", 422)
    # The contract being activated is still a draft, so it is already counted in
    # the site's contracted capacity; the test is a plain ceiling on that sum.
    if not footprint_ok(site, 0):
        raise ApiError(ERR_FOOTPRINT_EXCEEDED, "installation footprint is exceeded", 422)
    if ppa.get("term_years") not in C.COMMITTED_TERMS:
        raise ApiError(ERR_TERM_COMMITMENT_INVALID, "term is not a committed term", 422)
    transitions.activate(ppa, role)
    return middleware.ok(ppa)


@bp.route("/power/ppas/<ppa_id>/request-exit", methods=["POST"])
def request_exit(ppa_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/request-exit"))
    ppa = load_ppa(ppa_id)
    site = load_site(ppa["site_id"])
    if ppa.get("transfer_stage") == "TRANSFER_BLOCKED":
        raise ApiError(ERR_TRANSFER_BLOCKED, "contract is blocked from moving", 409)
    state = ppa.get("state")
    if state not in ("PPA_ACTIVE", "PPA_SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, "contract does not admit an exit request", 409)
    if state == "PPA_ACTIVE" and site.get("status") != "SITE_ACTIVE":
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)
    pending = [d for d in store.site_deliveries(site["id"])
               if d.get("lifecycle_state") in ("DELIVERY_SCHEDULED", "DELIVERY_IN_TRANSIT")]
    if pending:
        raise ApiError(ERR_INVALID_STATE, "fuel is already moving at this site", 409)
    if int(ppa.get("customer_cure_deadline_days") or 0) < 1:
        raise ApiError(ERR_INVALID_STATE, "a cure window of zero days is not admissible", 409)

    now = store.clock()
    deadline = now + timedelta(days=int(ppa.get("customer_cure_deadline_days") or 0))
    for plan in store.site_plans(site["id"]):
        if plan.get("ppa_id") == ppa["id"]:
            continue
        if not plan.get("window_start_iso8601") or not plan.get("window_end_iso8601"):
            continue
        start = store.parse_dt(plan["window_start_iso8601"])
        end = store.parse_dt(plan["window_end_iso8601"])
        if start < deadline and now < end:
            raise ApiError(ERR_EXIT_WINDOW_CONFLICT,
                           "a maintenance window overlaps the cure window", 422)
    transitions.request_exit(ppa, role)
    return middleware.ok(ppa)


@bp.route("/power/ppas/<ppa_id>/cure", methods=["POST"])
def cure_ppa(ppa_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/cure"))
    ppa = load_ppa(ppa_id)
    transitions.cure(ppa, role)
    return middleware.ok(ppa)


@bp.route("/power/ppas/<ppa_id>/terminate", methods=["POST"])
def terminate_ppa(ppa_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/terminate"))
    ppa = load_ppa(ppa_id)
    transitions.terminate(ppa, role)
    return middleware.ok(ppa)


@bp.route("/power/ppas/<ppa_id>/renew", methods=["POST"])
def renew_ppa(ppa_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/renew"))
    ppa = load_ppa(ppa_id)
    transitions.renew(ppa, role)
    return middleware.ok(ppa)


@bp.route("/power/ppas/<ppa_id>/adjust-contract", methods=["POST"])
def adjust_contract(ppa_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/adjust-contract"))
    ppa = load_ppa(ppa_id)
    site = load_site(ppa["site_id"])
    body = Body(request.get_json(silent=True))
    contracted_kw = body.req("contracted_kw", "integer")
    annual_kwh = body.req("contracted_annual_kwh", "integer")
    availability = body.req("guaranteed_availability_pct", "number")
    target_ppa_id = body.opt("target_ppa_id", "string")
    if contracted_kw is not None and contracted_kw <= 0:
        raise ApiError(ERR_EFFICIENCY_INVALID, "contracted capacity must be positive", 422)
    efficiency = ppa.get("contracted_efficiency_kwh_per_therm") or 0
    if efficiency <= 0:
        raise ApiError(ERR_EFFICIENCY_INVALID, "contracted efficiency must be positive", 422)
    body.raise_if_invalid()

    if contracted_kw is not None:
        ppa["contracted_kw"] = contracted_kw
    if annual_kwh is not None:
        ppa["contracted_annual_kwh"] = annual_kwh
    if availability is not None:
        ppa["guaranteed_availability_pct"] = availability

    netting = None
    if target_ppa_id:
        target = store.get_ppa(target_ppa_id)
        if target is None:
            raise ApiError("ERR_REFERENCE_NOT_FOUND", "no contract exists with that id", 404)
        target_settled = sum(int(ln.get("net_charge_cents") or 0) for ln in store.ppa_lines(target["id"])
                             if ln.get("status") == "SETTLEMENT_APPLIED")
        customer = store.get_customer(ppa["customer_id"])
        total_settled = 0
        if customer is not None:
            for owned in store.customer_ppas(customer["id"]):
                total_settled += sum(int(ln.get("net_charge_cents") or 0)
                                     for ln in store.ppa_lines(owned["id"])
                                     if ln.get("status") == "SETTLEMENT_APPLIED")
        first_line = None
        for line in store.by_created(store.ppa_lines(target["id"])):
            if line.get("status") == "SETTLEMENT_APPLIED":
                first_line = line
                break
        partition_a = int(first_line.get("net_charge_cents") or 0) if first_line else 0
        partition_b = total_settled - target_settled
        netting = min(partition_a, partition_b)

    calc.recompute_ppa(ppa)
    calc.recompute_site(site)
    store.touch(ppa)
    payload = dict(ppa)
    if netting is not None:
        payload["commitment_swap_netting_cents"] = netting
    return middleware.ok(payload)
