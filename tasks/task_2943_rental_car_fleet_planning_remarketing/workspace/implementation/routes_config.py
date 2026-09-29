"""Reference configuration owned by PlatformAdmin, plus the logical clock."""

import re

from flask import Blueprint

import serialize
import validate
from auth import ALL_ROLES, authorize
from envelope import created, ok
from errors import ApiError
from filters import collect
from store import base_row, store, touch

bp = Blueprint("config", __name__)

MARKET_CODE_RE = re.compile(r"^[A-Z]{3,5}$")
REGIONS = ("EAST", "CENTRAL", "WEST")
CHANNEL_CODES = ("AUCTION", "RETAIL_LOT", "DEALER_DIRECT", "PROGRAM_REPURCHASE")
PROGRAM_TYPES = ("PROGRAM", "RISK")


# ===================== logical clock =====================================


@bp.route("/fleet/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authorize(("PlatformAdmin",))
    payload = validate.body()
    raw, parsed = validate.s_instant(payload, "current_utc")
    store.set_clock(parsed, raw)
    return ok({"current_utc": store.clock_raw})


@bp.route("/fleet/_clock", methods=["GET"])
def read_clock():
    authorize(ALL_ROLES)
    return ok({"current_utc": store.clock_raw})


# ===================== Market ============================================


@bp.route("/fleet/markets", methods=["POST"])
def create_market():
    authorize(("PlatformAdmin",))
    payload = validate.body()
    code = validate.s_str(payload, "code", pattern=MARKET_CODE_RE)
    name = validate.s_str(payload, "name")
    region = validate.s_enum(payload, "region", REGIONS)
    hub_distance = validate.s_int(payload, "transport_hub_distance_km", ge=0)
    transfer_rate = validate.s_int(payload, "transfer_cost_per_km_cents", gt=0)
    storage = validate.s_int(payload, "storage_cost_per_day_cents", ge=0)
    prep_capacity = validate.s_int(payload, "prep_capacity_per_day", ge=1)
    lead_days = validate.s_int(payload, "registration_lead_days", ge=0)

    if any(row["code"] == code for row in store.markets.values()):
        raise ApiError(
            "ERR_DUPLICATE_MARKET_CODE",
            "A market with code '%s' already exists." % code,
        )

    row = base_row()
    row.update({
        "code": code,
        "name": name,
        "region": region,
        "transport_hub_distance_km": hub_distance,
        "transfer_cost_per_km_cents": transfer_rate,
        "storage_cost_per_day_cents": storage,
        "prep_capacity_per_day": prep_capacity,
        "registration_lead_days": lead_days,
        "status": "ACTIVE",
    })
    store.markets[row["id"]] = row
    return created(serialize.market(row))


@bp.route("/fleet/markets/<market_id>", methods=["GET"])
def read_market(market_id):
    authorize(ALL_ROLES)
    return ok(serialize.market(validate.load("market", market_id)))


@bp.route("/fleet/markets", methods=["GET"])
def list_markets():
    authorize(ALL_ROLES)
    return collect(
        store.markets.values(),
        [("region", "region", "str"), ("status", "status", "str"), ("code", "code", "str")],
        serialize.market,
    )


@bp.route("/fleet/markets/<market_id>/suspend", methods=["POST"])
def suspend_market(market_id):
    authorize(("PlatformAdmin",))
    market = validate.load("market", market_id)
    if market["status"] != "ACTIVE":
        raise ApiError("ERR_MARKET_SUSPENDED", "The market is already SUSPENDED.")
    market["status"] = "SUSPENDED"
    touch(market)
    return ok(serialize.market(market))


# ===================== VehicleSegment ====================================


@bp.route("/fleet/vehicle-segments", methods=["POST"])
def create_segment():
    authorize(("PlatformAdmin",))
    payload = validate.body()
    code = validate.s_str(payload, "code")
    if code != code.upper():
        raise ApiError("ERR_INVALID_REQUEST", "Field 'code' must be uppercase.")
    name = validate.s_str(payload, "name")
    daily_rate = validate.s_int(payload, "baseline_daily_rate_cents", gt=0)
    utilization = validate.s_num(payload, "target_utilization_pct", gt=0, le=1)
    revenue_target = validate.s_int(payload, "target_revenue_per_unit_month_cents", gt=0)
    soft_limit = validate.s_int(payload, "mileage_band_soft_limit_km", gt=0)
    hard_limit = validate.s_int(payload, "mileage_band_hard_limit_km", gt=0)
    cap = validate.s_int(payload, "recondition_cap_cents", ge=0)
    if hard_limit <= soft_limit:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'mileage_band_hard_limit_km' must be greater than "
            "'mileage_band_soft_limit_km'.",
        )

    if any(row["code"] == code for row in store.segments.values()):
        raise ApiError(
            "ERR_DUPLICATE_SEGMENT_CODE",
            "A vehicle segment with code '%s' already exists." % code,
        )

    row = base_row()
    row.update({
        "code": code,
        "name": name,
        "baseline_daily_rate_cents": daily_rate,
        "target_utilization_pct": utilization,
        "target_revenue_per_unit_month_cents": revenue_target,
        "mileage_band_soft_limit_km": soft_limit,
        "mileage_band_hard_limit_km": hard_limit,
        "recondition_cap_cents": cap,
    })
    store.segments[row["id"]] = row
    return created(serialize.segment(row))


