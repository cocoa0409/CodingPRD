"""Banking weeks, extensions, withdrawal and the valuation view."""

from flask import Blueprint

import calc
import shapes
from authz import authenticate, require_acting_identity, require_owner
from errors import ApiError
from response import object_response
from routes.common import ENUM, FK, listing, one, read
from services import deposits as deposit_service
from services import ledger
from services import resorts as resort_service
from store import (db, parse_date, parse_instant, serialize, touch,
                   DEPOSIT_LEAD_MIN_DAYS, DEPOSIT_STATUSES, MAX_EXTENSION_MONTHS,
                   RENTAL_STATUSES, UNIT_SIZES)

bp = Blueprint("deposits", __name__)

ALL_ROLES = ["Member", "ResortManager", "NetworkOperator", "DisputeAnalyst"]
AFFILIATED = ("ACTIVE", "PROBATION")


@bp.route("/deposits", methods=["POST"])
def create_deposit():
    caller = authenticate(["Member", "NetworkOperator"])
    payload = shapes.body()
    member_id = shapes.take_id(payload, "member_id")
    resort_id = shapes.take_id(payload, "resort_id")
    unit_size = shapes.take_enum(payload, "unit_size", UNIT_SIZES)
    check_in_date = shapes.take_date(payload, "check_in_date")
    require_acting_identity(caller)
    member = shapes.find_member(member_id)
    resort = shapes.find_resort(resort_id)
    require_owner(caller, member["id"])
    if member["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    if resort["affiliation_status"] not in AFFILIATED:
        raise ApiError("ERR_RESORT_NOT_AFFILIATED")
    lead_days = (parse_date(check_in_date) - db.today()).days
    if lead_days < DEPOSIT_LEAD_MIN_DAYS:
        raise ApiError("ERR_DEPOSIT_WINDOW_CLOSED")
    band = deposit_service.band_for_date(resort["id"], check_in_date)
    if band is None:
        raise ApiError("ERR_NO_SEASON_BAND_FOR_DATE")
    if not deposit_service.has_capacity(resort, unit_size, check_in_date):
        raise ApiError("ERR_UNIT_INVENTORY_CONFLICT")
    awarded_power = calc.trading_power(unit_size, band["band_code"], resort["demand_index"],
                                      resort["quality_rating"], lead_days)
    row = db.new_row({
        "member_id": member["id"],
        "resort_id": resort["id"],
        "unit_size": unit_size,
        "check_in_date": check_in_date,
        "season_band_code": band["band_code"],
        "occupancy_end_date": deposit_service.occupancy_end(check_in_date),
        "awarded_power": awarded_power,
        "settlement_power": None,
        "restoration_haircut_power": 0,
        "remaining_power": awarded_power,
        "deposit_status": "BANKED",
        "rental_status": "NOT_LISTED",
        "expires_at": deposit_service.expires_at(check_in_date, 0),
        "extension_months_purchased": 0,
        "_awarded_lead_time_days": lead_days,
        "_demand_index_at_deposit": resort["demand_index"],
        "_quality_rating_at_deposit": resort["quality_rating"],
        "_settlement_as_of": None,
    })
    db.deposits[row["id"]] = row
    resort_service.sync_inventory(resort)
    ledger.credit_power(member, "DEPOSIT_CREDIT", "DEPOSIT", row["id"],
                        "Banked week credited at its at-deposit trading power.", awarded_power)
    return object_response(serialize(row), 201)


@bp.route("/deposits/<deposit_id>", methods=["GET"])
def get_deposit(deposit_id):
    read(ALL_ROLES)
    return one(shapes.find_deposit(deposit_id))


@bp.route("/deposits", methods=["GET"])
def list_deposits():
    return listing(ALL_ROLES, db.deposits, [
        ("member_id", "member_id", FK, shapes.find_member),
        ("resort_id", "resort_id", FK, shapes.find_resort),
        ("unit_size", "unit_size", ENUM, UNIT_SIZES),
        ("deposit_status", "deposit_status", ENUM, DEPOSIT_STATUSES),
        ("rental_status", "rental_status", ENUM, RENTAL_STATUSES),
    ])


@bp.route("/deposits/<deposit_id>/extensions", methods=["POST"])
def extend_deposit(deposit_id):
    caller = authenticate(["Member"])
    payload = shapes.body()
    months = shapes.take_int(payload, "months", minimum=1)
    expected_version = shapes.take_int(payload, "expected_deposit_version")
    require_acting_identity(caller)
    deposit = shapes.find_deposit(deposit_id)
    require_owner(caller, deposit["member_id"])
    if expected_version != deposit["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if deposit["deposit_status"] != "BANKED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if parse_instant(deposit["expires_at"]) <= db.now():
        raise ApiError("ERR_DEPOSIT_EXPIRED")
    if deposit["extension_months_purchased"] + months > MAX_EXTENSION_MONTHS:
        raise ApiError("ERR_EXTENSION_CAP_EXCEEDED")
    member = db.members[deposit["member_id"]]
    tier = db.membership_tiers[member["tier_id"]]
    cost = tier["extension_fee_cents_per_month"] * months
    if member["wallet_credit_cents"] < cost:
        raise ApiError("ERR_INSUFFICIENT_WALLET_CREDIT")
    deposit["extension_months_purchased"] = deposit["extension_months_purchased"] + months
    deposit["expires_at"] = deposit_service.expires_at(
        deposit["check_in_date"], deposit["extension_months_purchased"])
    ledger.move_cash(member, "EXTENSION_FEE", "DEPOSIT", deposit["id"],
                     "Purchase of %d extension month(s) on a banked week." % months, -cost)
    touch(deposit)
    return one(deposit)


@bp.route("/deposits/<deposit_id>/withdrawal", methods=["POST"])
def withdraw_deposit(deposit_id):
    caller = authenticate(["Member"])
    shapes.body()
    require_acting_identity(caller)
    deposit = shapes.find_deposit(deposit_id)
    require_owner(caller, deposit["member_id"])
    if deposit["deposit_status"] != "BANKED" or deposit["rental_status"] != "NOT_LISTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if parse_instant(deposit["expires_at"]) <= db.now():
        raise ApiError("ERR_DEPOSIT_EXPIRED")
    resort = db.resorts[deposit["resort_id"]]
    member = db.members[deposit["member_id"]]
    deposit_service.withdraw_deposit(deposit, resort, member)
    return one(deposit)


@bp.route("/deposits/<deposit_id>/valuation", methods=["GET"])
def deposit_valuation(deposit_id):
    read(ALL_ROLES)
    deposit = shapes.find_deposit(deposit_id)
    settlement_lead = None
    if deposit["settlement_power"] is not None and deposit.get("_settlement_as_of"):
        settlement_lead = (parse_date(deposit["check_in_date"])
                           - parse_instant(deposit["_settlement_as_of"]).date()).days
    return object_response({
        "deposit_id": deposit["id"],
        "season_band_code": deposit["season_band_code"],
        "unit_size_base": calc.UNIT_SIZE_BASE[deposit["unit_size"]],
        "season_multiplier": float(calc.SEASON_MULT[deposit["season_band_code"]]),
        "demand_multiplier": float(calc.demand_multiplier(deposit["_demand_index_at_deposit"])),
        "quality_bonus": calc.QUALITY_BONUS[deposit["_quality_rating_at_deposit"]],
        "awarded_lead_time_days": deposit["_awarded_lead_time_days"],
        "awarded_power": deposit["awarded_power"],
        "settlement_lead_time_days": settlement_lead,
        "settlement_power": deposit["settlement_power"],
        "remaining_power": deposit["remaining_power"],
    })
