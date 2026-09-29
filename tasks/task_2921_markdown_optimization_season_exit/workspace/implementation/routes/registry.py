"""Season, price zone and store registration (PRD 3.1)."""

from flask import Blueprint

from common import fmt_date, r2
from db import apply_changes, db, new_row, touch
from errors import ApiError
from middleware import (ROLE_MERCHANDISE_DIRECTOR, body, endpoint)
from response import created, ok
from serializers import price_zone_json, season_json, store_json
from services import calc, lookup
from services.lifecycle import (items_of_season, reclassify_season_items,
                                recompute_season, recompute_store,
                                agreements_of_season, claims_of_agreement,
                                dispositions_of_season, exit_reviews_of_season,
                                reservations_of_season)

bp = Blueprint("registry", __name__)

SEASON_STATUSES = ("PLANNING", "ACTIVE", "EXIT_WINDOW", "CLOSED")
SEASON_TRANSITIONS = {
    "PLANNING": ("ACTIVE",),
    "ACTIVE": ("EXIT_WINDOW",),
    "EXIT_WINDOW": ("CLOSED",),
    "CLOSED": (),
}
ZONE_TYPES = ("CHAIN", "REGION", "STORE")
STORE_STATUSES = ("OPEN", "REMODEL", "CLOSING")


@endpoint(bp, "/seasons", ["POST"], (ROLE_MERCHANDISE_DIRECTOR,))
def create_season(user_id, role):
    from validation import req_date, req_int, req_num, req_str, req_enum
    payload = body()
    code = req_str(payload, "code", min_len=1, max_len=32)
    category = req_enum(payload, "category", calc.CATEGORIES)
    start = req_date(payload, "season_start_date")
    end = req_date(payload, "season_end_date")
    exit_target = req_date(payload, "exit_target_date")
    exit_units_target = req_int(payload, "exit_units_target", minimum=1)
    target_pct = req_num(payload, "sell_through_target_pct",
                         minimum="0.01", maximum="100.00")
    clearance_space_units = req_int(payload, "clearance_space_units", minimum=1)

    if not end > start:
        raise ApiError("ERR_VALIDATION",
                       "season_end_date must be strictly after "
                       "season_start_date.")
    if not exit_target > start:
        raise ApiError("ERR_VALIDATION",
                       "exit_target_date must be strictly after "
                       "season_start_date.")
    if exit_target > end:
        raise ApiError("ERR_VALIDATION",
                       "exit_target_date must be on or before "
                       "season_end_date.")

    for existing in db.seasons.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "Season code '%s' already exists." % code)

    season = new_row(
        code=code,
        category=category,
        season_start_date=fmt_date(start),
        season_end_date=fmt_date(end),
        exit_target_date=fmt_date(exit_target),
        exit_units_target=exit_units_target,
        sell_through_target_pct=r2(target_pct),
        clearance_space_units=clearance_space_units,
        reserved_clearance_units=0,
        committed_clearance_units=0,
        projected_exit_units=0,
        status="PLANNING",
    )
    db.insert("seasons", season)
    return created(season_json(season))


@endpoint(bp, "/seasons/<season_id>/transition", ["POST"],
          (ROLE_MERCHANDISE_DIRECTOR,))
def transition_season(user_id, role, season_id):
    from validation import req_enum
    payload = body()
    to_status = req_enum(payload, "to_status", SEASON_STATUSES)
    season = lookup.season(season_id)

    if to_status not in SEASON_TRANSITIONS[season["status"]]:
        raise ApiError("ERR_INVALID_STATE",
                       "A season in %s does not declare a transition to %s."
                       % (season["status"], to_status))

    if to_status == "ACTIVE" and not items_of_season(season):
        raise ApiError("ERR_INVALID_STATE",
                       "A season needs at least one item before it opens.")

    if to_status == "CLOSED":
        finals = [r for r in exit_reviews_of_season(season)
                  if r["review_type"] == "FINAL"]
        if not finals:
            raise ApiError("ERR_INVALID_STATE",
                           "A FINAL exit review must exist before closing.")
        for order in dispositions_of_season(season):
            if order["status"] in ("DRAFT", "APPROVED"):
                raise ApiError("ERR_INVALID_STATE",
                               "Every disposition order must be settled or "
                               "cancelled before closing.")

    season["status"] = to_status
    touch(season)

    if to_status == "CLOSED":
        _close_sweep(season)
    reclassify_season_items(season)
    recompute_season(season, cascade=False)
    return ok(season_json(season))


