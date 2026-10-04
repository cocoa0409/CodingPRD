"""State machines, cascades and business-rule enforcement (PRD sections 3 and 2.5).

Rule 8 (transition reachability) and rule 9 (terminal-state guard) are applied by
`check_reachability`: a terminal row with no declared outgoing transition reports
ERR_ENTITY_TERMINAL, any other undeclared move reports ERR_INVALID_STATE. The one
declared move out of a terminal state is the PAID -> DISPUTED cash reversal.
"""

from calculations import (
    field_kitchen_food_safety_score,
    run_cost_allocation,
    run_pending_planned_meals,
    supplier_standing,
    meal_order_final_settlement,
)
from core import DB, assign, hours_later, now, set_always, touch
from errors import fail
from models import (
    recompute_partner_quality,
    record_production,
    refresh_distribution_run,
    refresh_distribution_site,
    refresh_donor_commitment,
    refresh_field_kitchen,
    refresh_incident,
    refresh_meal_order,
    refresh_partner_kitchen,
    refresh_supplier,
)
from validations import ref_row, same_incident

# Declared outgoing transitions of every single-dimension state machine.
ALLOWED = {
    "incidents": {
        "MONITORING": {"ACTIVE"},
        "ACTIVE": {"WINDING_DOWN"},
        "WINDING_DOWN": {"ACTIVE", "CLOSED"},
    },
    "field_kitchens": {
        "SITED": {"UTILITIES_PENDING"},
        "UTILITIES_PENDING": {"FOOD_SAFETY_CLEARED"},
        "FOOD_SAFETY_CLEARED": {"OPERATIONAL"},
        "OPERATIONAL": {"SUSPENDED", "DEMOBILIZED"},
        "SUSPENDED": {"FOOD_SAFETY_CLEARED"},
    },
    "meal_orders": {
        "PLACED": {"IN_PRODUCTION", "CANCELLED"},
        "IN_PRODUCTION": {"QUALITY_HOLD"},
        "QUALITY_HOLD": {"READY", "IN_PRODUCTION", "REJECTED"},
        "READY": {"DISPATCHED"},
        "DISPATCHED": {"DELIVERED"},
    },
    "distribution_runs": {
        "PLANNED": {"LOADING", "ABORTED"},
        "LOADING": {"EN_ROUTE", "ABORTED"},
        "EN_ROUTE": {"DELIVERING"},
        "DELIVERING": {"EN_ROUTE", "COMPLETED"},
    },
    "distribution_stops": {
        "PENDING": {"DELIVERED", "FAILED"},
        "DELIVERED": {"FAILED"},
    },
    "ingredient_purchases": {
        "REQUESTED": {"CONFIRMED", "CANCELLED"},
        "CONFIRMED": {"DELIVERED"},
        "DELIVERED": {"PAID", "DISPUTED"},
        "DISPUTED": {"DELIVERED", "CANCELLED"},
        "PAID": {"DISPUTED"},
    },
    "donor_commitments": {
        "PLEDGED": {"RECEIVED", "WITHDRAWN"},
        "RECEIVED": {"ALLOCATED"},
        "ALLOCATED": {"RECEIVED", "PARTIALLY_DISBURSED", "CLOSED"},
        "PARTIALLY_DISBURSED": {"PARTIALLY_DISBURSED", "CLOSED"},
    },
}

CONTRACT_ALLOWED = {
    "PROSPECT": {"VETTING"},
    "VETTING": {"CONTRACTED", "PROSPECT"},
    "CONTRACTED": {"SUSPENDED", "TERMINATED"},
    "SUSPENDED": {"CONTRACTED"},
}

PRODUCTION_ALLOWED = {
    "IDLE": {"PRODUCING"},
    "PRODUCING": {"AT_CAPACITY"},
    "AT_CAPACITY": {"COOLDOWN"},
    "COOLDOWN": {"IDLE"},
}