@bp.route("/fleet/vehicle-segments/<segment_id>", methods=["GET"])
def read_segment(segment_id):
    authorize(ALL_ROLES)
    return ok(serialize.segment(validate.load("segment", segment_id)))


@bp.route("/fleet/vehicle-segments", methods=["GET"])
def list_segments():
    authorize(ALL_ROLES)
    return collect(store.segments.values(), [("code", "code", "str")], serialize.segment)


# ===================== ManufacturerProgram ===============================


@bp.route("/fleet/manufacturer-programs", methods=["POST"])
def create_program():
    authorize(("PlatformAdmin",))
    payload = validate.body()
    manufacturer = validate.s_str(payload, "manufacturer_name")
    year = validate.s_int(payload, "program_year", gt=0)
    program_type = validate.s_enum(payload, "program_type", PROGRAM_TYPES)
    guarantee = validate.s_num(payload, "repurchase_guarantee_pct", ge=0, le=1)
    min_days = validate.s_int(payload, "min_holding_days", ge=0)
    max_days = validate.s_int(payload, "max_holding_days", ge=0)
    max_mileage = validate.s_int(payload, "max_eligible_mileage_km", gt=0)
    excess_charge = validate.s_int(payload, "excess_mileage_charge_cents_per_km", ge=0)
    damage_cap = validate.s_int(payload, "damage_deduction_cap_cents", ge=0)
    if max_days <= min_days:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'max_holding_days' must be greater than 'min_holding_days'.",
        )
    if program_type == "RISK" and guarantee != 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'repurchase_guarantee_pct' must be exactly 0 for a RISK program.",
        )

    row = base_row()
    row.update({
        "manufacturer_name": manufacturer,
        "program_year": year,
        "program_type": program_type,
        "repurchase_guarantee_pct": guarantee,
        "min_holding_days": min_days,
        "max_holding_days": max_days,
        "max_eligible_mileage_km": max_mileage,
        "excess_mileage_charge_cents_per_km": excess_charge,
        "damage_deduction_cap_cents": damage_cap,
        "status": "ACTIVE",
    })
    store.programs[row["id"]] = row
    return created(serialize.program(row))


@bp.route("/fleet/manufacturer-programs/<program_id>", methods=["GET"])
def read_program(program_id):
    authorize(ALL_ROLES)
    return ok(serialize.program(validate.load("program", program_id)))


@bp.route("/fleet/manufacturer-programs", methods=["GET"])
def list_programs():
    authorize(ALL_ROLES)
    return collect(
        store.programs.values(),
        [
            ("program_type", "program_type", "str"),
            ("program_year", "program_year", "int"),
            ("status", "status", "str"),
        ],
        serialize.program,
    )


@bp.route("/fleet/manufacturer-programs/<program_id>/close", methods=["POST"])
def close_program(program_id):
    authorize(("PlatformAdmin",))
    program = validate.load("program", program_id)
    if program["status"] != "ACTIVE":
        raise ApiError("ERR_PROGRAM_CLOSED", "The program is already CLOSED.")
    program["status"] = "CLOSED"
    touch(program)
    return ok(serialize.program(program))


# ===================== RemarketingChannel ================================


@bp.route("/fleet/remarketing-channels", methods=["POST"])
def create_channel():
    authorize(("PlatformAdmin",))
    payload = validate.body()
    code = validate.s_enum(payload, "code", CHANNEL_CODES)
    name = validate.s_str(payload, "name")
    fee_pct = validate.s_num(payload, "fee_pct", ge=0, lt=1)
    fixed_fee = validate.s_int(payload, "fixed_fee_cents", ge=0)
    days_to_sell = validate.s_int(payload, "expected_days_to_sell", gt=0)
    multiplier = validate.s_num(payload, "expected_proceeds_multiplier", gt=0)
    recondition_required = validate.s_bool(payload, "recondition_required")

    if any(row["code"] == code for row in store.channels.values()):
        raise ApiError(
            "ERR_DUPLICATE_CHANNEL_CODE",
            "A remarketing channel with code '%s' already exists." % code,
        )

    row = base_row()
    row.update({
        "code": code,
        "name": name,
        "fee_pct": fee_pct,
        "fixed_fee_cents": fixed_fee,
        "expected_days_to_sell": days_to_sell,
        "expected_proceeds_multiplier": multiplier,
        "recondition_required": recondition_required,
        "status": "ACTIVE",
    })
    store.channels[row["id"]] = row
    return created(serialize.channel(row))


@bp.route("/fleet/remarketing-channels/<channel_id>", methods=["GET"])
def read_channel(channel_id):
    authorize(ALL_ROLES)
    return ok(serialize.channel(validate.load("channel", channel_id)))


@bp.route("/fleet/remarketing-channels", methods=["GET"])
def list_channels():
    authorize(ALL_ROLES)
    return collect(
        store.channels.values(),
        [
            ("code", "code", "str"),
            ("status", "status", "str"),
            ("recondition_required", "recondition_required", "bool"),
        ],
        serialize.channel,
    )


@bp.route("/fleet/remarketing-channels/<channel_id>/suspend", methods=["POST"])
def suspend_channel(channel_id):
    authorize(("PlatformAdmin",))
    channel = validate.load("channel", channel_id)
    if channel["status"] != "ACTIVE":
        # The catalogue carries no dedicated channel-state code.
        raise ApiError("ERR_INVALID_REQUEST", "The channel is already SUSPENDED.")
    channel["status"] = "SUSPENDED"
    touch(channel)
    return ok(serialize.channel(channel))