def _close_sweep(season):
    """Closing expires open offers, rejects their claims, frees the bays."""
    for agreement in agreements_of_season(season):
        if agreement["status"] in ("PROPOSED", "COUNTERED"):
            agreement["status"] = "EXPIRED"
            touch(agreement)
            for claim in claims_of_agreement(agreement):
                if claim["status"] == "SUBMITTED":
                    claim["status"] = "REJECTED"
                    claim["rejection_reason"] = "AGREEMENT_EXPIRED"
                    claim["recognized_cents"] = 0
                    touch(claim)
    stores = {}
    for reservation in reservations_of_season(season):
        if reservation["status"] in ("RESERVED", "COMMITTED"):
            reservation["status"] = "RELEASED"
            reservation["released_at"] = db.clock_instant()
            touch(reservation)
            stores[reservation["store_id"]] = True
    for store_id in stores:
        store = db.get("stores", store_id)
        if store is not None:
            recompute_store(store)


@endpoint(bp, "/price-zones", ["POST"], (ROLE_MERCHANDISE_DIRECTOR,))
def create_price_zone(user_id, role):
    from validation import opt_int, opt_str, req_enum, req_str
    payload = body()
    zone_code = req_str(payload, "zone_code", min_len=1, max_len=64)
    zone_type = req_enum(payload, "zone_type", ZONE_TYPES)
    parent_zone_id = opt_str(payload, "parent_zone_id")
    region_code = opt_str(payload, "region_code")
    signage_lead_days = opt_int(payload, "signage_lead_days",
                                minimum=1, maximum=30)

    parent = None
    if parent_zone_id is not None:
        parent = lookup.price_zone(parent_zone_id)

    if zone_type == "CHAIN":
        if parent is not None:
            raise ApiError("ERR_VALIDATION",
                           "A CHAIN zone must not name a parent zone.")
    elif zone_type == "REGION":
        if parent is None or parent["zone_type"] != "CHAIN":
            raise ApiError("ERR_VALIDATION",
                           "A REGION zone must name a CHAIN zone as parent.")
    else:
        if parent is None or parent["zone_type"] != "REGION":
            raise ApiError("ERR_VALIDATION",
                           "A STORE zone must name a REGION zone as parent.")

    for existing in db.price_zones.values():
        if existing["zone_code"] == zone_code:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "Zone code '%s' already exists." % zone_code)

    if signage_lead_days is None:
        signage_lead_days = calc.SIGNAGE_LEAD_DEFAULT_DAYS[zone_type]

    zone = new_row(
        zone_code=zone_code,
        zone_type=zone_type,
        parent_zone_id=parent["id"] if parent is not None else None,
        region_code=region_code,
        signage_lead_days=signage_lead_days,
    )
    db.insert("price_zones", zone)
    return created(price_zone_json(zone))


@endpoint(bp, "/stores", ["POST"], (ROLE_MERCHANDISE_DIRECTOR,))
def create_store(user_id, role):
    from validation import opt_enum, opt_str, req_int, req_str
    payload = body()
    store_number = req_str(payload, "store_number", min_len=1, max_len=16)
    price_zone_id = req_str(payload, "price_zone_id")
    region_code = opt_str(payload, "region_code")
    clearance_bay_units = req_int(payload, "clearance_bay_units", minimum=0)
    status = opt_enum(payload, "status", STORE_STATUSES, default="OPEN")

    zone = lookup.price_zone(price_zone_id)

    for existing in db.stores.values():
        if existing["store_number"] == store_number:
            raise ApiError("ERR_DUPLICATE_RESOURCE",
                           "Store number '%s' already exists." % store_number)

    store = new_row(
        store_number=store_number,
        price_zone_id=zone["id"],
        region_code=region_code,
        clearance_bay_units=clearance_bay_units,
        committed_clearance_units=0,
        available_clearance_units=clearance_bay_units,
        status=status,
    )
    db.insert("stores", store)
    return created(store_json(store))


@endpoint(bp, "/stores/<store_id>", ["PATCH"], (ROLE_MERCHANDISE_DIRECTOR,))
def update_store(user_id, role, store_id):
    from validation import opt_enum, opt_int
    payload = body()
    status = opt_enum(payload, "status", STORE_STATUSES)
    clearance_bay_units = opt_int(payload, "clearance_bay_units", minimum=0)
    store = lookup.store(store_id)

    if status is not None:
        store["status"] = status
    if clearance_bay_units is not None:
        store["clearance_bay_units"] = clearance_bay_units
    committed = store["committed_clearance_units"]
    store["available_clearance_units"] = store["clearance_bay_units"] - committed
    touch(store)
    recompute_store(store)
    return ok(store_json(store))
