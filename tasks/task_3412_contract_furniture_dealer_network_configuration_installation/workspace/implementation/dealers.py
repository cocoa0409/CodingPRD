# Dealers + EndUsers routes (PRD 3.1, 3.2; scaffold Tables 2/5).
from flask import Blueprint, request

import authz
import clock
import constants
import envelope
import errors
import serialize
import state
import validate

bp = Blueprint("dealers", __name__)


def _new_entity(fields):
    now = clock.now_iso()
    entity = {
        "id": state.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": state.next_seq(),
    }
    entity.update(fields)
    return entity


def _cascade_dealer_suspended(dealer):
    """CASCADE link 1 (PRD 3.1): every SUBMITTED order of this dealer -> ON_HOLD."""
    for order in state.orders.values():
        if order["dealer_id"] == dealer["id"] and order["status"] == "SUBMITTED":
            order["status"] = "ON_HOLD"
            state.touch(order)


def _cascade_dealer_reinstated(dealer):
    """CASCADE link 1 reversed (PRD 3.1): ON_HOLD orders return to SUBMITTED."""
    for order in state.orders.values():
        if order["dealer_id"] == dealer["id"] and order["status"] == "ON_HOLD":
            order["status"] = "SUBMITTED"
            state.touch(order)


@bp.post("/dealers")
def create_dealer():
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    body = validate.body_json(request)
    name = validate.req_str(body, "name")
    territory_codes = validate.req_territory_codes(body, "territory_codes")
    capability = validate.req_int(body, "service_capability_level")
    if not (1 <= capability <= 5):
        errors.validation("service_capability_level must be in 1..5")
    showroom = validate.opt_bool(body, "showroom_compliant", True)
    if showroom is None:
        showroom = True
    dealer = _new_entity({
        "name": name,
        "territory_codes": territory_codes,
        "service_capability_level": capability,
        "showroom_compliant": showroom,
        "status": "ACTIVE",
        "suspended_at": None,
    })
    state.dealers[dealer["id"]] = dealer
    return envelope.success_object(serialize.dealer(dealer), status=201)


@bp.patch("/dealers/<dealerId>")
def update_dealer(dealerId):
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    dealer = state.dealers.get(dealerId)
    if dealer is None:
        errors.not_found("ERR_DEALER_NOT_FOUND", "No dealer with the given id")
    body = validate.body_json(request)
    # Body shape (step 5): validate every field present in the payload.
    new_capability = None
    if "service_capability_level" in body and body["service_capability_level"] is not None:
        new_capability = body["service_capability_level"]
        if not validate.is_int(new_capability) or not (1 <= new_capability <= 5):
            errors.validation("service_capability_level must be an integer in 1..5")
    new_territories = None
    if "territory_codes" in body and body["territory_codes"] is not None:
        new_territories = validate.req_territory_codes(body, "territory_codes")
    new_showroom = None
    if "showroom_compliant" in body and body["showroom_compliant"] is not None:
        new_showroom = validate.req_bool(body, "showroom_compliant")
    new_status = None
    if "status" in body and body["status"] is not None:
        new_status = body["status"]
        if not validate.is_str(new_status) or new_status not in constants.DEALER_STATUSES:
            errors.validation("status must be ACTIVE or SUSPENDED")

    # State transitions (PRD 3.1): evaluate against status after showroom change.
    effective_showroom = dealer["showroom_compliant"] if new_showroom is None else new_showroom
    transition = None
    if new_status == "SUSPENDED":
        if dealer["status"] != "ACTIVE":
            errors.invalid_state("Dealer must be ACTIVE to suspend")
        transition = "suspend"
    elif new_status == "ACTIVE":
        if dealer["status"] != "SUSPENDED":
            errors.invalid_state("Dealer must be SUSPENDED to reinstate")
        if not effective_showroom:
            errors.invalid_state(
                "Dealer cannot be reinstated while showroom_compliant is false")
        transition = "reinstate"
    elif (new_showroom is False and dealer["showroom_compliant"] is True
          and dealer["status"] == "ACTIVE"):
        # Showroom violation auto-suspends even when status is absent (PRD 3.1).
        transition = "suspend"

    if new_capability is not None:
        dealer["service_capability_level"] = new_capability
    if new_territories is not None:
        dealer["territory_codes"] = new_territories
    if new_showroom is not None:
        dealer["showroom_compliant"] = new_showroom
    if transition == "suspend":
        dealer["status"] = "SUSPENDED"
        dealer["suspended_at"] = clock.now_iso()
    elif transition == "reinstate":
        dealer["status"] = "ACTIVE"
        dealer["suspended_at"] = None
    state.touch(dealer)
    if transition == "suspend":
        _cascade_dealer_suspended(dealer)
    elif transition == "reinstate":
        _cascade_dealer_reinstated(dealer)
    return envelope.success_object(serialize.dealer(dealer))


@bp.post("/end-users")
def create_end_user():
    role, _uid = authz.authenticate()
    authz.require_roles(role, ("ManufacturerAdmin",))
    body = validate.body_json(request)
    name = validate.req_str(body, "name")
    industry = validate.req_str(body, "industry")
    end_user = _new_entity({"name": name, "industry": industry})
    state.end_users[end_user["id"]] = end_user
    return envelope.success_object(serialize.end_user(end_user), status=201)
