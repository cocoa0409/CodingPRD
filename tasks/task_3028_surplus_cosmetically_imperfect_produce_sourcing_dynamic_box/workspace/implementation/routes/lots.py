"""Supply lots, bids, award and make-ready (§3.1, §3.2)."""

from flask import Blueprint

import clock
import common
import envelope
import params
import store
from common import ApiError
from routes import helpers
from services import lots as lots_svc
from services import suppliers as suppliers_svc

bp = Blueprint("lots", __name__)


@bp.get("/produce/supply-lots")
def list_all():
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    rows = list(store.SUPPLY_LOTS.values())
    rows = params.query_filter(rows, "supplier_id")
    rows = params.query_filter(rows, "fulfillment_center_id")
    rows = params.query_filter(rows, "status")
    rows = params.query_filter(rows, "quality_status")
    rows = params.query_filter(rows, "category")
    for row in rows:
        lots_svc.derived_lot(row)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/supply-lots/<lot_id>")
def read(lot_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_PLATFORM_ADMIN, common.ROLE_SUPPLIER))
    row = helpers.fetch_lot(lot_id)
    if actor["role"] == common.ROLE_SUPPLIER and row["supplier_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Supplier may only read its own lots.")
    lots_svc.derived_lot(row)
    return envelope.object_response(store.serialise(row))


@bp.get("/produce/supply-lots/<lot_id>/sourcing-bids")
def list_bids(lot_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_PLATFORM_ADMIN, common.ROLE_SUPPLIER))
    row = helpers.fetch_lot(lot_id)
    if actor["role"] == common.ROLE_SUPPLIER and row["supplier_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Supplier may only read its own lots.")
    rows = store.of(store.SOURCING_BIDS, supply_lot_id=lot_id)
    rows = params.query_filter(rows, "status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/supply-lots/<lot_id>/conventional-quotes")
def list_quotes(lot_id):
    actor = helpers.actor()
    helpers.admin(actor)
    helpers.fetch_lot(lot_id)
    rows = store.of(store.CONVENTIONAL_QUOTES, supply_lot_id=lot_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/supply-lots/<lot_id>/build-items")
def list_build_items(lot_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_PLATFORM_ADMIN,
                          common.ROLE_FULFILLMENT_OPERATOR))
    helpers.fetch_lot(lot_id)
    rows = store.of(store.BOX_BUILD_ITEMS, supply_lot_id=lot_id)
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/supply-lots/<lot_id>/quality-claims")
def list_claims(lot_id):
    actor = helpers.actor()
    helpers.admin(actor)
    helpers.fetch_lot(lot_id)
    rows = store.of(store.QUALITY_CLAIMS, supply_lot_id=lot_id)
    rows = params.query_filter(rows, "status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.post("/produce/sourcing-bids")
def create_bid():
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_SUPPLIER, common.ROLE_PLATFORM_ADMIN))
    payload = params.body()
    params.missing(payload, ["supply_lot_id", "supplier_id",
                             "bid_unit_cost_cents", "quantity_offered"])
    lot = helpers.fetch_lot(payload["supply_lot_id"])
    supplier = helpers.fetch_supplier(payload["supplier_id"])
    if actor["role"] == common.ROLE_SUPPLIER and actor["id"] != supplier["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Supplier may only bid in its own name.")

    row = lots_svc.create_bid(
        lot, supplier,
        params.as_int("bid_unit_cost_cents", payload["bid_unit_cost_cents"]),
        params.as_int("quantity_offered", payload["quantity_offered"]))
    return envelope.object_response(store.serialise(row), 201)


@bp.get("/produce/sourcing-bids")
def list_bid_all():
    actor = helpers.actor()
    helpers.admin(actor)
    rows = list(store.SOURCING_BIDS.values())
    rows = params.query_filter(rows, "supplier_id")
    rows = params.query_filter(rows, "supply_lot_id")
    rows = params.query_filter(rows, "status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.post("/produce/sourcing-bids/<bid_id>/withdraw")
def withdraw(bid_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_SUPPLIER, common.ROLE_PLATFORM_ADMIN))
    bid = helpers.fetch_bid(bid_id)
    if actor["role"] == common.ROLE_SUPPLIER and bid["supplier_id"] != actor["id"]:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Supplier may only withdraw its own bid.")
    lots_svc.withdraw_bid(bid)
    return envelope.object_response(store.serialise(bid))


@bp.post("/produce/supply-lots/<lot_id>/award")
def award(lot_id):
    actor = helpers.actor()
    helpers.admin(actor)
    lot = helpers.fetch_lot(lot_id)
    payload = params.body()
    helpers.require_version(payload, "expected_supply_lot_version", lot, "SupplyLot")
    bidder_quota = params.as_int("bidder_quota", payload.get("bidder_quota"))
    if bidder_quota is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "bidder_quota is required.")

    if lot["status"] == "QUOTED":
        lots_svc.open_for_bids(lot)
        lots_svc.subscription_shelf_life_cascade(lot)
    lots_svc.award(lot, bidder_quota)
    lots_svc.derived_lot(lot)
    suppliers_svc.recompute_for_lot(lot)
    return envelope.object_response(store.serialise(lot))


@bp.post("/produce/supply-lots/<lot_id>/make-ready")
def make_ready(lot_id):
    actor = helpers.actor()
    helpers.admin(actor)
    lot = helpers.fetch_lot(lot_id)
    payload = params.body()
    params.missing(payload, ["quality_outcome"])
    params.check_enum("quality_outcome", payload.get("quality_outcome"),
                      ("PASS", "REJECTED"))
    helpers.require_version(payload, "expected_supply_lot_version", lot, "SupplyLot")

    arrived_at = payload.get("arrived_at")
    if arrived_at is None:
        arrived_at = clock.now_iso()
    else:
        try:
            clock.parse_instant(arrived_at)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "arrived_at must be an ISO 8601 instant.")
    lot["arrived_at"] = arrived_at
    lots_svc.make_ready(lot, payload["quality_outcome"], arrived_at)
    return envelope.object_response(store.serialise(lot))