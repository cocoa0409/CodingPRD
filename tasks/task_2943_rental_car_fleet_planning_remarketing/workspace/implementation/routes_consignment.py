"""Remarketing consignments: the forked disposal workflow (PRD 3.8)."""

from flask import Blueprint

import calc
import cascade
import serialize
import validate
from auth import ALL_ROLES, authorize
from envelope import created, ok
from errors import ApiError
from filters import collect
from store import base_row, store, touch

bp = Blueprint("consignment", __name__)

SALEABLE_CONDITIONS = ("SOUND", "RECONDITIONED")


def _open_damage(vehicle):
    return any(
        d["status"] in calc.OPEN_DAMAGE_STATUSES
        for d in calc.damage_events_of_vehicle(vehicle["id"])
    )


@bp.route("/fleet/consignments", methods=["POST"])
def create_consignment():
    actor, _role = authorize(("RemarketingManager",))
    payload = validate.body()

    vehicle = validate.body_fk(payload, "vehicle_id", "vehicle")
    channel = validate.body_fk(payload, "channel_id", "channel")

    validate.s_id(payload, "vehicle_id")
    validate.s_id(payload, "channel_id")
    expected = validate.s_int(payload, "expected_vehicle_version", ge=0)

    if expected != vehicle["version"]:
        raise ApiError(
            "ERR_STALE_VEHICLE_VERSION",
            "expected_vehicle_version %s does not match the vehicle's current version %s."
            % (expected, vehicle["version"]),
        )

    if vehicle["fleet_status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "Only an IN_SERVICE vehicle may be consigned.",
        )

    if _open_damage(vehicle):
        raise ApiError(
            "ERR_OPEN_DAMAGE_BLOCKS_LISTING",
            "A damage event on this vehicle is still REPORTED or RECOVERY_PENDING.",
        )

    if vehicle["condition_status"] not in SALEABLE_CONDITIONS:
        raise ApiError(
            "ERR_VEHICLE_INVALID_CONDITION_STATE",
            "The vehicle's condition_status must be SOUND or RECONDITIONED.",
        )

    days = calc.holding_days(vehicle)
    program = store.programs[vehicle["program_id"]]
    if channel["code"] == "PROGRAM_REPURCHASE" and channel["status"] == "ACTIVE":
        if program["program_type"] == "PROGRAM" and days < program["min_holding_days"]:
            raise ApiError(
                "ERR_MIN_HOLDING_PERIOD_NOT_MET",
                "The vehicle has held for %d days, below the program minimum." % days,
            )

    reason = calc.channel_eligibility(vehicle, channel, days)
    if reason is not None and reason != "MILEAGE":
        raise ApiError(
            "ERR_CHANNEL_NOT_ELIGIBLE",
            "The named channel is not in the vehicle's eligible pool.",
        )

    values = calc.valuation(vehicle)

    if reason == "MILEAGE":
        raise ApiError(
            "ERR_MILEAGE_BAND_EXCLUDES_CHANNEL",
            "The vehicle's odometer exceeds the segment's hard mileage limit for RETAIL_LOT.",
        )

    nbv = values["net_book_value_cents"]
    row = base_row()
    row.update({
        "vehicle_id": vehicle["id"],
        "channel_id": channel["id"],
        "created_by_user_id": actor,
        "settled_by_user_id": None,
        "floor_price_cents": calc.floor_price_cents(nbv),
        "recondition_authorized_cents": None,
        "recondition_actual_cents": None,
        "recondition_loaded_cents": None,
        "gross_proceeds_cents": None,
        "channel_fee_cents": None,
        "transport_to_channel_cents": None,
        "net_proceeds_cents": None,
        "gain_loss_cents": None,
        "listed_at": None,
        "settled_at": None,
        "status": "DRAFT",
    })
    store.consignments[row["id"]] = row

    vehicle["fleet_status"] = "HELD_FOR_SALE"
    vehicle["held_for_sale_at"] = store.now_iso()
    vehicle["net_book_value_at_hold_cents"] = nbv
    touch(vehicle)
    return created(serialize.consignment(row))


@bp.route("/fleet/consignments/<consignment_id>", methods=["GET"])
def read_consignment(consignment_id):
    authorize(ALL_ROLES)
    return ok(serialize.consignment(validate.load("consignment", consignment_id)))


@bp.route("/fleet/consignments", methods=["GET"])
def list_consignments():
    authorize(ALL_ROLES)
    return collect(
        store.consignments.values(),
        [
            ("vehicle_id", "vehicle_id", "str"),
            ("channel_id", "channel_id", "str"),
            ("status", "status", "str"),
        ],
        serialize.consignment,
    )


