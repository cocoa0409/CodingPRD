"""Shared domain services: envelopes, tray recomputation, period ledgers and cascades."""

from datetime import timedelta
from decimal import Decimal

import calcs
import store

COMMITTED_STATES = ("VALIDATED", "IN_PRODUCTION", "PLATED", "DELIVERED")
OPEN_TRAY_STATES = ("PENDING_VALIDATION", "VALIDATED", "IN_PRODUCTION", "PLATED")
OPEN_CONSULT_STATES = ("REQUESTED", "ASSIGNED", "ASSESSED")


# ---------------------------------------------------------------------------
# Diet order envelope
# ---------------------------------------------------------------------------
def rules_of(diet_order):
    rules = [store.diet_rules[diet_order["primary_diet_rule_id"]]]
    secondary = diet_order.get("secondary_diet_rule_id")
    if secondary:
        rules.append(store.diet_rules[secondary])
    return rules


def compute_envelope(diet_order):
    patient = store.patients[diet_order["patient_id"]]
    return calcs.effective_diet_envelope(diet_order, patient, rules_of(diet_order))


def apply_envelope(diet_order):
    """Store the recomputed envelope on the order (submit / resubmit / cosign)."""
    diet_order.update(compute_envelope(diet_order))
    return diet_order


def envelope_of(diet_order):
    """Read the envelope.

    An ACTIVE order reflects the patient's current tolerances and NPO status the
    next time its envelope is read or a tray is validated against it, so it is
    recomputed live.  Any other order reports the snapshot taken at its last
    transition into PENDING_COSIGN or ACTIVE.
    """
    if diet_order["status"] == "ACTIVE":
        return compute_envelope(diet_order)
    return {
        "effective_sodium_cap_mg": diet_order["effective_sodium_cap_mg"],
        "effective_potassium_cap_mg": diet_order["effective_potassium_cap_mg"],
        "effective_carb_cap_g": diet_order["effective_carb_cap_g"],
        "effective_texture_level": diet_order["effective_texture_level"],
        "effective_liquid_level": diet_order["effective_liquid_level"],
        "forbidden_tag_codes_effective": list(
            diet_order.get("forbidden_tag_codes_effective") or []),
    }


# ---------------------------------------------------------------------------
# Meal order recomputation
# ---------------------------------------------------------------------------
def item_for(line):
    return store.menu_items[line["menu_item_id"]]


def compute_tray_values(meal_order, effective_texture_level):
    """Return (totals, line_costs, food_cost) without mutating anything."""
    lines = store.lines_of(meal_order["id"])
    totals = calcs.meal_order_nutrient_totals(lines, item_for)
    line_costs, food_cost = calcs.meal_order_food_cost(
        lines, item_for, effective_texture_level)
    return totals, line_costs, food_cost


def apply_tray_values(meal_order, totals, line_costs, food_cost):
    meal_order.update(totals)
    for line_id, cost in line_costs.items():
        store.meal_order_lines[line_id]["line_cost_cents"] = cost
    meal_order["food_cost_cents"] = food_cost


def recompute_tray(meal_order, effective_texture_level=None):
    texture = effective_texture_level or meal_order.get("effective_texture_level")
    totals, line_costs, food_cost = compute_tray_values(meal_order, texture)
    apply_tray_values(meal_order, totals, line_costs, food_cost)


# ---------------------------------------------------------------------------
# Meal period ledger
# ---------------------------------------------------------------------------
def refresh_period_ledger(period):
    """Recompute committed counters, the six-step cost rollup and the variance.

    Does not bump the period's version; the caller decides whether the period
    was mutated by the operation at hand.
    """
    trays = store.orders_of_period(period["id"])
    committed = [t for t in trays if t["fulfillment_status"] in COMMITTED_STATES]
    period["committed_tray_count"] = len(committed)
    period["committed_food_cost_cents"] = sum(t["food_cost_cents"] for t in committed)
    period["delivered_tray_count"] = sum(
        1 for t in trays if t["fulfillment_status"] == "DELIVERED")
    period.update(calcs.meal_period_cost_rollup(period["committed_food_cost_cents"]))
    period["forecast_variance_pct"] = calcs.forecast_variance(
        period["committed_tray_count"], period["forecast_tray_count"])


def refresh_variance(period):
    period["forecast_variance_pct"] = calcs.forecast_variance(
        period["committed_tray_count"], period["forecast_tray_count"])


# ---------------------------------------------------------------------------
# Nutrition consults
# ---------------------------------------------------------------------------
def consult_due_at(created_at, acuity):
    hours = (calcs.CONSULT_URGENT_SLA_HOURS if acuity == "URGENT"
             else calcs.CONSULT_ROUTINE_SLA_HOURS)
    return created_at + timedelta(hours=hours)


