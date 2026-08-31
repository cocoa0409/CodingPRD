"""Placing, validating and cancelling a room-service tray (PRD section 3.6)."""

from flask import Blueprint

import api
import calcs
import domain
import serialize
import store
from calcs import LIQUID_ORDINAL, TEXTURE_ORDINAL
from errors import ApiError

bp = Blueprint("meal_orders", __name__, url_prefix="/nutrition/meal-orders")

FULFILLMENT_STATUSES = ("PENDING_VALIDATION", "VALIDATED", "IN_PRODUCTION", "PLATED",
                        "DELIVERED", "CANCELLED", "MISSED")
QA_STATUSES = ("NOT_CHECKED", "ACCURACY_PASSED", "ACCURACY_FAILED", "TEMP_PASSED",
               "TEMP_FAILED")


def _parse_lines(body):
    if "lines" not in body or body["lines"] is None:
        api.bad("Field 'lines' is required.")
    raw = body["lines"]
    if not isinstance(raw, list):
        api.bad("Field 'lines' must be an array.")
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            api.bad("Each entry of 'lines' must be an object.")
        menu_item_id = api.req_str(entry, "menu_item_id")
        quantity = api.req_int(entry, "quantity", lo=1, hi=10)
        parsed.append({"menu_item_id": menu_item_id, "quantity": quantity})
    return parsed


@bp.post("")
@api.require("DietClerk")
def create_meal_order():
    body = api.body()
    patient_id = api.req_id(body, "patient_id")
    period_id = api.req_id(body, "meal_period_id")
    diet_order_id = api.req_id(body, "diet_order_id")
    expected_version = api.req_int(body, "expected_diet_order_version")
    lines = _parse_lines(body)

    # Priority 5 -- body references resolved in the order the input list declares them.
    patient = store.get_patient(patient_id)
    period = store.get_meal_period(period_id)
    diet_order = store.get_diet_order(diet_order_id)
    items = [store.get_menu_item(l["menu_item_id"]) for l in lines]

    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")
    if period["status"] == "CLOSED":
        raise ApiError("ERR_MEAL_PERIOD_CLOSED", "The meal period is CLOSED.")
    if expected_version != diet_order["version"]:
        raise ApiError("ERR_STALE_DIET_ORDER_VERSION",
                       "expected_diet_order_version does not match the diet order.")
    for item in items:
        if item["status"] != "ACTIVE":
            raise ApiError("ERR_MENU_ITEM_DISCONTINUED",
                           "Menu item '%s' is DISCONTINUED." % item["item_code"])
    if store.now() >= period["order_cutoff_at"]:
        raise ApiError("ERR_ORDER_CUTOFF_PASSED",
                       "The ordering cutoff for this meal period has passed.")
    if not lines:
        raise ApiError("ERR_EMPTY_MEAL_ORDER", "A tray must carry at least one line.")
    for other in store.meal_orders.values():
        if (other["patient_id"] == patient_id
                and other["meal_period_id"] == period_id
                and other["fulfillment_status"] not in ("CANCELLED", "MISSED")):
            raise ApiError("ERR_DUPLICATE_MEAL_ORDER",
                           "The patient already holds a live tray for this period.")

    envelope = domain.envelope_of(diet_order)
    order = {
        "patient_id": patient_id,
        "meal_period_id": period_id,
        "diet_order_id": diet_order_id,
        "pinned_diet_order_version": diet_order["version"],
        "placed_by_user_id": api.actor(),
        "fulfillment_status": "PENDING_VALIDATION",
        "qa_status": "NOT_CHECKED",
        "revalidation_required": False,
        "effective_texture_level": envelope["effective_texture_level"],
        "effective_liquid_level": envelope["effective_liquid_level"],
        "total_sodium_mg": 0,
        "total_potassium_mg": 0,
        "total_carb_g": calcs.rhu(0, 1),
        "total_protein_g": calcs.rhu(0, 1),
        "food_cost_cents": 0,
        "requires_hot_probe": False,
        "requires_cold_probe": False,
        "hot_probe_celsius": None,
        "cold_probe_celsius": None,
        "accuracy_retry_count": 0,
        "temperature_retry_count": 0,
        "accuracy_checked_by_user_id": None,
        "temperature_checked_by_user_id": None,
        "delivered_at": None,
        "delivery_window_compliance": None,
        "service_compliance_score": None,
        "missed_reason": None,
    }
    store.stamp_new(order)
    store.meal_orders[order["id"]] = order

    for spec in lines:
        line = {
            "meal_order_id": order["id"],
            "menu_item_id": spec["menu_item_id"],
            "substituted_from_menu_item_id": None,
            "quantity": spec["quantity"],
            "line_status": "REQUESTED",
            "substitution_reason": None,
            "line_cost_cents": 0,
        }
        store.stamp_new(line)
        store.meal_order_lines[line["id"]] = line

    domain.recompute_tray(order, envelope["effective_texture_level"])

    # The tray is now linked to the prescription: the diet order's
    # linked_meal_order_count moves, and the tray pins the version it lands on.
    diet_order["linked_meal_order_count"] += 1
    store.touch(diet_order)
    order["pinned_diet_order_version"] = diet_order["version"]

    return api.created(serialize.meal_order(order))


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_meal_orders():
    patient_id = api.q_str("patient_id")
    period_id = api.q_str("meal_period_id")
    diet_order_id = api.q_str("diet_order_id")
    fulfillment = api.q_enum("fulfillment_status", FULFILLMENT_STATUSES)
    qa = api.q_enum("qa_status", QA_STATUSES)
    rows = api.filtered(list(store.meal_orders.values()),
                        [(patient_id, "patient_id"), (period_id, "meal_period_id"),
                         (diet_order_id, "diet_order_id"),
                         (fulfillment, "fulfillment_status"), (qa, "qa_status")])
    return api.paged(rows, serialize.meal_order)


