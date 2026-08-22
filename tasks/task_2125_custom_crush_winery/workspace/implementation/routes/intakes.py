"""The crush pad: weigh-in, sampling, acceptance and the marginal crush fee."""

from decimal import Decimal

from flask import Blueprint

import calc
import domain
from auth import ALL_ROLES, CELLAR_SUPERVISOR, guard, scope
from envelope import respond
from errors import (
    ApiError,
    ERR_CONTRACT_NOT_ACTIVE,
    ERR_DUPLICATE_DELIVERY_TICKET,
    ERR_OUTSIDE_CONTRACT_WINDOW,
)
from helpers import declared, run_list
from store import db, iso, new_entity, rhu, touch
from validation import bad, v_enum, v_number, v_string

D = Decimal
bp = Blueprint("intakes", __name__)

VARIETALS = {"CABERNET_SAUVIGNON", "MERLOT", "CHARDONNAY", "PINOT_NOIR", "ZINFANDEL"}
APPELLATIONS = {"NAPA_VALLEY", "RUTHERFORD", "OAKVILLE", "STAGS_LEAP",
                "HOWELL_MOUNTAIN"}
INTAKE_ACTIONS = {
    "SAMPLE": [CELLAR_SUPERVISOR],
    "ACCEPT": [CELLAR_SUPERVISOR],
    "REJECT": [CELLAR_SUPERVISOR],
}


@bp.route("/harvest-intakes", methods=["POST"])
def create_intake():
    ctx = guard([CELLAR_SUPERVISOR])
    body = ctx.body
    contract_id = v_string(body, "contract_id")
    ticket = v_string(body, "delivery_ticket")
    varietal = v_enum(body, "varietal", VARIETALS)
    appellation = v_enum(body, "appellation", APPELLATIONS)
    block_code = v_string(body, "block_code")
    gross = v_number(body, "gross_weight_lbs", gt=0)
    tare = v_number(body, "tare_weight_lbs", ge=0)
    if tare >= gross:
        bad("Field 'tare_weight_lbs' must be strictly less than 'gross_weight_lbs'.")

    domain.get_contract(contract_id)

    for existing in db.intakes.values():
        if existing["delivery_ticket"] == ticket:
            raise ApiError(ERR_DUPLICATE_DELIVERY_TICKET,
                           "Delivery ticket '%s' is already held." % ticket)

    now = db.now()
    intake = new_entity({
        "contract_id": contract_id,
        "lot_id": None,
        "delivery_ticket": ticket,
        "varietal": varietal,
        "appellation": appellation,
        "block_code": block_code,
        "gross_weight_lbs": gross,
        "tare_weight_lbs": tare,
        "net_weight_lbs": gross - tare,
        "brix": None,
        "ph": None,
        "estimated_gallons": D(0),
        "crush_fee_cents": 0,
        "received_at": iso(now),
        "status": "WEIGHED",
        "rejection_reason": None,
        "_received_dt": now,
    })
    db.intakes[intake["id"]] = intake
    return respond(domain.serialize(intake), 201)


@bp.route("/harvest-intakes/<intake_id>", methods=["GET"])
def read_intake(intake_id):
    ctx = guard(ALL_ROLES, read_body=False)
    intake = domain.get_intake(intake_id)
    scope(ctx, domain.intake_client_id(intake))
    return respond(domain.serialize(intake))


@bp.route("/harvest-intakes", methods=["GET"])
def list_intakes():
    ctx = guard(ALL_ROLES, read_body=False)
    return run_list(db.intakes.values(), ctx, domain.serialize,
                    owner_fn=domain.intake_client_id,
                    filters=(("contract_id", "contract_id"), ("lot_id", "lot_id"),
                             ("status", "status")))


@bp.route("/harvest-intakes/<intake_id>/transitions", methods=["POST"])
def intake_transitions(intake_id):
    ctx = guard([CELLAR_SUPERVISOR], INTAKE_ACTIONS)
    body = ctx.body
    action = v_enum(body, "action", set(INTAKE_ACTIONS))

    brix = ph = None
    rejection_reason = None
    if action == "SAMPLE":
        brix = v_number(body, "brix", ge=D("10.00"), le=D("35.00"), max_dp=2)
        ph = v_number(body, "ph", ge=D("2.50"), le=D("4.50"))
    elif action == "REJECT":
        rejection_reason = v_string(body, "rejection_reason", required=False,
                                    nullable=True)

    intake = domain.get_intake(intake_id)

    if action == "SAMPLE":
        declared(intake["status"] == "WEIGHED")
        intake["brix"] = brix
        intake["ph"] = ph
        intake["status"] = "SAMPLED"
        touch(intake)
    elif action == "REJECT":
        declared(intake["status"] in ("WEIGHED", "SAMPLED"))
        intake["rejection_reason"] = rejection_reason
        intake["status"] = "REJECTED"
        touch(intake)
    else:  # ACCEPT
        declared(intake["status"] == "SAMPLED")
        contract = db.contracts.get(intake["contract_id"])
        # Rung 40 -- the governing contract must be ACTIVE.
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError(ERR_CONTRACT_NOT_ACTIVE,
                           "The governing contract is not ACTIVE.")
        # Rung 65 -- the load must have landed inside the contract window.
        received = intake["_received_dt"]
        if received < contract["_eff_from_dt"] or received >= contract["_eff_to_dt"]:
            raise ApiError(ERR_OUTSIDE_CONTRACT_WINDOW,
                           "received_at falls outside the contract's window.")

        net = D(intake["net_weight_lbs"])
        intake["estimated_gallons"] = calc.intake_yield(net, D(intake["brix"]))
        load_tons = calc.tons_from_lbs(net)
        intake["crush_fee_cents"] = calc.crush_fee(
            D(contract["tons_received"]), load_tons,
            contract["crush_rate_cents_per_ton"])
        intake["status"] = "ACCEPTED"
        touch(intake)

        contract["tons_received"] = rhu(D(contract["tons_received"]) + load_tons, 4)
        contract["billed_total_cents"] = (contract["billed_total_cents"]
                                          + intake["crush_fee_cents"])
        touch(contract)

    return respond(domain.serialize(intake))
