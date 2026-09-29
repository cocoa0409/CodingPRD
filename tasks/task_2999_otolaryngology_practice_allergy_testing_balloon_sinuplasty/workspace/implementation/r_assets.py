"""The endoscope register and the supply inventory (PRD 3.8)."""
from flask import Blueprint

import calc
import common
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("assets", __name__)

SERIAL_RE = r"^SC-[0-9]{4}$"
LOT_NUMBER_RE = r"^LOT-[0-9]{4}$"


# --- endoscopes --------------------------------------------------------------
@bp.post("/endoscopes")
def register_scope():
    common.begin(["PracticeAdmin"])
    values, _provided = shape.read_body([
        ("serial_number", True, shape.v_string(7, 7, SERIAL_RE), False),
        ("model", True, shape.v_string(1, 60), False),
    ])
    for row in store.rows("endoscope_assets"):
        if row["serial_number"] == values["serial_number"]:
            raise ApiError("ERR_DUPLICATE_SCOPE_SERIAL")
    row = common.new_row("endoscope_assets", {
        "serial_number": values["serial_number"],
        "model": values["model"],
        "status": "READY",
        "cycle_count": 0,
        "last_reprocessed_at": None,
        "hld_expires_at": None,
        "mec_test_due": False,
        "consecutive_mec_failures": 0,
        "reprocessing_started_by_user_id": None,
        "last_used_by_user_id": None,
    })
    return envelope.created(common.public("endoscope_assets", row))


