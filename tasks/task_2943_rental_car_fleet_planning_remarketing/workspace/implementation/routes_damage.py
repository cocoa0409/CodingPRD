"""Damage events: reporting, revision, recovery waterfall and total loss (PRD 3.7)."""

from flask import Blueprint

import calc
import cascade
import serialize
import validate
from auth import ALL_ROLES, authorize, require_scope
from envelope import created, ok
from errors import ApiError
from filters import collect
from store import base_row, store, touch

bp = Blueprint("damage", __name__)

DAMAGE_TYPES = ("COLLISION", "HAIL", "VANDALISM", "MECHANICAL")
RECOVERY_SOURCES = ("CUSTOMER", "THIRD_PARTY_INSURER", "OWN_INSURANCE")
RETIRED_FLEET_STATUSES = ("SOLD", "TOTAL_LOSS")


@bp.route("/fleet/vehicles/<vehicle_id>/damage-events", methods=["POST"])
def report_damage(vehicle_id):
    actor, _role = authorize(("MarketOperator",))
    vehicle = validate.load("vehicle", vehicle_id)
    require_scope(actor, vehicle["current_market_id"])
    payload = validate.body()

    damage_type = validate.s_enum(payload, "damage_type", DAMAGE_TYPES)
    estimate_cents = validate.s_int(payload, "estimate_cents", gt=0)

    if vehicle["fleet_status"] in RETIRED_FLEET_STATUSES:
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "Damage cannot be reported on a SOLD or TOTAL_LOSS vehicle.",
        )
    if vehicle["condition_status"] not in ("SOUND", "RECONDITIONED"):
        raise ApiError(
            "ERR_VEHICLE_INVALID_CONDITION_STATE",
            "Damage may only be reported on a SOUND or RECONDITIONED vehicle.",
        )

    baseline = calc.valuation(vehicle)["net_book_value_cents"]

    row = base_row()
    row.update({
        "vehicle_id": vehicle["id"],
        "market_id": vehicle["current_market_id"],
        "damage_type": damage_type,
        "estimate_cents": estimate_cents,
        "net_book_value_at_report_cents": baseline,
        "total_loss_required": calc.total_loss_required(estimate_cents, baseline),
        "recovery_source": None,
        "recovered_cents": None,
        "recovery_alloc_recondition_cents": None,
        "recovery_alloc_depreciation_cents": None,
        "recovery_alloc_income_cents": None,
        "salvage_proceeds_cents": None,
        "total_loss_gain_loss_cents": None,
        "status": "REPORTED",
    })
    store.damage_events[row["id"]] = row

    vehicle["condition_status"] = "DAMAGE_REPORTED"
    touch(vehicle)
    return created(serialize.damage_event(row))


@bp.route("/fleet/damage-events/<damage_event_id>", methods=["GET"])
def read_damage_event(damage_event_id):
    authorize(ALL_ROLES)
    return ok(serialize.damage_event(validate.load("damage_event", damage_event_id)))


@bp.route("/fleet/damage-events", methods=["GET"])
def list_damage_events():
    authorize(ALL_ROLES)
    return collect(
        store.damage_events.values(),
        [
            ("vehicle_id", "vehicle_id", "str"),
            ("market_id", "market_id", "str"),
            ("damage_type", "damage_type", "str"),
            ("status", "status", "str"),
        ],
        serialize.damage_event,
    )


@bp.route("/fleet/damage-events/<damage_event_id>/revise-estimate", methods=["POST"])
def revise_estimate(damage_event_id):
    actor, _role = authorize(("MarketOperator",))
    event = validate.load("damage_event", damage_event_id)
    require_scope(actor, event["market_id"])
    vehicle = store.vehicles[event["vehicle_id"]]
    payload = validate.body()

    estimate_cents = validate.s_int(payload, "estimate_cents", gt=0)

    if event["status"] not in calc.OPEN_DAMAGE_STATUSES:
        raise ApiError(
            "ERR_DAMAGE_EVENT_INVALID_STATE",
            "Only a REPORTED or RECOVERY_PENDING event may be revised.",
        )
    if vehicle["fleet_status"] in RETIRED_FLEET_STATUSES:
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "The event's vehicle is SOLD or written off.",
        )

    event["estimate_cents"] = estimate_cents
    event["total_loss_required"] = calc.total_loss_required(
        estimate_cents, event["net_book_value_at_report_cents"]
    )
    touch(event)
    return ok(serialize.damage_event(event))


@bp.route("/fleet/damage-events/<damage_event_id>/open-recovery", methods=["POST"])
def open_recovery(damage_event_id):
    authorize(("RemarketingManager",))
    event = validate.load("damage_event", damage_event_id)
    payload = validate.body()

    source = validate.s_enum(payload, "recovery_source", RECOVERY_SOURCES)

    if event["status"] != "REPORTED":
        raise ApiError(
            "ERR_DAMAGE_EVENT_INVALID_STATE",
            "Only a REPORTED event may open a recovery.",
        )
    if event["total_loss_required"]:
        raise ApiError(
            "ERR_TOTAL_LOSS_DETERMINATION_REQUIRED",
            "The event requires a total-loss determination and cannot open a recovery.",
        )

    event["recovery_source"] = source
    event["status"] = "RECOVERY_PENDING"
    touch(event)
    return ok(serialize.damage_event(event))


