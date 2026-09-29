"""Corn purchase contracts, pricing, rolls, and scale-house deliveries."""
from decimal import Decimal

import calc
import derive
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from routes import bp
from shape import (enum_param, month_param, no_body, pagination, page,
                   require_auth, str_param, take)
from store import db, new_row, touch
from util import D, rhu

CONTRACT_SPEC = {
    "supplier_name": {"type": "string", "required": True},
    "delivery_month": {"type": "month", "required": True},
    "bushels_contracted": {"type": "dec", "required": True, "gt": 0, "places": 2},
    "basis_cents_per_bushel": {"type": "dec", "required": True, "places": 2},
}
PRICE_SPEC = {
    "futures_price_cents_per_bushel": {"type": "dec", "required": True, "gt": 0,
                                       "places": 2},
}
ROLL_SPEC = {
    "delivery_month": {"type": "month", "required": True},
    "roll_basis_adjustment_cents": {"type": "dec", "required": True, "places": 2},
}
DELIVERY_SPEC = {
    "ticket_number": {"type": "string", "required": True},
    "gross_weight_lbs": {"type": "int", "required": True, "gt": 0},
    "tare_weight_lbs": {"type": "int", "required": True, "ge": 0},
}
GRADE_SPEC = {
    "moisture_pct": {"type": "dec", "required": True, "ge": 0, "le": 40, "places": 2},
    "test_weight_lb_per_bu": {"type": "dec", "required": True, "gt": 0, "places": 1},
    "foreign_material_pct": {"type": "dec", "required": True, "ge": 0, "le": 20,
                             "places": 2},
    "damaged_kernels_pct": {"type": "dec", "required": True, "ge": 0, "le": 40,
                            "places": 2},
    "aflatoxin_ppb": {"type": "int", "required": True, "ge": 0},
}

CONTRACT_STATUSES = ("OPEN", "PARTIALLY_FILLED", "FILLED", "ROLLED")
PRICING_STATUSES = ("UNPRICED", "PRICED")
GRADING_STATUSES = ("PENDING_GRADE", "GRADED", "REJECTED", "SETTLED")

NULL_DELIVERY_FIGURES = {
    "moisture_pct": None,
    "test_weight_lb_per_bu": None,
    "foreign_material_pct": None,
    "damaged_kernels_pct": None,
    "aflatoxin_ppb": None,
    "rejection_reason": None,
    "gross_wet_bushels": None,
    "net_dry_bushels": None,
    "moisture_discount_cents": None,
    "test_weight_discount_cents": None,
    "foreign_material_discount_cents": None,
    "damage_discount_cents": None,
    "discount_cents_per_bushel": None,
    "net_price_cents_per_bushel": None,
    "settlement_amount_cents": None,
    "graded_by_user_id": None,
    "settled_by_user_id": None,
    "settled_at": None,
}


@bp.route("/corn-contracts", methods=["POST"])
def create_contract():
    require_auth(["GrainBuyer"])
    body = take(CONTRACT_SPEC)
    contract = new_row({
        "supplier_name": body["supplier_name"],
        "delivery_month": body["delivery_month"],
        "bushels_contracted": rhu(body["bushels_contracted"], 2),
        "basis_cents_per_bushel": rhu(body["basis_cents_per_bushel"], 2),
        "futures_price_cents_per_bushel": None,
        "pricing_status": "UNPRICED",
        "priced_at": None,
        "status": "OPEN",
        "rolled_from_contract_id": None,
        "roll_basis_adjustment_cents": None,
    })
    db.contracts[contract["id"]] = contract
    return ok(serialize.contract_out(contract), 201)


@bp.route("/corn-contracts/<contract_id>", methods=["GET"])
def get_contract(contract_id):
    require_auth(["PlantManager", "GrainBuyer", "GrainAccountant", "ScaleOperator",
                  "RiskManager"])
    contract = guards.get_contract(contract_id)
    return ok(serialize.contract_out(contract))


@bp.route("/corn-contracts", methods=["GET"])
def list_contracts():
    require_auth(["PlantManager", "GrainBuyer", "GrainAccountant", "RiskManager"])
    status = enum_param("status", CONTRACT_STATUSES)
    delivery_month = month_param("delivery_month")
    pricing_status = enum_param("pricing_status", PRICING_STATUSES)
    rolled_from = str_param("rolled_from_contract_id")
    limit, offset = pagination()
    if rolled_from is not None:
        guards.get_contract(rolled_from)
    rows = list(db.contracts.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if delivery_month is not None:
        rows = [r for r in rows if r["delivery_month"] == delivery_month]
    if pricing_status is not None:
        rows = [r for r in rows if r["pricing_status"] == pricing_status]
    if rolled_from is not None:
        rows = [r for r in rows if r["rolled_from_contract_id"] == rolled_from]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.contract_out(r) for r in window], limit, offset,
                   len(rows))


