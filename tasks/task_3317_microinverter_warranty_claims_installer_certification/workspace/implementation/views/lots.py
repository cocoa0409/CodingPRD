"""Production lot routes and the operator lot actions (PRD 3.5)."""

import db
import shapes
from approval import as_enum, as_number, as_str, body, raw
from auth import (
    ROLE_INSTALLER,
    ROLE_MONITORING,
    ROLE_PLATFORM_ADMIN,
    get_lot,
    require,
)
from errors import fail
from respond import ok, ok_list, pagination_meta
from services import common
from services import lots as lot_service

EMBED_MODELS = ("IQ7", "IQ8", "IQ7X_DISCONTINUED")
REPLACEMENT_MODELS = ("IQ7", "IQ8", "IQ8HC", "NONE")
LOT_ACTIONS = ("CLEAR_RECALL", "FORCE_WATCH", "OPEN_CAMPAIGN_BY_HAND")


def create_lot():
    data = body()
    lot_code = as_str(data, "lot_code")
    manufacture_month = as_str(data, "manufacture_month")
    embed_model_code = as_enum(data, "embed_model_code", EMBED_MODELS)
    replacement_model_code = as_enum(data, "replacement_model_code", REPLACEMENT_MODELS)
    defect_threshold_pct = as_number(
        data, "defect_threshold_pct", required_=False,
        default=float(common.DEFAULT_DEFECT_THRESHOLD_PCT), exclusive_minimum=0)

    for existing in db.DB.production_lots.values():
        if existing.get("lot_code") == lot_code:
            fail("ERR_INVALID_REQUEST_BODY", "lot_code must be unique")

    lot = {
        "id": common.new_id(),
        "created_at": common.now_iso(),
        "lot_code": lot_code,
        "manufacture_month": manufacture_month,
        "defect_threshold_pct": defect_threshold_pct,
        "embed_model_code": embed_model_code,
        "units_registered_count": 0,
        "failed_unit_count": 0,
        "window_failed_unit_count": 0,
        "defect_rate_cumulative_pct": 0.00,
        "defect_rate_window_pct": 0.00,
        "lot_status": "NORMAL",
        "corrective_action_required": False,
        "replacement_model_code": None if replacement_model_code == "NONE"
                                   else replacement_model_code,
        "watch_started_at": None,
        "status_overridden": False,
    }
    db.DB.production_lots[lot["id"]] = lot
    lot_service.evaluate_lot(lot)
    return ok(shapes.production_lot(lot), 201)


def read_lot(lot_id):
    lot = get_lot(lot_id)
    lot_service.evaluate_lot(lot)
    return ok(shapes.production_lot(lot))


def list_lot_units(lot_id):
    """The units registered against a lot.  No pagination parameters are
    declared for this nested read, so the whole collection is returned."""
    get_lot(lot_id)
    rows = db.by_created_at(db.all_units_of_lot(lot_id))
    return ok_list([shapes.unit(u) for u in rows],
                   pagination=pagination_meta(len(rows), len(rows)))


def lot_action():
    """Operator override of the automatic posture (PRD 3.5)."""
    data = body()
    lot_id = as_str(data, "lot_id")
    action = as_enum(data, "action", LOT_ACTIONS)
    lot = get_lot(lot_id)

    if action == "CLEAR_RECALL":
        common.set_many(lot, {
            "lot_status": "NORMAL",
            "corrective_action_required": False,
            "status_overridden": False,
        })
    elif action == "FORCE_WATCH":
        values = {"lot_status": "WATCH", "corrective_action_required": False,
                  "status_overridden": True}
        if not lot.get("watch_started_at"):
            values["watch_started_at"] = common.now_iso()
        common.set_many(lot, values)
    else:  # OPEN_CAMPAIGN_BY_HAND -- the manual entry into the same cascade
        common.set_many(lot, {
            "lot_status": "RECALL",
            "corrective_action_required": True,
            "status_overridden": True,
        })
        if not lot.get("watch_started_at"):
            common.set_many(lot, {"watch_started_at": common.now_iso()})
        lot_service.evaluate_lot(lot)

    common.recompute_units_of_lot(lot["id"])
    return ok(shapes.production_lot(lot))


def register(app):
    app.add_url_rule("/warranty/production-lots", "create_lot",
                     require(ROLE_PLATFORM_ADMIN)(create_lot), methods=["POST"])
    app.add_url_rule("/warranty/production-lots/<lot_id>", "read_lot",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_MONITORING)(read_lot),
                     methods=["GET"])
    app.add_url_rule("/warranty/production-lots/<lot_id>/units", "list_lot_units",
                     require(ROLE_PLATFORM_ADMIN, ROLE_INSTALLER, ROLE_MONITORING)(list_lot_units),
                     methods=["GET"])
    app.add_url_rule("/warranty/lot-actions", "lot_action",
                     require(ROLE_PLATFORM_ADMIN)(lot_action), methods=["POST"])