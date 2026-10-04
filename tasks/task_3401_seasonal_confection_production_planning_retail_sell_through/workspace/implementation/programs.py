"""SeasonalProgram routes: create, read, supply-summary, advance (OCC).

The advance endpoint drives the whole program state machine, including the
allocation waterfall at IN_PRODUCTION -> SHIPPING and the three-link pull
cascade at ON_SHELF -> DISPOSITION.
"""

from decimal import Decimal

from flask import Blueprint

from db import db, new_id, next_seq, now_ts3, touch
from domain import (
    SHORTFALL_CREDIT_PCT, TIER_RANK, SEASON_CODES, MAX_REOPEN,
    round_cents, get_program, ser_program,
    program_produced_total, program_committed_total, program_allocated_total,
    program_shipped_total, program_disposed_total, produced_units_of_product,
    remaining_pool,
)
from errors import (
    ApiError, ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_PROGRAM_ADVANCE_TOO_EARLY, ERR_PROGRAM_REOPEN_EXHAUSTED,
    ERR_NO_PRODUCTION_SCHEDULED, ERR_UNDISPOSED_STOCK_REMAINS,
)
from middleware import authorize, ROLE_PLATFORM_ADMIN, ALL_ROLES
from respond import ok, created
from validate import json_body, v_str, v_int, v_enum, v_dt

bp = Blueprint("programs", __name__)

PROGRAM_STATUSES = (
    "PLANNING", "OPEN_FOR_COMMITMENTS", "LOCKED", "IN_PRODUCTION", "SHIPPING",
    "ON_SHELF", "DISPOSITION", "CLOSED", "CANCELLED",
)

# Valid (from_state, to_state) advance pairs per SCAFFOLD 1.2 / PRD 3.
ADVANCE_TRANSITIONS = {
    ("PLANNING", "OPEN_FOR_COMMITMENTS"),
    ("OPEN_FOR_COMMITMENTS", "LOCKED"),
    ("LOCKED", "OPEN_FOR_COMMITMENTS"),
    ("LOCKED", "IN_PRODUCTION"),
    ("IN_PRODUCTION", "SHIPPING"),
    ("SHIPPING", "ON_SHELF"),
    ("ON_SHELF", "DISPOSITION"),
    ("DISPOSITION", "CLOSED"),
    ("PLANNING", "CANCELLED"),
    ("OPEN_FOR_COMMITMENTS", "CANCELLED"),
}


def _create_entity(table, fields):
    entity = {"id": new_id(), "_seq": next_seq(),
              "created_at": now_ts3(), "updated_at": now_ts3(), "version": 1}
    entity.update(fields)
    table[entity["id"]] = entity
    return entity


@bp.post("/confection/seasonal-programs")
def create_program():
    data = json_body()
    season_code = v_enum(data, "season_code", SEASON_CODES)
    season_year = v_int(data, "season_year", min_v=2026)
    open_dt, open_raw = v_dt(data, "commitment_open_on")
    close_dt, close_raw = v_dt(data, "commitment_close_on")
    deadline_dt, deadline_raw = v_dt(data, "production_deadline_on")
    ship_open_dt, ship_open_raw = v_dt(data, "ship_window_open_on")
    ship_close_dt, ship_close_raw = v_dt(data, "ship_window_close_on")
    on_shelf_dt, on_shelf_raw = v_dt(data, "on_shelf_on")
    pull_dt, pull_raw = v_dt(data, "pull_on")
    destroy_dt, destroy_raw = v_dt(data, "destroy_by_on")
    retail_price = v_int(data, "retail_price_cents", min_v=1)
    forecast = v_int(data, "forecast_units", min_v=1)

    # Window chain (PRD 2.5): open < close <= deadline <= ship_open <
    # ship_close <= on_shelf < pull < destroy_by. Violations are 400.
    chain_ok = (
        open_dt < close_dt <= deadline_dt <= ship_open_dt < ship_close_dt
        <= on_shelf_dt < pull_dt < destroy_dt
    )
    if not chain_ok:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "program window dates violate the required ordering")

    authorize(ROLE_PLATFORM_ADMIN)

    for p in db.programs.values():
        if p["season_code"] == season_code and p["season_year"] == season_year:
            raise ApiError(409, ERR_DUPLICATE_RESOURCE,
                           "a program already exists for this season_code and season_year")

    program = _create_entity(db.programs, {
        "season_code": season_code,
        "season_year": season_year,
        "commitment_open_on": open_raw,
        "commitment_close_on": close_raw,
        "production_deadline_on": deadline_raw,
        "ship_window_open_on": ship_open_raw,
        "ship_window_close_on": ship_close_raw,
        "on_shelf_on": on_shelf_raw,
        "pull_on": pull_raw,
        "destroy_by_on": destroy_raw,
        "_commitment_open_dt": open_dt,
        "_commitment_close_dt": close_dt,
        "_production_deadline_dt": deadline_dt,
        "_ship_window_open_dt": ship_open_dt,
        "_ship_window_close_dt": ship_close_dt,
        "_on_shelf_dt": on_shelf_dt,
        "_pull_dt": pull_dt,
        "_destroy_by_dt": destroy_dt,
        "retail_price_cents": retail_price,
        "forecast_units": forecast,
        "reopen_count": 0,
        "status": "PLANNING",
    })
    return created(ser_program(program))


