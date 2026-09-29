"""Waste captures: recording, flagging, voiding and correcting."""
from datetime import timedelta

from flask import Blueprint

from db import base_row, date_of, db, iso, parse_ts, sort_rows, touch
from errors import fail
from middleware import (ALL_READERS, KITCHEN_STAFF, SHIFT_LEAD, authenticate)
from response import row_response
from routes.common import filtered, must_exist, respond_list
from services import calc, derive
from services.calc import D
from validation import (body_json, field_enum, field_int, field_str, field_ts,
                       query_enum, query_str)

bp = Blueprint("entries", __name__)

LOSS_REASONS = ("OVERPRODUCTION", "SPOILAGE", "TRIM", "EXPIRATION",
                "PLATE_WASTE", "CONTAMINATION")
ENTRY_STATUSES = ("RECORDED", "FLAGGED", "VOIDED", "SUPERSEDED")
STREAMS = ("PRE_CONSUMER", "POST_CONSUMER")
PRE_SERVICE_REASONS = ("TRIM", "OVERPRODUCTION", "SPOILAGE")


def _check_loss_reason(loss_reason, station):
    kind = station["station_kind"]
    if loss_reason == "PLATE_WASTE" and kind != "DISH_RETURN":
        fail("ERR_LOSS_REASON_STATION_MISMATCH",
             "PLATE_WASTE is accepted only at a DISH_RETURN station.")
    if loss_reason in PRE_SERVICE_REASONS and kind not in ("PREP", "HOT_LINE"):
        fail("ERR_LOSS_REASON_STATION_MISMATCH",
             "%s is accepted only at a PREP or HOT_LINE station." % loss_reason)


def _check_station_free(station, captured_at, ignore_entry_id=None):
    """The reserved stretch is captured_at .. captured_at + lock + 60, inclusive."""
    for other in db.entries.values():
        if other["station_id"] != station["id"]:
            continue
        if other["status"] not in ("RECORDED", "FLAGGED"):
            continue
        if ignore_entry_id is not None and other["id"] == ignore_entry_id:
            continue
        start = parse_ts(other["captured_at"])
        end = start + timedelta(seconds=station["capture_lock_seconds"]
                                + calc.STATION_TURNAROUND_SECONDS)
        if start <= captured_at <= end:
            fail("ERR_STATION_OCCUPIED",
                 "The station is reserved by an earlier capture.")


def _check_timing(captured_at, shift):
    if captured_at > db.now():
        fail("ERR_CAPTURE_IN_FUTURE",
             "captured_at may not be later than the current logical clock.")
    if iso(captured_at)[:10] != shift["shift_date"]:
        fail("ERR_CAPTURE_OUTSIDE_SHIFT_DATE",
             "captured_at must fall on the period's shift_date.")


