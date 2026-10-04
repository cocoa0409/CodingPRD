# Shared business logic: costing calculations (PRD 3.2/3.4/3.5), parity,
# cascades, derived batch status (PRD 3.7), program scorecards (PRD 3.6).
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import constants
from store import db, mark


def rhu(value, places):
    """Round half-up a Decimal to `places` fractional digits."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rhu0_int(value):
    """Round half-up to a whole integer."""
    return int(rhu(value, 0))


def clamp(x, lo, hi):
    """Inclusive clamp: min(hi, max(lo, x)) — floor/cap bounds are kept."""
    return min(hi, max(lo, x))


# --- lot_landed_unit_cost (provisional variant; PRD 3.2) ---
def compute_provisional_unit_cost(supplier, market_index_pct):
    indexed = rhu(
        Decimal(supplier["base_price_per_kg_cents"]) * (Decimal(1) + Decimal(str(market_index_pct))),
        0,
    )
    clamped = clamp(int(indexed), supplier["price_floor_cents"], supplier["price_cap_cents"])
    return clamped + constants.FREIGHT_ESTIMATE_CENTS_PER_KG


# --- lot_landed_unit_cost (final variant; PRD 3.2) ---
def compute_final_unit_cost(supplier, invoiced_unit_cost_cents, actual_freight_cents_per_kg):
    clamped = clamp(invoiced_unit_cost_cents, supplier["price_floor_cents"], supplier["price_cap_cents"])
    return clamped + actual_freight_cents_per_kg


# --- agreement completion re-evaluation (PRD 3.1) ---
def reevaluate_agreement_completion(supplier):
    if (
        supplier["agreement_status"] == "ACTIVE"
        and supplier["delivered_volume_kg"] >= supplier["committed_volume_kg"]
        and supplier["open_lot_count"] == 0
    ):
        supplier["agreement_status"] = "COMPLETED"
        mark(supplier)


# --- price_parity_index (PRD 3.4) ---
def eligible_released_lots(isolate_type):
    """RELEASED lots whose supplier's isolate_type matches, FIFO order:
    received_at ASC, tie-break created_at ASC (never id)."""
    lots = []
    for lot in db["lots"].values():
        if lot["qc_status"] != "RELEASED":
            continue
        supplier = db["suppliers"].get(lot["supplier_id"])
        if supplier is None or supplier["isolate_type"] != isolate_type:
            continue
        lots.append(lot)
    lots.sort(key=lambda l: (l["_dt"]["received_at"], l["created_at"], l["_seq"]))
    return lots


def compute_parity_trio(isolate_type):
    lots = [l for l in eligible_released_lots(isolate_type) if l["remaining_kg"] > 0]
    if not lots:
        return None, None, None
    numerator = sum(l["final_unit_cost_cents"] * l["remaining_kg"] for l in lots)
    denominator = sum(l["remaining_kg"] for l in lots)
    weighted_avg = Decimal(numerator) / Decimal(denominator)  # exact rational division
    unit_cost = rhu0_int(
        weighted_avg * (Decimal(1) + Decimal(constants.EXTRUSION_PROCESSING_MARKUP_PCT) / Decimal(100))
        + Decimal(constants.PACKAGING_CENTS_PER_KG)
    )
    index = rhu(
        Decimal(unit_cost) / Decimal(constants.ANIMAL_PROTEIN_REFERENCE_CENTS_PER_KG), 4
    )
    goal_met = bool(index <= constants.PARITY_GOAL_MAX)
    return unit_cost, float(index), goal_met


def recompute_parity_for_isolate(isolate_type):
    """Recompute the parity trio on every ACTIVE product of the isolate type."""
    for product in db["products"].values():
        if product["status"] == "ACTIVE" and product["isolate_type"] == isolate_type:
            unit, index, goal = compute_parity_trio(isolate_type)
            product["unit_cost_per_kg_cents"] = unit
            product["price_parity_index"] = index
            product["parity_goal_met"] = goal
            mark(product)


# --- batch_costing: FIFO consumption (PRD 3.5) ---
def total_available_isolate_kg(isolate_type):
    return sum(l["remaining_kg"] for l in eligible_released_lots(isolate_type))


def required_isolate_kg(actual_quantity_kg):
    """ceil(actual * 85 / 100) — exact integer ceiling."""
    return (actual_quantity_kg * constants.ISOLATE_KG_PER_FINISHED_KG_PCT + 99) // 100


def consume_lots_fifo(isolate_type, needed_kg):
    """Consume RELEASED lots of the isolate type oldest-first until needed_kg is
    covered. Mutates lots (remaining_kg, DEPLETED transition), decrements
    supplier open_lot_count on depletion, re-evaluates agreement completion.
    Returns (consumed_lot_ids in order, total_cost_cents)."""
    consumed_ids = []
    total_cost = 0
    need = needed_kg
    affected_suppliers = []
    for lot in eligible_released_lots(isolate_type):
        if need <= 0:
            break
        if lot["remaining_kg"] <= 0:
            continue
        take = min(lot["remaining_kg"], need)
        lot["remaining_kg"] -= take
        need -= take
        consumed_ids.append(lot["id"])
        # per-lot cost rounded half-up to whole cents FIRST (pinned order);
        # final_unit_cost_cents and kg are integers, so the product is exact.
        total_cost += rhu0_int(Decimal(lot["final_unit_cost_cents"]) * Decimal(take))
        mark(lot)
        if lot["remaining_kg"] == 0:
            lot["qc_status"] = "DEPLETED"
            supplier = db["suppliers"][lot["supplier_id"]]
            supplier["open_lot_count"] -= 1
            mark(supplier)
            if supplier["id"] not in affected_suppliers:
                affected_suppliers.append(supplier["id"])
    for supplier_id in affected_suppliers:
        reevaluate_agreement_completion(db["suppliers"][supplier_id])
    return consumed_ids, total_cost


# --- batch_derived_status (PRD 3.7) — computed, never stored ---
def batch_derived_status(batch):
    if batch["written_off_cases"] == batch["quantity_cases"]:
        return "WRITTEN_OFF"
    if clock.now() >= batch["_dt"]["expiry_date"]:
        return "EXPIRED"
    if batch["available_cases"] == 0 and batch["reserved_cases"] == 0:
        return "DEPLETED"
    if batch["reserved_cases"] > 0:
        return "RESERVED"
    return "AVAILABLE"


def serialize_batch(batch):
    from store import public

    out = public(batch)
    out["derived_status"] = batch_derived_status(batch)
    return out


# --- program_attainment / sampling_redemption_rate (PRD 3.6) ---
def recompute_program_attainment(program):
    if program["program_type"] != "FOODSERVICE_LTO" or not program["committed_cases"]:
        return
    program["attainment_pct"] = float(
        rhu(Decimal(program["delivered_cases"]) * Decimal(100) / Decimal(program["committed_cases"]), 2)
    )
    program["commitment_met"] = program["delivered_cases"] >= program["committed_cases"]


def compute_redemption_rate(coupons_redeemed, coupons_issued):
    if not coupons_issued:
        return None
    return float(rhu(Decimal(coupons_redeemed) * Decimal(100) / Decimal(coupons_issued), 2))


# --- forecast_variance (PRD 3.8) ---
def compute_variance(forecast_cases, actual_cases):
    variance = rhu(
        Decimal(actual_cases - forecast_cases) * Decimal(100) / Decimal(forecast_cases), 2
    )
    is_miss = bool(variance <= -constants.FORECAST_MISS_THRESHOLD_PCT)
    return float(variance), is_miss


# --- write_down_amounts (PRD 3.8) ---
def nrv_for_channel(channel):
    return constants.NRV_CENTS_PER_CASE[channel]


def shelf_life_days(channel):
    return constants.SHELF_LIFE_DAYS[channel]


def expiry_from(produced_dt, channel):
    return produced_dt + timedelta(days=shelf_life_days(channel))