@bp.get("/confection/seasonal-programs/<program_id>")
def read_program(program_id):
    authorize(*ALL_ROLES)
    program = get_program(program_id)
    return ok(ser_program(program))


@bp.get("/confection/seasonal-programs/<program_id>/supply-summary")
def supply_summary(program_id):
    authorize(*ALL_ROLES)
    program = get_program(program_id)
    pool = 0
    for product in db.products.values():
        if product["kind"] == "SEASONAL" and product["program_id"] == program["id"]:
            pool += remaining_pool(product["id"])
    return ok({
        "program_id": program["id"],
        "produced_units_total": program_produced_total(program["id"]),
        "committed_units_total": program_committed_total(program["id"]),
        "allocated_units_total": program_allocated_total(program["id"]),
        "shipped_units_total": program_shipped_total(program["id"]),
        "disposed_units_total": program_disposed_total(program["id"]),
        "remaining_supply_pool_units": pool,
    })


def _run_allocation(program):
    """commitment_supply_allocation (PRD 3.5): per SEASONAL product, drain the
    produced pool across CONFIRMED commitments in tier-major, created_at-minor
    order; full grant -> ALLOCATED, partial/zero grant -> SHORTED plus a 10%
    shortfall credit posted to the retailer account."""
    products = [p for p in db.products.values()
                if p["kind"] == "SEASONAL" and p["program_id"] == program["id"]]
    for product in products:
        remaining = produced_units_of_product(product["id"])
        eligible = [c for c in db.commitments.values()
                    if c["product_id"] == product["id"] and c["status"] == "CONFIRMED"]
        eligible.sort(key=lambda c: (
            TIER_RANK[db.retailers[c["retailer_id"]]["tier"]],
            c["created_at"],
            c["_seq"],
        ))
        for commitment in eligible:
            grant = min(commitment["committed_units"], remaining)
            remaining -= grant
            commitment["allocated_units"] = grant
            if grant == commitment["committed_units"]:
                commitment["status"] = "ALLOCATED"
            else:
                commitment["status"] = "SHORTED"
                shortfall = commitment["committed_units"] - grant
                credit = round_cents(
                    Decimal(shortfall)
                    * Decimal(program["retail_price_cents"])
                    * SHORTFALL_CREDIT_PCT
                )
                retailer = db.retailers[commitment["retailer_id"]]
                retailer["credit_balance_cents"] += credit
                touch(retailer)
            touch(commitment)


def _pull_cascade(program):
    """Pull cascade (PRD 3.9): LINK 1 quarantines every AVAILABLE seasonal lot
    of the program; LINK 2 cancels every PLANNED shipment of the program's
    commitments; LINK 3 restores each cancelled shipment's units to its source
    lots in the reverse of the FEFO draw order."""
    seasonal_product_ids = {
        p["id"] for p in db.products.values()
        if p["kind"] == "SEASONAL" and p["program_id"] == program["id"]
    }
    # LINK 1
    for lot in db.lots.values():
        if lot["status"] == "AVAILABLE" and lot["product_id"] in seasonal_product_ids:
            lot["status"] = "QUARANTINED"
            touch(lot)
    # LINK 2 + LINK 3
    for shipment in list(db.shipments.values()):
        if shipment["status"] != "PLANNED":
            continue
        commitment = db.commitments.get(shipment["commitment_id"])
        if commitment is None or commitment["program_id"] != program["id"]:
            continue
        shipment["status"] = "CANCELLED"
        touch(shipment)
        for lot_id, units in reversed(shipment["_draws"]):
            lot = db.lots[lot_id]
            lot["units_on_hand"] += units
            if lot["status"] != "QUARANTINED":
                # restored seasonal stock is post-pull stock: quarantined
                lot["status"] = "QUARANTINED"
            touch(lot)


