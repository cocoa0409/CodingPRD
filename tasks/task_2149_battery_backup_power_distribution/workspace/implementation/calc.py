"""Domain constants, derivations and calculation rules."""
from datetime import timedelta

from common import (
    DB, ApiError, D, cents, ceil_int, days_between, floor_int, num, parse_date,
    parse_dt, public, rhu, sort_rows,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CHEMISTRIES = ("FLOODED_LEAD_ACID", "AGM", "GEL", "LITHIUM_IRON_PHOSPHATE", "NICKEL_CADMIUM")
HAZMAT_CLASSES = (
    "NON_REGULATED", "UN2800_EXCEPTED", "UN2795", "UN2800", "UN2794",
    "UN3480_SECTION_II", "UN3480_SECTION_IA",
)
HAZMAT_SEVERITY_RANK = {
    "NON_REGULATED": 0,
    "UN2800_EXCEPTED": 1,
    "UN2795": 2,
    "UN2800": 3,
    "UN2794": 4,
    "UN3480_SECTION_II": 5,
    "UN3480_SECTION_IA": 6,
}
RANK_TO_CLASS = {v: k for k, v in HAZMAT_SEVERITY_RANK.items()}
HAZMAT_BASE_FEE_CENTS = {
    "NON_REGULATED": 0,
    "UN2800_EXCEPTED": 1500,
    "UN2795": 4200,
    "UN2800": 5500,
    "UN2794": 7800,
    "UN3480_SECTION_II": 6400,
    "UN3480_SECTION_IA": 12500,
}
AGM_GEL_NON_SPILLABLE_MAX_KG = D("30.0")
LITHIUM_EXCEPTED_MAX_WH = D("20.0")
LITHIUM_SECTION_II_MAX_WH = D("100.0")
HAZMAT_PER_10KG_CENTS = 275
HAZMAT_MAX_PACKAGE_KG = D("30.0")
HAZMAT_ENDORSED_DISCOUNT = D("0.85")
HAZMAT_FEE_WAIVER_SUBTOTAL_CENTS = 5000000

DAYS_PER_STORAGE_MONTH = 30
REFRESH_THRESHOLD_PCT = D("75.0")
MAX_REFRESH_CYCLES = 3
REFRESH_COOLDOWN_HOURS = 72

ACCOUNT_TIER_DISCOUNT = {"PLATINUM": D("0.12"), "GOLD": D("0.07"), "STANDARD": D("0.00")}
MAX_DISCOUNT_PCT = D("0.15")

TIER_POINTS = {"PLATINUM": 40, "GOLD": 28, "STANDARD": 12}
SEVERITY_POINTS = {"WATCH": 5, "WARNING": 12, "EMERGENCY": 20}
SEVERITY_MIN_SCORE = {"WATCH": 0, "WARNING": 45, "EMERGENCY": 70}

LEAD_RECOVERY_YIELD = D("0.965")
LEAD_PRICE_CENTS_PER_KG = D("196")
LATE_CORE_PENALTY_PCT = D("0.25")
CORE_RETURN_WINDOW_DAYS = 45
CORE_RETURN_GRACE_DAYS = 30
MAX_INSPECTION_ROUNDS = 3
CORE_LIABILITY_ALERT_CENTS = 500000

INVERTER_EFFICIENCY = D("0.90")
DOD_LIMIT = {
    "FLOODED_LEAD_ACID": D("0.50"),
    "AGM": D("0.60"),
    "GEL": D("0.60"),
    "LITHIUM_IRON_PHOSPHATE": D("0.90"),
    "NICKEL_CADMIUM": D("0.70"),
}
COVERAGE_RATE = {"BRONZE": D("0.0075"), "SILVER": D("0.0125"), "GOLD": D("0.0200")}
CHEM_SERVICE_MULT = {
    "FLOODED_LEAD_ACID": D("1.30"),
    "AGM": D("1.10"),
    "GEL": D("1.15"),
    "LITHIUM_IRON_PHOSPHATE": D("0.90"),
    "NICKEL_CADMIUM": D("1.25"),
}
TIER_FLOOR_CENTS = {"BRONZE": 2500, "SILVER": 4900, "GOLD": 9900}
CONTRACT_PREPAY_MONTHS = 12

EPA_MANIFEST_MAX_LEAD_KG = D("1000.000")


# ---------------------------------------------------------------------------
# Hazmat classification
# ---------------------------------------------------------------------------
def classify_model(chemistry, unit_weight_kg, watt_hour_rating):
    if chemistry == "FLOODED_LEAD_ACID":
        return "UN2794"
    if chemistry == "NICKEL_CADMIUM":
        return "UN2795"
    if chemistry in ("AGM", "GEL"):
        if D(unit_weight_kg) <= AGM_GEL_NON_SPILLABLE_MAX_KG:
            return "UN2800_EXCEPTED"
        return "UN2800"
    if D(watt_hour_rating) <= LITHIUM_EXCEPTED_MAX_WH:
        return "NON_REGULATED"
    if D(watt_hour_rating) <= LITHIUM_SECTION_II_MAX_WH:
        return "UN3480_SECTION_II"
    return "UN3480_SECTION_IA"


# ---------------------------------------------------------------------------
# Inventory lot derivations
# ---------------------------------------------------------------------------
def lot_state_of_charge(lot, model):
    if lot.get("last_refresh_charged_at"):
        baseline = parse_dt(lot["last_refresh_charged_at"]).date()
    else:
        baseline = parse_date(lot["manufactured_on"])
    elapsed = days_between(baseline, DB.clock.date())
    months = max(0, elapsed // DAYS_PER_STORAGE_MONTH)
    value = D("100.0") - D(model["self_discharge_pct_per_month"]) * D(months)
    if value < 0:
        value = D("0.0")
    return rhu(value, 1)


def lot_condition(lot, model, soc):
    if lot.get("scrap_manifest_id"):
        return "SCRAPPED"
    age_days = days_between(parse_date(lot["manufactured_on"]), DB.clock.date())
    if age_days > int(model["shelf_life_days"]):
        return "SHELF_EXPIRED"
    if int(lot.get("refresh_charge_count", 0)) >= MAX_REFRESH_CYCLES and soc < REFRESH_THRESHOLD_PCT:
        return "SHELF_EXPIRED"
    if soc < REFRESH_THRESHOLD_PCT:
        return "REFRESH_REQUIRED"
    return "SELLABLE"


def storm_active_for_state(state_code):
    for event in DB.storm_events.values():
        if event["status"] in ("DECLARED", "ALLOCATING") and event["region_state_code"] == state_code:
            return True
    return False


def storm_carve_out(lot, warehouse):
    if not storm_active_for_state(warehouse["state_code"]):
        return 0
    return floor_int(D(lot["quantity_on_hand"]) * D(warehouse["storm_reserve_pct"]))


def lot_view(lot):
    model = DB.battery_models[lot["battery_model_id"]]
    warehouse = DB.warehouses[lot["warehouse_id"]]
    soc = lot_state_of_charge(lot, model)
    condition = lot_condition(lot, model, soc)
    available = int(lot["quantity_on_hand"]) - int(lot["quantity_reserved"]) - storm_carve_out(lot, warehouse)
    lot["state_of_charge_pct"] = float(soc)
    lot["condition_state"] = condition
    lot["quantity_available"] = available
    return lot


def serialize_lot(lot):
    lot_view(lot)
    return public(lot)


def effective_available(lot, is_storm_order, extra_reserved=0):
    warehouse = DB.warehouses[lot["warehouse_id"]]
    base = int(lot["quantity_on_hand"]) - int(lot["quantity_reserved"]) - extra_reserved
    if is_storm_order:
        return base
    return base - storm_carve_out(lot, warehouse)


# ---------------------------------------------------------------------------
# Disposal manifest derivations
# ---------------------------------------------------------------------------
def manifest_totals(manifest):
    returns = [r for r in DB.core_returns.values()
               if r.get("disposal_manifest_id") == manifest["id"] and r["status"] == "CREDITED"]
    lots = [l for l in DB.inventory_lots.values() if l.get("scrap_manifest_id") == manifest["id"]]
    core_lead = rhu(sum((D(r["lead_recovered_kg"]) for r in returns), D(0)), 3)
    lot_lead = D(0)
    for lot in lots:
        model = DB.battery_models[lot["battery_model_id"]]
        lot_lead += D(lot["quantity_on_hand"]) * D(model["lead_content_kg"])
    lot_lead = rhu(lot_lead, 3)
    total = rhu(core_lead + lot_lead, 3)
    manifest["attached_core_return_count"] = len(returns)
    manifest["scrapped_lot_count"] = len(lots)
    manifest["core_lead_kg"] = float(core_lead)
    manifest["lot_lead_kg"] = float(lot_lead)
    manifest["total_lead_kg"] = float(total)
    return total


def serialize_manifest(manifest):
    manifest_totals(manifest)
    return public(manifest)


# ---------------------------------------------------------------------------
# Order helpers
# ---------------------------------------------------------------------------
def order_lines(order_id):
    return sort_rows([l for l in DB.order_lines.values() if l["order_id"] == order_id])


def order_class_code(lines):
    ranks = [HAZMAT_SEVERITY_RANK[DB.battery_models[l["battery_model_id"]]["hazmat_class_code"]]
             for l in lines]
    if not ranks:
        return "NON_REGULATED"
    return RANK_TO_CLASS[max(ranks)]


def lines_weight_kg(lines):
    total = D(0)
    for line in lines:
        model = DB.battery_models[line["battery_model_id"]]
        total += D(line["quantity"]) * D(model["unit_weight_kg"])
    return rhu(total, 3)


def lines_lead_kg(lines):
    total = D(0)
    for line in lines:
        model = DB.battery_models[line["battery_model_id"]]
        total += D(line["quantity"]) * D(model["lead_content_kg"])
    return rhu(total, 3)


def hazmat_surcharge(class_code, weight_kg, warehouse, base_multiplier):
    weight_fee = ceil_int(D(weight_kg) / D("10.0")) * HAZMAT_PER_10KG_CENTS
    base_fee = HAZMAT_BASE_FEE_CENTS[class_code] * base_multiplier
    raw = D(base_fee + weight_fee)
    if warehouse["hazmat_endorsement"]:
        return cents(raw * HAZMAT_ENDORSED_DISCOUNT)
    return int(raw)


def volume_discount(quantity):
    if quantity >= 100:
        return D("0.05")
    if quantity >= 25:
        return D("0.03")
    if quantity >= 10:
        return D("0.01")
    return D("0.00")


def price_lines(order, account, lines):
    """Returns [(line, unit_price, discount_pct, line_total)] and the subtotal."""
    priced = []
    subtotal = 0
    tier_pct = ACCOUNT_TIER_DISCOUNT[account["account_tier"]]
    for line in lines:
        model = DB.battery_models[line["battery_model_id"]]
        unit_price = int(model["list_price_cents"])
        raw_discount = tier_pct + volume_discount(int(line["quantity"]))
        if raw_discount > MAX_DISCOUNT_PCT:
            raw_discount = MAX_DISCOUNT_PCT
        discount = rhu(raw_discount, 4)
        total = cents(D(unit_price) * D(line["quantity"]) * (D(1) - discount))
        priced.append((line, unit_price, discount, total))
        subtotal += total
    return priced, subtotal


def core_deposit_charge(lines):
    total = 0
    for line in lines:
        model = DB.battery_models[line["battery_model_id"]]
        total += (int(line["quantity"]) - int(line["core_expected_count"])) * int(model["core_deposit_cents"])
    return total


def assemble_total(order):
    return (int(order["subtotal_cents"]) + int(order["core_deposit_charge_cents"])
            + int(order["hazmat_fee_cents"]) + int(order["service_contract_fee_cents"]))


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------
def allocation_priority_score(order, account, event):
    if not order.get("storm_event_id"):
        return 0
    tier_points = TIER_POINTS[account["account_tier"]]
    rank_points = max(0, 6 - int(account["storm_priority_rank"])) * 5
    severity_points = SEVERITY_POINTS[event["severity_tier"]]
    value_points = min(15, floor_int(D(order["subtotal_cents"]) / D(100000)))
    return int(tier_points + rank_points + severity_points + value_points)


def select_lot(order, line, is_storm, tentative):
    """Returns the winning lot, or raises the fallback error."""
    model_id = line["battery_model_id"]
    warehouse_id = order["warehouse_id"]
    pool = []
    for lot in DB.inventory_lots.values():
        if lot["battery_model_id"] != model_id or lot["warehouse_id"] != warehouse_id:
            continue
        lot_view(lot)
        if lot["condition_state"] == "SCRAPPED":
            continue
        pool.append(lot)

    quantity = int(line["quantity"])
    candidates = []
    for lot in pool:
        if lot["condition_state"] != "SELLABLE":
            continue
        extra = tentative.get(lot["id"], 0)
        if effective_available(lot, is_storm, extra) >= quantity:
            candidates.append(lot)
    if candidates:
        candidates = sorted(candidates, key=lambda l: (l["manufactured_on"], l["created_at"], l["_seq"]))
        return candidates[0]

    coverable = []
    for lot in pool:
        extra = tentative.get(lot["id"], 0)
        if int(lot["quantity_on_hand"]) - int(lot["quantity_reserved"]) - extra >= quantity:
            coverable.append(lot)
    if any(l["condition_state"] == "SHELF_EXPIRED" for l in coverable):
        raise ApiError("ERR_LOT_SHELF_EXPIRED", "a shelf-expired lot blocks this line")
    if any(l["condition_state"] == "REFRESH_REQUIRED" for l in coverable):
        raise ApiError("ERR_LOT_REFRESH_REQUIRED", "a refresh-required lot blocks this line")
    raise ApiError("ERR_INSUFFICIENT_SELLABLE_STOCK", "no sellable lot can cover this line")


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------
def months_in_service(installed_on, failed_on):
    start = parse_date(installed_on)
    end = parse_date(failed_on)
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def warranty_credit(model, months):
    free = int(model["warranty_free_replacement_months"])
    prorata = int(model["warranty_prorata_months"])
    if months <= free:
        return "FREE", int(model["list_price_cents"])
    if months < free + prorata:
        remaining = free + prorata - months
        return "PRORATA", cents(D(model["list_price_cents"]) * D(remaining) / D(prorata))
    return "EXPIRED", 0


# ---------------------------------------------------------------------------
# Runtime sizing
# ---------------------------------------------------------------------------
def temp_derate(ambient_temp_c):
    temp = D(ambient_temp_c)
    if temp >= D("25.0"):
        return D("1.00")
    if temp >= D("15.0"):
        return D("0.95")
    if temp >= D("5.0"):
        return D("0.87")
    return D("0.75")


def size_contract(contract):
    system_voltage = D(contract["system_voltage"])
    dc_load_amps = rhu(D(contract["load_watts"]) / (system_voltage * INVERTER_EFFICIENCY), 3)
    runtime_hours = float(contract["required_runtime_minutes"]) / 60.0
    derate = temp_derate(contract["ambient_temp_c"])

    candidates = []
    for model in DB.battery_models.values():
        if model["status"] != "ACTIVE":
            continue
        if model["chemistry"] not in contract["allowed_chemistries"]:
            continue
        if D(model["nominal_voltage"]) > system_voltage:
            continue
        peukert_ah = rhu(D(dc_load_amps) * D(runtime_hours ** float(model["peukert_exponent"])), 3)
        usable_ah = rhu(D(model["amp_hour_capacity"]) * DOD_LIMIT[model["chemistry"]] * derate, 3)
        units_per_string = ceil_int(system_voltage / D(model["nominal_voltage"]))
        if usable_ah <= 0:
            continue
        string_count = ceil_int(peukert_ah / usable_ah)
        unit_count = string_count * units_per_string
        candidates.append({
            "model": model,
            "peukert_ah": peukert_ah,
            "units_per_string": units_per_string,
            "string_count": string_count,
            "unit_count": unit_count,
        })
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_BATTERY_MODEL", "no catalog model satisfies this sizing")

    candidates.sort(key=lambda c: (
        c["unit_count"],
        c["unit_count"] * int(c["model"]["list_price_cents"]),
        c["model"]["created_at"],
        c["model"]["_seq"],
    ))
    winner = candidates[0]
    model = winner["model"]
    covered_value = winner["unit_count"] * int(model["list_price_cents"])
    raw = D(covered_value) * COVERAGE_RATE[contract["coverage_tier"]] * CHEM_SERVICE_MULT[model["chemistry"]]
    monthly = max(TIER_FLOOR_CENTS[contract["coverage_tier"]], cents(raw))
    return {
        "dc_load_amps": float(dc_load_amps),
        "temp_derate_factor": float(derate),
        "required_peukert_ah": float(winner["peukert_ah"]),
        "sized_battery_model_id": model["id"],
        "sized_string_count": winner["string_count"],
        "sized_units_per_string": winner["units_per_string"],
        "sized_unit_count": winner["unit_count"],
        "covered_value_cents": covered_value,
        "monthly_fee_cents": monthly,
        "prepay_total_cents": monthly * CONTRACT_PREPAY_MONTHS,
    }


# ---------------------------------------------------------------------------
# Core exchange credit
# ---------------------------------------------------------------------------
def core_lead_recovery(accepted, model):
    lead = rhu(D(accepted) * D(model["lead_content_kg"]) * LEAD_RECOVERY_YIELD, 3)
    scrap = cents(lead * LEAD_PRICE_CENTS_PER_KG)
    return float(lead), scrap


def assayed_final_credit(core_return, model):
    deposit_value = int(core_return["accepted_core_count"]) * int(model["core_deposit_cents"])
    gross = max(deposit_value, int(core_return["scrap_value_cents"]))
    penalty = cents(D(gross) * LATE_CORE_PENALTY_PCT) if core_return["late_return"] else 0
    return gross - penalty


# ---------------------------------------------------------------------------
# Ledger cascades
# ---------------------------------------------------------------------------
from common import touch  # noqa: E402


def adjust_receivable(account, delta):
    if delta:
        account["open_receivable_cents"] = int(account["open_receivable_cents"]) + int(delta)
        touch(account)


def apply_credit_hold(account):
    """Delivery cascade hops 4 and 5."""
    if int(account["core_deposit_balance_cents"]) >= CORE_LIABILITY_ALERT_CENTS \
            and account["status"] == "ACTIVE":
        account["status"] = "CREDIT_HOLD"
        for order in sort_rows(list(DB.orders.values())):
            if order["account_id"] != account["id"]:
                continue
            if order["fulfillment_status"] in ("SUBMITTED", "ALLOCATED") \
                    and order["credit_status"] == "CLEARED":
                order["credit_status"] = "HELD"
                touch(order)


def apply_credit_release(account):
    """Core-credit cascade hops 3 and 4."""
    if int(account["core_deposit_balance_cents"]) < CORE_LIABILITY_ALERT_CENTS \
            and account["status"] == "CREDIT_HOLD":
        account["status"] = "ACTIVE"
        for order in sort_rows(list(DB.orders.values())):
            if order["account_id"] != account["id"]:
                continue
            if order["credit_status"] == "HELD":
                order["credit_status"] = "CLEARED"
                touch(order)
