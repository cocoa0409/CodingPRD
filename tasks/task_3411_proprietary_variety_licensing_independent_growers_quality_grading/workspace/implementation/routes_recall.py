"""RecallOrder endpoint: enforce (pinned 3-link cascade: plantings -> lots -> windows)."""
from flask import Blueprint

import store
from calc import finalize_royalty
from errors import err, ERR_INVALID_STATE, ERR_NOT_FOUND
from helpers import dump, require_roles, success
from routes_plant_lots import recompute_availability

bp = Blueprint("recall_orders", __name__)


@bp.route("/licensing/recall-orders/<recallOrderId>/enforce", methods=["POST"])
@require_roles("ComplianceOfficer")
def enforce_recall_order(recallOrderId):
    order = store.db["recall_orders"].get(recallOrderId)
    if order is None:
        raise err(ERR_NOT_FOUND, "No recall order with the given id")
    if order["status"] != "ISSUED":
        raise err(ERR_INVALID_STATE, "Recall order is not ISSUED")
    now = store.clock_now()
    variety_id = order["variety_id"]

    # CASCADE link 1: plantings of the recalled variety
    touched_lot_ids = set()
    touched_window_ids = set()
    recalled_count = 0
    total_comp = 0
    targets = [
        p for p in store.db["plantings"].values()
        if store.db["plant_lots"][p["plant_lot_id"]]["variety_id"] == variety_id
        and p["status"] in ("PLANNED", "PLANTED", "HARVESTING")
    ]
    targets.sort(key=lambda p: (p["created_at"], p["id"]))
    for p in targets:
        lot = store.db["plant_lots"][p["plant_lot_id"]]
        if p["status"] == "PLANNED":
            lot["plants_reserved"] -= p["planned_plants"]
            p["recall_compensation_cents"] = 0
        else:  # PLANTED | HARVESTING: full field settlement
            lot["plants_planted"] -= p["plants_planted_actual"]
            lot["plants_destroyed"] += p["plants_planted_actual"]
            window = store.db["harvest_windows"].get(p["harvest_window_id"])
            if window is not None:
                window["booked_volume_kg"] -= p["expected_yield_kg"]
                touched_window_ids.add(window["id"])
            agreement = store.db["agreements"].get(p["agreement_id"])
            if agreement is not None:
                agreement["units_planted"] -= p["plants_planted_actual"]
                store.touch(agreement)
            p["recall_compensation_cents"] = (
                p["plants_planted_actual"] * order["compensation_per_plant_cents"]
            )
            total_comp += p["recall_compensation_cents"]
        p["status"] = "RECALLED"
        p["recalled_at"] = now
        store.touch(p)
        recalled_count += 1
        touched_lot_ids.add(lot["id"])

    # CASCADE link 2/3: touched lots recompute; lots with availability -> RECALLED
    for lot_id in touched_lot_ids:
        lot = store.db["plant_lots"][lot_id]
        recompute_availability(lot)
        if lot["plants_available"] > 0 and lot["status"] in ("SHIPPED", "PLANTED"):
            lot["plants_destroyed"] += lot["plants_available"]
            recompute_availability(lot)
            lot["status"] = "RECALLED"
            finalize_royalty(lot)  # final royalty exactly as at depletion
        store.touch(lot)

    # CASCADE link 3 (windows): booked volumes already debited above; touch them
    for window_id in touched_window_ids:
        store.touch(store.db["harvest_windows"][window_id])

    order["status"] = "COMPLETE"
    order["plantings_recalled_count"] = recalled_count
    order["total_compensation_cents"] = total_comp
    order["enforced_at"] = now
    store.touch(order)
    return success(dump(order))
