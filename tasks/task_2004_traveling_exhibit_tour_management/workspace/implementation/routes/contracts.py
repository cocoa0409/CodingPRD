"""ParticipationContract endpoints (PRD §3.3)."""

from flask import Blueprint

import db
import system
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import contract_out
from validate import (json_body, req_int, get_tour, get_stop, paginate,
                      sorted_created)

bp = Blueprint("contracts", __name__)


@bp.route("/tours/<tour_id>/stops/<stop_id>/contract", methods=["POST"])
def create_contract(tour_id, stop_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    data = json_body()
    base_fee = req_int(data, "base_fee_cents")
    credit = req_int(data, "sponsorship_credit_cents")
    # One non-terminal contract per stop (business priority 12).
    if system.live_contract(stop["id"]) is not None:
        fail("ERR_DUPLICATE_CONTRACT",
             "Stop already has a non-terminal participation contract")
    contract = db.stamp_new({
        "id": db.new_id(),
        "tour_stop_id": stop["id"],
        "base_fee_cents": base_fee,
        "sponsorship_credit_cents": credit,
        "status": "DRAFT",
        "provisional_fee_cents": None,
        "final_fee_cents": None,
        "amount_paid_cents": 0,
    })
    db.contracts[contract["id"]] = contract
    return ok_object(contract_out(contract), status=201)


@bp.route("/tours/<tour_id>/stops/<stop_id>/contract", methods=["GET"])
def list_contracts(tour_id, stop_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    items = sorted_created(system.contracts_of_stop(stop["id"]))
    return paginate([contract_out(c) for c in items])


@bp.route("/tours/<tour_id>/stops/<stop_id>/contract/transition",
          methods=["POST"])
def contract_transition(tour_id, stop_id):
    require_roles("TourManager", "VenueRegistrar")
    tour = get_tour(tour_id)
    stop = get_stop(tour, stop_id)
    data = json_body()
    action = data.get("action")
    if action not in ("SEND", "REVOKE", "SIGN"):
        fail("ERR_INVALID_REQUEST", "Unrecognized action: %r" % action)
    # Action-level authorization: SEND/REVOKE are the manager's; SIGN belongs
    # to the VenueRegistrar alone.
    if action in ("SEND", "REVOKE"):
        require_roles("TourManager")
    else:
        require_roles("VenueRegistrar")

    contract = system.live_contract(stop["id"])
    if contract is None:
        fail("ERR_INVALID_STATE", "No non-terminal contract on this stop")

    if action == "SEND":
        if contract["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "SEND is only permitted from DRAFT")
        contract["provisional_fee_cents"] = \
            system.compute_provisional(contract, stop)
        contract["status"] = "SENT"
        db.touch(contract)
        return ok_object(contract_out(contract))

    if action == "REVOKE":
        if contract["status"] != "SENT":
            fail("ERR_INVALID_STATE", "REVOKE is only permitted from SENT")
        contract["status"] = "DRAFT"
        db.touch(contract)
        return ok_object(contract_out(contract))

    # SIGN
    if contract["status"] != "SENT":
        fail("ERR_INVALID_STATE", "SIGN is only permitted from SENT")
    venue = system.venue_of_stop(stop)
    if contract["sponsorship_credit_cents"] > venue["local_sponsorship_cap_cents"]:
        fail("ERR_SPONSORSHIP_OVER_CAP",
             "sponsorship_credit_cents exceeds the venue's sponsorship cap")
    contract["status"] = "SIGNED"
    db.touch(contract)
    if stop["status"] == "TENTATIVE":
        stop["status"] = "CONTRACTED"
        db.touch(stop)
    waiver = min(contract["sponsorship_credit_cents"],
                 contract["provisional_fee_cents"])
    tour["total_waived_cents"] += waiver
    db.touch(tour)
    return ok_object(contract_out(contract))