@bp.route("/waste-entries", methods=["POST"])
def create_entry():
    caller = authenticate((KITCHEN_STAFF, SHIFT_LEAD))
    body = body_json()
    station_id = field_str(body, "station_id")
    shift_id = field_str(body, "shift_id")
    food_type_id = field_str(body, "food_type_id")
    weight_grams = field_int(body, "weight_grams", minimum=1, maximum=200000)
    loss_reason = field_enum(body, "loss_reason", LOSS_REASONS)
    recipe_id = field_str(body, "recipe_id", required=False)
    captured_at = field_ts(body, "captured_at", required=False)
    note = field_str(body, "note", required=False)

    station = must_exist(db.stations, station_id, "ERR_STATION_NOT_FOUND")
    shift = must_exist(db.shifts, shift_id, "ERR_SHIFT_NOT_FOUND")
    food_type = must_exist(db.food_types, food_type_id, "ERR_FOOD_TYPE_NOT_FOUND")
    recipe = None
    if recipe_id is not None:
        recipe = must_exist(db.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")

    # Step 12: cross-entity state preconditions, in the order of PRD 3.2.
    if station["status"] != "ACTIVE":
        fail("ERR_STATION_NOT_ACTIVE", "Only an ACTIVE station accepts captures.")
    if db.now() >= parse_ts(station["calibration_due_at"]):
        fail("ERR_STATION_CALIBRATION_OVERDUE",
             "The station's calibration has lapsed.")
    if shift["status"] != "OPEN":
        fail("ERR_INVALID_SHIFT_STATE", "Only an OPEN period accepts captures.")
    if recipe is not None and recipe["status"] != "PUBLISHED":
        fail("ERR_RECIPE_NOT_PUBLISHED",
             "A capture may only reference a PUBLISHED recipe.")
    # Step 16
    if shift["site_id"] != station["site_id"]:
        fail("ERR_ENTRY_SITE_MISMATCH",
             "The period and the station belong to different sites.")
    if captured_at is None:
        captured_at = db.now()
    # Step 17
    _check_timing(captured_at, shift)
    # Step 19
    _check_station_free(station, captured_at)
    # Step 28
    _check_loss_reason(loss_reason, station)

    entry = base_row(
        site_id=station["site_id"],
        station_id=station["id"],
        shift_id=shift["id"],
        food_type_id=food_type["id"],
        recipe_id=recipe["id"] if recipe else None,
        corrects_entry_id=None,
        weight_grams=weight_grams,
        loss_reason=loss_reason,
        stream=calc.entry_stream(station["station_kind"], loss_reason),
        captured_at=iso(captured_at),
        capture_window_end=iso(captured_at + timedelta(
            seconds=station["capture_lock_seconds"])),
        captured_by_user_id=caller.user_id,
        status="RECORDED",
        flag_reason=None,
        void_reason=None,
        correction_note=None,
        catalog_cost_basis_cents=None,
        recipe_cost_basis_cents=None,
        provisional_cost_cents=None,
        final_cost_cents=None,
        effective_cost_cents=None,
        valuation_delta_cents=None,
        routed_weight_grams=0,
        unrouted_weight_grams=weight_grams,
        note=note,
    )
    derive.apply_capture_valuation(entry, food_type, recipe)
    db.entries[entry["id"]] = entry

    site = db.sites[entry["site_id"]]
    derive.recompute_shift(shift)
    derive.recompute_site(site)
    derive.evaluate_coaching(shift, entry)
    derive.recompute_site(site)
    touch(shift)
    touch(site)
    return row_response(entry, 201)


@bp.route("/waste-entries/<entry_id>/flag", methods=["POST"])
def flag_entry(entry_id):
    authenticate((SHIFT_LEAD,))
    body = body_json()
    flag_reason = field_str(body, "flag_reason")
    entry = must_exist(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    if entry["status"] != "RECORDED":
        fail("ERR_INVALID_ENTRY_STATE", "Only a RECORDED capture may be flagged.")
    entry["status"] = "FLAGGED"
    entry["flag_reason"] = flag_reason
    touch(entry)
    return row_response(entry)


@bp.route("/waste-entries/<entry_id>/clear-flag", methods=["POST"])
def clear_flag(entry_id):
    authenticate((SHIFT_LEAD,))
    body_json()
    entry = must_exist(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    if entry["status"] != "FLAGGED":
        fail("ERR_INVALID_ENTRY_STATE",
             "Only a FLAGGED capture may have its flag cleared.")
    entry["status"] = "RECORDED"
    touch(entry)
    return row_response(entry)


@bp.route("/waste-entries/<entry_id>/void", methods=["POST"])
def void_entry(entry_id):
    caller = authenticate((SHIFT_LEAD,))
    body = body_json()
    void_reason = field_str(body, "void_reason")
    entry = must_exist(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    # Step 11 precedes the duty separation of step 13.
    if entry["status"] not in ("RECORDED", "FLAGGED"):
        fail("ERR_INVALID_ENTRY_STATE",
             "Only a RECORDED or FLAGGED capture may be voided.")
    if entry["captured_by_user_id"] == caller.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "A lead may not void their own capture.")
    if entry["routed_weight_grams"] != 0:
        fail("ERR_ENTRY_ROUTED_CANNOT_VOID",
             "Release the routed grams before voiding this capture.")

    # Hop 1
    entry["status"] = "VOIDED"
    entry["void_reason"] = void_reason
    touch(entry)
    # The compensation edge: a superseded predecessor returns to RECORDED.
    if entry["corrects_entry_id"]:
        predecessor = db.entries.get(entry["corrects_entry_id"])
        if predecessor is not None and predecessor["status"] == "SUPERSEDED":
            predecessor["status"] = "RECORDED"
            touch(predecessor)

    shift = db.shifts[entry["shift_id"]]
    site = db.sites[entry["site_id"]]
    # Hop 2
    derive.recompute_shift(shift)
    # Hop 3
    intensity = shift["waste_intensity_kg_per_1k_meals"]
    if intensity is None or D(intensity) < calc.COACHING_INTENSITY_THRESHOLD:
        breaches = [a for a in db.alerts.values()
                    if a["shift_id"] == shift["id"]
                    and a["alert_type"] == "INTENSITY_BREACH"
                    and a["status"] in ("OPEN", "ACKNOWLEDGED")]
        for alert in sort_rows(breaches):
            alert["status"] = "AUTO_RESOLVED"
            alert["resolved_at"] = db.now_iso()
            touch(alert)
    # Hop 4 together with the direct site recompute of hop 1.
    derive.recompute_site(site)
    touch(shift)
    touch(site)
    return row_response(entry)


@bp.route("/waste-entries/<entry_id>/corrections", methods=["POST"])
def correct_entry(entry_id):
    caller = authenticate((SHIFT_LEAD,))
    body = body_json()
    expected_version = field_int(body, "expected_entry_version")
    correction_note = field_str(body, "correction_note")
    weight_grams = field_int(body, "weight_grams", required=False, minimum=1,
                             maximum=200000)
    food_type_id = field_str(body, "food_type_id", required=False)
    loss_reason = field_enum(body, "loss_reason", LOSS_REASONS, required=False)
    recipe_id = field_str(body, "recipe_id", required=False)

    original = must_exist(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND")
    if food_type_id is not None:
        must_exist(db.food_types, food_type_id, "ERR_FOOD_TYPE_NOT_FOUND")
    if recipe_id is not None:
        must_exist(db.recipes, recipe_id, "ERR_RECIPE_NOT_FOUND")

    # Step 10 sits ahead of step 11: a stale token wins over an invalid state.
    if expected_version != original["version"]:
        fail("ERR_STALE_ENTRY_VERSION",
             "expected_entry_version does not match the capture's version.")
    if original["status"] not in ("RECORDED", "FLAGGED"):
        fail("ERR_INVALID_ENTRY_STATE",
             "Only a RECORDED or FLAGGED capture may be corrected.")
    shift = db.shifts[original["shift_id"]]
    if shift["status"] != "OPEN":
        fail("ERR_INVALID_SHIFT_STATE",
             "The owning period must still be OPEN to correct a capture.")

    new_food_type_id = food_type_id or original["food_type_id"]
    new_loss_reason = loss_reason or original["loss_reason"]
    new_weight = weight_grams if weight_grams is not None else original["weight_grams"]
    new_recipe_id = recipe_id or original["recipe_id"]
    recipe = db.recipes.get(new_recipe_id) if new_recipe_id else None
    if recipe is not None and recipe["status"] != "PUBLISHED":
        fail("ERR_RECIPE_NOT_PUBLISHED",
             "A capture may only reference a PUBLISHED recipe.")
    if original["routed_weight_grams"] != 0:
        fail("ERR_ENTRY_ROUTED_CANNOT_VOID",
             "Release the routed grams before correcting this capture.")
    station = db.stations[original["station_id"]]
    captured_at = parse_ts(original["captured_at"])
    _check_timing(captured_at, shift)
    for other in db.entries.values():
        if other["corrects_entry_id"] == original["id"]:
            fail("ERR_ENTRY_ALREADY_CORRECTED",
                 "This capture already has a successor.")
    _check_loss_reason(new_loss_reason, station)

    food_type = db.food_types[new_food_type_id]
    original["status"] = "SUPERSEDED"
    touch(original)

    entry = base_row(
        site_id=original["site_id"],
        station_id=original["station_id"],
        shift_id=original["shift_id"],
        food_type_id=new_food_type_id,
        recipe_id=new_recipe_id,
        corrects_entry_id=original["id"],
        weight_grams=new_weight,
        loss_reason=new_loss_reason,
        stream=calc.entry_stream(station["station_kind"], new_loss_reason),
        captured_at=original["captured_at"],
        capture_window_end=iso(captured_at + timedelta(
            seconds=station["capture_lock_seconds"])),
        captured_by_user_id=caller.user_id,
        status="RECORDED",
        flag_reason=None,
        void_reason=None,
        correction_note=correction_note,
        catalog_cost_basis_cents=None,
        recipe_cost_basis_cents=None,
        provisional_cost_cents=None,
        final_cost_cents=None,
        effective_cost_cents=None,
        valuation_delta_cents=None,
        routed_weight_grams=0,
        unrouted_weight_grams=new_weight,
        note=None,
    )
    derive.apply_capture_valuation(entry, food_type, recipe)
    db.entries[entry["id"]] = entry

    site = db.sites[entry["site_id"]]
    derive.recompute_shift(shift)
    derive.recompute_site(site)
    derive.evaluate_coaching(shift, entry)
    derive.recompute_site(site)
    touch(shift)
    touch(site)
    return row_response(entry, 201)


@bp.route("/waste-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    authenticate(ALL_READERS)
    return row_response(must_exist(db.entries, entry_id, "ERR_ENTRY_NOT_FOUND"))


@bp.route("/waste-entries", methods=["GET"])
def list_entries():
    authenticate(ALL_READERS)
    rows = filtered(list(db.entries.values()),
                    site_id=query_str("site_id"),
                    shift_id=query_str("shift_id"),
                    station_id=query_str("station_id"),
                    food_type_id=query_str("food_type_id"),
                    recipe_id=query_str("recipe_id"),
                    corrects_entry_id=query_str("corrects_entry_id"),
                    status=query_enum("status", ENTRY_STATUSES),
                    stream=query_enum("stream", STREAMS),
                    loss_reason=query_enum("loss_reason", LOSS_REASONS))
    return respond_list(rows)
