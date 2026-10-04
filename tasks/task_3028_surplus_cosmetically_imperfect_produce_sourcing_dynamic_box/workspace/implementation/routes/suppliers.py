"""Suppliers and their lots (§3.1)."""

from flask import Blueprint

import common
import envelope
import params
import store
from common import ApiError
from routes import helpers
from services import lots as lots_svc

bp = Blueprint("suppliers", __name__)


@bp.post("/produce/suppliers")
def create():
    actor = helpers.actor()
    helpers.admin(actor)
    payload = params.body()
    params.missing(payload, ["name", "region"])
    params.check_enum("region", payload.get("region"), common.REGIONS)

    for existing in store.SUPPLIERS.values():
        if existing["name"] == payload["name"]:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "name is unique across all Suppliers.")

    row = store.new_row({
        "name": payload["name"],
        "region": payload["region"],
        "relationship_status": "PREFERRED",
        "reliability_score_bp": 10000,
        "lots_awarded_total": 0,
        "lots_accepted_total": 0,
        "lots_on_time_total": 0,
        "claims_upheld_total": 0,
        "status": "ACTIVE",
    })
    store.SUPPLIERS[row["id"]] = row
    return envelope.object_response(store.serialise(row), 201)


@bp.get("/produce/suppliers")
def list_all():
    actor = helpers.actor()
    helpers.admin(actor)
    rows = list(store.SUPPLIERS.values())
    rows = params.query_filter(rows, "region")
    rows = params.query_filter(rows, "relationship_status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.get("/produce/suppliers/<supplier_id>")
def read(supplier_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_SUPPLIER, common.ROLE_PLATFORM_ADMIN))
    row = helpers.fetch_supplier(supplier_id)
    if actor["role"] == common.ROLE_SUPPLIER and actor["id"] != supplier_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Supplier may only read its own record.")
    return envelope.object_response(store.serialise(row))


@bp.get("/produce/suppliers/<supplier_id>/sourcing-bids")
def list_bids(supplier_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_SUPPLIER, common.ROLE_PLATFORM_ADMIN))
    helpers.fetch_supplier(supplier_id)
    if actor["role"] == common.ROLE_SUPPLIER and actor["id"] != supplier_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Supplier may only read its own bids.")
    rows = store.of(store.SOURCING_BIDS, supplier_id=supplier_id)
    rows = params.query_filter(rows, "status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))


@bp.post("/produce/suppliers/<supplier_id>/lots")
def create_lot(supplier_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_SUPPLIER, common.ROLE_PLATFORM_ADMIN))
    supplier = helpers.fetch_supplier(supplier_id)
    if actor["role"] == common.ROLE_SUPPLIER and actor["id"] != supplier_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Supplier may only list lots in its own scope.")

    payload = params.body()
    params.missing(payload, [
        "fulfillment_center_id", "product_name", "category", "procurement_grade",
        "unit_weight_grams", "quantity_available", "unit_cost_cents",
        "harvest_date", "expiry_date", "ready_date",
    ])
    helpers.fetch_center(payload["fulfillment_center_id"])
    params.check_enum("category", payload.get("category"), common.CATEGORIES)
    params.check_enum("procurement_grade", payload.get("procurement_grade"),
                      common.PROCUREMENT_GRADES)

    row = store.new_row({
        "supplier_id": supplier["id"],
        "fulfillment_center_id": payload["fulfillment_center_id"],
        "product_name": payload["product_name"],
        "category": payload["category"],
        "procurement_grade": payload["procurement_grade"],
        "unit_weight_grams": params.as_int("unit_weight_grams",
                                           payload["unit_weight_grams"]),
        "quantity_available": params.as_int("quantity_available",
                                            payload["quantity_available"]),
        "unit_cost_cents": params.as_int("unit_cost_cents",
                                         payload["unit_cost_cents"]),
        "harvest_date": payload["harvest_date"],
        "shelf_life_days": 0,
        "expiry_date": payload["expiry_date"],
        "allergen_codes": params.as_string_list(
            "allergen_codes", payload.get("allergen_codes")),
        "preference_tags": params.as_string_list(
            "preference_tags", payload.get("preference_tags")),
        "preference_eligible": False,
        "billing_weight_grams": 0,
        "display_price_cents": 0,
        "ready_date": payload["ready_date"],
        "status": "QUOTED",
        "quality_status": "PENDING_INSPECTION",
        "arrived_at": None,
        "source_count": 0,
        "_status_awarded": False,
        "_accepted": False,
        "_on_time": False,
        "_award_executed": False,
    })
    store.SUPPLY_LOTS[row["id"]] = row
    lots_svc.derived_lot(row)
    return envelope.object_response(store.serialise(row), 201)


@bp.get("/produce/suppliers/<supplier_id>/lots")
def list_lots(supplier_id):
    actor = helpers.actor()
    helpers.admin(actor, (common.ROLE_SUPPLIER, common.ROLE_PLATFORM_ADMIN))
    helpers.fetch_supplier(supplier_id)
    if actor["role"] == common.ROLE_SUPPLIER and actor["id"] != supplier_id:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "A Supplier may only read its own lots.")
    rows = store.of(store.SUPPLY_LOTS, supplier_id=supplier_id)
    rows = params.query_filter(rows, "status")
    data, limit, offset, ordered = helpers.list_response(rows)
    return envelope.array_response(data, limit, offset, len(ordered))