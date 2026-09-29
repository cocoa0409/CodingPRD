"""The logical clock, the operating season and the cabin inventory (PRD 3.1, 3.2)."""

from flask import Blueprint

import calc
import derive
import fields
from auth import ALL_OPERATIONAL, EVERYONE, auth
from derive import Touch, cabin_json, season_json
from envelope import created, listing, ok
from errors import ApiError
from fields import body, require
from lookup import find
from store import db

bp = Blueprint("seasons", __name__)

WEEKDAYS = {
    "MONDAY": 0,
    "TUESDAY": 1,
    "WEDNESDAY": 2,
    "THURSDAY": 3,
    "FRIDAY": 4,
    "SATURDAY": 5,
    "SUNDAY": 6,
}
SEASON_STATUSES = ("PLANNING", "OPEN", "IN_SEASON", "CLOSED", "OFF_SEASON")
SEASON_STEPS = {
    "OPEN": "PLANNING",
    "IN_SEASON": "OPEN",
    "CLOSED": "IN_SEASON",
    "OFF_SEASON": "CLOSED",
}
CABIN_STATUSES = ("READY", "OCCUPIED", "TURNOVER", "OUT_OF_SERVICE")


# ------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(*ALL_OPERATIONAL)
    data = body()
    require(data, "current_utc")
    instant = fields.as_instant(data, "current_utc")
    db.set_clock(instant)
    return ok({"current_utc": db.clock_iso()})


# ------------------------------------------------------------------- seasons
def _validate_tiers(data):
    tiers = fields.as_list(data, "package_tiers", min_len=1)
    seen = set()
    cleaned = []
    for index, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            fields.bad("package_tiers", "elements must be objects")
        label = "package_tiers[%d]" % index
        for key in (
            "code",
            "adult_nightly_rate_cents",
            "child_discount_pct",
            "included_activity_credit_cents",
        ):
            if key not in tier or tier[key] is None:
                raise ApiError(
                    "ERR_MISSING_REQUIRED_FIELD",
                    "Field '%s.%s' is required." % (label, key),
                )
        code = tier["code"]
        if not isinstance(code, str) or code == "":
            fields.bad(label + ".code", "must be a non-empty string")
        if code in seen:
            fields.bad(label + ".code", "must be unique within the season")
        seen.add(code)
        rate = fields.as_cents({"v": tier["adult_nightly_rate_cents"]}, "v")
        credit = fields.as_cents({"v": tier["included_activity_credit_cents"]}, "v")
        discount = fields.as_pct({"v": tier["child_discount_pct"]}, "v")
        cleaned.append(
            {
                "code": code,
                "adult_nightly_rate_cents": rate,
                "child_discount_pct": discount,
                "included_activity_credit_cents": credit,
            }
        )
    return cleaned


@bp.post("/seasons")
def create_season():
    auth("RanchManager")
    data = body()
    require(
        data,
        "name",
        "arrival_weekday",
        "season_start_date",
        "season_end_date",
        "dining_seat_capacity",
        "package_tiers",
    )
    name = fields.as_str(data, "name")
    weekday = fields.as_enum(data, "arrival_weekday", tuple(WEEKDAYS))
    start = fields.as_date(data, "season_start_date")
    end = fields.as_date(data, "season_end_date")
    min_nights = fields.as_int(data, "min_stay_nights", default=7, minimum=1)
    max_nights = fields.as_int(data, "max_stay_nights", default=21, minimum=1)
    if max_nights < min_nights:
        fields.bad("max_stay_nights", "must be >= min_stay_nights")
    deposit_pct = fields.as_pct(data, "deposit_pct", default=0.30, exclusive_min=0)
    buyout_pct = fields.as_pct(data, "buyout_premium_pct", default=0.15)
    no_show = fields.as_cents(data, "no_show_penalty_cents", default=4500)
    retention = fields.as_cents(data, "retention_bonus_cents", default=120000)
    dining = fields.as_int(data, "dining_seat_capacity", minimum=1)
    tiers = _validate_tiers(data)

    row = db.insert(
        "seasons",
        {
            "name": name,
            "arrival_weekday": weekday,
            "season_start_date": start,
            "season_end_date": end,
            "min_stay_nights": min_nights,
            "max_stay_nights": max_nights,
            "deposit_pct": deposit_pct,
            "buyout_premium_pct": buyout_pct,
            "no_show_penalty_cents": no_show,
            "retention_bonus_cents": retention,
            "dining_seat_capacity": dining,
            "package_tiers": tiers,
            "season_status": "PLANNING",
            "gross_package_revenue_cents": 0,
            "retention_bonus_liability_cents": 0,
            "net_surplus_cents": 0,
            "capital_reserve_cents": 0,
            "capital_committed_cents": 0,
            "bed_nights_sold": 0,
            "in_house_guest_count": 0,
        },
    )
    return created(season_json(row))