@bp.get("/<order_id>")
@api.require(*api.ALL_ROLES)
def read_meal_order(order_id):
    return api.ok(serialize.meal_order(store.get_meal_order(order_id)))


@bp.post("/<order_id>/validate")
@api.require("DietClerk")
def validate_meal_order(order_id):
    order = store.get_meal_order(order_id)
    patient = store.patients[order["patient_id"]]
    period = store.meal_periods[order["meal_period_id"]]

    if patient["status"] != "ADMITTED":
        raise ApiError("ERR_PATIENT_DISCHARGED", "The patient is DISCHARGED.")
    if period["status"] == "CLOSED":
        raise ApiError("ERR_MEAL_PERIOD_CLOSED", "The meal period is CLOSED.")
    if order["fulfillment_status"] != "PENDING_VALIDATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a PENDING_VALIDATION tray may be validated.")

    diet_order = store.diet_orders[order["diet_order_id"]]
    if diet_order["status"] != "ACTIVE":
        raise ApiError("ERR_DIET_ORDER_NOT_ACTIVE",
                       "The pinned diet order is not ACTIVE.")
    if order["pinned_diet_order_version"] != diet_order["version"]:
        raise ApiError("ERR_DIET_ORDER_SUPERSEDED",
                       "The tray has drifted away from the diet order envelope.")
    if patient["npo_status"] != "NONE":
        raise ApiError("ERR_NPO_ACTIVE", "The patient is under a nil-per-os hold.")

    envelope = domain.envelope_of(diet_order)
    lines = store.lines_of(order["id"])
    items = [store.menu_items[l["menu_item_id"]] for l in lines]

    documented = set(patient["allergen_codes"])
    for item in items:
        if documented & set(item["allergen_codes"]):
            raise ApiError("ERR_ALLERGEN_CONFLICT",
                           "Menu item '%s' declares a documented allergen."
                           % item["item_code"])
    floor_texture = TEXTURE_ORDINAL[envelope["effective_texture_level"]]
    for item in items:
        if TEXTURE_ORDINAL[item["texture_level"]] < floor_texture:
            raise ApiError("ERR_TEXTURE_LEVEL_VIOLATION",
                           "Menu item '%s' is coarser than the texture floor."
                           % item["item_code"])
    floor_liquid = LIQUID_ORDINAL[envelope["effective_liquid_level"]]
    for item in items:
        if item["liquid_level"] is not None and LIQUID_ORDINAL[item["liquid_level"]] < floor_liquid:
            raise ApiError("ERR_LIQUID_LEVEL_VIOLATION",
                           "Menu item '%s' is thinner than the thickness floor."
                           % item["item_code"])
    forbidden = set(envelope["forbidden_tag_codes_effective"] or [])
    for item in items:
        if forbidden & set(item["tag_codes"]):
            raise ApiError("ERR_FORBIDDEN_TAG",
                           "Menu item '%s' carries a forbidden dietary tag."
                           % item["item_code"])
    for item in items:
        if item["status"] != "ACTIVE":
            raise ApiError("ERR_MENU_ITEM_DISCONTINUED",
                           "Menu item '%s' is DISCONTINUED." % item["item_code"])

    totals, line_costs, food_cost = domain.compute_tray_values(
        order, envelope["effective_texture_level"])

    if (envelope["effective_sodium_cap_mg"] is not None
            and totals["total_sodium_mg"] > envelope["effective_sodium_cap_mg"]):
        raise ApiError("ERR_NUTRIENT_CAP_EXCEEDED", "The tray exceeds its sodium ceiling.")
    if (envelope["effective_potassium_cap_mg"] is not None
            and totals["total_potassium_mg"] > envelope["effective_potassium_cap_mg"]):
        raise ApiError("ERR_NUTRIENT_CAP_EXCEEDED",
                       "The tray exceeds its potassium ceiling.")
    if (envelope["effective_carb_cap_g"] is not None
            and totals["total_carb_g"] > calcs.dec(envelope["effective_carb_cap_g"])):
        raise ApiError("ERR_NUTRIENT_CAP_EXCEEDED",
                       "The tray exceeds its carbohydrate ceiling.")

    if period["committed_tray_count"] + 1 > period["production_capacity_trays"]:
        raise ApiError("ERR_TRAY_CAPACITY_EXCEEDED",
                       "The meal period has no production capacity left.")
    if (period["cost_ceiling_cents"] is not None
            and period["committed_food_cost_cents"] + food_cost > period["cost_ceiling_cents"]):
        raise ApiError("ERR_PERIOD_COST_CEILING_EXCEEDED",
                       "The meal period cost ceiling would be exceeded.")

    order["effective_texture_level"] = envelope["effective_texture_level"]
    order["effective_liquid_level"] = envelope["effective_liquid_level"]
    domain.apply_tray_values(order, totals, line_costs, food_cost)
    order["revalidation_required"] = False
    order["fulfillment_status"] = "VALIDATED"
    store.touch(order)

    domain.refresh_period_ledger(period)
    store.touch(period)
    return api.ok(serialize.meal_order(order))


@bp.post("/<order_id>/cancel")
@api.require("DietClerk")
def cancel_meal_order(order_id):
    order = store.get_meal_order(order_id)
    if order["fulfillment_status"] not in domain.OPEN_TRAY_STATES:
        raise ApiError("ERR_INVALID_STATE",
                       "A %s tray cannot be cancelled." % order["fulfillment_status"])

    was_committed = order["fulfillment_status"] in domain.COMMITTED_STATES
    order["fulfillment_status"] = "CANCELLED"
    store.touch(order)

    if was_committed:
        period = store.meal_periods[order["meal_period_id"]]
        domain.refresh_period_ledger(period)
        store.touch(period)
    return api.ok(serialize.meal_order(order))