TERMINAL = {
    "incidents": lambda r: r["status"] == "CLOSED",
    "field_kitchens": lambda r: r["site_status"] == "DEMOBILIZED",
    "meal_orders": lambda r: r["status"] in ("DELIVERED", "REJECTED", "CANCELLED"),
    "distribution_runs": lambda r: r["status"] in ("COMPLETED", "ABORTED"),
    "distribution_stops": lambda r: r["status"] in ("FAILED", "SKIPPED"),
    "ingredient_purchases": lambda r: r["status"] in ("PAID", "CANCELLED"),
    "donor_commitments": lambda r: r["status"] in ("CLOSED", "WITHDRAWN"),
}


def check_reachability(kind, row, current_state, to_state):
    if to_state in ALLOWED.get(kind, {}).get(current_state, set()):
        return
    is_terminal = TERMINAL.get(kind)
    if is_terminal is not None and is_terminal(row):
        fail("ERR_ENTITY_TERMINAL")
    fail("ERR_INVALID_STATE")


def _kitchens_of(incident_id):
    return [k for k in DB["field_kitchens"].values() if k["incident_id"] == incident_id]


def _runs_of(incident_id):
    return [r for r in DB["distribution_runs"].values() if r["incident_id"] == incident_id]


def _orders_of_kitchen(kitchen_id):
    return [o for o in DB["meal_orders"].values() if o["partner_kitchen_id"] == kitchen_id]


def _stops_of_run(run_id):
    return [s for s in DB["distribution_stops"].values() if s["distribution_run_id"] == run_id]


# --------------------------------------------------------------------------
# Shared cascades
# --------------------------------------------------------------------------

def _maybe_service_alert(site):
    """Hop 2: skipped stops strictly outnumbering delivered ones alerts the site."""
    if site["skipped_stop_count"] > site["delivered_stop_count"] \
            and site["status"] in ("REGISTERED", "ACTIVE"):
        assign(site, "status", "SERVICE_ALERT")


def skip_pending_stops(run, reason):
    """Cascade hop 1 of a run abort: every PENDING stop becomes SKIPPED."""
    for stop in _stops_of_run(run["id"]):
        if stop["status"] != "PENDING":
            continue
        assign(stop, "status", "SKIPPED")
        assign(stop, "failure_reason", reason)
        site = DB["distribution_sites"].get(stop["distribution_site_id"])
        if site is not None:
            refresh_distribution_site(site)
            _maybe_service_alert(site)


def _abort_runs_of_kitchen(kitchen, abort_reason, stop_reason, only_planned=False):
    for run in DB["distribution_runs"].values():
        if run["field_kitchen_id"] != kitchen["id"]:
            continue
        if only_planned:
            if run["status"] != "PLANNED":
                continue
        elif run["status"] not in ("PLANNED", "LOADING"):
            continue
        assign(run, "status", "ABORTED")
        assign(run, "abort_reason", abort_reason)
        skip_pending_stops(run, stop_reason)
        refresh_distribution_run(run)


def _cancel_placed_orders(kitchen, reason):
    for order in _orders_of_kitchen(kitchen["id"]):
        if order["status"] != "PLACED":
            continue
        assign(order, "status", "CANCELLED")
        assign(order, "cancel_reason", reason)
        refresh_meal_order(order)
        incident = DB["incidents"].get(order["incident_id"])
        if incident is not None:
            refresh_incident(incident)


# --------------------------------------------------------------------------
# Incident
# --------------------------------------------------------------------------