@bp.get("/seasons/<season_id>")
def read_season(season_id):
    auth(*EVERYONE)
    return ok(season_json(find("seasons", season_id)))


@bp.get("/seasons")
def list_seasons():
    auth(*ALL_OPERATIONAL)
    status = fields.query_enum("season_status", SEASON_STATUSES)
    return listing(derive.rows_of("seasons", season_status=status), season_json)


@bp.post("/seasons/<season_id>/advance")
def advance_season(season_id):
    auth("RanchManager")
    season = find("seasons", season_id)
    data = body()
    require(data, "target_status")
    target = fields.as_str(data, "target_status")

    expected_from = SEASON_STEPS.get(target)
    if expected_from is None or season["season_status"] != expected_from:
        raise ApiError(
            "ERR_INVALID_SEASON_TRANSITION",
            "Cannot move a %s season to '%s'." % (season["season_status"], target),
        )
    if target == "OPEN" and len(season["package_tiers"]) < 1:
        raise ApiError(
            "ERR_INVALID_SEASON_TRANSITION",
            "A season must publish at least one package tier before opening.",
        )
    if target == "CLOSED":
        for booking in db.bookings.values():
            if booking["season_id"] == season["id"] and booking["booking_status"] == "CHECKED_IN":
                raise ApiError(
                    "ERR_SEASON_HAS_LIVE_BOOKINGS",
                    "A booking of this season is still CHECKED_IN.",
                )
    if target == "OFF_SEASON":
        for staff in db.staff_members.values():
            if staff["season_id"] == season["id"] and staff["employment_status"] not in derive.TERMINAL_EMPLOYMENT:
                raise ApiError(
                    "ERR_INVALID_SEASON_TRANSITION",
                    "Every staff contract must reach a terminal status first.",
                )

    season["season_status"] = target
    if target == "CLOSED":
        gross = 0
        for booking in db.bookings.values():
            if booking["season_id"] == season["id"] and booking["booking_status"] == "CHECKED_OUT":
                gross += int(booking["final_folio_total_cents"])
        liability = 0
        for staff in db.staff_members.values():
            if staff["season_id"] == season["id"] and staff["employment_status"] in derive.TERMINAL_EMPLOYMENT:
                liability += int(staff["retention_bonus_settled_cents"])
        net = gross - liability - int(season["capital_committed_cents"])
        season["gross_package_revenue_cents"] = gross
        season["retention_bonus_liability_cents"] = liability
        season["net_surplus_cents"] = net
        season["capital_reserve_cents"] = calc.capital_reserve(net)
    db.touch(season)
    return ok(season_json(season))


# -------------------------------------------------------------------- cabins
@bp.post("/cabins")
def create_cabin():
    auth("RanchManager")
    data = body()
    require(data, "name", "bed_capacity")
    name = fields.as_str(data, "name")
    capacity = fields.as_int(data, "bed_capacity", minimum=1)
    for existing in db.cabins.values():
        if existing["name"] == name:
            fields.bad("name", "must be unique across the ranch")
    row = db.insert(
        "cabins",
        {
            "name": name,
            "bed_capacity": capacity,
            "cabin_status": "READY",
            "maintenance_project_code": None,
            "maintenance_capital_cost_cents": 0,
            "last_turnover_completed_at": None,
        },
    )
    return created(cabin_json(row))


@bp.get("/cabins/<cabin_id>")
def read_cabin(cabin_id):
    auth("RanchManager", "ReservationsAgent", "HorseProgramDirector", "SafetyOfficer")
    return ok(cabin_json(find("cabins", cabin_id)))