@bp.route("/corn-contracts/<contract_id>/price", methods=["POST"])
def price_contract(contract_id):
    require_auth(["GrainBuyer"])
    body = take(PRICE_SPEC)
    contract = guards.get_contract(contract_id)
    if contract["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        fail("ERR_INVALID_CONTRACT_STATE",
             "Contract is %s and may not be priced" % contract["status"])
    if contract["pricing_status"] != "UNPRICED":
        fail("ERR_CONTRACT_ALREADY_PRICED", "Contract is already priced")
    contract["futures_price_cents_per_bushel"] = rhu(
        body["futures_price_cents_per_bushel"], 2)
    contract["pricing_status"] = "PRICED"
    contract["priced_at"] = db.clock
    touch(contract)
    return ok(serialize.contract_out(contract))


@bp.route("/corn-contracts/<contract_id>/roll", methods=["POST"])
def roll_contract(contract_id):
    require_auth(["GrainBuyer"])
    body = take(ROLL_SPEC)
    contract = guards.get_contract(contract_id)
    if contract["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        fail("ERR_INVALID_CONTRACT_STATE",
             "Contract is %s and may not be rolled" % contract["status"])
    for delivery in db.deliveries.values():
        if (delivery["contract_id"] == contract["id"]
                and delivery["grading_status"] in ("PENDING_GRADE", "GRADED")):
            fail("ERR_CONTRACT_HAS_OPEN_DELIVERIES",
                 "Deliveries against this contract are still in flight")
    remainder = derive.contract_remainder(contract)
    if remainder <= 0:
        fail("ERR_CONTRACT_FULLY_DELIVERED",
             "Contract has no unfilled remainder to roll")
    successor = new_row({
        "supplier_name": contract["supplier_name"],
        "delivery_month": body["delivery_month"],
        "bushels_contracted": remainder,
        "basis_cents_per_bushel": rhu(
            D(contract["basis_cents_per_bushel"])
            + D(body["roll_basis_adjustment_cents"]), 2),
        "futures_price_cents_per_bushel": None,
        "pricing_status": "UNPRICED",
        "priced_at": None,
        "status": "OPEN",
        "rolled_from_contract_id": contract["id"],
        "roll_basis_adjustment_cents": rhu(body["roll_basis_adjustment_cents"], 2),
    })
    db.contracts[successor["id"]] = successor
    contract["status"] = "ROLLED"
    touch(contract)
    return ok(serialize.contract_out(successor), 201)


@bp.route("/corn-contracts/<contract_id>/deliveries", methods=["GET"])
def list_contract_deliveries(contract_id):
    require_auth(["PlantManager", "GrainBuyer", "ScaleOperator", "GrainAccountant"])
    grading_status = enum_param("grading_status", GRADING_STATUSES)
    limit, offset = pagination()
    contract = guards.get_contract(contract_id)
    rows = [d for d in db.deliveries.values() if d["contract_id"] == contract["id"]]
    if grading_status is not None:
        rows = [r for r in rows if r["grading_status"] == grading_status]
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.delivery_out(r) for r in window], limit, offset,
                   len(rows))


@bp.route("/corn-contracts/<contract_id>/deliveries", methods=["POST"])
def create_delivery(contract_id):
    require_auth(["ScaleOperator"])
    body = take(DELIVERY_SPEC)
    if body["tare_weight_lbs"] >= body["gross_weight_lbs"]:
        fail("ERR_VALIDATION",
             "tare_weight_lbs must be strictly less than gross_weight_lbs")
    contract = guards.get_contract(contract_id)
    guards.unique(db.deliveries, "ticket_number", body["ticket_number"])
    if contract["status"] == "ROLLED":
        fail("ERR_INVALID_CONTRACT_STATE",
             "Contract is ROLLED and accepts no further loads")
    delivered = derive.contract_bushels_delivered(contract["id"])
    if delivered >= D(contract["bushels_contracted"]):
        fail("ERR_CONTRACT_FULLY_DELIVERED",
             "Contract is already fully delivered")
    fields = dict(NULL_DELIVERY_FIGURES)
    fields.update({
        "contract_id": contract["id"],
        "ticket_number": body["ticket_number"],
        "gross_weight_lbs": body["gross_weight_lbs"],
        "tare_weight_lbs": body["tare_weight_lbs"],
        "grading_status": "PENDING_GRADE",
    })
    delivery = new_row(fields)
    db.deliveries[delivery["id"]] = delivery
    return ok(serialize.delivery_out(delivery), 201)