@bp.route("/fleet/consignments/<consignment_id>/authorize-recondition", methods=["POST"])
def authorize_recondition(consignment_id):
    authorize(("RemarketingManager",))
    consignment = validate.load("consignment", consignment_id)
    vehicle = store.vehicles[consignment["vehicle_id"]]
    payload = validate.body()

    amount = validate.s_int(payload, "recondition_authorized_cents", ge=0)

    if consignment["status"] != "DRAFT":
        raise ApiError(
            "ERR_CONSIGNMENT_INVALID_STATE",
            "Only a DRAFT consignment may authorize reconditioning.",
        )
    if vehicle["condition_status"] not in ("SOUND", "DAMAGE_REPORTED"):
        raise ApiError(
            "ERR_VEHICLE_INVALID_CONDITION_STATE",
            "Reconditioning may only start from condition SOUND or DAMAGE_REPORTED.",
        )

    segment = store.segments[vehicle["segment_id"]]
    if amount > segment["recondition_cap_cents"]:
        raise ApiError(
            "ERR_RECONDITION_CAP_EXCEEDED",
            "recondition_authorized_cents exceeds the segment's recondition_cap_cents.",
        )

    consignment["recondition_authorized_cents"] = amount
    consignment["status"] = "RECONDITION_PENDING"
    touch(consignment)
    vehicle["condition_status"] = "RECONDITIONING"
    touch(vehicle)
    return ok(serialize.consignment(consignment))


@bp.route("/fleet/consignments/<consignment_id>/complete-recondition", methods=["POST"])
def complete_recondition(consignment_id):
    authorize(("RemarketingManager",))
    consignment = validate.load("consignment", consignment_id)
    vehicle = store.vehicles[consignment["vehicle_id"]]
    payload = validate.body()

    amount = validate.s_int(payload, "recondition_actual_cents", ge=0)

    if consignment["status"] != "RECONDITION_PENDING":
        raise ApiError(
            "ERR_CONSIGNMENT_INVALID_STATE",
            "Only a RECONDITION_PENDING consignment may book a spend.",
        )
    if vehicle["condition_status"] != "RECONDITIONING":
        raise ApiError(
            "ERR_VEHICLE_INVALID_CONDITION_STATE",
            "The vehicle is not in condition RECONDITIONING.",
        )
    if amount > (consignment["recondition_authorized_cents"] or 0):
        raise ApiError(
            "ERR_RECONDITION_OVERRUN",
            "recondition_actual_cents exceeds the authorized budget.",
        )

    loaded = calc.recondition_loaded_cents(amount)
    consignment["recondition_actual_cents"] = amount
    consignment["recondition_loaded_cents"] = loaded
    # the consignment deliberately stays in RECONDITION_PENDING
    touch(consignment)

    cascade.post_ledger(
        vehicle["id"],
        "RECONDITION_COST",
        loaded,
        "Consignment",
        consignment["id"],
        "reconditioning spend loaded at 7.5 percent shop overhead",
    )
    vehicle["condition_status"] = "RECONDITIONED"
    touch(vehicle)
    return ok(serialize.consignment(consignment))


@bp.route("/fleet/consignments/<consignment_id>/list", methods=["POST"])
def publish_consignment(consignment_id):
    authorize(("RemarketingManager",))
    consignment = validate.load("consignment", consignment_id)
    vehicle = store.vehicles[consignment["vehicle_id"]]
    channel = store.channels[consignment["channel_id"]]

    if consignment["status"] not in ("DRAFT", "RECONDITION_PENDING"):
        raise ApiError(
            "ERR_CONSIGNMENT_INVALID_STATE",
            "Only a DRAFT or RECONDITION_PENDING consignment may be published.",
        )
    from_draft = consignment["status"] == "DRAFT"
    if from_draft and channel["recondition_required"]:
        raise ApiError(
            "ERR_CONSIGNMENT_INVALID_STATE",
            "The channel requires reconditioning, so the car cannot be listed from DRAFT.",
        )

    if _open_damage(vehicle):
        raise ApiError(
            "ERR_OPEN_DAMAGE_BLOCKS_LISTING",
            "A damage event on this vehicle is still REPORTED or RECOVERY_PENDING.",
        )

    if from_draft and vehicle["condition_status"] not in SALEABLE_CONDITIONS:
        raise ApiError(
            "ERR_VEHICLE_INVALID_CONDITION_STATE",
            "The vehicle's condition_status must be SOUND or RECONDITIONED.",
        )

    consignment["status"] = "LISTED"
    consignment["listed_at"] = store.now_iso()
    touch(consignment)
    return ok(serialize.consignment(consignment))