def transition_incident(row, data):
    to_state = data["to_state"]
    check_reachability("incidents", row, row["status"], to_state)

    if to_state == "ACTIVE":
        if row["status"] == "MONITORING":
            submitted = [a for a in DB["assessments"].values()
                         if a["incident_id"] == row["id"] and a["status"] == "SUBMITTED"]
            if not submitted:
                fail("ERR_INVALID_STATE", "The activation needs a SUBMITTED assessment first.")
            assign(row, "status", "ACTIVE")
            assign(row, "activated_at", now())
            for kitchen in _kitchens_of(row["id"]):
                if kitchen["site_status"] == "SITED":
                    assign(kitchen, "site_status", "UTILITIES_PENDING")
        else:
            wind_down_at = row["wind_down_started_at"]
            fresh = [a for a in DB["assessments"].values()
                     if a["incident_id"] == row["id"] and a["status"] == "SUBMITTED"
                     and wind_down_at is not None and a["assessed_at"] > wind_down_at]
            if not fresh:
                fail("ERR_INVALID_STATE", "Re-escalation needs an assessment newer than the wind-down.")
            assign(row, "status", "ACTIVE")
            assign(row, "wind_down_started_at", None)
            for kitchen in _kitchens_of(row["id"]):
                if kitchen["site_status"] == "DEMOBILIZED" \
                        and kitchen["demobilized_at"] == wind_down_at:
                    assign(kitchen, "site_status", "SITED")
                    assign(kitchen, "demobilized_at", None)

    elif to_state == "WINDING_DOWN":
        busy = [o for o in DB["meal_orders"].values()
                if o["incident_id"] == row["id"] and o["status"] in ("IN_PRODUCTION", "QUALITY_HOLD")]
        if busy:
            fail("ERR_INVALID_STATE", "Food is still on the line.")
        assign(row, "status", "WINDING_DOWN")
        stamp = now()
        assign(row, "wind_down_started_at", stamp)
        for kitchen in _kitchens_of(row["id"]):
            if kitchen["site_status"] in ("SITED", "UTILITIES_PENDING"):
                assign(kitchen, "site_status", "DEMOBILIZED")
                assign(kitchen, "demobilized_at", stamp)

    elif to_state == "CLOSED":
        if any(k["site_status"] != "DEMOBILIZED" for k in _kitchens_of(row["id"])):
            fail("ERR_INVALID_STATE", "Every field kitchen must be DEMOBILIZED.")
        if any(r["status"] not in ("COMPLETED", "ABORTED") for r in _runs_of(row["id"])):
            fail("ERR_INVALID_STATE", "Every distribution run must be COMPLETED or ABORTED.")
        assign(row, "status", "CLOSED")
        assign(row, "closed_at", now())
        for site in DB["distribution_sites"].values():
            if site["incident_id"] == row["id"] \
                    and site["status"] in ("REGISTERED", "ACTIVE", "SERVICE_ALERT"):
                assign(site, "status", "CLOSED")
        for commitment in DB["donor_commitments"].values():
            if commitment["incident_id"] == row["id"] \
                    and commitment["status"] in ("ALLOCATED", "PARTIALLY_DISBURSED"):
                assign(commitment, "status", "CLOSED")

    refresh_incident(row)
    return row


# --------------------------------------------------------------------------
# FieldKitchen
# --------------------------------------------------------------------------

