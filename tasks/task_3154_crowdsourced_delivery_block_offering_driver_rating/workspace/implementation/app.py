"""Crowdsourced Delivery Blocks API — Flask application.

Implements the PRD in workspace/PRD.md against SCAFFOLD.yaml.
In-memory storage only (db.py); every boot starts from an empty store.

Validation priority order (PRD §2.5), pinned:
  1 auth headers            -> ERR_UNAUTHENTICATED (401)
  2 role + ownership        -> ERR_FORBIDDEN (403) / ERR_OFFER_WRONG_DRIVER (403)
  3 existence               -> ERR_NOT_FOUND (404)
  4 state-machine legality  -> ERR_INVALID_STATE / domain state errors (409)
  5 business safety         -> screening / vehicle / insurance gates (409)
  6 business temporal       -> visibility / overlap / buffer / expiry / check-in (409)
  7 business constraint     -> duplicates, appeal-open (409)
  8 business fiscal + OCC   -> ERR_VALIDATION (400) / ERR_STALE_VERSION (412)
  9 body shape              -> ERR_VALIDATION (400)
"""

import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask

import db
from errors import (
    ApiError,
    raise_err,
    ERR_VALIDATION,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_DRIVER_NOT_ACTIVE,
    ERR_SCREENING_NOT_CLEARED,
    ERR_NO_ELIGIBLE_VEHICLE,
    ERR_INSURANCE_NOT_ATTESTED,
    ERR_INSURANCE_WINDOW_LAPSE,
    ERR_VEHICLE_CLASS_MISMATCH,
    ERR_BLOCK_NOT_PUBLISHED,
    ERR_BLOCK_NOT_VISIBLE_YET,
    ERR_BLOCK_WINDOW_OVERLAP,
    ERR_OFFER_BUFFER_CONFLICT,
    ERR_OFFER_EXPIRED,
    ERR_OFFER_WRONG_DRIVER,
    ERR_CHECKIN_TOO_EARLY,
    ERR_CHECKIN_WINDOW_CLOSED,
    ERR_APPEAL_NOT_OPEN,
    ERR_PACKAGE_NOT_DELIVERABLE,
    ERR_DUPLICATE_EMAIL,
    ERR_DUPLICATE_VIN,
    ERR_STALE_VERSION,
)
from middleware import (
    authenticate,
    require_roles,
    require_driver_ownership,
    get_json_body,
    parse_pagination,
    paginate,
)
from response import success_object, success_list, error_response
import services as svc

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

VEHICLE_CLASSES = ("SEDAN", "SUV", "VAN")
TIERS = ("STANDARD", "PLUS", "PREMIER")


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Route not found"))


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Route not found"))


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response(ApiError("ERR_VALIDATION", 400, "Internal error"))


# ---------------------------------------------------------------------------
# Body field helpers (priority-9 shape checks)
# ---------------------------------------------------------------------------

def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise_err(ERR_VALIDATION, "Missing required field: %s" % f)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_VALIDATION, "Field %s must be a non-empty string" % field)
    return v


def parse_dt_field(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, "Field %s must be an ISO8601 string" % field)
    try:
        return db.parse_iso(v)
    except Exception:
        raise_err(ERR_VALIDATION, "Field %s is not a parseable ISO8601 datetime" % field)


def require_positive_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
        raise_err(ERR_VALIDATION, "Field %s must be a positive integer" % field)
    return v


def require_enum(body, field, values):
    v = body.get(field)
    if v not in values:
        raise_err(ERR_VALIDATION, "Field %s must be one of %s" % (field, list(values)))
    return v


def normalize_dt(dt):
    return db.format_ts(dt)


# ---------------------------------------------------------------------------
# Shared acceptance logic (first-come + reserved offer)
# ---------------------------------------------------------------------------

def run_acceptance(caller, block, vehicle_id, offer=None):
    """DeliveryBlock PUBLISHED -> ASSIGNED. Returns the created BlockAssignment.

    `offer` is None for first-come acceptance, else the BlockOffer being
    accepted (which bypasses the tier visibility gate).
    """
    # state: block must be PUBLISHED
    if block["status"] != "PUBLISHED":
        raise_err(ERR_BLOCK_NOT_PUBLISHED, "Block is not PUBLISHED")

    # state: driver must be ACTIVE
    driver = svc.get_driver_or_404(caller.user_id)
    if driver["status"] != "ACTIVE":
        raise_err(ERR_DRIVER_NOT_ACTIVE, "Driver is not ACTIVE")

    # temporal: tier visibility lead (first-come only; offers bypass it)
    if offer is None:
        now = db.now()
        lead_minutes = svc.TIER_LEAD_MIN[driver["rating_tier"]]
        if now < db.parse_iso(block["starts_at"]) - timedelta(minutes=lead_minutes):
            raise_err(ERR_BLOCK_NOT_VISIBLE_YET, "Block is not yet visible to your tier")

    # state: no other non-terminal assignment for this block
    for a in db.assignments.values():
        if a["block_id"] == block["id"] and a["status"] in svc.NON_TERMINAL_ASSIGNMENT_STATUSES:
            raise_err(ERR_INVALID_STATE, "Block already has a non-terminal assignment")

    # safety: vehicle exists, belongs to driver, ACTIVE
    vehicle = db.vehicles.get(vehicle_id)
    if vehicle is None or vehicle["driver_id"] != driver["id"] or vehicle["status"] != "ACTIVE":
        raise_err(ERR_NO_ELIGIBLE_VEHICLE, "Vehicle is missing, retired, or not yours")

    # safety: insurance ATTESTED
    if svc.insurance_status(vehicle) != "ATTESTED":
        raise_err(ERR_INSURANCE_NOT_ATTESTED, "Vehicle insurance is not ATTESTED")

    # safety: vehicle class rank >= required rank
    if svc.VEHICLE_CLASS_RANK[vehicle["vehicle_class"]] < svc.VEHICLE_CLASS_RANK[block["required_vehicle_class"]]:
        raise_err(ERR_VEHICLE_CLASS_MISMATCH, "Vehicle class below the block's requirement")

    # temporal: no overlapping non-terminal assignment window for this driver
    if svc.check_window_overlap(driver["id"], block):
        raise_err(ERR_BLOCK_WINDOW_OVERLAP, "Block window overlaps an existing assignment")

    # create assignment with snapshots
    assignment = svc.base_resource()
    assignment.update(
        block_id=block["id"],
        driver_id=driver["id"],
        offer_id=offer["id"] if offer is not None else None,
        vehicle_id=vehicle["id"],
        status="ASSIGNED",
        surge_multiplier_snapshot_bp=block["surge_multiplier_bp"],
        tier_at_accept=driver["rating_tier"],
        provisional_pay_cents=svc.provisional_pay_cents(block, block["surge_multiplier_bp"]),
        check_in_at=None,
        forfeited_at=None,
        no_show_at=None,
        forfeit_cause=None,
        strike_reversed=False,
    )
    db.assignments[assignment["id"]] = assignment

    block["status"] = "ASSIGNED"
    block["assigned_driver_id"] = driver["id"]
    svc.touch(block)

    if offer is not None:
        offer["status"] = "ACCEPTED"
        svc.touch(offer)

    return assignment


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------