@bp.get("/endoscopes/<scope_id>")
def read_scope(scope_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("endoscope_assets", scope_id)
    return envelope.ok(common.public("endoscope_assets", row))


@bp.get("/endoscopes")
def list_scopes():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "status": shape.q_enum(calc.SCOPE_STATUSES),
        "mec_test_due": shape.q_bool(),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("endoscope_assets",
                               lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("endoscope_assets", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/endoscopes/<scope_id>/reprocessing-start")
def start_reprocessing(scope_id):
    ctx = common.begin(["SterileProcessingTech"])
    shape.no_body()
    scope = common.find("endoscope_assets", scope_id)
    if scope["status"] not in ("SOILED", "QUARANTINED"):
        raise ApiError("ERR_SCOPE_STATE_INVALID")
    if scope["status"] == "QUARANTINED" and scope["consecutive_mec_failures"] >= 2:
        raise ApiError("ERR_SCOPE_STATE_INVALID")
    scope["status"] = "REPROCESSING"
    scope["reprocessing_started_by_user_id"] = ctx.user_id
    common.touch(scope)
    return envelope.ok(common.public("endoscope_assets", scope))


@bp.post("/endoscopes/<scope_id>/reprocessing-completion")
def complete_reprocessing(scope_id):
    ctx = common.begin(["SterileProcessingTech"])
    values, provided = shape.read_body([
        ("leak_test_passed", True, shape.v_bool(), False),
        ("mec_test_passed", False, shape.v_bool(), False),
    ])
    scope = common.find("endoscope_assets", scope_id)
    if scope["status"] != "REPROCESSING":
        raise ApiError("ERR_SCOPE_STATE_INVALID")
    if ctx.user_id != scope["reprocessing_started_by_user_id"]:
        raise ApiError("ERR_REPROCESSING_TECH_MISMATCH")

    mec_passed = values.get("mec_test_passed") is True
    passed = values["leak_test_passed"] and (not scope["mec_test_due"] or mec_passed)

    if passed:
        instant = store.iso(store.now())
        scope["status"] = "READY"
        scope["cycle_count"] = scope["cycle_count"] + 1
        scope["last_reprocessed_at"] = instant
        scope["hld_expires_at"] = store.iso(
            store.plus_hours(store.now(), calc.HLD_SHELF_HOURS)
        )
        scope["consecutive_mec_failures"] = 0
        scope["mec_test_due"] = calc.mec_test_due(scope["cycle_count"])
        scope["reprocessing_started_by_user_id"] = None
        common.touch(scope)
        return envelope.ok(common.public("endoscope_assets", scope))

    # hop one
    scope["status"] = "QUARANTINED"
    scope["consecutive_mec_failures"] = scope["consecutive_mec_failures"] + 1
    scope["reprocessing_started_by_user_id"] = None
    common.touch(scope)
    # hop two
    if scope["consecutive_mec_failures"] >= 2:
        scope["status"] = "RETIRED"
        common.touch(scope)
        # hop three
        common.retire_scope_cascade(scope)
    return envelope.ok(common.public("endoscope_assets", scope))


# --- supply lots -------------------------------------------------------------
@bp.post("/supply-lots")
def receive_lot():
    common.begin(["PracticeAdmin"])
    values, _provided = shape.read_body([
        ("item_type", True, shape.v_enum(calc.ITEM_TYPES), False),
        ("lot_number", True, shape.v_string(8, 8, LOT_NUMBER_RE), False),
        ("quantity_received", True, shape.v_int(1, 1000), False),
        ("expires_at", True, shape.v_instant(), False),
    ])
    for row in store.rows("supply_lots"):
        if row["lot_number"] == values["lot_number"]:
            raise ApiError("ERR_DUPLICATE_LOT_NUMBER")
    quantity = values["quantity_received"]
    row = common.new_row("supply_lots", {
        "item_type": values["item_type"],
        "lot_number": values["lot_number"],
        "quantity_received": quantity,
        "quantity_on_hand": quantity,
        "quantity_reserved": 0,
        "quantity_consumed": 0,
        "quantity_wasted": 0,
        "available_quantity": quantity,
        "expires_at": values["expires_at"],
        "status": "ACTIVE",
    })
    return envelope.created(common.public("supply_lots", row))


@bp.get("/supply-lots/<lot_id>")
def read_lot(lot_id):
    common.begin(shape.ALL_ROLES)
    shape.read_query({})
    shape.no_body()
    row = common.find("supply_lots", lot_id)
    return envelope.ok(common.public("supply_lots", row))


@bp.get("/supply-lots")
def list_lots():
    common.begin(shape.ALL_ROLES)
    filters = shape.read_query({
        "item_type": shape.q_enum(calc.ITEM_TYPES),
        "status": shape.q_enum(calc.LOT_STATUSES),
    })
    limit, offset = shape.pagination()
    shape.no_body()
    items = common.sorted_rows("supply_lots", lambda r: common.matches(r, filters))
    page = common.paginate(items, limit, offset)
    return envelope.listing(
        [common.public("supply_lots", r) for r in page],
        limit, offset, len(items),
    )


@bp.post("/supply-lots/<lot_id>/adjustments")
def adjust_lot(lot_id):
    common.begin(["PracticeAdmin"])
    values, provided = shape.read_body([
        ("reason", True, shape.v_enum(calc.ADJUSTMENT_REASONS), False),
        ("quantity", False, shape.v_int(1, 1000), False),
    ])
    reason = values["reason"]
    if reason in ("RECEIVE", "WRITE_OFF") and "quantity" not in provided:
        shape.bad("quantity is required for a %s adjustment" % reason)

    lot = common.find("supply_lots", lot_id)
    if lot["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise ApiError("ERR_LOT_STATE_INVALID")

    if reason == "RECEIVE":
        quantity = values["quantity"]
        lot["quantity_received"] = lot["quantity_received"] + quantity
        lot["quantity_on_hand"] = lot["quantity_on_hand"] + quantity
        common.lot_replenish_check(lot)
    elif reason == "WRITE_OFF":
        quantity = values["quantity"]
        if quantity > calc.lot_available(lot):
            raise ApiError("ERR_SUPPLY_EXHAUSTED")
        lot["quantity_on_hand"] = lot["quantity_on_hand"] - quantity
        lot["quantity_wasted"] = lot["quantity_wasted"] + quantity
        common.lot_exhaustion_check(lot)
    else:
        remainder = calc.lot_available(lot)
        lot["quantity_on_hand"] = lot["quantity_on_hand"] - remainder
        lot["quantity_wasted"] = lot["quantity_wasted"] + remainder
        lot["status"] = "QUARANTINED"
        calc.refresh_lot(lot)

    common.touch(lot)
    return envelope.ok(common.public("supply_lots", lot))
