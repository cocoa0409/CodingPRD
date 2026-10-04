"""Season windows and aisle resets (PRD §3.10)."""

from db import db, parse_dt
from errors import (
    ApiError,
    ERR_AISLE_RESET_NOT_EXECUTING,
    ERR_AISLE_RESET_NOT_PLANNED,
    ERR_AISLE_RESET_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_SEASON_WINDOW,
    ERR_NO_ELIGIBLE_ITEMS,
    ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION,
    ERR_RESET_OUTSIDE_CALENDAR,
    ERR_SEASON_WINDOW_NOT_DRAFT,
    ERR_SEASON_WINDOW_NOT_OPEN,
    ERR_SEASON_WINDOW_NOT_SCHEDULED,
    ERR_STORE_DAY_CAPACITY_EXCEEDED,
)
from common import (
    apply_eq,
    as_bool,
    body,
    get_ok,
    get_row,
    insert,
    new_row,
    paginate,
    query,
    require,
    route,
    touch,
)
from response import ok_object
from derivations import (
    dec,
    refresh_after_config_change,
    refresh_season_window,
    season_window_status,
    serialize_reset,
    serialize_season_window,
)

NON_TERMINAL_RESET_STATES = ("PLANNED", "EXECUTING")


# ---------------------------------------------------------------------------
# SeasonWindow
# ---------------------------------------------------------------------------

@route("/merchandise/season-windows", ["POST"], ["ResetCalendarPlanner"])
def create_season_window():
    data = body()
    require(data, ["season_code", "opens_on", "closes_on"])
    opens_on = parse_dt(data["opens_on"])
    closes_on = parse_dt(data["closes_on"])
    if opens_on is None or closes_on is None:
        raise ApiError(ERR_INVALID_SEASON_WINDOW, "opens_on and closes_on must be ISO 8601 instants.")
    if not closes_on > opens_on:
        raise ApiError(ERR_INVALID_SEASON_WINDOW)

    row = new_row("season_window", {
        "season_code": data["season_code"],
        "opens_on": opens_on,
        "closes_on": closes_on,
        "status": "DRAFT",
        "overlapping_reset_count": 0,
    })
    insert("season_window", row)
    refresh_after_config_change()
    return ok_object(serialize_season_window(row), 201)


@route("/merchandise/season-windows", ["GET"],
       ["ResetCalendarPlanner", "StoreOperationsManager", "MerchandiseAnalyst"])
def list_season_windows():
    rows = db.creation_order(db.season_windows)
    rows = apply_eq(rows, "season_code", query("season_code"))
    status = query("status")
    if status:
        rows = [r for r in rows if season_window_status(r) == status]
    return paginate([serialize_season_window(r) for r in rows])


@route("/merchandise/season-windows/<window_id>", ["GET"],
       ["ResetCalendarPlanner", "StoreOperationsManager", "MerchandiseAnalyst"])
def read_season_window(window_id):
    return get_ok("season_window", window_id)


@route("/merchandise/season-windows/<window_id>/aisle-resets", ["GET"],
       ["ResetCalendarPlanner", "StoreOperationsManager", "MerchandiseAnalyst"])
def window_aisle_resets(window_id):
    get_row("season_window", window_id)
    rows = [r for r in db.creation_order(db.aisle_resets) if r["season_window_id"] == window_id]
    rows = apply_eq(rows, "status", query("status"))
    rows = apply_eq(rows, "store_id", query("store_id"))
    return paginate([serialize_reset(r) for r in rows])


@route("/merchandise/season-windows/<window_id>/schedule", ["POST"], ["ResetCalendarPlanner"])
def schedule_window(window_id):
    row = get_row("season_window", window_id)
    if row["status"] != "DRAFT":
        raise ApiError(ERR_SEASON_WINDOW_NOT_DRAFT)
    if not row["closes_on"] > row["opens_on"]:
        raise ApiError(ERR_INVALID_SEASON_WINDOW)
    row["status"] = "SCHEDULED"
    if db.logical_clock >= row["opens_on"]:
        row["status"] = "OPEN"
    touch(row)
    refresh_season_window(row)
    return ok_object(serialize_season_window(row))


@route("/merchandise/season-windows/<window_id>/unschedule", ["POST"], ["ResetCalendarPlanner"])
def unschedule_window(window_id):
    row = get_row("season_window", window_id)
    if row["status"] != "SCHEDULED":
        raise ApiError(ERR_SEASON_WINDOW_NOT_SCHEDULED)
    if not db.logical_clock < row["opens_on"]:
        raise ApiError(ERR_SEASON_WINDOW_NOT_SCHEDULED)
    row["status"] = "DRAFT"
    touch(row)
    return ok_object(serialize_season_window(row))


# ---------------------------------------------------------------------------
# AisleReset
# ---------------------------------------------------------------------------

def intervals_half_open_overlap(existing, starts_at, ends_at):
    """existing.starts_at < new.ends_at AND new.starts_at < existing.ends_at."""
    return existing["starts_at"] < ends_at and starts_at < existing["ends_at"]


def intervals_closed_overlap(existing, starts_at, ends_at):
    """existing.starts_at <= new.ends_at AND new.starts_at <= existing.ends_at."""
    return existing["starts_at"] <= ends_at and starts_at <= existing["ends_at"]