@bp.route("/fleet/damage-events/<damage_event_id>/settle-recovery", methods=["POST"])
def settle_recovery(damage_event_id):
    authorize(("RemarketingManager",))
    event = validate.load("damage_event", damage_event_id)
    vehicle = store.vehicles[event["vehicle_id"]]
    payload = validate.body()

    recovered = validate.s_int(payload, "recovered_cents", ge=0)

    if event["status"] != "RECOVERY_PENDING":
        raise ApiError(
            "ERR_DAMAGE_EVENT_INVALID_STATE",
            "Only a RECOVERY_PENDING event may be settled.",
        )
    if recovered > calc.recovery_cap_cents(event["estimate_cents"]):
        raise ApiError(
            "ERR_RECOVERY_EXCEEDS_CAP",
            "recovered_cents exceeds 1.25 times the current estimate.",
        )

    recondition_total = calc.total_recondition_cents(vehicle)
    bucket_1, bucket_2, bucket_3 = calc.recovery_waterfall(
        recovered, recondition_total, event["estimate_cents"]
    )
    event["recovered_cents"] = recovered
    event["recovery_alloc_recondition_cents"] = bucket_1
    event["recovery_alloc_depreciation_cents"] = bucket_2
    event["recovery_alloc_income_cents"] = bucket_3
    event["status"] = "RECOVERED"
    touch(event)

    cascade.post_ledger(
        vehicle["id"],
        "DAMAGE_RECOVERY",
        -recovered,
        "DamageEvent",
        event["id"],
        "recovery waterfall recondition %d / depreciation %d / income %d"
        % (bucket_1, bucket_2, bucket_3),
    )
    cascade.damage_condition_cascade(vehicle)
    return ok(serialize.damage_event(event))


@bp.route("/fleet/damage-events/<damage_event_id>/write-off", methods=["POST"])
def write_off(damage_event_id):
    authorize(("FleetController",))
    event = validate.load("damage_event", damage_event_id)
    vehicle = store.vehicles[event["vehicle_id"]]

    if event["status"] not in calc.OPEN_DAMAGE_STATUSES:
        raise ApiError(
            "ERR_DAMAGE_EVENT_INVALID_STATE",
            "Only a REPORTED or RECOVERY_PENDING event may be written off.",
        )
    if event["total_loss_required"]:
        raise ApiError(
            "ERR_TOTAL_LOSS_DETERMINATION_REQUIRED",
            "The event requires a total-loss determination and cannot be written off.",
        )

    event["recovered_cents"] = 0
    event["recovery_alloc_recondition_cents"] = 0
    event["recovery_alloc_depreciation_cents"] = 0
    event["recovery_alloc_income_cents"] = 0
    event["status"] = "WRITTEN_OFF"
    touch(event)
    cascade.damage_condition_cascade(vehicle)
    return ok(serialize.damage_event(event))


@bp.route("/fleet/damage-events/<damage_event_id>/declare-total-loss", methods=["POST"])
def declare_total_loss(damage_event_id):
    authorize(("FleetController",))
    event = validate.load("damage_event", damage_event_id)
    vehicle = store.vehicles[event["vehicle_id"]]
    payload = validate.body()

    salvage = validate.s_int(payload, "salvage_proceeds_cents", ge=0)

    if event["status"] not in calc.OPEN_DAMAGE_STATUSES:
        raise ApiError(
            "ERR_DAMAGE_EVENT_INVALID_STATE",
            "Only a REPORTED or RECOVERY_PENDING event may declare a total loss.",
        )
    if vehicle["fleet_status"] in RETIRED_FLEET_STATUSES:
        raise ApiError(
            "ERR_VEHICLE_INVALID_FLEET_STATE",
            "A SOLD or already TOTAL_LOSS vehicle cannot be declared a total loss.",
        )
    if not event["total_loss_required"]:
        raise ApiError(
            "ERR_TOTAL_LOSS_NOT_APPLICABLE",
            "The ratio test did not require a total-loss determination.",
        )

    recovered = event["recovered_cents"] or 0
    gain_loss = salvage + recovered - event["net_book_value_at_report_cents"]
    event["salvage_proceeds_cents"] = salvage
    event["total_loss_gain_loss_cents"] = gain_loss
    event["status"] = "TOTAL_LOSS_DECLARED"
    touch(event)

    cascade.post_ledger(
        vehicle["id"],
        "SALVAGE_PROCEEDS",
        -salvage,
        "DamageEvent",
        event["id"],
        "salvage proceeds realised on the wreck",
    )
    cascade.post_ledger(
        vehicle["id"],
        "DISPOSAL_GAIN_LOSS",
        gain_loss,
        "DamageEvent",
        event["id"],
        "total loss gain or loss against the frozen book value",
    )
    cascade.total_loss_cascade(vehicle)
    return ok(serialize.damage_event(event))
