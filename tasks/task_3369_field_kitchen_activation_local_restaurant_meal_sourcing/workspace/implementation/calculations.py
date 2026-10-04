"""Every calculation from PRD section 3 / SCAFFOLD `calculations`, implemented
exactly as written (pinned evaluation order, named rounding points only).
"""

from decimal import Decimal

from core import DB, assign, dec, round_half_up

# --- field_kitchen_food_safety_score constants -----------------------------
POWER_POINTS = {"GRID": 40, "GENERATOR": 30, "SOLAR": 20, "NONE": 0}
WATER_POINTS = {"PIPED": 35, "TRUCKED": 25, "WELL": 15, "NONE": 0}
COLD_FULL_HOURS = 12
COLD_PARTIAL_HOURS = 6
COLD_SCORE_FULL = 25
COLD_SCORE_PARTIAL = 15
MIN_VIABLE_CAPACITY_MEALS = 500
CAPACITY_PENALTY = 10

# --- assessment_feeding_priority constants ---------------------------------
ACCESS_WEIGHT = {"OPEN": 10, "LIMITED": 25, "RESTRICTED": 40, "BLOCKED": 55}
WATER_MISSING_PENALTY = 20
POWER_MISSING_PENALTY = 15
PARTNER_BASE = 25
PARTNER_STEP = 5
DURABLE_INFRA_DIVISOR = 2
DURABLE_PARTNER_MULTIPLIER = 2
DURABLE_PARTNER_CAP = 40
PRIORITY_SCORE_CAP = 100

# --- meal_order_cost_buildup constants -------------------------------------
LOGISTICS_FEE_RATE = "0.03"
TIER_BULK_MIN_CENTS = 2000000
TIER_STANDARD_MIN_CENTS = 800000
TIER_RATE = {"BULK": "0.08", "STANDARD": "0.05", "SMALL": "0.00"}

# --- supplier_reliability_and_standing constants ---------------------------
RELIABILITY_BASE = 50
DELIVERED_PURCHASE_CREDIT = 10
DISPUTED_PURCHASE_PENALTY = 25
SUPPLIER_SUSPENSION_MAX_SCORE = 40
PREFERRED_CASHFLOW_MIN_CENTS = 500000
PREFERRED_RELIABILITY_MIN = 70

# --- partner_kitchen_quality_score constants -------------------------------
QUALITY_HISTORY_WINDOW = 5
QUALITY_WEIGHTS = [5, 4, 3, 2, 1]

# --- incident_local_sourcing_ratio constants -------------------------------
LOCAL_SOURCING_TARGET_PCT = 30


def clamp(value, low, high):
    return max(low, min(high, value))


def field_kitchen_food_safety_score(power_source, water_source,
                                    refrigeration_hours_available, daily_capacity_meals):
    """power + water + cold - capacity penalty, clamped to 0..100."""
    power_score = POWER_POINTS.get(power_source, 0)
    water_score = WATER_POINTS.get(water_source, 0)
    if refrigeration_hours_available >= COLD_FULL_HOURS:
        cold_score = COLD_SCORE_FULL
    elif refrigeration_hours_available >= COLD_PARTIAL_HOURS:
        cold_score = COLD_SCORE_PARTIAL
    else:
        cold_score = 0
    penalty = CAPACITY_PENALTY if daily_capacity_meals < MIN_VIABLE_CAPACITY_MEALS else 0
    return clamp(power_score + water_score + cold_score - penalty, 0, 100)


def assessment_feeding_priority(population_affected, estimated_daily_meal_need,
                                access_constraint, water_available, power_available,
                                partner_kitchens_identified, assessment_mode):
    """0-100 deployment priority; RAPID and DURABLE weight the last two terms."""
    if population_affected == 0:
        need_component = 0
    else:
        need_component = min(
            PRIORITY_SCORE_CAP,
            round_half_up(dec(estimated_daily_meal_need) * dec(100) / dec(population_affected)),
        )
    access_component = ACCESS_WEIGHT.get(access_constraint, 0)
    infra_raw = (0 if water_available else WATER_MISSING_PENALTY) + \
                (0 if power_available else POWER_MISSING_PENALTY)
    partner_raw = max(0, PARTNER_BASE - PARTNER_STEP * partner_kitchens_identified)

    if assessment_mode == "DURABLE":
        infra_component = round_half_up(dec(infra_raw) / dec(DURABLE_INFRA_DIVISOR))
        partner_component = min(DURABLE_PARTNER_CAP, DURABLE_PARTNER_MULTIPLIER * partner_raw)
    else:
        infra_component = infra_raw
        partner_component = partner_raw

    return min(PRIORITY_SCORE_CAP,
               need_component + access_component + infra_component + partner_component)


