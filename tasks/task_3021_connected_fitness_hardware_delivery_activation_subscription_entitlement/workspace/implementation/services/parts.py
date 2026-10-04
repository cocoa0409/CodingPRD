"""PartsInventory: registration, restock and the derived stock identity."""

import db
from db import LEGAL_SKUS
from errors import api_error
from services import calc
from services.common import (
    field_enum,
    field_int,
    field_str,
    reject_unknown,
)


def register(payload):
    reject_unknown(payload, {"part_code", "compatible_sku", "safety_stock_qty", "part_lot_key"})
    part_code = field_str(payload, "part_code")
    compatible_sku = field_enum(payload, "compatible_sku", LEGAL_SKUS)
    part_lot_key = field_str(payload, "part_lot_key")
    safety_stock_qty = field_int(
        payload, "safety_stock_qty", required=False,
        default=calc.DEFAULT_SAFETY_STOCK_QTY, minimum=0,
    )

    for row in db.STORE["parts_inventory"].values():
        if row["part_code"] == part_code:
            raise api_error(
                "ERR_INVALID_REQUEST",
                "A part with code '%s' already exists." % part_code,
            )

    part = db.create("parts_inventory", {
        "part_code": part_code,
        "compatible_sku": compatible_sku,
        "on_hand_qty": 0,
        "stock_received_qty": 0,
        "reserved_qty": 0,
        "consumed_qty": 0,
        "safety_stock_qty": safety_stock_qty,
        "part_lot_key": part_lot_key,
    })
    calc.recompute_stock(part)
    return part


def restock(part, payload):
    reject_unknown(payload, {"quantity"})
    quantity = field_int(payload, "quantity", minimum=1)

    part["stock_received_qty"] = part["stock_received_qty"] + quantity
    calc.recompute_stock(part)
    db.touch(part)
    return part


def shipping_order_key(row):
    """Documented shipping tie-break for same-SKU parts.

    PRD section 3.6: "parts of the same compatible_sku are held for shipping in
    a documented tie-break order: part_lot_key ascending, then creation
    timestamp ascending".  No endpoint changes its ordering on this key (list
    reads follow the global creation-timestamp order of section 2.3), so it is
    exposed for callers that need the shipping order explicitly.
    """
    return (row["part_lot_key"], row.created_at)