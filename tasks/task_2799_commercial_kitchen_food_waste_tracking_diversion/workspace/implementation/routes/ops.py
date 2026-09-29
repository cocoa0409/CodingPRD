"""Tracking stations and service periods (shifts)."""
from flask import Blueprint

from db import base_row, db, iso, sort_rows, touch
from errors import fail
from middleware import (ALL_READERS, PLATFORM_ADMIN, SHIFT_LEAD, SITE_MANAGER,
                        authenticate, require_site_scope)
from response import row_response
from routes.common import filtered, must_exist, respond_list
from services import derive
from validation import (body_json, field_enum, field_int, field_str, field_ts,
                       field_date, query_date, query_enum, query_str)

bp = Blueprint("ops", __name__)

STATION_KINDS = ("PREP", "HOT_LINE", "DISH_RETURN")
STATION_STATUSES = ("ACTIVE", "MAINTENANCE", "RETIRED")
SHIFT_CODES = ("AM", "PM", "NIGHT")
SHIFT_STATUSES = ("OPEN", "CLOSED")

ALLOWED_STATION_TRANSITIONS = (
    ("ACTIVE", "MAINTENANCE"),
    ("MAINTENANCE", "ACTIVE"),
    ("ACTIVE", "RETIRED"),
    ("MAINTENANCE", "RETIRED"),
)


# -------------------------------------------------------- tracking stations
@bp.route("/tracking-stations", methods=["POST"])
def create_station():
    caller = authenticate((PLATFORM_ADMIN, SITE_MANAGER))
    body = body_json()
    site_id = field_str(body, "site_id")
    station_code = field_str(body, "station_code")
    station_kind = field_enum(body, "station_kind", STATION_KINDS)
    calibration_due_at = field_ts(body, "calibration_due_at")
    tare_grams = field_int(body, "tare_grams", required=False, minimum=0, default=0)
    lock_seconds = field_int(body, "capture_lock_seconds", required=False,
                             minimum=0, maximum=600, default=30)
    status = field_enum(body, "status", STATION_STATUSES, required=False,
                        default="ACTIVE")
    must_exist(db.sites, site_id, "ERR_SITE_NOT_FOUND")
    require_site_scope(caller, site_id)
    for row in db.stations.values():
        if row["site_id"] == site_id and row["station_code"] == station_code:
            fail("ERR_DUPLICATE_STATION_CODE",
                 "station_code is already in use at this site.")
    station = base_row(
        site_id=site_id,
        station_code=station_code,
        station_kind=station_kind,
        tare_grams=tare_grams,
        capture_lock_seconds=lock_seconds,
        calibration_due_at=iso(calibration_due_at),
        status=status,
    )
    db.stations[station["id"]] = station
    return row_response(station, 201)


@bp.route("/tracking-stations/<station_id>/status", methods=["POST"])
def change_station_status(station_id):
    caller = authenticate((SITE_MANAGER, PLATFORM_ADMIN))
    body = body_json()
    status = field_enum(body, "status", STATION_STATUSES)
    calibration_due_at = field_ts(body, "calibration_due_at", required=False)
    field_str(body, "note", required=False)
    station = must_exist(db.stations, station_id, "ERR_STATION_NOT_FOUND")
    require_site_scope(caller, station["site_id"])
    if (station["status"], status) not in ALLOWED_STATION_TRANSITIONS:
        fail("ERR_INVALID_STATION_STATE",
             "A station may not move from %s to %s." % (station["status"], status))
    if station["status"] == "MAINTENANCE" and status == "ACTIVE" \
            and calibration_due_at is not None:
        station["calibration_due_at"] = iso(calibration_due_at)
    station["status"] = status
    touch(station)
    return row_response(station)


@bp.route("/tracking-stations/<station_id>", methods=["GET"])
def get_station(station_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.stations, station_id,
                                   "ERR_STATION_NOT_FOUND"))


@bp.route("/tracking-stations", methods=["GET"])
def list_stations():
    authenticate(ALL_READERS)
    rows = filtered(list(db.stations.values()),
                    site_id=query_str("site_id"),
                    status=query_enum("status", STATION_STATUSES),
                    station_kind=query_enum("station_kind", STATION_KINDS))
    return respond_list(rows)


# --------------------------------------------------------- service periods
@bp.route("/shifts", methods=["POST"])
def create_shift():
    caller = authenticate((SHIFT_LEAD, SITE_MANAGER))
    body = body_json()
    site_id = field_str(body, "site_id")
    shift_date = field_date(body, "shift_date")
    shift_code = field_enum(body, "shift_code", SHIFT_CODES)
    meals_served = field_int(body, "meals_served", minimum=0)
    must_exist(db.sites, site_id, "ERR_SITE_NOT_FOUND")
    require_site_scope(caller, site_id)
    for row in db.shifts.values():
        if (row["site_id"] == site_id and row["shift_date"] == shift_date
                and row["shift_code"] == shift_code):
            fail("ERR_DUPLICATE_SHIFT",
                 "This site already has a %s period on %s."
                 % (shift_code, shift_date))
    shift = base_row(
        site_id=site_id,
        shift_date=shift_date,
        shift_code=shift_code,
        meals_served=meals_served,
        status="OPEN",
        shift_waste_grams=0,
        waste_intensity_kg_per_1k_meals=None,
        capture_compliance_pct=None,
        pre_consumer_share_pct=None,
        leaderboard_score=None,
        closed_at=None,
    )
    derive.recompute_shift(shift)
    db.shifts[shift["id"]] = shift
    return row_response(shift, 201)


@bp.route("/shifts/<shift_id>/close", methods=["POST"])
def close_shift(shift_id):
    authenticate((SHIFT_LEAD,))
    body_json()
    shift = must_exist(db.shifts, shift_id, "ERR_SHIFT_NOT_FOUND")
    if shift["status"] != "OPEN":
        fail("ERR_INVALID_SHIFT_STATE", "Only an OPEN period may be closed.")

    # Hop 1: the period closes.
    shift["status"] = "CLOSED"
    shift["closed_at"] = db.now_iso()
    # The final valuation pass, oldest capture first.
    derive.final_valuation_pass(shift)
    # Hop 1 (continued): the period's own metrics and its leaderboard score.
    derive.recompute_shift(shift)
    touch(shift)

    site = db.sites[shift["site_id"]]
    # Hop 3: OPEN alerts of this period expire; ACKNOWLEDGED ones are spared.
    expiring = [a for a in db.alerts.values()
                if a["shift_id"] == shift["id"] and a["status"] == "OPEN"]
    for alert in sort_rows(expiring):
        alert["status"] = "EXPIRED"
        alert["resolved_at"] = db.now_iso()
        touch(alert)
    # Hops 2 and 4: the site's valued cost, open alert count and posture.
    derive.recompute_site(site)
    touch(site)

    # A newly closed period is the only thing that adds meals to a window.
    for target in derive.active_targets_of_site(site["id"]):
        if target["window_start"] <= shift["shift_date"] <= target["window_end"]:
            derive.apply_attainment(target, bump=True)

    return row_response(shift)


@bp.route("/shifts/<shift_id>", methods=["GET"])
def get_shift(shift_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.shifts, shift_id, "ERR_SHIFT_NOT_FOUND"))


@bp.route("/shifts", methods=["GET"])
def list_shifts():
    authenticate(ALL_READERS)
    rows = filtered(list(db.shifts.values()),
                    site_id=query_str("site_id"),
                    shift_date=query_date("shift_date"),
                    shift_code=query_enum("shift_code", SHIFT_CODES),
                    status=query_enum("status", SHIFT_STATUSES))
    return respond_list(rows)