def transition_field_kitchen(row, data):
    to_state = data["to_state"]
    current = row["site_status"]
    check_reachability("field_kitchens", row, current, to_state)

    if to_state == "UTILITIES_PENDING":
        assessment = DB["assessments"].get(row["assessment_id"])
        if assessment is not None and assessment["access_constraint"] == "BLOCKED":
            fail("ERR_SITE_ACCESS_BLOCKED")
        assign(row, "site_status", "UTILITIES_PENDING")

    elif to_state == "FOOD_SAFETY_CLEARED":
        if current == "UTILITIES_PENDING":
            if row["power_source"] == "NONE" or row["water_source"] == "NONE":
                fail("ERR_KITCHEN_UTILITY_MISSING")
            if row["food_safety_score"] < 70:
                fail("ERR_FOOD_SAFETY_SCORE_TOO_LOW")
        else:
            inspected = row["last_inspection_at"]
            suspended = row["suspended_at"]
            if inspected is None or suspended is None or not inspected > suspended:
                fail("ERR_INVALID_STATE", "A fresh inspection is required before recovery.")
            if row["food_safety_score"] < 70:
                fail("ERR_FOOD_SAFETY_SCORE_TOO_LOW")
            assign(row, "suspended_at", None)
        assign(row, "site_status", "FOOD_SAFETY_CLEARED")

    elif to_state == "OPERATIONAL":
        incident = DB["incidents"].get(row["incident_id"])
        if incident is None or incident["status"] != "ACTIVE":
            fail("ERR_INCIDENT_NOT_ACTIVE")
        assign(row, "site_status", "OPERATIONAL")
        assign(row, "activated_at", now())

    elif to_state == "SUSPENDED":
        assign(row, "site_status", "SUSPENDED")
        assign(row, "suspended_at", now())
        _abort_runs_of_kitchen(row, "ORIGIN_KITCHEN_SUSPENDED", "ORIGIN_KITCHEN_SUSPENDED")

    elif to_state == "DEMOBILIZED":
        incident = DB["incidents"].get(row["incident_id"])
        if incident is None or incident["status"] not in ("WINDING_DOWN", "CLOSED"):
            fail("ERR_INVALID_STATE", "The activation must be winding down or closed.")
        assign(row, "site_status", "DEMOBILIZED")
        assign(row, "demobilized_at", now())
        _abort_runs_of_kitchen(row, "KITCHEN_DEMOBILIZED", "RUN_ABORTED", only_planned=True)

    refresh_field_kitchen(row)
    return row


def inspect_field_kitchen(row, data):
    assign(row, "power_source", data["power_source"])
    assign(row, "water_source", data["water_source"])
    assign(row, "refrigeration_hours_available", data["refrigeration_hours_available"])
    assign(row, "daily_capacity_meals", data["daily_capacity_meals"])
    assign(row, "last_inspection_at", now())
    assign(row, "food_safety_score", field_kitchen_food_safety_score(
        row["power_source"], row["water_source"],
        row["refrigeration_hours_available"], row["daily_capacity_meals"]))
    return row


# --------------------------------------------------------------------------
# PartnerKitchen -- two independent dimensions
# --------------------------------------------------------------------------

def transition_partner_kitchen(row, data):
    dimension = data["dimension"]
    to_state = data["to_state"]

    if dimension == "CONTRACT":
        current = row["contract_status"]
        if to_state not in CONTRACT_ALLOWED.get(current, set()):
            fail("ERR_ENTITY_TERMINAL" if current == "TERMINATED" else "ERR_INVALID_STATE")

        if to_state == "VETTING":
            if not row["bank_verified"]:
                fail("ERR_BANK_NOT_VERIFIED")
        # The payload's vetting_score is applied by this transition, but every
        # precondition is validated first so a rejected request mutates nothing.
        payload_score = data.get("vetting_score")
        effective_score = payload_score if payload_score is not None else row["vetting_score"]
        if to_state == "CONTRACTED" and effective_score < 60:
            fail("ERR_VETTING_SCORE_TOO_LOW")
        if payload_score is not None:
            assign(row, "vetting_score", payload_score)
        if to_state == "PROSPECT":
            assign(row, "vetting_score", 0)
        if to_state == "TERMINATED":
            unresolved = [o for o in _orders_of_kitchen(row["id"])
                          if o["status"] not in ("DELIVERED", "REJECTED", "CANCELLED")]
            if unresolved:
                fail("ERR_INVALID_STATE", "Every batch must be resolved before termination.")

        assign(row, "contract_status", to_state)

        if to_state == "CONTRACTED":
            assign(row, "contracted_at", now())
        elif to_state == "SUSPENDED":
            if row["production_status"] != "IDLE":
                assign(row, "production_status", "COOLDOWN")
                assign(row, "cooldown_until", hours_later(8))
        elif to_state == "TERMINATED":
            assign(row, "terminated_at", now())
            _cancel_placed_orders(row, "KITCHEN_TERMINATED")
        return row

    current = row["production_status"]
    if to_state not in PRODUCTION_ALLOWED.get(current, set()):
        fail("ERR_INVALID_STATE")

    refresh_partner_kitchen(row)
    if to_state == "PRODUCING":
        if row["contract_status"] != "CONTRACTED":
            fail("ERR_INVALID_STATE", "The restaurant is not under contract.")
        cooldown = row.get("cooldown_until")
        if cooldown is not None and now() < cooldown:
            fail("ERR_COOLDOWN_ACTIVE")
        assign(row, "production_status", "PRODUCING")
        assign(row, "production_started_at", now())
    elif to_state == "AT_CAPACITY":
        if row["meals_produced_today"] < row["daily_capacity_meals"]:
            fail("ERR_INVALID_STATE", "Daily capacity has not been reached.")
        assign(row, "production_status", "AT_CAPACITY")
        _cancel_placed_orders(row, "KITCHEN_AT_CAPACITY")
    elif to_state == "COOLDOWN":
        assign(row, "production_status", "COOLDOWN")
        assign(row, "cooldown_until", hours_later(8))
    elif to_state == "IDLE":
        cooldown = row.get("cooldown_until")
        if cooldown is not None and now() < cooldown:
            fail("ERR_COOLDOWN_ACTIVE")
        assign(row, "production_status", "IDLE")
        assign(row, "cooldown_until", None)
    return row


