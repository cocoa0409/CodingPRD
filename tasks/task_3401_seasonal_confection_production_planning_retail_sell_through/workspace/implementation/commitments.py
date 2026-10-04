"""RetailerCommitment routes: create, read, list, submit, confirm, revise
(create-with-supersede under OCC), reorder (single mid-season reorder), cancel."""

from flask import Blueprint, request

from db import db, touch
from domain import (
    get_commitment, ser_commitment, remaining_pool, delivered_units_of_commitment,
)
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_PROGRAM_NOT_FOUND, ERR_RETAILER_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND, ERR_OWNERSHIP_MISMATCH, ERR_INVALID_STATE,
    ERR_PROGRAM_NOT_OPEN, ERR_COMMITMENT_WINDOW_CLOSED, ERR_PRODUCT_PROGRAM_MISMATCH,
    ERR_STALE_VERSION, ERR_SHELF_CAP_EXCEEDED, ERR_REORDER_NOT_ALLOWED,
    ERR_SUPPLY_POOL_EXHAUSTED,
)
from middleware import authorize, ROLE_RETAILER, ROLE_CATEGORY_MANAGER, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_dt

bp = Blueprint("commitments", __name__)

SHELF_CAP_STATUSES = ("SUBMITTED", "CONFIRMED", "ALLOCATED", "SHORTED",
                      "FULFILLING", "FULFILLED")
REORDERABLE_STATUSES = ("ALLOCATED", "SHORTED", "FULFILLING", "FULFILLED")


def _check_window_bounds(program, open_dt, close_dt):
    """Retailer-specific ship window must sit inside the program ship window;
    violations are ERR_INVALID_REQUEST (PRD 3.4)."""
    if open_dt > close_dt:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "ship_window_open_on must not be after ship_window_close_on")
    if open_dt < program["_ship_window_open_dt"]:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "ship_window_open_on must not be earlier than the program ship window open")
    if close_dt > program["_ship_window_close_dt"]:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "ship_window_close_on must not be later than the program ship window close")


@bp.post("/confection/retailer-commitments")
def create_commitment():
    data = json_body()
    program_id = v_str(data, "program_id")
    retailer_id = v_str(data, "retailer_id")
    product_id = v_str(data, "product_id")
    committed_units = v_int(data, "committed_units", min_v=1)
    open_dt, open_raw = v_dt(data, "ship_window_open_on")
    close_dt, close_raw = v_dt(data, "ship_window_close_on")
    if open_dt > close_dt:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       "ship_window_open_on must not be after ship_window_close_on")

    actor = authorize(ROLE_RETAILER)

    # Ownership (priority 4) precedes body-FK existence (priority 5).
    if retailer_id != actor.user_id:
        raise ApiError(403, ERR_OWNERSHIP_MISMATCH,
                       "retailer_id must equal the acting X-User-ID")

    # Body FKs in declared input order: program_id, retailer_id, product_id.
    program = db.programs.get(program_id)
    if program is None:
        raise ApiError(404, ERR_PROGRAM_NOT_FOUND,
                       "SeasonalProgram %s does not exist" % program_id)
    if retailer_id not in db.retailers:
        raise ApiError(404, ERR_RETAILER_NOT_FOUND,
                       "RetailerAccount %s does not exist" % retailer_id)
    product = db.products.get(product_id)
    if product is None:
        raise ApiError(404, ERR_PRODUCT_NOT_FOUND,
                       "Product %s does not exist" % product_id)

    # Program-relative window bounds (400), then state, then structural.
    _check_window_bounds(program, open_dt, close_dt)

    if program["status"] != "OPEN_FOR_COMMITMENTS":
        raise ApiError(409, ERR_PROGRAM_NOT_OPEN,
                       "the program is not OPEN_FOR_COMMITMENTS")

    if product["kind"] != "SEASONAL" or product["program_id"] != program["id"]:
        raise ApiError(422, ERR_PRODUCT_PROGRAM_MISMATCH,
                       "the product must be a SEASONAL product of this program")

    commitment = _create_entity(db.commitments, {
        "program_id": program_id,
        "retailer_id": retailer_id,
        "product_id": product_id,
        "committed_units": committed_units,
        "allocated_units": 0,
        "reorder_units": 0,
        "reorder_used": False,
        "revision": 1,
        "supersedes_commitment_id": None,
        "ship_window_open_on": open_raw,
        "ship_window_close_on": close_raw,
        "_ship_open_dt": open_dt,
        "_ship_close_dt": close_dt,
        "status": "DRAFT",
    })
    return created(ser_commitment(commitment))


@bp.get("/confection/retailer-commitments/<commitment_id>")
def read_commitment(commitment_id):
    authorize(*ALL_ROLES)
    return ok(ser_commitment(get_commitment(commitment_id)))


@bp.get("/confection/retailer-commitments")
def list_commitments():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.commitments.values())
    for param in ("program_id", "retailer_id", "product_id", "status",
                  "supersedes_commitment_id"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c[param] == val]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_commitment(c) for c in page], total, limit, offset)


def _own(actor, commitment):
    if commitment["retailer_id"] != actor.user_id:
        raise ApiError(403, ERR_OWNERSHIP_MISMATCH,
                       "the acting retailer does not own this commitment")


@bp.post("/confection/retailer-commitments/<commitment_id>/submit")
def submit_commitment(commitment_id):
    actor = authorize(ROLE_RETAILER)
    commitment = get_commitment(commitment_id)
    _own(actor, commitment)
    if commitment["status"] != "DRAFT":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a DRAFT commitment can be submitted")
    program = db.programs[commitment["program_id"]]
    if program["status"] != "OPEN_FOR_COMMITMENTS":
        raise ApiError(409, ERR_PROGRAM_NOT_OPEN,
                       "the program is not OPEN_FOR_COMMITMENTS")
    if not (program["_commitment_open_dt"] <= db.clock < program["_commitment_close_dt"]):
        raise ApiError(422, ERR_COMMITMENT_WINDOW_CLOSED,
                       "the logical clock is outside the commitment collection window")
    commitment["status"] = "SUBMITTED"
    touch(commitment)
    return ok(ser_commitment(commitment))