@route("/merchandise/aisle-resets", ["POST"], ["ResetCalendarPlanner"])
def create_aisle_reset():
    data = body()
    require(data, ["store_id", "price_point_id", "season_window_id", "aisle_code",
                   "starts_at", "ends_at", "allocated_shelf_sqft", "seasonal_changeover"])
    store = get_row("store", data["store_id"])
    price_point = get_row("price_point", data["price_point_id"])
    window = get_row("season_window", data["season_window_id"])

    seasonal_changeover = as_bool(data, "seasonal_changeover")
    if seasonal_changeover is None:
        invalid("'seasonal_changeover' must be a boolean.")
    starts_at = parse_dt(data["starts_at"])
    ends_at = parse_dt(data["ends_at"])
    if starts_at is None or ends_at is None:
        invalid("starts_at and ends_at must be ISO 8601 instants.")
    try:
        allocated_shelf_sqft = float(data["allocated_shelf_sqft"])
    except (TypeError, ValueError):
        invalid("allocated_shelf_sqft must be a number.")

    # declared request-shape constraints
    if not ends_at > starts_at:
        invalid("ends_at must be strictly after starts_at.")
    if not allocated_shelf_sqft > 0:
        invalid("allocated_shelf_sqft must be greater than zero.")

    # same-aisle conflict — half-open convention
    for existing in db.aisle_resets.values():
        if existing["store_id"] != store["id"] or existing["aisle_code"] != data["aisle_code"]:
            continue
        if existing["status"] not in NON_TERMINAL_RESET_STATES:
            continue
        if intervals_half_open_overlap(existing, starts_at, ends_at):
            raise ApiError(ERR_AISLE_RESET_OVERLAP)

    # calendar containment — inclusive both ends
    if starts_at < window["opens_on"] or ends_at > window["closes_on"]:
        raise ApiError(ERR_RESET_OUTSIDE_CALENDAR)

    # aggregate store-day commitment — closed convention
    committed = 0.0
    for existing in db.aisle_resets.values():
        if existing["store_id"] != store["id"]:
            continue
        if existing["status"] not in NON_TERMINAL_RESET_STATES:
            continue
        if intervals_closed_overlap(existing, starts_at, ends_at):
            committed += float(existing["allocated_shelf_sqft"])
    if dec(committed + allocated_shelf_sqft) > dec(store["shelf_facing_capacity_sqft"]):
        raise ApiError(ERR_STORE_DAY_CAPACITY_EXCEEDED)

    # a mixed price point inside a single conversion is rejected
    if store["status"] == "CONVERTING" and store["conversion_price_point_id"] is not None:
        if price_point["id"] != store["conversion_price_point_id"]:
            raise ApiError(ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION)

    row = new_row("aisle_reset", {
        "store_id": store["id"],
        "price_point_id": price_point["id"],
        "season_window_id": window["id"],
        "aisle_code": data["aisle_code"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "allocated_shelf_sqft": allocated_shelf_sqft,
        "seasonal_changeover": seasonal_changeover,
        "status": "PLANNED",
    })
    insert("aisle_reset", row)
    refresh_after_config_change()
    return ok_object(serialize_reset(row), 201)


@route("/merchandise/aisle-resets", ["GET"],
       ["ResetCalendarPlanner", "StoreOperationsManager", "MerchandiseAnalyst"])
def list_aisle_resets():
    rows = db.creation_order(db.aisle_resets)
    rows = apply_eq(rows, "store_id", query("store_id"))
    rows = apply_eq(rows, "season_window_id", query("season_window_id"))
    rows = apply_eq(rows, "status", query("status"))
    return paginate([serialize_reset(r) for r in rows])


@route("/merchandise/aisle-resets/<reset_id>", ["GET"],
       ["ResetCalendarPlanner", "StoreOperationsManager", "MerchandiseAnalyst"])
def read_aisle_reset(reset_id):
    return get_ok("aisle_reset", reset_id)


@route("/merchandise/aisle-resets/<reset_id>/begin", ["POST"], ["ResetCalendarPlanner"])
def begin_aisle_reset(reset_id):
    row = get_row("aisle_reset", reset_id)
    if row["status"] != "PLANNED":
        raise ApiError(ERR_AISLE_RESET_NOT_PLANNED)
    window = get_row("season_window", row["season_window_id"])
    if season_window_status(window) != "OPEN":
        raise ApiError(ERR_SEASON_WINDOW_NOT_OPEN)
    if db.logical_clock < row["starts_at"]:
        raise ApiError(ERR_RESET_OUTSIDE_CALENDAR)
    if row["starts_at"] < window["opens_on"] or row["ends_at"] > window["closes_on"]:
        raise ApiError(ERR_RESET_OUTSIDE_CALENDAR)

    row["status"] = "EXECUTING"
    touch(row)
    store = get_row("store", row["store_id"])
    touch(store)
    refresh_after_config_change()
    return ok_object(serialize_reset(row))


@route("/merchandise/aisle-resets/<reset_id>/execute", ["POST"], ["ResetCalendarPlanner"])
def execute_aisle_reset(reset_id):
    row = get_row("aisle_reset", reset_id)
    if row["status"] != "EXECUTING":
        raise ApiError(ERR_AISLE_RESET_NOT_EXECUTING)
    eligible = any(
        item["status"] == "ACTIVE" and item["price_point_id"] == row["price_point_id"]
        for item in db.items.values()
    )
    if not eligible:
        raise ApiError(ERR_NO_ELIGIBLE_ITEMS)
    row["status"] = "EXECUTED"
    touch(row)
    store = get_row("store", row["store_id"])
    touch(store)
    refresh_after_config_change()
    return ok_object(serialize_reset(row))


@route("/merchandise/aisle-resets/<reset_id>/abandon", ["POST"], ["StoreOperationsManager"])
def abandon_aisle_reset(reset_id):
    row = get_row("aisle_reset", reset_id)
    if row["status"] not in ("PLANNED", "EXECUTING"):
        raise ApiError(ERR_AISLE_RESET_NOT_PLANNED)
    row["status"] = "ABANDONED"
    touch(row)
    refresh_after_config_change()
    return ok_object(serialize_reset(row))


def invalid(message):
    raise ApiError(ERR_INVALID_REQUEST, message)