@bp.route("/fleet/consignments/<consignment_id>/record-sale", methods=["POST"])
def record_sale(consignment_id):
    authorize(("RemarketingManager",))
    consignment = validate.load("consignment", consignment_id)
    vehicle = store.vehicles[consignment["vehicle_id"]]
    channel = store.channels[consignment["channel_id"]]
    payload = validate.body()

    gross = validate.s_int(payload, "gross_proceeds_cents", ge=0)

    if consignment["status"] != "LISTED":
        raise ApiError(
            "ERR_CONSIGNMENT_INVALID_STATE",
            "Only a LISTED consignment may record a sale.",
        )
    if gross < consignment["floor_price_cents"]:
        raise ApiError(
            "ERR_PROCEEDS_BELOW_FLOOR",
            "gross_proceeds_cents is below the frozen floor_price_cents.",
        )

    market = store.markets[vehicle["current_market_id"]]
    consignment["gross_proceeds_cents"] = gross
    lines = calc.net_proceeds(consignment, channel, vehicle, market)
    consignment["channel_fee_cents"] = lines["channel_fee_cents"]
    consignment["transport_to_channel_cents"] = lines["transport_to_channel_cents"]
    consignment["net_proceeds_cents"] = lines["net_proceeds_cents"]
    consignment["gain_loss_cents"] = lines["gain_loss_cents"]
    consignment["status"] = "SOLD_PENDING_SETTLEMENT"
    touch(consignment)
    # no ledger line posts here: the four disposal rows post at settlement
    return ok(serialize.consignment(consignment))


@bp.route("/fleet/consignments/<consignment_id>/settle", methods=["POST"])
def settle_consignment(consignment_id):
    actor, _role = authorize(("RemarketingManager",))
    consignment = validate.load("consignment", consignment_id)
    vehicle = store.vehicles[consignment["vehicle_id"]]

    if consignment["status"] != "SOLD_PENDING_SETTLEMENT":
        raise ApiError(
            "ERR_CONSIGNMENT_INVALID_STATE",
            "Only a SOLD_PENDING_SETTLEMENT consignment may be settled.",
        )
    if actor == consignment["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The settling operator must differ from created_by_user_id.",
        )

    consignment["settled_by_user_id"] = actor
    consignment["settled_at"] = store.now_iso()
    consignment["status"] = "SETTLED"
    touch(consignment)

    for entry_type, amount, memo in (
        ("DISPOSAL_PROCEEDS", -consignment["gross_proceeds_cents"], "sale proceeds credited"),
        ("CHANNEL_FEE", consignment["channel_fee_cents"], "channel fee on the sale"),
        (
            "TRANSPORT_COST",
            consignment["transport_to_channel_cents"],
            "haul to the disposal channel",
        ),
        (
            "DISPOSAL_GAIN_LOSS",
            consignment["gain_loss_cents"],
            "gain or loss against the frozen hold value",
        ),
    ):
        cascade.post_ledger(
            vehicle["id"], entry_type, amount, "Consignment", consignment["id"], memo
        )

    vehicle["fleet_status"] = "SOLD"
    touch(vehicle)
    return ok(serialize.consignment(consignment))


@bp.route("/fleet/consignments/<consignment_id>/withdraw", methods=["POST"])
def withdraw_consignment(consignment_id):
    authorize(("RemarketingManager",))
    consignment = validate.load("consignment", consignment_id)
    vehicle = store.vehicles[consignment["vehicle_id"]]

    if consignment["status"] not in calc.NON_TERMINAL_CONSIGNMENT_STATUSES:
        raise ApiError(
            "ERR_CONSIGNMENT_INVALID_STATE",
            "A SOLD_PENDING_SETTLEMENT or SETTLED consignment may not be withdrawn.",
        )

    consignment["status"] = "WITHDRAWN"
    touch(consignment)

    if consignment["recondition_loaded_cents"] is not None:
        cascade.post_ledger(
            vehicle["id"],
            "RECONDITION_REVERSAL",
            -consignment["recondition_loaded_cents"],
            "Consignment",
            consignment["id"],
            "compensating reversal of the loaded reconditioning spend",
        )

    vehicle["fleet_status"] = "IN_SERVICE"
    vehicle["held_for_sale_at"] = None
    vehicle["net_book_value_at_hold_cents"] = None
    if vehicle["condition_status"] in ("RECONDITIONING", "RECONDITIONED"):
        vehicle["condition_status"] = "SOUND"
    touch(vehicle)
    return ok(serialize.consignment(consignment))