# --------------------------------------------------------------------------
# MealOrder
# --------------------------------------------------------------------------

def transition_meal_order(row, data):
    to_state = data["to_state"]
    current = row["status"]
    check_reachability("meal_orders", row, current, to_state)

    kitchen = DB["partner_kitchens"].get(row["partner_kitchen_id"])
    incident = DB["incidents"].get(row["incident_id"])

    if to_state == "IN_PRODUCTION":
        if current == "PLACED":
            if kitchen is None or kitchen["contract_status"] != "CONTRACTED":
                fail("ERR_PARTNER_KITCHEN_NOT_CONTRACTED")
            if kitchen["production_status"] not in ("IDLE", "PRODUCING"):
                fail("ERR_INVALID_STATE", "The kitchen cannot take on new work.")
        else:
            score = data.get("quality_check_score")
            if score is None:
                fail("ERR_INVALID_REQUEST", "quality_check_score is required for rework.")
            if not 60 <= score <= 79:
                fail("ERR_INVALID_STATE", "The score does not fall in the rework band.")
            if row["rework_count"] >= 2:
                fail("ERR_INVALID_STATE", "The batch has already been reworked twice.")
            assign(row, "rework_count", row["rework_count"] + 1)
            assign(row, "quality_check_score", score)
        assign(row, "status", "IN_PRODUCTION")

    elif to_state == "QUALITY_HOLD":
        produced = data.get("produced_meals")
        if produced is None:
            fail("ERR_INVALID_REQUEST", "produced_meals is required.")
        assign(row, "produced_meals", produced)
        refresh_meal_order(row)
        assign(row, "status", "QUALITY_HOLD")
        if kitchen is not None:
            record_production(kitchen, produced)

    elif to_state == "READY":
        score = data.get("quality_check_score")
        if score is None:
            fail("ERR_INVALID_REQUEST", "quality_check_score is required.")
        if score < 80:
            fail("ERR_INVALID_STATE", "A score below 80 cannot release the batch.")
        assign(row, "quality_check_score", score)
        assign(row, "rejected_meals", data.get("rejected_meals") or 0)
        refresh_meal_order(row)
        assign(row, "ready_at", now())
        assign(row, "status", "READY")
        if kitchen is not None:
            recompute_partner_quality(kitchen)

    elif to_state == "REJECTED":
        score = data.get("quality_check_score")
        if score is None:
            fail("ERR_INVALID_REQUEST", "quality_check_score is required.")
        if not (score <= 59 or row["rework_count"] >= 2):
            fail("ERR_INVALID_STATE", "The batch cannot be rejected on this score.")
        assign(row, "quality_check_score", score)
        assign(row, "rejected_meals", row.get("produced_meals") or 0)
        assign(row, "accepted_meals", 0)
        assign(row, "status", "REJECTED")
        row["_rejected_at"] = now()
        if kitchen is not None:
            recompute_partner_quality(kitchen)
        if incident is not None:
            refresh_incident(incident)

    elif to_state == "DISPATCHED":
        run_id = data.get("distribution_run_id")
        if run_id is None:
            fail("ERR_INVALID_REQUEST", "distribution_run_id is required.")
        run = DB["distribution_runs"].get(run_id)
        if run is None:
            fail("ERR_REFERENCED_ENTITY_NOT_FOUND")
        same_incident(row["incident_id"], run)
        if run["status"] != "LOADING":
            fail("ERR_INVALID_STATE", "The run must be LOADING to receive a batch.")
        assign(row, "distribution_run_id", run["id"])
        assign(run, "loaded_meals", (run.get("loaded_meals") or 0) + (row.get("accepted_meals") or 0))
        refresh_distribution_run(run)
        assign(row, "status", "DISPATCHED")

    elif to_state == "DELIVERED":
        run = DB["distribution_runs"].get(row.get("distribution_run_id"))
        if run is None or run["status"] != "DELIVERING":
            fail("ERR_INVALID_STATE", "The run must be DELIVERING.")
        price = kitchen["per_meal_price_cents"] if kitchen is not None else 0
        assign(row, "final_cost_cents", meal_order_final_settlement(
            row.get("accepted_meals") or 0, price, row.get("quality_check_score")))
        assign(row, "delivered_at", now())
        assign(row, "status", "DELIVERED")
        if kitchen is not None:
            recompute_partner_quality(kitchen)
            refresh_partner_kitchen(kitchen)
            if kitchen["meals_produced_today"] >= kitchen["daily_capacity_meals"] \
                    and kitchen["production_status"] != "AT_CAPACITY":
                assign(kitchen, "production_status", "AT_CAPACITY")
                _cancel_placed_orders(kitchen, "KITCHEN_AT_CAPACITY")
        if incident is not None:
            refresh_incident(incident)

    elif to_state == "CANCELLED":
        assign(row, "cancel_reason", data.get("cancel_reason"))
        assign(row, "status", "CANCELLED")
        if incident is not None:
            refresh_incident(incident)

    return row