def meal_order_cost_buildup(ordered_meals, per_meal_price_cents):
    """Returns (subtotal, tier, logistics_fee, volume_discount, total)."""
    subtotal = ordered_meals * per_meal_price_cents
    if subtotal >= TIER_BULK_MIN_CENTS:
        tier = "BULK"
    elif subtotal >= TIER_STANDARD_MIN_CENTS:
        tier = "STANDARD"
    else:
        tier = "SMALL"
    logistics_fee = round_half_up(dec(subtotal) * dec(LOGISTICS_FEE_RATE))
    discount_base = subtotal + logistics_fee
    volume_discount = round_half_up(dec(discount_base) * dec(TIER_RATE[tier]))
    total = subtotal + logistics_fee - volume_discount
    return subtotal, tier, logistics_fee, volume_discount, total


def meal_order_final_settlement(accepted_meals, per_meal_price_cents, quality_check_score):
    """Final variant: accepted meals x raw price x quality multiplier, one rounding."""
    billable_meals = accepted_meals
    base_cents = billable_meals * per_meal_price_cents
    if quality_check_score is None:
        multiplier = "0.00"
    elif quality_check_score >= 90:
        multiplier = "1.00"
    elif quality_check_score >= 75:
        multiplier = "0.95"
    elif quality_check_score >= 60:
        multiplier = "0.85"
    else:
        multiplier = "0.00"
    return round_half_up(dec(base_cents) * dec(multiplier))


def partner_kitchen_quality_score(partner_kitchen_id):
    """Weighted mean over the 5 most recent DELIVERED/REJECTED batches, or None
    when the window is empty (the stored score is then left unchanged)."""
    rows = [o for o in DB["meal_orders"].values()
            if o["partner_kitchen_id"] == partner_kitchen_id
            and o["status"] in ("DELIVERED", "REJECTED")]
    # created_at DESC, tie -> scheduled_start ASC, then menu_name ASC (never by id)
    rows.sort(key=lambda o: (-o["created_at"].timestamp(),
                             o["scheduled_start"], o["menu_name"]))
    window = rows[:QUALITY_HISTORY_WINDOW]
    if not window:
        return None
    weighted_sum = 0
    weight_total = 0
    for index, order in enumerate(window):
        weight = QUALITY_WEIGHTS[index]
        score = order.get("quality_check_score")
        weighted_sum += (score or 0) * weight
        weight_total += weight
    if weight_total == 0:
        return None
    return clamp(round_half_up(dec(weighted_sum) / dec(weight_total)), 0, 100)


def supplier_counts(supplier_id):
    delivered = 0
    disputed = 0
    for purchase in DB["ingredient_purchases"].values():
        if purchase["supplier_id"] != supplier_id:
            continue
        if purchase["status"] in ("DELIVERED", "PAID"):
            delivered += 1
        elif purchase["status"] in ("DISPUTED", "CANCELLED"):
            disputed += 1
    return delivered, disputed


def supplier_reliability_score(delivered_count, disputed_count):
    return clamp(RELIABILITY_BASE
                 + DELIVERED_PURCHASE_CREDIT * delivered_count
                 - DISPUTED_PURCHASE_PENALTY * disputed_count, 0, 100)


def supplier_standing(reliability_score, cash_flow_received_cents,
                      delivered_count, disputed_count):
    """Standing resolution order is pinned: SUSPENDED, PREFERRED, PROSPECT, APPROVED."""
    if reliability_score < SUPPLIER_SUSPENSION_MAX_SCORE:
        return "SUSPENDED"
    if (cash_flow_received_cents >= PREFERRED_CASHFLOW_MIN_CENTS
            and reliability_score >= PREFERRED_RELIABILITY_MIN):
        return "PREFERRED"
    if delivered_count == 0 and disputed_count == 0:
        return "PROSPECT"
    return "APPROVED"