@bp.get("/cabins")
def list_cabins():
    auth("RanchManager", "ReservationsAgent", "HorseProgramDirector", "SafetyOfficer")
    status = fields.query_enum("cabin_status", CABIN_STATUSES)
    return listing(derive.rows_of("cabins", cabin_status=status), cabin_json)


@bp.post("/cabins/<cabin_id>/maintenance-hold")
def maintenance_hold(cabin_id):
    auth("RanchManager")
    cabin = find("cabins", cabin_id)
    data = body()
    season = None
    if isinstance(data.get("season_id"), str):
        season = find("seasons", data["season_id"])
    require(data, "season_id", "maintenance_project_code", "maintenance_capital_cost_cents")
    fields.as_str(data, "season_id")
    project = fields.as_str(data, "maintenance_project_code")
    cost = fields.as_cents(data, "maintenance_capital_cost_cents")
    if season is None:
        season = find("seasons", data["season_id"])

    if season["season_status"] not in ("CLOSED", "OFF_SEASON"):
        raise ApiError(
            "ERR_SEASON_NOT_OPEN",
            "Capital work requires a CLOSED or OFF_SEASON season.",
        )
    if cabin["cabin_status"] != "READY":
        raise ApiError("ERR_CABIN_NOT_READY", "The cabin is not READY.")
    for booking in db.bookings.values():
        if booking["cabin_id"] != cabin["id"]:
            continue
        if booking["booking_status"] not in ("HELD", "CONFIRMED"):
            continue
        if booking["arrival_date"] >= season["season_start_date"]:
            raise ApiError(
                "ERR_CABIN_DOUBLE_BOOKED",
                "A live booking of this cabin arrives on or after the season start.",
            )
    available = int(season["capital_reserve_cents"]) - int(season["capital_committed_cents"])
    if cost > available:
        raise ApiError(
            "ERR_CAPITAL_RESERVE_INSUFFICIENT",
            "The project exceeds the unspent capital reserve.",
        )

    cabin["cabin_status"] = "OUT_OF_SERVICE"
    cabin["maintenance_project_code"] = project
    cabin["maintenance_capital_cost_cents"] = cost
    season["capital_committed_cents"] = int(season["capital_committed_cents"]) + cost
    db.touch(cabin)
    db.touch(season)
    return ok(cabin_json(cabin))


@bp.post("/cabins/<cabin_id>/return-to-ready")
def return_to_ready(cabin_id):
    auth("RanchManager")
    cabin = find("cabins", cabin_id)
    data = body()
    season = None
    if isinstance(data.get("season_id"), str):
        season = find("seasons", data["season_id"])
    require(data, "season_id")
    fields.as_str(data, "season_id")
    if season is None:
        season = find("seasons", data["season_id"])

    if cabin["cabin_status"] not in ("TURNOVER", "OUT_OF_SERVICE"):
        raise ApiError(
            "ERR_CABIN_NOT_READY",
            "Only a TURNOVER or OUT_OF_SERVICE cabin may be returned to READY.",
        )
    if cabin["cabin_status"] == "OUT_OF_SERVICE":
        committed = int(cabin["maintenance_capital_cost_cents"] or 0)
        season["capital_committed_cents"] = int(season["capital_committed_cents"]) - committed
        cabin["maintenance_project_code"] = None
        cabin["maintenance_capital_cost_cents"] = 0
        db.touch(season)
    cabin["cabin_status"] = "READY"
    cabin["last_turnover_completed_at"] = db.clock_iso()
    db.touch(cabin)
    return ok(cabin_json(cabin))


@bp.post("/cabins/<cabin_id>/turnover-complete")
def turnover_complete(cabin_id):
    auth("RanchManager")
    cabin = find("cabins", cabin_id)
    if cabin["cabin_status"] != "TURNOVER":
        raise ApiError("ERR_CABIN_NOT_READY", "The cabin is not awaiting turnover.")
    cabin["cabin_status"] = "READY"
    cabin["last_turnover_completed_at"] = db.clock_iso()
    db.touch(cabin)
    return ok(cabin_json(cabin))