@app.post("/_clock/set_current_utc")
def set_clock():
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    target = parse_dt_field(body, "to_iso8601")
    db.clock.set(target)
    return success_object({"current_utc": db.now_iso()})


# ---------------------------------------------------------------------------
# Stations
# ---------------------------------------------------------------------------

@app.post("/stations")
def create_station():
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["name", "zone_code"])
    name = require_string(body, "name")
    zone_code = require_string(body, "zone_code")
    surge_enabled = body.get("surge_enabled", True)
    if not isinstance(surge_enabled, bool):
        raise_err(ERR_VALIDATION, "surge_enabled must be a boolean")

    station = svc.base_resource()
    station.update(
        name=name,
        zone_code=zone_code,
        surge_enabled=surge_enabled,
        pay_liabilities_cents=0,
    )
    db.stations[station["id"]] = station
    return success_object(svc.serialize_station(station), status=201)


@app.get("/stations/<station_id>")
def get_station(station_id):
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin", "StationOps"])
    station = svc.get_station_or_404(station_id)
    svc.recompute_station_liabilities(station)
    return success_object(svc.serialize_station(station))


@app.get("/stations/<station_id>/blocks")
def list_station_blocks(station_id):
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin", "StationOps"])
    station = svc.get_station_or_404(station_id)
    limit, offset = parse_pagination()
    status_filter = None
    from flask import request

    status_filter = request.args.get("status")
    items = [b for b in db.blocks.values() if b["station_id"] == station["id"]]
    if status_filter is not None:
        items = [b for b in items if b["status"] == status_filter]
    items.sort(key=lambda b: (db.parse_iso(b["starts_at"]), b["created_at"], b["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_block(b) for b in page], limit, offset, total)


@app.post("/stations/<station_id>/blocks")
def create_block(station_id):
    caller = authenticate()
    require_roles(caller, ["StationOps"])
    station = svc.get_station_or_404(station_id)
    body = get_json_body()
    require_fields(body, ["starts_at", "ends_at", "required_vehicle_class", "base_pay_cents"])
    starts_at = parse_dt_field(body, "starts_at")
    ends_at = parse_dt_field(body, "ends_at")
    required_vehicle_class = require_enum(body, "required_vehicle_class", VEHICLE_CLASSES)
    base_pay_cents = require_positive_int(body, "base_pay_cents")
    if ends_at <= starts_at:
        raise_err(ERR_VALIDATION, "ends_at must be strictly after starts_at")

    block = svc.base_resource()
    block.update(
        station_id=station["id"],
        starts_at=normalize_dt(starts_at),
        ends_at=normalize_dt(ends_at),
        required_vehicle_class=required_vehicle_class,
        base_pay_cents=base_pay_cents,
        surge_multiplier_bp=svc.SURGE_BASE_BP,
        estimated_pay_cents=0,
        status="DRAFT",
        assigned_driver_id=None,
    )
    block["estimated_pay_cents"] = svc.estimated_pay_cents(block)
    db.blocks[block["id"]] = block
    return success_object(svc.serialize_block(block), status=201)


@app.post("/stations/<station_id>/run-surge-cycle")
def run_surge_cycle(station_id):
    caller = authenticate()
    require_roles(caller, ["StationOps"])
    station = svc.get_station_or_404(station_id)
    body = get_json_body()
    require_fields(body, ["expected_station_version"])
    expected = body.get("expected_station_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_VALIDATION, "expected_station_version must be an integer")
    # OCC evaluated at the money-side priority tier (after existence/state)
    if expected != station["version"]:
        raise_err(ERR_STALE_VERSION, "Station version has advanced")

    now = db.now()

    def cycle_sort_key(block_id):
        b = db.blocks[block_id]
        return (db.parse_iso(b["starts_at"]), b["created_at"], b["id"])

    # Step 1: OFFERED offers on this station's blocks with expires_at <= now -> EXPIRED
    station_block_ids = {b["id"] for b in db.blocks.values() if b["station_id"] == station["id"]}
    expiring_offers = [
        o for o in db.offers.values()
        if o["block_id"] in station_block_ids
        and o["status"] == "OFFERED"
        and db.parse_iso(o["expires_at"]) <= now
    ]
    expiring_offers.sort(key=lambda o: cycle_sort_key(o["block_id"]))
    for offer in expiring_offers:
        offer["status"] = "EXPIRED"
        svc.touch(offer)

    # Step 2: no-show sweep — ASSIGNED assignments whose block.starts_at + 15min <= now
    no_shows = [
        a for a in db.assignments.values()
        if a["status"] == "ASSIGNED"
        and a["block_id"] in station_block_ids
        and db.parse_iso(db.blocks[a["block_id"]]["starts_at"]) + timedelta(minutes=svc.CHECK_IN_LATE_MINUTES) <= now
    ]
    no_shows.sort(key=lambda a: cycle_sort_key(a["block_id"]))
    relisted_block_ids = set()
    for assignment in no_shows:
        assignment["status"] = "NO_SHOW"
        assignment["no_show_at"] = db.now_iso()
        svc.touch(assignment)
        block = db.blocks[assignment["block_id"]]
        svc.relist_block(block)
        relisted_block_ids.add(block["id"])
        driver = db.drivers.get(assignment["driver_id"])
        if driver is not None:
            svc.recompute_driver_aggregates(driver, reliability_changed=True)
            driver["updated_at"] = db.now_iso()
            driver["version"] += 1

    # Step 3: block expiry — PUBLISHED blocks with starts_at <= now -> EXPIRED.
    # Blocks relisted by the no-show sweep in step 2 of this same cycle are
    # excluded: relisting them only to expire them in the same cycle would
    # defeat the relist (PRD §3.7).
    expiring_blocks = [
        b for b in db.blocks.values()
        if b["station_id"] == station["id"]
        and b["status"] == "PUBLISHED"
        and b["id"] not in relisted_block_ids
        and db.parse_iso(b["starts_at"]) <= now
    ]
    expiring_blocks.sort(key=lambda b: (db.parse_iso(b["starts_at"]), b["created_at"], b["id"]))
    for block in expiring_blocks:
        block["status"] = "EXPIRED"
        svc.touch(block)
        for offer in db.offers.values():
            if offer["block_id"] == block["id"] and offer["status"] == "OFFERED":
                offer["status"] = "EXPIRED"
                svc.touch(offer)

    # Step 4: surge escalation (only when station.surge_enabled)
    if station["surge_enabled"]:
        surge_blocks = [
            b for b in db.blocks.values()
            if b["station_id"] == station["id"]
            and b["status"] == "PUBLISHED"
            and db.parse_iso(b["starts_at"]) > now
        ]
        surge_blocks.sort(key=lambda b: (db.parse_iso(b["starts_at"]), b["created_at"], b["id"]))
        for block in surge_blocks:
            delta_seconds = (db.parse_iso(block["starts_at"]) - now).total_seconds()
            minutes_to_start = int(delta_seconds // 60)
            if minutes_to_start <= 30:
                bracket = svc.SURGE_STEP_30_BP
            elif minutes_to_start <= 60:
                bracket = svc.SURGE_STEP_60_BP
            elif minutes_to_start <= 120:
                bracket = svc.SURGE_STEP_120_BP
            else:
                bracket = svc.SURGE_BASE_BP
            new_value = max(block["surge_multiplier_bp"], bracket)
            if new_value != block["surge_multiplier_bp"]:
                block["surge_multiplier_bp"] = new_value
                block["estimated_pay_cents"] = svc.estimated_pay_cents(block)
                svc.touch(block)

    svc.touch(station)
    svc.recompute_station_liabilities(station)
    return success_object(svc.serialize_station(station))


# ---------------------------------------------------------------------------
# Driver onboarding
# ---------------------------------------------------------------------------

@app.post("/drivers/register")
def register_driver():
    caller = authenticate()
    require_roles(caller, ["Anonymous"])
    body = get_json_body()
    require_fields(body, ["legal_name", "email"])
    legal_name = require_string(body, "legal_name")
    email = require_string(body, "email")

    for d in db.drivers.values():
        if d["email"] == email:
            raise_err(ERR_DUPLICATE_EMAIL, "Email is already registered")

    driver = svc.base_resource()
    driver.update(
        legal_name=legal_name,
        email=email,
        status="APPLIED",
        rating_tier="STANDARD",
        rating_score_x100=0,
        lifetime_rating_x100=0,
        reliability_score_bp=10000,
    )
    db.drivers[driver["id"]] = driver

    screening = svc.base_resource()
    screening.update(
        driver_id=driver["id"],
        status="INITIATED",
        failure_reason=None,
        decided_at=None,
    )
    db.screenings[screening["id"]] = screening

    return success_object(svc.serialize_driver(driver), status=201)


@app.get("/drivers/<driver_id>")
def get_driver(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "PlatformAdmin", "StationOps", "AppealsReviewer"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    return success_object(svc.serialize_driver(driver))


@app.get("/drivers/<driver_id>/screenings")
def list_driver_screenings(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    limit, offset = parse_pagination()
    items = [s for s in db.screenings.values() if s["driver_id"] == driver["id"]]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_screening(s) for s in page], limit, offset, total)


@app.post("/screenings/<screening_id>/begin-review")
def begin_review(screening_id):
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin"])
    screening = svc.get_screening_or_404(screening_id)
    if screening["status"] != "INITIATED":
        raise_err(ERR_INVALID_STATE, "Screening is not INITIATED")
    screening["status"] = "IN_REVIEW"
    svc.touch(screening)
    return success_object(svc.serialize_screening(screening))


@app.post("/screenings/<screening_id>/decide")
def decide_screening(screening_id):
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin"])
    screening = svc.get_screening_or_404(screening_id)
    if screening["status"] != "IN_REVIEW":
        raise_err(ERR_INVALID_STATE, "Screening is not IN_REVIEW")
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = body.get("decision")
    if decision == "CLEARED":
        screening["status"] = "CLEARED"
        screening["failure_reason"] = None
        screening["decided_at"] = db.now_iso()
    elif decision == "FAILED":
        failure_reason = body.get("failure_reason")
        if not isinstance(failure_reason, str) or failure_reason == "":
            raise_err(ERR_VALIDATION, "failure_reason is required for a FAILED decision")
        screening["status"] = "FAILED"
        screening["failure_reason"] = failure_reason
        screening["decided_at"] = db.now_iso()
    else:
        raise_err(ERR_VALIDATION, "decision must be CLEARED or FAILED")
    svc.touch(screening)
    return success_object(svc.serialize_screening(screening))


@app.post("/screenings/<screening_id>/reopen")
def reopen_screening(screening_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    screening = svc.get_screening_or_404(screening_id)
    require_driver_ownership(caller, screening["driver_id"])
    if screening["status"] != "FAILED":
        raise_err(ERR_INVALID_STATE, "Screening is not FAILED")
    screening["status"] = "IN_REVIEW"
    screening["failure_reason"] = None
    svc.touch(screening)
    return success_object(svc.serialize_screening(screening))


@app.post("/drivers/<driver_id>/vehicles")
def register_vehicle(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    body = get_json_body()
    require_fields(body, ["vin", "vehicle_class"])
    vin = require_string(body, "vin")
    vehicle_class = require_enum(body, "vehicle_class", VEHICLE_CLASSES)

    for v in db.vehicles.values():
        if v["vin"] == vin and v["status"] == "ACTIVE":
            raise_err(ERR_DUPLICATE_VIN, "VIN is already held by an ACTIVE vehicle")

    vehicle = svc.base_resource()
    vehicle.update(
        driver_id=driver["id"],
        vin=vin,
        vehicle_class=vehicle_class,
        insurance_expires_on=None,
        status="ACTIVE",
    )
    db.vehicles[vehicle["id"]] = vehicle
    return success_object(svc.serialize_vehicle(vehicle), status=201)


@app.get("/drivers/<driver_id>/vehicles")
def list_driver_vehicles(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    limit, offset = parse_pagination()
    items = [v for v in db.vehicles.values() if v["driver_id"] == driver["id"]]
    items.sort(key=lambda v: (v["created_at"], v["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_vehicle(v) for v in page], limit, offset, total)


@app.get("/drivers/<driver_id>/assigned-blocks")
def list_driver_assigned_blocks(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    limit, offset = parse_pagination()
    items = [b for b in db.blocks.values() if b["assigned_driver_id"] == driver["id"]]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_block(b) for b in page], limit, offset, total)


@app.get("/drivers/<driver_id>/rating-events")
def list_driver_rating_events(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    limit, offset = parse_pagination()
    items = [e for e in db.rating_events.values() if e["driver_id"] == driver["id"]]
    items.sort(key=lambda e: (db.parse_iso(e["event_at"]), e["created_at"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_rating_event(e) for e in page], limit, offset, total)


@app.get("/vehicles/<vehicle_id>")
def get_vehicle(vehicle_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "PlatformAdmin", "StationOps"])
    vehicle = svc.get_vehicle_or_404(vehicle_id)
    require_driver_ownership(caller, vehicle["driver_id"])
    return success_object(svc.serialize_vehicle(vehicle))


@app.post("/vehicles/<vehicle_id>/attest-insurance")
def attest_insurance(vehicle_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    vehicle = svc.get_vehicle_or_404(vehicle_id)
    require_driver_ownership(caller, vehicle["driver_id"])
    body = get_json_body()
    require_fields(body, ["insurance_expires_on"])
    value = body.get("insurance_expires_on")
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, "insurance_expires_on must be a YYYY-MM-DD date string")
    import datetime as _dt

    try:
        _dt.date.fromisoformat(value)
    except Exception:
        raise_err(ERR_VALIDATION, "insurance_expires_on must be a YYYY-MM-DD date string")
    vehicle["insurance_expires_on"] = value
    svc.touch(vehicle)
    return success_object(svc.serialize_vehicle(vehicle))


@app.post("/vehicles/<vehicle_id>/retire")
def retire_vehicle(vehicle_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    vehicle = svc.get_vehicle_or_404(vehicle_id)
    require_driver_ownership(caller, vehicle["driver_id"])
    if vehicle["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Vehicle is not ACTIVE")
    vehicle["status"] = "RETIRED"
    svc.touch(vehicle)
    return success_object(svc.serialize_vehicle(vehicle))


@app.get("/vehicles/<vehicle_id>/assignments")
def list_vehicle_assignments(vehicle_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    vehicle = svc.get_vehicle_or_404(vehicle_id)
    require_driver_ownership(caller, vehicle["driver_id"])
    limit, offset = parse_pagination()
    items = [a for a in db.assignments.values() if a["vehicle_id"] == vehicle["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_assignment(a) for a in page], limit, offset, total)


@app.post("/drivers/<driver_id>/activate")
def activate_driver(driver_id):
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    if driver["status"] != "APPLIED":
        raise_err(ERR_INVALID_STATE, "Driver is not APPLIED")

    # safety: latest screening (by created_at, latest first) must be CLEARED
    screenings = [s for s in db.screenings.values() if s["driver_id"] == driver["id"]]
    latest = None
    if screenings:
        screenings.sort(key=lambda s: (s["created_at"], s["id"]))
        latest = screenings[-1]
    if latest is None or latest["status"] != "CLEARED":
        raise_err(ERR_SCREENING_NOT_CLEARED, "Latest screening is not CLEARED")

    # safety: >= 1 ACTIVE vehicle with ATTESTED insurance
    eligible = any(
        v["driver_id"] == driver["id"]
        and v["status"] == "ACTIVE"
        and svc.insurance_status(v) == "ATTESTED"
        for v in db.vehicles.values()
    )
    if not eligible:
        raise_err(ERR_NO_ELIGIBLE_VEHICLE, "No ACTIVE vehicle with ATTESTED insurance")

    driver["status"] = "ACTIVE"
    svc.touch(driver)
    return success_object(svc.serialize_driver(driver))


@app.post("/drivers/<driver_id>/deactivate")
def deactivate_driver(driver_id):
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    if driver["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Driver is not ACTIVE")

    # hop 1: forfeit every non-terminal assignment (SYSTEM_DEACTIVATION)
    # hop 2: each forfeiture relists its block
    targets = [
        a for a in db.assignments.values()
        if a["driver_id"] == driver["id"] and a["status"] in svc.NON_TERMINAL_ASSIGNMENT_STATUSES
    ]
    targets.sort(key=lambda a: (a["created_at"], a["id"]))
    for assignment in targets:
        svc.forfeit_assignment(assignment, "SYSTEM_DEACTIVATION", recompute_driver=False)

    driver["status"] = "DEACTIVATED"
    # hop 3 + hop 4: single reliability/tier recompute (hop 5 offer revocation
    # happens inside recompute_tier on demotion)
    svc.recompute_driver_aggregates(driver, reliability_changed=True)
    svc.touch(driver)
    return success_object(svc.serialize_driver(driver))


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

@app.get("/blocks/<block_id>")
def get_block(block_id):
    caller = authenticate()
    require_roles(caller, ["StationOps", "PlatformAdmin", "Driver"])
    block = svc.get_block_or_404(block_id)
    return success_object(svc.serialize_block(block))


@app.post("/blocks/<block_id>/publish")
def publish_block(block_id):
    caller = authenticate()
    require_roles(caller, ["StationOps"])
    block = svc.get_block_or_404(block_id)
    if block["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Block is not DRAFT")
    # temporal gate on publish: starts_at must still lie in the future
    if db.parse_iso(block["starts_at"]) <= db.now():
        raise_err(ERR_INVALID_STATE, "Block starts_at is not in the future")
    block["status"] = "PUBLISHED"
    block["estimated_pay_cents"] = svc.estimated_pay_cents(block)
    svc.touch(block)
    return success_object(svc.serialize_block(block))


@app.post("/blocks/<block_id>/revise")
def revise_block(block_id):
    caller = authenticate()
    require_roles(caller, ["StationOps"])
    block = svc.get_block_or_404(block_id)
    if block["status"] not in ("DRAFT", "PUBLISHED"):
        raise_err(ERR_INVALID_STATE, "Only DRAFT or PUBLISHED blocks may be revised")
    body = get_json_body()
    require_fields(body, ["expected_block_version"])

    new_starts = None
    new_ends = None
    new_class = None
    new_pay = None
    if "starts_at" in body and body["starts_at"] is not None:
        new_starts = parse_dt_field(body, "starts_at")
    if "ends_at" in body and body["ends_at"] is not None:
        new_ends = parse_dt_field(body, "ends_at")
    if "required_vehicle_class" in body and body["required_vehicle_class"] is not None:
        new_class = require_enum(body, "required_vehicle_class", VEHICLE_CLASSES)
    if "base_pay_cents" in body and body["base_pay_cents"] is not None:
        new_pay = require_positive_int(body, "base_pay_cents")

    eff_starts = new_starts if new_starts is not None else db.parse_iso(block["starts_at"])
    eff_ends = new_ends if new_ends is not None else db.parse_iso(block["ends_at"])
    if eff_ends <= eff_starts:
        raise_err(ERR_VALIDATION, "ends_at must be strictly after starts_at")

    # OCC evaluated at the money-side priority tier
    expected = body.get("expected_block_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_VALIDATION, "expected_block_version must be an integer")
    if expected != block["version"]:
        raise_err(ERR_STALE_VERSION, "Block version has advanced")

    if new_starts is not None:
        block["starts_at"] = normalize_dt(new_starts)
    if new_ends is not None:
        block["ends_at"] = normalize_dt(new_ends)
    if new_class is not None:
        block["required_vehicle_class"] = new_class
    if new_pay is not None:
        block["base_pay_cents"] = new_pay
    block["estimated_pay_cents"] = svc.estimated_pay_cents(block)
    svc.touch(block)
    return success_object(svc.serialize_block(block))


@app.post("/blocks/<block_id>/cancel")
def cancel_block(block_id):
    caller = authenticate()
    require_roles(caller, ["StationOps"])
    block = svc.get_block_or_404(block_id)
    if block["status"] not in ("DRAFT", "PUBLISHED"):
        raise_err(ERR_INVALID_STATE, "Only DRAFT or PUBLISHED blocks may be cancelled")
    block["status"] = "CANCELLED"
    svc.touch(block)
    return success_object(svc.serialize_block(block))


@app.post("/blocks/<block_id>/accept")
def accept_block(block_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    block = svc.get_block_or_404(block_id)
    body = get_json_body()
    require_fields(body, ["vehicle_id"])
    vehicle_id = body.get("vehicle_id")
    if not isinstance(vehicle_id, str):
        raise_err(ERR_VALIDATION, "vehicle_id must be a string")
    assignment = run_acceptance(caller, block, vehicle_id, offer=None)
    return success_object(svc.serialize_assignment(assignment), status=201)


@app.get("/blocks/<block_id>/offers")
def list_block_offers(block_id):
    caller = authenticate()
    require_roles(caller, ["StationOps", "PlatformAdmin"])
    block = svc.get_block_or_404(block_id)
    limit, offset = parse_pagination()
    from flask import request

    status_filter = request.args.get("status")
    items = [o for o in db.offers.values() if o["block_id"] == block["id"]]
    if status_filter is not None:
        items = [o for o in items if o["status"] == status_filter]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_offer(o) for o in page], limit, offset, total)


@app.get("/blocks/<block_id>/assignments")
def list_block_assignments(block_id):
    caller = authenticate()
    require_roles(caller, ["StationOps", "PlatformAdmin", "Driver"])
    block = svc.get_block_or_404(block_id)
    limit, offset = parse_pagination()
    from flask import request

    status_filter = request.args.get("status")
    items = [a for a in db.assignments.values() if a["block_id"] == block["id"]]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_assignment(a) for a in page], limit, offset, total)


@app.post("/blocks/<block_id>/offers")
def create_offer(block_id):
    caller = authenticate()
    require_roles(caller, ["StationOps"])
    block = svc.get_block_or_404(block_id)
    body = get_json_body()
    require_fields(body, ["driver_id", "tier_floor", "expires_at"])
    driver_id = body.get("driver_id")
    if not isinstance(driver_id, str):
        raise_err(ERR_VALIDATION, "driver_id must be a string")
    driver = svc.get_driver_or_404(driver_id)
    tier_floor = require_enum(body, "tier_floor", TIERS)
    expires_at = parse_dt_field(body, "expires_at")

    if block["status"] != "PUBLISHED":
        raise_err(ERR_BLOCK_NOT_PUBLISHED, "Block is not PUBLISHED")

    # tier gate at creation: driver's tier must rank at or above the floor
    if svc.TIER_RANK[driver["rating_tier"]] < svc.TIER_RANK[tier_floor]:
        raise_err(ERR_INVALID_STATE, "Driver's tier is below the offer's tier_floor")

    # buffered gap: offered block window must sit >= 30 minutes (either
    # direction) from every existing non-terminal assignment window of the
    # driver; exactly 30 minutes is allowed
    buf = timedelta(minutes=svc.OFFER_BUFFER_MINUTES)
    new_start = db.parse_iso(block["starts_at"])
    new_end = db.parse_iso(block["ends_at"])
    for a in db.assignments.values():
        if a["driver_id"] != driver["id"] or a["status"] not in svc.NON_TERMINAL_ASSIGNMENT_STATUSES:
            continue
        other = db.blocks.get(a["block_id"])
        if other is None:
            continue
        o_start = db.parse_iso(other["starts_at"])
        o_end = db.parse_iso(other["ends_at"])
        if new_start < o_end + buf and o_start < new_end + buf:
            raise_err(ERR_OFFER_BUFFER_CONFLICT, "Block window is within 30 minutes of an existing assignment")

    offer = svc.base_resource()
    offer.update(
        block_id=block["id"],
        driver_id=driver["id"],
        tier_floor=tier_floor,
        expires_at=normalize_dt(expires_at),
        status="OFFERED",
    )
    db.offers[offer["id"]] = offer
    return success_object(svc.serialize_offer(offer), status=201)


# ---------------------------------------------------------------------------
# Offers
# ---------------------------------------------------------------------------

@app.get("/offers/<offer_id>")
def get_offer(offer_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    offer = svc.get_offer_or_404(offer_id)
    return success_object(svc.serialize_offer(offer))


@app.post("/offers/<offer_id>/accept")
def accept_offer(offer_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    offer = svc.get_offer_or_404(offer_id)
    if caller.user_id != offer["driver_id"]:
        raise_err(ERR_OFFER_WRONG_DRIVER, "Offer belongs to a different driver")
    body = get_json_body()
    require_fields(body, ["vehicle_id"])
    vehicle_id = body.get("vehicle_id")
    if not isinstance(vehicle_id, str):
        raise_err(ERR_VALIDATION, "vehicle_id must be a string")
    if offer["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "Offer is not OFFERED")
    if db.now() >= db.parse_iso(offer["expires_at"]):
        raise_err(ERR_OFFER_EXPIRED, "Offer has expired")
    block = svc.get_block_or_404(offer["block_id"])
    assignment = run_acceptance(caller, block, vehicle_id, offer=offer)
    return success_object(svc.serialize_assignment(assignment), status=201)


@app.post("/offers/<offer_id>/decline")
def decline_offer(offer_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    offer = svc.get_offer_or_404(offer_id)
    if caller.user_id != offer["driver_id"]:
        raise_err(ERR_OFFER_WRONG_DRIVER, "Offer belongs to a different driver")
    if offer["status"] != "OFFERED":
        raise_err(ERR_INVALID_STATE, "Offer is not OFFERED")
    if db.now() >= db.parse_iso(offer["expires_at"]):
        raise_err(ERR_OFFER_EXPIRED, "Offer has expired")
    offer["status"] = "DECLINED"
    svc.touch(offer)
    return success_object(svc.serialize_offer(offer))


@app.get("/offers/<offer_id>/assignments")
def list_offer_assignments(offer_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    offer = svc.get_offer_or_404(offer_id)
    limit, offset = parse_pagination()
    items = [a for a in db.assignments.values() if a["offer_id"] == offer["id"]]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_assignment(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------

@app.get("/assignments/<assignment_id>")
def get_assignment(assignment_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    assignment = svc.get_assignment_or_404(assignment_id)
    require_driver_ownership(caller, assignment["driver_id"])
    return success_object(svc.serialize_assignment(assignment))


@app.get("/drivers/<driver_id>/assignments")
def list_driver_assignments(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    limit, offset = parse_pagination()
    from flask import request

    status_filter = request.args.get("status")
    items = [a for a in db.assignments.values() if a["driver_id"] == driver["id"]]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_assignment(a) for a in page], limit, offset, total)


@app.get("/drivers/<driver_id>/offers")
def list_driver_offers(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    limit, offset = parse_pagination()
    from flask import request

    status_filter = request.args.get("status")
    items = [o for o in db.offers.values() if o["driver_id"] == driver["id"]]
    if status_filter is not None:
        items = [o for o in items if o["status"] == status_filter]
    items.sort(key=lambda o: (o["created_at"], o["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_offer(o) for o in page], limit, offset, total)


@app.post("/assignments/<assignment_id>/check-in")
def check_in(assignment_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    assignment = svc.get_assignment_or_404(assignment_id)
    require_driver_ownership(caller, assignment["driver_id"])
    if assignment["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE, "Assignment is not ASSIGNED")

    driver = svc.get_driver_or_404(assignment["driver_id"])
    if driver["status"] != "ACTIVE":
        raise_err(ERR_DRIVER_NOT_ACTIVE, "Driver is not ACTIVE")

    block = svc.get_block_or_404(assignment["block_id"])
    vehicle = svc.get_vehicle_or_404(assignment["vehicle_id"])

    # safety before temporal: insurance must cover the whole block window under
    # closed-interval containment (insurance_expires_on >= date(block.ends_at))
    expires = vehicle.get("insurance_expires_on")
    if expires is None or expires < db.parse_iso(block["ends_at"]).date().isoformat():
        raise_err(ERR_INSURANCE_WINDOW_LAPSE, "Insurance does not cover the whole block window")

    now = db.now()
    starts_at = db.parse_iso(block["starts_at"])
    if now < starts_at - timedelta(minutes=svc.CHECK_IN_EARLY_MINUTES):
        raise_err(ERR_CHECKIN_TOO_EARLY, "Check-in is more than 30 minutes before block start")
    if now > starts_at + timedelta(minutes=svc.CHECK_IN_LATE_MINUTES):
        raise_err(ERR_CHECKIN_WINDOW_CLOSED, "Check-in is more than 15 minutes after block start")

    assignment["status"] = "CHECKED_IN"
    assignment["check_in_at"] = db.now_iso()
    svc.touch(assignment)

    block["status"] = "IN_PROGRESS"
    svc.touch(block)
    return success_object(svc.serialize_assignment(assignment))


@app.post("/assignments/<assignment_id>/load-packages")
def load_packages(assignment_id):
    caller = authenticate()
    require_roles(caller, ["StationOps"])
    assignment = svc.get_assignment_or_404(assignment_id)
    if assignment["status"] != "CHECKED_IN":
        raise_err(ERR_INVALID_STATE, "Assignment is not CHECKED_IN")
    body = get_json_body()
    require_fields(body, ["packages"])
    packages_input = body.get("packages")
    if not isinstance(packages_input, list) or len(packages_input) == 0:
        raise_err(ERR_VALIDATION, "packages must be a non-empty array")

    seen_codes = set()
    for el in packages_input:
        if not isinstance(el, dict):
            raise_err(ERR_VALIDATION, "Each package must be an object")
        for f in ("tracking_code", "billable_weight_kg", "promised_by"):
            if f not in el or el[f] is None:
                raise_err(ERR_VALIDATION, "Missing required package field: %s" % f)
        if not isinstance(el["tracking_code"], str) or el["tracking_code"] == "":
            raise_err(ERR_VALIDATION, "tracking_code must be a non-empty string")
        if el["tracking_code"] in seen_codes:
            raise_err(ERR_VALIDATION, "tracking_code must be unique within the assignment")
        seen_codes.add(el["tracking_code"])
        w = el["billable_weight_kg"]
        if isinstance(w, bool) or not isinstance(w, (int, float)) or w <= 0:
            raise_err(ERR_VALIDATION, "billable_weight_kg must be positive")
        try:
            db.parse_iso(el["promised_by"])
        except Exception:
            raise_err(ERR_VALIDATION, "promised_by is not a parseable ISO8601 datetime")

    for el in packages_input:
        package = svc.base_resource()
        package.update(
            assignment_id=assignment["id"],
            tracking_code=el["tracking_code"],
            billable_weight_kg=el["billable_weight_kg"],
            promised_by=normalize_dt(db.parse_iso(el["promised_by"])),
            status="LOADED",
            delivered_at=None,
            photo_url="",
            photo_gps_tagged=False,
            photo_compliant=None,
            on_time_delivery=None,
            failure_reason=None,
        )
        db.packages[package["id"]] = package

    assignment["status"] = "ROUTE_ASSIGNED"
    svc.touch(assignment)
    return success_object(svc.serialize_assignment(assignment))


@app.get("/assignments/<assignment_id>/packages")
def list_assignment_packages(assignment_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps"])
    assignment = svc.get_assignment_or_404(assignment_id)
    require_driver_ownership(caller, assignment["driver_id"])
    limit, offset = parse_pagination()
    items = [p for p in db.packages.values() if p["assignment_id"] == assignment["id"]]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_package(p) for p in page], limit, offset, total)


@app.get("/assignments/<assignment_id>/rating-events")
def list_assignment_rating_events(assignment_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    assignment = svc.get_assignment_or_404(assignment_id)
    require_driver_ownership(caller, assignment["driver_id"])
    limit, offset = parse_pagination()
    items = [e for e in db.rating_events.values() if e["assignment_id"] == assignment["id"]]
    items.sort(key=lambda e: (db.parse_iso(e["event_at"]), e["created_at"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_rating_event(e) for e in page], limit, offset, total)


@app.post("/assignments/<assignment_id>/depart")
def depart(assignment_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    assignment = svc.get_assignment_or_404(assignment_id)
    require_driver_ownership(caller, assignment["driver_id"])
    if assignment["status"] != "ROUTE_ASSIGNED":
        raise_err(ERR_INVALID_STATE, "Assignment is not ROUTE_ASSIGNED")
    for p in db.packages.values():
        if p["assignment_id"] == assignment["id"] and p["status"] == "LOADED":
            p["status"] = "OUT_FOR_DELIVERY"
            svc.touch(p)
    assignment["status"] = "IN_DELIVERY"
    svc.touch(assignment)
    return success_object(svc.serialize_assignment(assignment))


@app.post("/assignments/<assignment_id>/forfeit")
def forfeit(assignment_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    assignment = svc.get_assignment_or_404(assignment_id)
    require_driver_ownership(caller, assignment["driver_id"])
    if assignment["status"] != "ASSIGNED":
        raise_err(ERR_INVALID_STATE, "Assignment is not ASSIGNED")
    svc.forfeit_assignment(assignment, "DRIVER_INITIATED")
    return success_object(svc.serialize_assignment(assignment))


@app.post("/assignments/<assignment_id>/complete")
def complete_assignment(assignment_id):
    caller = authenticate()
    require_roles(caller, ["StationOps"])
    assignment = svc.get_assignment_or_404(assignment_id)
    if assignment["status"] != "IN_DELIVERY":
        raise_err(ERR_INVALID_STATE, "Assignment is not IN_DELIVERY")

    assignment_packages = [p for p in db.packages.values() if p["assignment_id"] == assignment["id"]]
    for p in assignment_packages:
        if p["status"] not in ("DELIVERED", "DELIVERY_FAILED"):
            raise_err(ERR_PACKAGE_NOT_DELIVERABLE, "A package is still LOADED or OUT_FOR_DELIVERY")

    block = svc.get_block_or_404(assignment["block_id"])
    driver = svc.get_driver_or_404(assignment["driver_id"])

    # hop 1: DELIVERY_FAILED packages -> RETURNED_TO_STATION
    returned_count = 0
    late_count = 0
    noncompliant_count = 0
    for p in assignment_packages:
        if p["status"] == "DELIVERY_FAILED":
            p["status"] = "RETURNED_TO_STATION"
            svc.touch(p)
        if p["status"] == "RETURNED_TO_STATION":
            returned_count += 1
        elif p["status"] == "DELIVERED":
            if p["on_time_delivery"] is False:
                late_count += 1
            if p["photo_compliant"] is False:
                noncompliant_count += 1

    # hop 1: rating event (completion_rating_points), floored at 100
    points = max(
        100,
        500
        - 100 * late_count
        - 50 * noncompliant_count
        - 200 * returned_count,
    )
    event = svc.base_resource()
    event.update(
        driver_id=driver["id"],
        assignment_id=assignment["id"],
        event_type="COMPLETION_SCORE",
        points=points,
        event_at=db.now_iso(),
    )
    db.rating_events[event["id"]] = event

    # hop 1: pay statement (final_settlement_pay), pinned evaluation order
    gross = svc.provisional_pay_cents(block, assignment["surge_multiplier_snapshot_bp"])
    tier_applied = assignment["tier_at_accept"]
    tier_bonus = svc.round_half_up(Decimal(gross) * Decimal(svc.TIER_BONUS_BP[tier_applied]) / Decimal(10000))
    surcharges = 0
    for p in assignment_packages:
        if p["status"] == "DELIVERED":
            surcharges += svc.round_half_up(
                Decimal(str(p["billable_weight_kg"])) * Decimal(svc.SURCHARGE_PER_KG_CENTS)
            )
    raw_penalties = (
        svc.LATE_PENALTY_CENTS * late_count
        + svc.PHOTO_PENALTY_CENTS * noncompliant_count
        + svc.FAILED_PENALTY_CENTS * returned_count
    )
    penalty_cap = svc.round_half_up(Decimal(gross + tier_bonus) * Decimal("0.5"))
    penalties = min(raw_penalties, penalty_cap)
    final_pay = gross + tier_bonus + surcharges - penalties

    statement = svc.base_resource()
    statement.update(
        assignment_id=assignment["id"],
        status="OPEN",
        gross_cents=gross,
        tier_bonus_cents=tier_bonus,
        surcharges_cents=surcharges,
        penalties_cents=penalties,
        final_pay_cents=final_pay,
        tier_applied=tier_applied,
        settled_at=None,
        voided_at=None,
    )
    db.pay_statements[statement["id"]] = statement

    # hops 2-4: rating recompute -> tier recompute -> tier-floor offer revocation
    svc.recompute_driver_aggregates(driver, rating_changed=True)
    driver["updated_at"] = db.now_iso()
    driver["version"] += 1

    assignment["status"] = "COMPLETED"
    svc.touch(assignment)

    block["status"] = "COMPLETED"
    svc.touch(block)

    return success_object(svc.serialize_pay_statement(statement), status=201)


@app.get("/assignments/<assignment_id>/pay-statement")
def get_assignment_pay_statement(assignment_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "StationOps", "PlatformAdmin"])
    assignment = svc.get_assignment_or_404(assignment_id)
    require_driver_ownership(caller, assignment["driver_id"])
    limit, offset = parse_pagination()
    items = [ps for ps in db.pay_statements.values() if ps["assignment_id"] == assignment["id"]]
    items.sort(key=lambda ps: (ps["created_at"], ps["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_pay_statement(ps) for ps in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Packages
# ---------------------------------------------------------------------------

@app.post("/packages/<package_id>/deliver")
def deliver_package(package_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    package = svc.get_package_or_404(package_id)
    assignment = svc.get_assignment_or_404(package["assignment_id"])
    require_driver_ownership(caller, assignment["driver_id"])
    if package["status"] != "OUT_FOR_DELIVERY":
        raise_err(ERR_PACKAGE_NOT_DELIVERABLE, "Package is not OUT_FOR_DELIVERY")
    if assignment["status"] != "IN_DELIVERY":
        raise_err(ERR_INVALID_STATE, "Assignment is not IN_DELIVERY")
    driver = svc.get_driver_or_404(assignment["driver_id"])
    if driver["status"] != "ACTIVE":
        raise_err(ERR_DRIVER_NOT_ACTIVE, "Driver is not ACTIVE")
    body = get_json_body()
    require_fields(body, ["photo_url", "photo_gps_tagged"])
    photo_url = body.get("photo_url")
    if not isinstance(photo_url, str):
        raise_err(ERR_VALIDATION, "photo_url must be a string")
    photo_gps_tagged = body.get("photo_gps_tagged")
    if not isinstance(photo_gps_tagged, bool):
        raise_err(ERR_VALIDATION, "photo_gps_tagged must be a boolean")

    delivered_at = db.now()
    package["delivered_at"] = db.now_iso()
    package["photo_url"] = photo_url
    package["photo_gps_tagged"] = photo_gps_tagged
    package["photo_compliant"] = (photo_url != "") and (photo_gps_tagged is True)
    package["on_time_delivery"] = delivered_at <= db.parse_iso(package["promised_by"])
    package["status"] = "DELIVERED"
    svc.touch(package)
    return success_object(svc.serialize_package(package))


@app.post("/packages/<package_id>/report-failed")
def report_failed_package(package_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    package = svc.get_package_or_404(package_id)
    assignment = svc.get_assignment_or_404(package["assignment_id"])
    require_driver_ownership(caller, assignment["driver_id"])
    if package["status"] != "OUT_FOR_DELIVERY":
        raise_err(ERR_PACKAGE_NOT_DELIVERABLE, "Package is not OUT_FOR_DELIVERY")
    body = get_json_body()
    require_fields(body, ["reason"])
    reason = require_string(body, "reason")
    package["failure_reason"] = reason
    package["status"] = "DELIVERY_FAILED"
    svc.touch(package)
    return success_object(svc.serialize_package(package))


# ---------------------------------------------------------------------------
# Pay statements
# ---------------------------------------------------------------------------

@app.post("/pay-statements/<pay_statement_id>/settle")
def settle_pay_statement(pay_statement_id):
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin"])
    statement = svc.get_pay_statement_or_404(pay_statement_id)
    if statement["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "PayStatement is not OPEN")
    statement["status"] = "SETTLED"
    statement["settled_at"] = db.now_iso()
    svc.touch(statement)
    assignment = db.assignments.get(statement["assignment_id"])
    if assignment is not None:
        block = db.blocks.get(assignment["block_id"])
        if block is not None:
            station = db.stations.get(block["station_id"])
            if station is not None:
                svc.recompute_station_liabilities(station)
    return success_object(svc.serialize_pay_statement(statement))


@app.post("/pay-statements/<pay_statement_id>/void")
def void_pay_statement(pay_statement_id):
    caller = authenticate()
    require_roles(caller, ["PlatformAdmin"])
    statement = svc.get_pay_statement_or_404(pay_statement_id)
    if statement["status"] != "SETTLED":
        raise_err(ERR_INVALID_STATE, "PayStatement is not SETTLED")
    statement["status"] = "VOIDED"
    statement["voided_at"] = db.now_iso()
    svc.touch(statement)
    assignment = db.assignments.get(statement["assignment_id"])
    if assignment is not None:
        block = db.blocks.get(assignment["block_id"])
        if block is not None:
            station = db.stations.get(block["station_id"])
            if station is not None:
                svc.recompute_station_liabilities(station)
    return success_object(svc.serialize_pay_statement(statement))


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------

OPEN_APPEAL_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "EVIDENCE_REQUESTED")


@app.post("/drivers/<driver_id>/appeals")
def create_appeal(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    body = get_json_body()
    require_fields(body, ["reason"])
    reason = require_string(body, "reason")

    if driver["status"] != "DEACTIVATED":
        raise_err(ERR_APPEAL_NOT_OPEN, "Driver is not DEACTIVATED")
    for a in db.appeals.values():
        if a["driver_id"] == driver["id"] and a["status"] in OPEN_APPEAL_STATUSES:
            raise_err(ERR_APPEAL_NOT_OPEN, "An open appeal already exists for this driver")

    appeal = svc.base_resource()
    appeal.update(
        driver_id=driver["id"],
        reason=reason,
        status="SUBMITTED",
        evidence_count=0,
        decision_reason=None,
    )
    db.appeals[appeal["id"]] = appeal
    return success_object(svc.serialize_appeal(appeal), status=201)


@app.get("/drivers/<driver_id>/appeals")
def list_driver_appeals(driver_id):
    caller = authenticate()
    require_roles(caller, ["Driver", "AppealsReviewer", "PlatformAdmin"])
    driver = svc.get_driver_or_404(driver_id)
    require_driver_ownership(caller, driver["id"])
    limit, offset = parse_pagination()
    from flask import request

    status_filter = request.args.get("status")
    items = [a for a in db.appeals.values() if a["driver_id"] == driver["id"]]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_appeal(a) for a in page], limit, offset, total)


@app.post("/appeals/<appeal_id>/submit-evidence")
def submit_evidence(appeal_id):
    caller = authenticate()
    require_roles(caller, ["Driver"])
    appeal = svc.get_appeal_or_404(appeal_id)
    require_driver_ownership(caller, appeal["driver_id"])
    if appeal["status"] not in ("SUBMITTED", "EVIDENCE_REQUESTED"):
        raise_err(ERR_INVALID_STATE, "Appeal is not SUBMITTED or EVIDENCE_REQUESTED")
    body = get_json_body()
    require_fields(body, ["evidence_note"])
    require_string(body, "evidence_note")
    appeal["status"] = "UNDER_REVIEW"
    appeal["evidence_count"] += 1
    svc.touch(appeal)
    return success_object(svc.serialize_appeal(appeal))


@app.post("/appeals/<appeal_id>/request-evidence")
def request_evidence(appeal_id):
    caller = authenticate()
    require_roles(caller, ["AppealsReviewer"])
    appeal = svc.get_appeal_or_404(appeal_id)
    if appeal["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Appeal is not UNDER_REVIEW")
    appeal["status"] = "EVIDENCE_REQUESTED"
    svc.touch(appeal)
    return success_object(svc.serialize_appeal(appeal))


@app.post("/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    caller = authenticate()
    require_roles(caller, ["AppealsReviewer"])
    appeal = svc.get_appeal_or_404(appeal_id)
    if appeal["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Appeal is not UNDER_REVIEW")
    if appeal["evidence_count"] < 1:
        raise_err(ERR_INVALID_STATE, "Appeal requires at least one evidence submission")
    body = get_json_body()
    require_fields(body, ["decision"])
    decision = body.get("decision")
    if decision not in ("UPHELD", "OVERTURNED"):
        raise_err(ERR_VALIDATION, "decision must be UPHELD or OVERTURNED")
    decision_reason = body.get("decision_reason")
    if decision_reason is not None and not isinstance(decision_reason, str):
        raise_err(ERR_VALIDATION, "decision_reason must be a string")

    appeal["status"] = decision
    appeal["decision_reason"] = decision_reason
    svc.touch(appeal)

    if decision == "OVERTURNED":
        driver = db.drivers.get(appeal["driver_id"])
        if driver is not None and driver["status"] == "DEACTIVATED":
            # strike reversal: deactivation-forfeits stop counting
            for a in db.assignments.values():
                if (
                    a["driver_id"] == driver["id"]
                    and a["forfeit_cause"] == "SYSTEM_DEACTIVATION"
                    and not a["strike_reversed"]
                ):
                    a["strike_reversed"] = True
                    svc.touch(a)
            driver["status"] = "ACTIVE"
            svc.recompute_driver_aggregates(driver, reliability_changed=True)
            svc.touch(driver)

    return success_object(svc.serialize_appeal(appeal))


# ---------------------------------------------------------------------------
# Driver feed
# ---------------------------------------------------------------------------

@app.get("/driver-feed/blocks")
def driver_feed():
    caller = authenticate()
    require_roles(caller, ["Driver"])
    driver = svc.get_driver_or_404(caller.user_id)
    limit, offset = parse_pagination()
    from flask import request

    station_filter = request.args.get("station_id")
    now = db.now()
    lead_minutes = svc.TIER_LEAD_MIN[driver["rating_tier"]]
    threshold = now + timedelta(minutes=lead_minutes)
    items = [
        b for b in db.blocks.values()
        if b["status"] == "PUBLISHED" and db.parse_iso(b["starts_at"]) <= threshold
    ]
    if station_filter is not None:
        items = [b for b in items if b["station_id"] == station_filter]
    items.sort(key=lambda b: (db.parse_iso(b["starts_at"]), b["created_at"], b["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([svc.serialize_block(b) for b in page], limit, offset, total)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