def run_pending_planned_meals(run_id):
    return sum(s["planned_meals"] for s in DB["distribution_stops"].values()
               if s["distribution_run_id"] == run_id and s["status"] == "PENDING")


def run_delivered_meals(run_id):
    return sum(s["delivered_meals"] for s in DB["distribution_stops"].values()
               if s["distribution_run_id"] == run_id and s["status"] == "DELIVERED")


def run_returned_meals(run):
    """loaded - delivered - pending_planned: the conserved third term of the invariant."""
    return (run.get("loaded_meals") or 0) - run_delivered_meals(run["id"]) \
        - run_pending_planned_meals(run["id"])


def run_cost_allocation(run):
    """Spread total_cost_cents over DELIVERED stops; residual to the lowest sequence."""
    run_total = (run.get("fuel_cost_cents") or 0) + (run.get("handling_cost_cents") or 0)
    stops = [s for s in DB["distribution_stops"].values()
             if s["distribution_run_id"] == run["id"]]
    eligible = sorted([s for s in stops if s["status"] == "DELIVERED"],
                      key=lambda s: s["stop_sequence"])
    for stop in stops:
        if stop["status"] != "DELIVERED":
            assign(stop, "allocated_cost_cents", 0)
    total_delivered = sum(s["delivered_meals"] for s in eligible)
    if total_delivered == 0:
        for stop in eligible:
            assign(stop, "allocated_cost_cents", 0)
        return run_total  # whole pool stays unallocated
    allocated_sum = 0
    shares = []
    for stop in eligible:
        share = round_half_up(dec(run_total) * dec(stop["delivered_meals"]) / dec(total_delivered))
        shares.append((stop, share))
        allocated_sum += share
    residual = run_total - allocated_sum
    lowest = eligible[0]  # eligible is sorted by stop_sequence ASC
    for stop, share in shares:
        assign(stop, "allocated_cost_cents", share + (residual if stop is lowest else 0))
    return 0


def incident_aggregates(incident_id):
    """The four derived accountability figures of one activation (PRD 2.11 / 3.8)."""
    committed = sum(c["amount_cents"] for c in DB["donor_commitments"].values()
                    if c["incident_id"] == incident_id
                    and c["status"] in ("RECEIVED", "ALLOCATED", "PARTIALLY_DISBURSED", "CLOSED"))
    spent = 0
    delivered_final = 0
    delivered_meals = 0
    for order in DB["meal_orders"].values():
        if order["incident_id"] != incident_id:
            continue
        if order["status"] in ("PLACED", "IN_PRODUCTION", "QUALITY_HOLD", "READY", "DISPATCHED"):
            spent += order.get("provisional_cost_cents") or 0
        elif order["status"] == "DELIVERED":
            spent += order.get("final_cost_cents") or 0
            delivered_final += order.get("final_cost_cents") or 0
            delivered_meals += order.get("accepted_meals") or 0
    for purchase in DB["ingredient_purchases"].values():
        if purchase["incident_id"] == incident_id and purchase["status"] in ("DELIVERED", "PAID"):
            spent += purchase["amount_cents"]
    numerator = sum(p["amount_cents"] for p in DB["ingredient_purchases"].values()
                    if p["incident_id"] == incident_id and p["status"] in ("DELIVERED", "PAID"))
    local_pct = 0 if delivered_final == 0 else round_half_up(
        dec(numerator) * dec(100) / dec(delivered_final))
    cost_per_meal = 0 if delivered_meals == 0 else round_half_up(
        dec(delivered_final) / dec(delivered_meals))
    return {
        "committed_cents": committed,
        "spent_cents": spent,
        "delivered_meal_total": delivered_meals,
        "local_sourcing_pct": local_pct,
        "cost_per_meal_cents": cost_per_meal,
        "donor_report_flag": ("BELOW_LOCAL_SOURCING_TARGET"
                              if local_pct < LOCAL_SOURCING_TARGET_PCT else "ON_TARGET"),
    }