@bp.post("/confection/seasonal-programs/<program_id>/advance")
def advance_program(program_id):
    data = json_body()
    to_state = v_enum(data, "to_state", PROGRAM_STATUSES)
    expected_version = v_int(data, "expected_program_version")

    authorize(ROLE_PLATFORM_ADMIN)
    program = get_program(program_id)

    # OCC (priority 6): expected_program_version must match the current version.
    if expected_version != program["version"]:
        raise ApiError(412, ERR_STALE_VERSION,
                       "expected_program_version does not match the program's current version")

    # State-machine validity (priority 7).
    pair = (program["status"], to_state)
    if pair not in ADVANCE_TRANSITIONS:
        raise ApiError(409, ERR_INVALID_STATE,
                       "no advance transition from %s to %s" % pair)

    if pair == ("OPEN_FOR_COMMITMENTS", "LOCKED"):
        if db.clock < program["_commitment_close_dt"]:
            raise ApiError(422, ERR_PROGRAM_ADVANCE_TOO_EARLY,
                           "the logical clock has not reached commitment_close_on")
    elif pair == ("LOCKED", "OPEN_FOR_COMMITMENTS"):
        if program["reopen_count"] >= MAX_REOPEN:
            raise ApiError(422, ERR_PROGRAM_REOPEN_EXHAUSTED,
                           "the single sanctioned reopen has already been used")
    elif pair == ("LOCKED", "IN_PRODUCTION"):
        has_run = any(r["program_id"] == program["id"] and r["status"] != "CANCELLED"
                      for r in db.runs.values())
        if not has_run:
            raise ApiError(422, ERR_NO_PRODUCTION_SCHEDULED,
                           "no non-CANCELLED production run exists for this program")
    elif pair == ("IN_PRODUCTION", "SHIPPING"):
        if db.clock < program["_ship_window_open_dt"]:
            raise ApiError(422, ERR_PROGRAM_ADVANCE_TOO_EARLY,
                           "the logical clock has not reached ship_window_open_on")
    elif pair == ("SHIPPING", "ON_SHELF"):
        if db.clock < program["_on_shelf_dt"]:
            raise ApiError(422, ERR_PROGRAM_ADVANCE_TOO_EARLY,
                           "the logical clock has not reached on_shelf_on")
    elif pair == ("ON_SHELF", "DISPOSITION"):
        if db.clock < program["_pull_dt"]:
            raise ApiError(422, ERR_PROGRAM_ADVANCE_TOO_EARLY,
                           "the logical clock has not reached pull_on")
    elif pair == ("DISPOSITION", "CLOSED"):
        seasonal_product_ids = {
            p["id"] for p in db.products.values()
            if p["kind"] == "SEASONAL" and p["program_id"] == program["id"]
        }
        undisposed = any(
            lot["status"] == "QUARANTINED" and lot["units_on_hand"] > 0
            and lot["product_id"] in seasonal_product_ids
            for lot in db.lots.values()
        )
        if undisposed:
            raise ApiError(422, ERR_UNDISPOSED_STOCK_REMAINS,
                           "QUARANTINED lots with units remain for this program")

    # Side effects.
    if pair == ("LOCKED", "OPEN_FOR_COMMITMENTS"):
        program["reopen_count"] += 1
    elif pair == ("IN_PRODUCTION", "SHIPPING"):
        _run_allocation(program)
    elif pair == ("ON_SHELF", "DISPOSITION"):
        _pull_cascade(program)
    elif pair in (("PLANNING", "CANCELLED"), ("OPEN_FOR_COMMITMENTS", "CANCELLED")):
        for commitment in db.commitments.values():
            if (commitment["program_id"] == program["id"]
                    and commitment["status"] in ("DRAFT", "SUBMITTED", "CONFIRMED")):
                commitment["status"] = "CANCELLED"
                touch(commitment)

    program["status"] = to_state
    touch(program)
    return ok(ser_program(program))