@bp.post("/confection/retailer-commitments/<commitment_id>/confirm")
def confirm_commitment(commitment_id):
    authorize(ROLE_CATEGORY_MANAGER)
    commitment = get_commitment(commitment_id)
    if commitment["status"] != "SUBMITTED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a SUBMITTED commitment can be confirmed")
    retailer = db.retailers[commitment["retailer_id"]]
    total = sum(c["committed_units"] for c in db.commitments.values()
                if c["retailer_id"] == retailer["id"] and c["status"] in SHELF_CAP_STATUSES)
    if total > retailer["max_seasonal_units"]:
        raise ApiError(422, ERR_SHELF_CAP_EXCEEDED,
                       "confirming would exceed the retailer's max_seasonal_units")
    commitment["status"] = "CONFIRMED"
    touch(commitment)
    return ok(ser_commitment(commitment))


@bp.post("/confection/retailer-commitments/<commitment_id>/revise")
def revise_commitment(commitment_id):
    data = json_body()
    new_units = v_int(data, "committed_units", min_v=1)
    expected_version = v_int(data, "expected_commitment_version")
    new_open_dt, new_open_raw = v_dt(data, "ship_window_open_on", required=False)
    new_close_dt, new_close_raw = v_dt(data, "ship_window_close_on", required=False)

    actor = authorize(ROLE_RETAILER)
    commitment = get_commitment(commitment_id)
    _own(actor, commitment)

    # OCC (priority 6).
    if expected_version != commitment["version"]:
        raise ApiError(412, ERR_STALE_VERSION,
                       "expected_commitment_version does not match the commitment's current version")

    # State (priority 7).
    if commitment["status"] != "SUBMITTED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a SUBMITTED commitment can be revised")
    program = db.programs[commitment["program_id"]]
    if program["status"] != "OPEN_FOR_COMMITMENTS":
        raise ApiError(409, ERR_PROGRAM_NOT_OPEN,
                       "the program is not OPEN_FOR_COMMITMENTS")

    # Temporal (priority 9): revision requires the clock strictly before close.
    if not (db.clock < program["_commitment_close_dt"]):
        raise ApiError(422, ERR_COMMITMENT_WINDOW_CLOSED,
                       "the commitment collection window has closed")

    # Effective ship window: supplied sides replace, others carry over.
    eff_open_dt = new_open_dt if new_open_dt is not None else commitment["_ship_open_dt"]
    eff_close_dt = new_close_dt if new_close_dt is not None else commitment["_ship_close_dt"]
    eff_open_raw = new_open_raw if new_open_dt is not None else commitment["ship_window_open_on"]
    eff_close_raw = new_close_raw if new_close_dt is not None else commitment["ship_window_close_on"]
    _check_window_bounds(program, eff_open_dt, eff_close_dt)

    # Supersede the old row, create the successor at revision+1.
    commitment["status"] = "SUPERSEDED"
    touch(commitment)
    successor = _create_entity(db.commitments, {
        "program_id": commitment["program_id"],
        "retailer_id": commitment["retailer_id"],
        "product_id": commitment["product_id"],
        "committed_units": new_units,
        "allocated_units": 0,
        "reorder_units": 0,
        "reorder_used": False,
        "revision": commitment["revision"] + 1,
        "supersedes_commitment_id": commitment["id"],
        "ship_window_open_on": eff_open_raw,
        "ship_window_close_on": eff_close_raw,
        "_ship_open_dt": eff_open_dt,
        "_ship_close_dt": eff_close_dt,
        "status": "SUBMITTED",
    })
    return created(ser_commitment(successor))


@bp.post("/confection/retailer-commitments/<commitment_id>/reorder")
def reorder_commitment(commitment_id):
    data = json_body()
    units = v_int(data, "units", min_v=1)

    actor = authorize(ROLE_RETAILER)
    commitment = get_commitment(commitment_id)
    _own(actor, commitment)

    program = db.programs[commitment["program_id"]]
    if (commitment["reorder_used"]
            or commitment["status"] not in REORDERABLE_STATUSES
            or program["status"] not in ("SHIPPING", "ON_SHELF")):
        raise ApiError(422, ERR_REORDER_NOT_ALLOWED,
                       "this commitment cannot reorder (reorder consumed or state forbids it)")

    pool = remaining_pool(commitment["product_id"])
    if units > pool:
        raise ApiError(422, ERR_SUPPLY_POOL_EXHAUSTED,
                       "the requested units exceed the remaining supply pool")

    commitment["allocated_units"] += units
    commitment["reorder_units"] = units
    commitment["reorder_used"] = True
    if commitment["status"] == "FULFILLED":
        if delivered_units_of_commitment(commitment["id"]) < commitment["allocated_units"]:
            commitment["status"] = "FULFILLING"
    touch(commitment)
    return ok(ser_commitment(commitment))


@bp.post("/confection/retailer-commitments/<commitment_id>/cancel")
def cancel_commitment(commitment_id):
    actor = authorize(ROLE_RETAILER)
    commitment = get_commitment(commitment_id)
    _own(actor, commitment)
    if commitment["status"] not in ("DRAFT", "SUBMITTED", "CONFIRMED"):
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a DRAFT, SUBMITTED or CONFIRMED commitment can be cancelled")
    commitment["status"] = "CANCELLED"
    touch(commitment)
    return ok(ser_commitment(commitment))