# --------------------------------------------------------------------------
# DistributionRun
# --------------------------------------------------------------------------

def transition_run(row, data):
    to_state = data["to_state"]
    current = row["status"]
    check_reachability("distribution_runs", row, current, to_state)

    kitchen = DB["field_kitchens"].get(row["field_kitchen_id"])

    if to_state == "LOADING":
        if kitchen is None or kitchen["site_status"] != "OPERATIONAL":
            fail("ERR_ORIGIN_KITCHEN_NOT_OPERATIONAL")
        if not row["driver_safety_training_completed"]:
            fail("ERR_DRIVER_SAFETY_TRAINING_REQUIRED")
        if data.get("loaded_meals") is not None:
            assign(row, "loaded_meals", data["loaded_meals"])
        assign(row, "status", "LOADING")

    elif to_state == "EN_ROUTE":
        if current == "LOADING":
            loaded = data.get("loaded_meals")
            if loaded is None:
                fail("ERR_INVALID_REQUEST", "loaded_meals is required to leave LOADING.")
            if loaded <= 0:
                fail("ERR_INVALID_REQUEST", "loaded_meals must be greater than 0.")
            if run_pending_planned_meals(row["id"]) > loaded:
                fail("ERR_RUN_LOAD_EXCEEDS_CAPACITY")
            assign(row, "loaded_meals", loaded)
        else:
            refresh_distribution_run(row)
            if row["returned_meals"] <= 0:
                fail("ERR_INVALID_STATE", "Nothing was returned to the depot.")
            if run_pending_planned_meals(row["id"]) < 1:
                fail("ERR_INVALID_STATE", "No stop is still pending.")
            refresh_distribution_run(row)   # recompute returned_meals on the reload
        assign(row, "status", "EN_ROUTE")

    elif to_state == "DELIVERING":
        assign(row, "status", "DELIVERING")

    elif to_state == "COMPLETED":
        if any(s["status"] == "PENDING" for s in _stops_of_run(row["id"])):
            fail("ERR_INVALID_STATE", "Every stop must have an outcome before completion.")
        assign(row, "status", "COMPLETED")
        assign(row, "completed_at", now())
        unallocated = run_cost_allocation(row)
        assign(row, "unallocated_cost_cents", unallocated)
        refresh_distribution_run(row)   # pins returned_meals via run_meal_conservation

    elif to_state == "ABORTED":
        assign(row, "status", "ABORTED")
        assign(row, "abort_reason", data.get("abort_reason"))
        skip_pending_stops(row, "RUN_ABORTED")
        refresh_distribution_run(row)

    return row


