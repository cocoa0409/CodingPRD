# Project orders routes (PRD 3.5, 3.6; scaffold Tables 2/5).
from datetime import timedelta

from flask import Blueprint, request

import authz
import calc
import clock
import constants
import envelope
import errors
import serialize
import state
import validate
from dealers import _new_entity
from phases import cancel_phase_cascade

bp = Blueprint("orders", __name__)


def _load_order(order_id):
    order = state.orders.get(order_id)
    if order is None:
        errors.not_found("ERR_ORDER_NOT_FOUND", "No project order with the given id")
    return order


def _check_agreement_usable(agreement):
    """Gate 19 (PRD 3.5): agreement ACTIVE and clock date inside its window."""
    calc.maybe_expire_agreement(agreement)
    if agreement["status"] != "ACTIVE" or not calc.agreement_in_window(agreement):
        errors.err("ERR_AGREEMENT_NOT_ACTIVE", 422,
                   "Agreement is not ACTIVE and inside its effective window")


@bp.post("/project-orders")
def create_order():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    body = validate.body_json(request)
    # Step 3: body FKs resolve in the PRD 2.9 listed order.
    agreement_id = body.get("volume_agreement_id")
    if isinstance(agreement_id, str) and agreement_id not in state.agreements:
        errors.not_found("ERR_AGREEMENT_NOT_FOUND", "No volume agreement with the given id")
    config_id = body.get("configuration_id")
    if isinstance(config_id, str) and config_id not in state.configurations:
        errors.not_found("ERR_CONFIGURATION_NOT_FOUND", "No configuration with the given id")
    # Step 4: a DealerRep may only reference their own configuration (PRD 2.1).
    spec = state.configurations.get(config_id) if isinstance(config_id, str) else None
    if spec is not None and spec["dealer_id"] != user_id:
        errors.forbidden_ownership()
    # Step 5: body shape.
    agreement_id = validate.req_str(body, "volume_agreement_id")
    config_id = validate.req_str(body, "configuration_id")
    territory_code = validate.req_str(body, "territory_code")
    install_date = validate.req_date(body, "requested_install_date")
    # Gate 19 at create (PRD 3.5).
    agreement = state.agreements[agreement_id]
    _check_agreement_usable(agreement)
    order = _new_entity({
        "dealer_id": user_id,
        "volume_agreement_id": agreement_id,
        "configuration_id": config_id,
        "configuration_revision": None,
        "territory_code": territory_code,
        "requested_install_date": install_date.isoformat(),
        "status": "DRAFT",
        "pre_discount_total_cents": None,
        "provisional_tier": None,
        "provisional_total_cents": None,
        "final_tier": None,
        "final_total_cents": None,
        "submitted_at": None,
        "acknowledged_at": None,
        "cancelled_at": None,
        "cancel_reason": None,
    })
    state.orders[order["id"]] = order
    return envelope.success_object(serialize.order(order), status=201)


