"""Membership tiers, the season calendar and the logical clock."""

from decimal import Decimal
from flask import Blueprint

import calc
import shapes
from authz import authenticate, require_acting_identity, require_resort_manager
from errors import ApiError
from response import object_response
from routes.common import ENUM, FK, listing, one, read
from store import (db, format_instant, serialize, BAND_CODES, TIER_CODES)

bp = Blueprint("config", __name__)

ALL_ROLES = ["Member", "ResortManager", "NetworkOperator", "DisputeAnalyst"]


# ---------------------------------------------------------------------------
# membership tiers
# ---------------------------------------------------------------------------
@bp.route("/membership-tiers", methods=["POST"])
def create_tier():
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    tier = {
        "tier_code": shapes.take_enum(payload, "tier_code", TIER_CODES),
        "annual_dues_cents": shapes.take_int(payload, "annual_dues_cents", minimum=0),
        "base_exchange_fee_cents": shapes.take_int(payload, "base_exchange_fee_cents", minimum=0),
        "priority_surcharge_cents": shapes.take_int(payload, "priority_surcharge_cents", minimum=0),
        "priority_window_days": shapes.take_int(payload, "priority_window_days", minimum=1),
        "deposit_first_bonus_pct": shapes.take_int(payload, "deposit_first_bonus_pct",
                                                  minimum=0, maximum=100),
        "max_active_requests": shapes.take_int(payload, "max_active_requests", minimum=1),
        "cancellation_fee_cents": shapes.take_int(payload, "cancellation_fee_cents", minimum=0),
        "reinstatement_fee_cents": shapes.take_int(payload, "reinstatement_fee_cents", minimum=0),
        "extension_fee_cents_per_month": shapes.take_int(payload, "extension_fee_cents_per_month",
                                                        minimum=0),
    }
    require_acting_identity(caller)
    for existing in db.membership_tiers.values():
        if existing["tier_code"] == tier["tier_code"]:
            raise ApiError("ERR_INVALID_REQUEST", "tier_code must be unique across all tiers.")
    row = db.new_row(tier)
    db.membership_tiers[row["id"]] = row
    return object_response(serialize(row), 201)


@bp.route("/membership-tiers/<tier_id>", methods=["GET"])
def get_tier(tier_id):
    read(ALL_ROLES)
    return one(shapes.find_tier(tier_id))


@bp.route("/membership-tiers", methods=["GET"])
def list_tiers():
    return listing(ALL_ROLES, db.membership_tiers,
                   [("tier_code", "tier_code", ENUM, TIER_CODES)])


# ---------------------------------------------------------------------------
# season bands
# ---------------------------------------------------------------------------
def _overlaps(first, second):
    return (first["start_month_day"] <= second["end_month_day"]
            and second["start_month_day"] <= first["end_month_day"])


@bp.route("/season-bands", methods=["POST"])
def create_season_band():
    caller = authenticate(["NetworkOperator", "ResortManager"])
    payload = shapes.body()
    resort_id = shapes.take_id(payload, "resort_id")
    band_code = shapes.take_enum(payload, "band_code", BAND_CODES)
    start_month_day = shapes.take_month_day(payload, "start_month_day")
    end_month_day = shapes.take_month_day(payload, "end_month_day")
    require_acting_identity(caller)
    resort = shapes.find_resort(resort_id)
    require_resort_manager(caller, resort["id"])
    if end_month_day < start_month_day:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    candidate = {"start_month_day": start_month_day, "end_month_day": end_month_day}
    for existing in db.season_bands.values():
        if existing["resort_id"] == resort["id"] and _overlaps(existing, candidate):
            raise ApiError("ERR_SEASON_BAND_OVERLAP")
    row = db.new_row({
        "resort_id": resort["id"],
        "band_code": band_code,
        "start_month_day": start_month_day,
        "end_month_day": end_month_day,
        "season_multiplier": float(calc.SEASON_MULT[band_code]),
    })
    db.season_bands[row["id"]] = row
    return object_response(serialize(row), 201)


@bp.route("/season-bands/<band_id>", methods=["GET"])
def get_season_band(band_id):
    read(ALL_ROLES)
    return one(shapes.find_band(band_id))


@bp.route("/season-bands", methods=["GET"])
def list_season_bands():
    return listing(ALL_ROLES, db.season_bands, [
        ("resort_id", "resort_id", FK, shapes.find_resort),
        ("band_code", "band_code", ENUM, BAND_CODES),
    ])


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    moment = shapes.take_instant(payload, "to_iso8601")
    require_acting_identity(caller)
    previous = db.now_iso()
    db.clock = moment
    return object_response({"current_utc": db.now_iso(), "previous_utc": previous})