# --------------------------------------------------------------------------
# DistributionStop
# --------------------------------------------------------------------------

def transition_stop(row, data):
    to_state = data["to_state"]
    current = row["status"]
    check_reachability("distribution_stops", row, current, to_state)

    run = DB["distribution_runs"].get(row["distribution_run_id"])
    site = DB["distribution_sites"].get(row["distribution_site_id"])

    if to_state == "DELIVERED":
        if run is None or run["status"] != "DELIVERING":
            fail("ERR_RUN_NOT_DELIVERING")
        if site is not None and site["access_constraint"] == "BLOCKED":
            fail("ERR_SITE_ACCESS_BLOCKED")
        delivered = data.get("delivered_meals")
        if delivered is None:
            fail("ERR_INVALID_REQUEST", "delivered_meals is required.")
        if delivered > row["planned_meals"]:
            fail("ERR_INVALID_STATE", "The handover cannot exceed the planned meals.")
        assign(row, "delivered_meals", delivered)
        assign(row, "delivered_at", now())
        assign(row, "status", "DELIVERED")
        if site is not None:
            refresh_distribution_site(site)
            if site["status"] == "REGISTERED":
                assign(site, "status", "ACTIVE")
            elif site["status"] == "SERVICE_ALERT" \
                    and site["delivered_stop_count"] > site["skipped_stop_count"]:
                assign(site, "status", "ACTIVE")

    elif to_state == "FAILED":
        if current == "PENDING":
            if run is None or run["status"] != "DELIVERING":
                fail("ERR_RUN_NOT_DELIVERING")
            assign(row, "failure_reason", data.get("failure_reason"))
            assign(row, "status", "FAILED")
        else:
            # compensating reversal of a recorded handover
            if run is None or run["status"] not in ("DELIVERING", "COMPLETED"):
                fail("ERR_INVALID_STATE", "The run must be DELIVERING or COMPLETED.")
            assign(row, "failure_reason", data.get("failure_reason"))
            assign(row, "delivered_meals", 0)
            assign(row, "status", "FAILED")
            if site is not None:
                refresh_distribution_site(site)

    if run is not None:
        refresh_distribution_run(run)
    return row


# --------------------------------------------------------------------------
# Supplier standing recomputation (derived, never set by hand)
# --------------------------------------------------------------------------

def _recompute_standing(supplier):
    if supplier is None:
        return None
    refresh_supplier(supplier)
    standing = supplier_standing(
        supplier["reliability_score"], supplier["cash_flow_received_cents"],
        supplier["delivered_purchase_count"], supplier["disputed_purchase_count"])
    assign(supplier, "status", standing)
    return standing


# --------------------------------------------------------------------------
# IngredientPurchase
# --------------------------------------------------------------------------