@bp.route("/corn-deliveries/<delivery_id>", methods=["GET"])
def get_delivery(delivery_id):
    require_auth(["PlantManager", "GrainBuyer", "ScaleOperator", "GrainAccountant"])
    delivery = guards.get_delivery(delivery_id)
    return ok(serialize.delivery_out(delivery))


def _recompute_delivery_money(delivery, contract):
    figures = calc.corn_delivery_settlement(
        delivery, contract["futures_price_cents_per_bushel"],
        contract["basis_cents_per_bushel"])
    return figures


@bp.route("/corn-deliveries/<delivery_id>/grade", methods=["POST"])
def grade_delivery(delivery_id):
    user_id, _role = require_auth(["ScaleOperator"])
    body = take(GRADE_SPEC)
    delivery = guards.get_delivery(delivery_id)
    if delivery["grading_status"] != "PENDING_GRADE":
        fail("ERR_INVALID_DELIVERY_STATE",
             "Delivery is %s and may not be graded" % delivery["grading_status"])
    contract = db.contracts[delivery["contract_id"]]

    delivery["moisture_pct"] = body["moisture_pct"]
    delivery["test_weight_lb_per_bu"] = body["test_weight_lb_per_bu"]
    delivery["foreign_material_pct"] = body["foreign_material_pct"]
    delivery["damaged_kernels_pct"] = body["damaged_kernels_pct"]
    delivery["aflatoxin_ppb"] = body["aflatoxin_ppb"]
    delivery["graded_by_user_id"] = user_id

    gross_wet, net_dry = calc.corn_delivery_weights(
        delivery["gross_weight_lbs"], delivery["tare_weight_lbs"],
        delivery["moisture_pct"])
    discounts = calc.corn_delivery_discounts(
        delivery["moisture_pct"], delivery["test_weight_lb_per_bu"],
        delivery["foreign_material_pct"], delivery["damaged_kernels_pct"])
    delivery["gross_wet_bushels"] = gross_wet
    delivery["net_dry_bushels"] = net_dry
    delivery.update(discounts)

    rejection = calc.grading_rejection(body["aflatoxin_ppb"], body["moisture_pct"])
    if rejection is not None:
        delivery["grading_status"] = "REJECTED"
        delivery["rejection_reason"] = rejection
        delivery["net_price_cents_per_bushel"] = None
        delivery["settlement_amount_cents"] = None
    else:
        delivery["grading_status"] = "GRADED"
        delivery["rejection_reason"] = None
        if contract["futures_price_cents_per_bushel"] is not None:
            figures = _recompute_delivery_money(delivery, contract)
            delivery["net_price_cents_per_bushel"] = figures[
                "net_price_cents_per_bushel"]
    touch(delivery)
    return ok(serialize.delivery_out(delivery))


@bp.route("/corn-deliveries/<delivery_id>/settle", methods=["POST"])
def settle_delivery(delivery_id):
    user_id, _role = require_auth(["GrainAccountant"])
    no_body()
    delivery = guards.get_delivery(delivery_id)
    if (delivery["graded_by_user_id"] is not None
            and delivery["graded_by_user_id"] == user_id):
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The settling operator must differ from the grading operator")
    if delivery["grading_status"] != "GRADED":
        fail("ERR_INVALID_DELIVERY_STATE",
             "Delivery is %s and may not be settled" % delivery["grading_status"])
    contract = db.contracts[delivery["contract_id"]]
    if contract["pricing_status"] != "PRICED":
        fail("ERR_CONTRACT_NOT_PRICED",
             "The parent contract must be PRICED before settlement")

    figures = _recompute_delivery_money(delivery, contract)
    delivery["net_price_cents_per_bushel"] = figures["net_price_cents_per_bushel"]
    delivery["settlement_amount_cents"] = figures["settlement_amount_cents"]
    delivery["grading_status"] = "SETTLED"
    delivery["settled_by_user_id"] = user_id
    delivery["settled_at"] = db.clock
    touch(delivery)

    delivered = derive.contract_bushels_delivered(contract["id"])
    if delivered >= D(contract["bushels_contracted"]):
        contract["status"] = "FILLED"
    elif delivered > 0:
        contract["status"] = "PARTIALLY_FILLED"
    touch(contract)
    return ok(serialize.delivery_out(delivery))
