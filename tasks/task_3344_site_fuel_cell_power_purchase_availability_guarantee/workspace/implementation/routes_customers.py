"""Customer endpoints: relationship posture and the renewal dimension."""

from flask import Blueprint, request

import calc
import constants as C
import middleware
import store
import transitions
from errors import (
    ERR_CUSTOMER_NOT_FOUND, ERR_INVALID_STATE, ERR_RENEWAL_STAGE_INVALID, ApiError,
)
from fields import Body

bp = Blueprint("customers", __name__)


def load_customer(customer_id):
    customer = store.get_customer(customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "no customer exists with that id", 404)
    return customer


@bp.route("/power/customers", methods=["POST"])
def create_customer():
    middleware.authenticate(request.headers, ("POST", "/power/customers"))
    body = Body(request.get_json(silent=True))
    customer = {
        "name": body.req("name", "string"),
        "industry_code": body.req("industry_code", "string"),
        "credit_tier": body.req("credit_tier", "string", enum=C.CREDIT_TIERS),
        "status": "CUSTOMER_ACTIVE",
        "renewal_stage": "RENEWAL_NONE",
        "outstanding_balance_cents": 0,
        "lifetime_settled_cents": 0,
        "lifetime_output_guarantee_credit_cents": 0,
        "lifetime_availability_credit_cents": 0,
        "active_ppa_count": 0,
        "earned_customer_tokens": 0,
        "spent_customer_tokens": 0,
        "exposure_hold_pct": 0.0,
        "hold_armed": False,
        "reconcile_cadence_slots": 0,
    }
    body.raise_if_invalid()
    store.create(store.customers, customer)
    calc.recompute_customer(customer)
    return middleware.ok(customer, status=201)


@bp.route("/power/customers", methods=["GET"])
def list_customers():
    middleware.authenticate(request.headers, ("GET", "/power/customers"))
    rows = store.by_created(list(store.customers.values()))
    for key in ("credit_tier", "status", "renewal_stage"):
        wanted = request.args.get(key)
        if wanted:
            rows = [c for c in rows if c.get(key) == wanted]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    middleware.authenticate(request.headers, ("GET", "/power/customers/{id}"))
    return middleware.ok(load_customer(customer_id))


@bp.route("/power/customers/<customer_id>/ppas", methods=["GET"])
def list_customer_ppas(customer_id):
    role, user_id = middleware.authenticate(request.headers, ("GET", "/power/customers/{id}/ppas"))
    customer = load_customer(customer_id)
    middleware.require_customer_scope(role, user_id, customer["id"])
    rows = store.by_created(store.customer_ppas(customer["id"]))
    state = request.args.get("state")
    if state:
        rows = [p for p in rows if p.get("state") == state]
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/customers/<customer_id>/fuel-deliveries", methods=["GET"])
def list_customer_deliveries(customer_id):
    middleware.authenticate(request.headers, ("GET", "/power/customers/{id}/fuel-deliveries"))
    customer = load_customer(customer_id)
    rows = store.by_created([d for d in store.fuel_deliveries.values()
                             if d.get("attesting_customer_id") == customer["id"]])
    page, meta = store.paginate(rows, request.args)
    return middleware.ok_list(page, meta)


@bp.route("/power/customers/<customer_id>/apply-exposure-hold", methods=["POST"])
def apply_exposure_hold(customer_id):
    role, _ = middleware.authenticate(
        request.headers, ("POST", "/power/customers/{id}/apply-exposure-hold"))
    customer = load_customer(customer_id)
    if customer.get("credit_tier") == "CREDIT_PRIME" \
            or float(customer.get("exposure_hold_pct") or 0) <= 0:
        raise ApiError("ERR_CREDIT_TIER_INELIGIBLE",
                       "an exposure hold may not be armed for this credit tier", 422)
    transitions.apply_exposure_hold(customer, role)
    return middleware.ok(customer)


@bp.route("/power/customers/<customer_id>/release-exposure-hold", methods=["POST"])
def release_exposure_hold(customer_id):
    role, _ = middleware.authenticate(
        request.headers, ("POST", "/power/customers/{id}/release-exposure-hold"))
    customer = load_customer(customer_id)
    transitions.release_exposure_hold(customer, role)
    return middleware.ok(customer)


@bp.route("/power/customers/<customer_id>/offer-renewal", methods=["POST"])
def offer_renewal(customer_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/customers/{id}/offer-renewal"))
    customer = load_customer(customer_id)
    if customer.get("status") != "CUSTOMER_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "customer is not active", 409)
    if int(customer.get("active_ppa_count") or 0) < 1:
        raise ApiError(ERR_INVALID_STATE, "customer holds no active contracts", 409)
    if customer.get("renewal_stage") not in ("RENEWAL_NONE", "RENEWAL_DECLINED"):
        raise ApiError(ERR_INVALID_STATE, "renewal review is already in progress", 409)
    customer["renewal_stage"] = "RENEWAL_OFFERED"
    calc.recompute_customer(customer)
    store.touch(customer)
    return middleware.ok(customer)


@bp.route("/power/customers/<customer_id>/accept-renewal", methods=["POST"])
def accept_renewal(customer_id):
    middleware.authenticate(request.headers, ("POST", "/power/customers/{id}/accept-renewal"))
    customer = load_customer(customer_id)
    if customer.get("renewal_stage") != "RENEWAL_OFFERED":
        raise ApiError(ERR_RENEWAL_STAGE_INVALID, "no renewal offer is outstanding", 409)
    customer["renewal_stage"] = "RENEWAL_ACCEPTED"
    calc.recompute_customer(customer)
    store.touch(customer)
    return middleware.ok(customer)


@bp.route("/power/customers/<customer_id>/decline-renewal", methods=["POST"])
def decline_renewal(customer_id):
    role, _ = middleware.authenticate(request.headers, ("POST", "/power/customers/{id}/decline-renewal"))
    customer = load_customer(customer_id)
    if customer.get("renewal_stage") != "RENEWAL_OFFERED":
        raise ApiError(ERR_RENEWAL_STAGE_INVALID, "no renewal offer is outstanding", 409)
    customer["renewal_stage"] = "RENEWAL_DECLINED"
    for ppa in store.customer_ppas(customer["id"]):
        if ppa.get("state") == "PPA_SUSPENDED":
            transitions.add_transition(ppa, "PPA_SUSPENDED", "PPA_SUSPENDED",
                                       "PPA_RENEWAL_REFUSED", role)
    calc.recompute_customer(customer)
    store.touch(customer)
    return middleware.ok(customer)