def transition_purchase(row, data):
    to_state = data["to_state"]
    current = row["status"]
    check_reachability("ingredient_purchases", row, current, to_state)

    supplier = DB["suppliers"].get(row["supplier_id"])
    incident = DB["incidents"].get(row["incident_id"])

    if to_state == "CONFIRMED":
        if supplier is not None and supplier["status"] == "SUSPENDED":
            fail("ERR_SUPPLIER_NOT_APPROVED")
        assign(row, "status", "CONFIRMED")

    elif to_state == "DELIVERED":
        if current == "CONFIRMED":
            assign(row, "delivered_at", now())
        else:
            assign(row, "dispute_reason", None)
        assign(row, "status", "DELIVERED")
        _recompute_standing(supplier)

    elif to_state == "PAID":
        previous = supplier["status"] if supplier is not None else None
        assign(row, "paid_at", now())
        assign(row, "status", "PAID")
        if supplier is not None:
            assign(supplier, "cash_flow_received_cents",
                   (supplier.get("cash_flow_received_cents") or 0) + row["amount_cents"])
            standing = _recompute_standing(supplier)
            if standing == "PREFERRED" and previous != "PREFERRED":
                # Cascade hop 2: a preferred producer's other orders auto-confirm.
                for other in DB["ingredient_purchases"].values():
                    if other["supplier_id"] == supplier["id"] \
                            and other["status"] == "REQUESTED":
                        assign(other, "status", "CONFIRMED")

    elif to_state == "DISPUTED":
        if current == "PAID" and supplier is not None:
            assign(supplier, "cash_flow_received_cents",
                   max(0, (supplier.get("cash_flow_received_cents") or 0) - row["amount_cents"]))
        assign(row, "dispute_reason", data.get("dispute_reason"))
        assign(row, "status", "DISPUTED")
        _recompute_standing(supplier)

    elif to_state == "CANCELLED":
        assign(row, "status", "CANCELLED")
        _recompute_standing(supplier)

    if incident is not None:
        refresh_incident(incident)
    return row


# --------------------------------------------------------------------------
# DonorCommitment
# --------------------------------------------------------------------------

def transition_commitment(row, data):
    to_state = data["to_state"]
    current = row["status"]
    check_reachability("donor_commitments", row, current, to_state)

    incident = DB["incidents"].get(row["incident_id"])

    if to_state == "RECEIVED":
        if current == "PLEDGED":
            assign(row, "received_at", now())
        else:
            if (row.get("disbursed_cents") or 0) != 0:
                fail("ERR_INVALID_STATE", "Money already disbursed cannot be de-allocated.")
            assign(row, "allocated_cents", 0)
        assign(row, "status", "RECEIVED")

    elif to_state == "WITHDRAWN":
        if row.get("received_at") is not None:
            fail("ERR_INVALID_STATE", "Received money cannot be withdrawn.")
        assign(row, "status", "WITHDRAWN")

    elif to_state == "ALLOCATED":
        if incident is None or incident["status"] != "ACTIVE":
            fail("ERR_INCIDENT_NOT_ACTIVE")
        assign(row, "allocated_cents", row["amount_cents"])
        assign(row, "status", "ALLOCATED")

    elif to_state == "PARTIALLY_DISBURSED":
        disbursement = data.get("disbursement_cents")
        if disbursement is None:
            fail("ERR_INVALID_REQUEST", "disbursement_cents is required.")
        if (row.get("disbursed_cents") or 0) + disbursement > row["amount_cents"]:
            fail("ERR_DISBURSEMENT_EXCEEDS_COMMITMENT")
        assign(row, "disbursed_cents", (row.get("disbursed_cents") or 0) + disbursement)
        assign(row, "status", "PARTIALLY_DISBURSED")

    elif to_state == "CLOSED":
        if (row.get("disbursed_cents") or 0) != row["amount_cents"]:
            fail("ERR_INVALID_STATE", "The commitment is not fully disbursed.")
        assign(row, "status", "CLOSED")

    refresh_donor_commitment(row)
    if incident is not None:
        refresh_incident(incident)
    return row