@bp.get("/project-orders/<orderId>")
def get_order(orderId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin", "EndUserRep"))
    order = _load_order(orderId)
    authz.check_order_ownership(order, role, user_id)
    return envelope.success_object(serialize.order(order))


@bp.get("/project-orders")
def list_orders():
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin", "EndUserRep"))
    items = [o for o in state.orders.values()
             if authz.order_visible_to(o, role, user_id)]
    for param, field in (("dealer_id", "dealer_id"),
                         ("volume_agreement_id", "volume_agreement_id"),
                         ("configuration_id", "configuration_id"),
                         ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o[field] == value]
    page, total, limit, offset = envelope.paginate(items, request.args)
    return envelope.success_list(
        [serialize.order(o) for o in page], total, limit, offset)


@bp.post("/project-orders/<orderId>/submit")
def submit_order(orderId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep",))
    order = _load_order(orderId)
    authz.check_order_ownership(order, role, user_id)
    body = validate.body_json(request)
    expected = validate.req_int(body, "expected_order_version")
    # Gate order pinned by PRD 3.5: OCC, state, dealer, spec, territory,
    # capability, agreement, lead time.
    if expected != order["version"]:
        errors.stale_version()
    if order["status"] != "DRAFT":
        errors.invalid_state("Only a DRAFT order can be submitted")
    dealer = state.dealers.get(order["dealer_id"])
    if dealer is None:
        errors.not_found("ERR_DEALER_NOT_FOUND", "No dealer with the given id")
    if dealer["status"] != "ACTIVE":
        errors.err("ERR_DEALER_SUSPENDED", 409, "Dealer is SUSPENDED")
    spec = state.configurations.get(order["configuration_id"])
    if spec is None:
        errors.not_found("ERR_CONFIGURATION_NOT_FOUND",
                         "No configuration with the given id")
    if spec["status"] != "LOCKED":
        errors.err("ERR_SPEC_NOT_LOCKED", 409, "Configuration is not LOCKED")
    if order["territory_code"] not in dealer["territory_codes"]:
        errors.err("ERR_TERRITORY_NOT_AUTHORIZED", 422,
                   "Order territory_code is not in the dealer's territory_codes")
    for entry in spec["modules"]:
        category = constants.MODULE_FAMILY_CATEGORY[entry["module_type"]]
        required = constants.CAPABILITY_REQUIRED[category]
        if dealer["service_capability_level"] < required:
            errors.err("ERR_CAPABILITY_INSUFFICIENT", 422,
                       f"Dealer capability below required level for {category}")
    agreement = state.agreements.get(order["volume_agreement_id"])
    if agreement is None:
        errors.not_found("ERR_AGREEMENT_NOT_FOUND", "No volume agreement with the given id")
    _check_agreement_usable(agreement)
    today = clock.today()
    earliest = today + timedelta(days=spec["max_lead_time_days"])
    if calc._parse_date(order["requested_install_date"]) < earliest:
        errors.err("ERR_LEAD_TIME_VIOLATION", 422,
                   "requested_install_date is earlier than clock date + max_lead_time_days")
    # PROVISIONAL pricing: tier basis excludes this order (PRD 3.5 step 5).
    basis = calc.agreement_cumulative_cents(agreement["id"])
    pre_discount, tier, total = calc.price_order(spec["modules"], agreement, basis)
    order["pre_discount_total_cents"] = pre_discount
    order["provisional_tier"] = tier
    order["provisional_total_cents"] = total
    order["configuration_revision"] = spec["revision_number"]
    order["status"] = "SUBMITTED"
    order["submitted_at"] = clock.now_iso()
    state.touch(order)
    return envelope.success_object(serialize.order(order))


@bp.post("/project-orders/<orderId>/acknowledge")
def acknowledge_order(orderId):
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    order = _load_order(orderId)
    if order["status"] != "SUBMITTED":
        errors.invalid_state("Only a SUBMITTED order can be acknowledged")
    agreement = state.agreements.get(order["volume_agreement_id"])
    if agreement is None:
        errors.not_found("ERR_AGREEMENT_NOT_FOUND", "No volume agreement with the given id")
    spec = state.configurations.get(order["configuration_id"])
    # FINAL pricing: tier basis includes this order (PRD 3.5 step 5 FINAL variant).
    basis = calc.agreement_cumulative_cents(agreement["id"]) + order["pre_discount_total_cents"]
    _pre, tier, total = calc.price_order(spec["modules"], agreement, basis)
    order["final_tier"] = tier
    order["final_total_cents"] = total
    order["status"] = "ACKNOWLEDGED"
    order["acknowledged_at"] = clock.now_iso()
    state.touch(order)
    # Ledger debit happens implicitly: cumulative_volume_cents is derived on read
    # from ACKNOWLEDGED/CLOSED orders (PRD 3.2), so it now includes this order.
    return envelope.success_object(serialize.order(order))


@bp.post("/project-orders/<orderId>/cancel")
def cancel_order(orderId):
    role, user_id = authz.authenticate()
    authz.require_roles(role, ("DealerRep", "ManufacturerAdmin"))
    order = _load_order(orderId)
    authz.check_order_ownership(order, role, user_id)
    body = validate.body_json(request)
    reason = validate.opt_str(body, "reason")
    departing = order["status"]
    if departing not in ("DRAFT", "SUBMITTED", "ON_HOLD", "ACKNOWLEDGED"):
        errors.invalid_state(f"Cannot cancel an order in state {departing}")
    order["status"] = "CANCELLED"
    order["cancelled_at"] = clock.now_iso()
    order["cancel_reason"] = reason
    state.touch(order)
    if departing != "DRAFT":
        # Phase cancellation cascade (PRD 3.5/3.6). The ACKNOWLEDGED ledger
        # compensation is implicit: the order leaves the ACKNOWLEDGED set, so the
        # derived cumulative volume drops by this order's pre-discount total.
        for phase in list(state.phases.values()):
            if phase["project_order_id"] == order["id"]:
                cancel_phase_cascade(phase)
    return envelope.success_object(serialize.order(order))