def new_consult(patient_id, reason_code, acuity, requested_by_user_id,
                auto_generated=False):
    consult = {
        "patient_id": patient_id,
        "acuity": acuity,
        "reason_code": reason_code,
        "requested_by_user_id": requested_by_user_id,
        "assigned_dietitian_user_id": None,
        "auto_generated": auto_generated,
        "status": "REQUESTED",
        "assessment_variant": None,
        "weight_loss_pct": None,
        "intake_pct": None,
        "bmi": None,
        "albumin_g_dl": None,
        "malnutrition_risk_score": None,
        "risk_tier": None,
        "recommended_supplement_item_id": None,
        "signed_by_user_id": None,
        "linked_supplement_order_count": 0,
    }
    store.stamp_new(consult)
    consult["due_at"] = consult_due_at(consult["created_at"], acuity)
    store.consults[consult["id"]] = consult
    return consult


def consult_is_overdue(consult):
    if consult["status"] in ("SIGNED", "CANCELLED"):
        return False
    return store.now() >= consult["due_at"]


def has_open_consult(patient_id):
    return any(c["patient_id"] == patient_id and c["status"] in OPEN_CONSULT_STATES
               for c in store.consults.values())


# ---------------------------------------------------------------------------
# Missed-meal escalation
# ---------------------------------------------------------------------------
def mark_tray_missed(meal_order, reason, bump_patient_version=True):
    """Move one tray into MISSED and run the missed-meal escalation for its patient.

    Returns True when the tray left a committed state (its meal period must then
    be re-ledgered by the caller).
    """
    patient = store.patients[meal_order["patient_id"]]
    was_committed = meal_order["fulfillment_status"] in COMMITTED_STATES
    meal_order["fulfillment_status"] = "MISSED"
    meal_order["missed_reason"] = reason
    store.touch(meal_order)

    patient["missed_meal_count"] += 1
    patient["protein_deficit_g"] = calcs.rhu(
        calcs.dec(patient["protein_deficit_g"]) + calcs.dec(meal_order["total_protein_g"]), 1)
    if bump_patient_version:
        store.touch(patient)

    if (patient["missed_meal_count"] >= calcs.MISSED_MEAL_CONSULT_THRESHOLD
            and not has_open_consult(patient["id"])):
        new_consult(patient["id"], "MISSED_MEALS", "URGENT", "SYSTEM",
                    auto_generated=True)
    return was_committed


def reledger_periods(period_ids):
    """Re-ledger every period a cascade touched, in creation order, bumping each once."""
    periods = store.sort_rows([store.meal_periods[p] for p in set(period_ids)])
    for period in periods:
        refresh_period_ledger(period)
        store.touch(period)


# ---------------------------------------------------------------------------
# Patient satisfaction rollup
# ---------------------------------------------------------------------------
def refresh_patient_satisfaction(patient):
    rows = store.sort_rows([s for s in store.surveys.values()
                            if s["patient_id"] == patient["id"]])
    patient["survey_count"] = len(rows)
    patient["satisfaction_score_avg"] = calcs.patient_satisfaction_average(
        [r["composite_score"] for r in rows])


# ---------------------------------------------------------------------------
# Diet order activation cascade (cosign, and the auto-activating submit fork)
# ---------------------------------------------------------------------------
def run_activation_cascade(new_order):
    """Supersede the patient's prior ACTIVE order and revert that order's open trays.

    `new_order` must already be ACTIVE with its own version bump applied, so the
    trays are re-pinned onto the version the order actually carries afterwards.
    """
    patient_id = new_order["patient_id"]
    predecessor = None
    for row in store.sort_rows(list(store.diet_orders.values())):
        if (row["patient_id"] == patient_id and row["status"] == "ACTIVE"
                and row["id"] != new_order["id"]):
            predecessor = row
            break
    if predecessor is None:
        return

    predecessor["status"] = "SUPERSEDED"
    predecessor["superseded_by_diet_order_id"] = new_order["id"]
    new_order["supersedes_diet_order_id"] = predecessor["id"]
    store.touch(predecessor)

    envelope = envelope_of(new_order)
    touched_periods = []
    trays = store.sort_rows([o for o in store.meal_orders.values()
                             if o["diet_order_id"] == predecessor["id"]
                             and o["fulfillment_status"] in ("PENDING_VALIDATION",
                                                             "VALIDATED")])
    for tray in trays:
        was_committed = tray["fulfillment_status"] in COMMITTED_STATES
        tray["diet_order_id"] = new_order["id"]
        tray["pinned_diet_order_version"] = new_order["version"]
        tray["fulfillment_status"] = "PENDING_VALIDATION"
        tray["revalidation_required"] = True
        tray["effective_texture_level"] = envelope["effective_texture_level"]
        tray["effective_liquid_level"] = envelope["effective_liquid_level"]
        store.touch(tray)
        if was_committed:
            touched_periods.append(tray["meal_period_id"])
    reledger_periods(touched_periods)


def number_or_none(value):
    if value is None:
        return None
    return Decimal(str(value))
