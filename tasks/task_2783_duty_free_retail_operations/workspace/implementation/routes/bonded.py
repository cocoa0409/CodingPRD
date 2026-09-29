"""Bonded stock items and the append-only movement ledger."""
from flask import Blueprint

import db
import response
from errors import ApiError
from middleware import actor, body, endpoint
from services import ledger
from services.lookup import fetch, fetch_body, listing
from services.scope import ALL_ROLES, LEDGER_ROLES

bp = Blueprint("bonded", __name__)

MOVEMENT_TYPES = ("RECEIPT", "SALE_ISSUE", "RESERVATION_HOLD", "RESERVATION_RELEASE",
                  "SHRINKAGE_WRITE_OFF", "AUDIT_ADJUSTMENT", "REVERSAL")
MANUAL_TYPES = ("RECEIPT", "AUDIT_ADJUSTMENT")


@bp.post("/bonded-stock-items")
@endpoint("StockController")
def create_stock_item():
    payload = body()
    terminal = fetch_body("terminals", "terminal_id", payload)
    product = fetch_body("products", "product_id", payload)
    for existing in db.stock_items.values():
        if existing["terminal_id"] == terminal["id"] and existing["product_id"] == product["id"]:
            raise ApiError("ERR_DUPLICATE_STOCK_ITEM")
    item = db.base()
    item.update({
        "terminal_id": terminal["id"],
        "product_id": product["id"],
        "on_hand_qty": 0,
        "reserved_qty": 0,
        "available_qty": 0,
        "duty_suspended_value_cents": 0,
        "last_reconciled_at": None,
    })
    db.stock_items[item["id"]] = item
    return response.created(db.public(item))


@bp.get("/bonded-stock-items/<stock_item_id>")
@endpoint(*ALL_ROLES)
def get_stock_item(stock_item_id):
    return response.single(db.public(fetch("stock_items", stock_item_id)))


@bp.get("/bonded-stock-items")
@endpoint(*ALL_ROLES)
def list_stock_items():
    rows, limit, offset, total = listing(db.stock_items, ("terminal_id", "product_id"))
    return response.collection(rows, limit, offset, total)


@bp.post("/bonded-movements")
@endpoint("StockController")
def create_movement():
    payload = body()
    item = fetch_body("stock_items", "stock_item_id", payload)
    movement_type = payload.get("movement_type")
    if not isinstance(movement_type, str) or movement_type not in MANUAL_TYPES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "movement_type must be one of RECEIPT, AUDIT_ADJUSTMENT; every other type is synthesised.",
        )
    if "qty_delta" not in payload or payload["qty_delta"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'qty_delta' is required.")
    qty_delta = payload["qty_delta"]
    if isinstance(qty_delta, bool) or not isinstance(qty_delta, int):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'qty_delta' must be an integer.")
    if qty_delta == 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'qty_delta' must not be zero.")
    if movement_type == "RECEIPT" and qty_delta <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "A RECEIPT must carry a positive qty_delta.")
    if item["on_hand_qty"] + qty_delta < 0:
        raise ApiError("ERR_BONDED_STOCK_INSUFFICIENT")
    movement = ledger.append(item, movement_type, qty_delta, "MANUAL", None, actor())
    return response.created(db.public(movement))


@bp.get("/bonded-movements/<movement_id>")
@endpoint(*LEDGER_ROLES)
def get_movement(movement_id):
    return response.single(db.public(fetch("movements", movement_id)))


@bp.get("/bonded-movements")
@endpoint(*LEDGER_ROLES)
def list_movements():
    rows, limit, offset, total = listing(
        db.movements,
        ("stock_item_id", "movement_type", "reversal_of_movement_id",
         "agreement_period_code", "source_ref_type", "source_ref_id"),
    )
    return response.collection(rows, limit, offset, total)


@bp.post("/bonded-movements/<movement_id>/reverse")
@endpoint("StockController")
def reverse_movement(movement_id):
    original = fetch("movements", movement_id)
    if original["movement_type"] not in MANUAL_TYPES or original["reversed"]:
        raise ApiError("ERR_MOVEMENT_NOT_REVERSIBLE")
    item = db.stock_items[original["stock_item_id"]]
    qty_delta = -original["qty_delta"]
    if original["affects"] == "ON_HAND" and item["on_hand_qty"] + qty_delta < 0:
        raise ApiError("ERR_BONDED_STOCK_INSUFFICIENT")
    movement = ledger.append(item, "REVERSAL", qty_delta, "MANUAL", None, actor(),
                             original=original)
    return response.created(db.public(movement))
