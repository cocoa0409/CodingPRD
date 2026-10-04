"""Fulfillment centers (§2.6, §2.7, §3.5)."""

from flask import Blueprint

import common
import envelope
import params
import store
from common import ApiError
from routes import helpers
from services import centers as centers_svc

bp = Blueprint("centers", __name__)


@bp.post("/produce/fulfillment-centers")
def create():
    actor = helpers.actor()
    helpers.admin(actor)
    payload = params.body()
    params.missing(payload, ["code", "name", "region", "insulation_profile"])
    params.check_enum("region", payload.get("region"), common.REGIONS)
    params.check_enum("insulation_profile", payload.get("insulation_profile"),
                      common.INSULATION_PROFILES)

    for existing in store.FULFILLMENT_CENTERS.values():
        if existing["code"] == payload["code"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "code is unique across all centers.")

    cap = params.as_int("max_concurrent_building_cycles",
                        payload.get("max_concurrent_building_cycles"))
    if cap is None:
        cap = 1
    if cap < 1 or cap > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "max_concurrent_building_cycles must be 1..100.")

    row = store.new_row({
        "code": payload["code"],
        "name": payload["name"],
        "region": payload["region"],
        "is_active": bool(payload.get("is_active", True)),
        "insulation_profile": payload["insulation_profile"],
        "serving_cycle_index": 0,
        "max_concurrent_building_cycles": cap,
        "forward_posture": "OPEN",
        "open_claim_count": 0,
    })
    store.FULFILLMENT_CENTERS[row["id"]] = row
    return envelope.object_response(store.serialise(row), 201)


@bp.get("/produce/fulfillment-centers")
def list_all():
    actor = helpers.actor()
    helpers.admin(actor)
    rows = list(store.FULFILLMENT_CENTERS.values())
    rows = params.query_filter(rows, "region")
    rows = params.query_filter_bool(rows, "is_active")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/fulfillment-centers/<center_id>")
def read(center_id):
    actor = helpers.actor()
    helpers.admin(actor)
    row = helpers.fetch_center(center_id)
    return envelope.object_response(store.serialise(row))


@bp.put("/produce/fulfillment-centers/<center_id>")
def update(center_id):
    actor = helpers.actor()
    helpers.admin(actor)
    row = helpers.fetch_center(center_id)
    payload = params.body()
    helpers.require_version(payload, "expected_fulfillment_center_version", row,
                            "FulfillmentCenter")

    if payload.get("insulation_profile") is not None:
        params.check_enum("insulation_profile", payload["insulation_profile"],
                          common.INSULATION_PROFILES)
        row["insulation_profile"] = payload["insulation_profile"]
    if payload.get("is_active") is not None:
        row["is_active"] = bool(payload["is_active"])
    if payload.get("max_concurrent_building_cycles") is not None:
        cap = params.as_int("max_concurrent_building_cycles",
                            payload["max_concurrent_building_cycles"])
        if cap < 1 or cap > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "max_concurrent_building_cycles must be 1..100.")
        row["max_concurrent_building_cycles"] = cap

    store.touch(row)
    centers_svc.reassign_region(row["region"])
    centers_svc.refresh_posture(row)
    return envelope.object_response(store.serialise(row))


@bp.post("/produce/fulfillment-centers/<center_id>/advance-cycle")
def advance_cycle(center_id):
    actor = helpers.actor()
    helpers.admin(actor)
    row = helpers.fetch_center(center_id)
    payload = params.body()
    helpers.require_version(payload, "expected_fulfillment_center_version", row,
                            "FulfillmentCenter")
    row["serving_cycle_index"] = max(0, row["serving_cycle_index"] - 1)
    centers_svc.refresh_posture(row)
    store.touch(row)
    return envelope.object_response(store.serialise(row))


@bp.get("/produce/fulfillment-centers/<center_id>/lots")
def list_lots(center_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    helpers.fetch_center(center_id)
    rows = store.of(store.SUPPLY_LOTS, fulfillment_center_id=center_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/fulfillment-centers/<center_id>/cold-chain-packs")
def list_cold_chain_packs(center_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    helpers.fetch_center(center_id)
    rows = store.of(store.COLD_CHAIN_PACKS, lane_fulfillment_center_id=center_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/fulfillment-centers/<center_id>/customers")
def list_customers(center_id):
    actor = helpers.actor()
    helpers.admin(actor)
    helpers.fetch_center(center_id)
    rows = store.of(store.CUSTOMERS, home_fulfillment_center_id=center_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/fulfillment-centers/<center_id>/subscriptions")
def list_subscriptions(center_id):
    actor = helpers.actor()
    helpers.admin(actor)
    helpers.fetch_center(center_id)
    rows = store.of(store.SUBSCRIPTIONS, home_fulfillment_center_id=center_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/fulfillment-centers/<center_id>/sourcing-bids")
def list_bids(center_id):
    actor = helpers.actor()
    helpers.admin(actor)
    helpers.fetch_center(center_id)
    lot_ids = {l["id"] for l in store.SUPPLY_LOTS.values()
               if l["fulfillment_center_id"] == center_id}
    rows = [b for b in store.SOURCING_BIDS.values() if b["supply_lot_id"] in lot_ids]
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/fulfillment-centers/<center_id>/box-orders")
def list_box_orders(center_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    helpers.fetch_center(center_id)
    rows = store.of(store.BOX_ORDERS, fulfillment_center_id=center_id)
    rows = params.query_filter(rows, "status")
    from services import orders as orders_svc
    for row in rows:
        orders_svc.tick(row)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))