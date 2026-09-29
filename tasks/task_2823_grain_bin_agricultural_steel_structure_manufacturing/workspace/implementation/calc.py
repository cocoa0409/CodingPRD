"""Every normative calculation from PRD section 3, to the last decimal place."""
from decimal import Decimal

from common import D, dceil, dfloor, money, rhu

# --- geometry and capacity -------------------------------------------------
PI = Decimal("3.14159")
SHEET_COURSE_HEIGHT_M = Decimal("0.8")
SHEET_WIDTH_M = Decimal("1.1")
ROOF_PANEL_ARC_M = Decimal("0.9")
ROOF_RISE_RATIO = {25: Decimal("0.466"), 30: Decimal("0.577"), 35: Decimal("0.700")}

# --- structural ------------------------------------------------------------
G = Decimal("9.81")
JANSSEN_DEPTH_CAP_M = Decimal("12.0")
MOISTURE_SURCHARGE_PER_PCT = Decimal("0.04")
WIND_COEFF = Decimal("0.9")
SEISMIC_FACTOR = {
    "A": Decimal("0.05"),
    "B": Decimal("0.12"),
    "C": Decimal("0.22"),
    "D": Decimal("0.33"),
}
HIGH_WIND_THRESHOLD_MPH = 115
HIGH_WIND_STIFFENER_BONUS = 2
STIFFENER_NOMINAL_KPA_M = Decimal("180.0")
ASD_SAFETY_FACTOR = Decimal("2.00")
LRFD_RESISTANCE_FACTOR = Decimal("0.90")
LRFD_LOAD_FACTOR = Decimal("1.60")
STIFFENER_MIN_COUNT = 4
STIFFENER_MAX_COUNT = 24
SHEET_GAUGE_LADDER = [
    Decimal("1.0"),
    Decimal("1.3"),
    Decimal("1.6"),
    Decimal("2.0"),
    Decimal("2.5"),
    Decimal("3.0"),
]
GAUGE_KPA_TO_MM = Decimal("0.05")

# --- aeration, drying, unloading ------------------------------------------
DEPTH_PENALTY_PER_M = Decimal("0.03")
DEPTH_PENALTY_FREE_M = Decimal("8.0")
MOISTURE_CFM_PER_PCT = Decimal("0.12")
FAN_UNIT_CFM = Decimal("5000")
MAX_FAN_CFM = Decimal("60000")
DRY_RATE_KG_PER_CFM_HR = Decimal("0.010")
WET_HOUR_PER_PCT = Decimal("0.25")
GRAVITY_BPH_PER_M3 = Decimal("3")
SWEEP_BPH = 5000
POWER_SWEEP_BPH = 9000

# --- bill of materials -----------------------------------------------------
COMPONENT_ORDER = [
    "SIDEWALL_SHEET",
    "STIFFENER",
    "ROOF_PANEL",
    "ANCHOR_BOLT",
    "BOLT_PACK",
    "AERATION_FAN",
    "UNLOAD_SYSTEM",
]
STEEL_COMPONENTS = {"SIDEWALL_SHEET", "STIFFENER", "ROOF_PANEL", "ANCHOR_BOLT", "BOLT_PACK"}
ANCHOR_BOLTS_PER_STIFFENER = 4
BOLTS_PER_SEAM = Decimal("18")
BOLTS_PER_PACK = Decimal("250")
COMPONENT_BASE_PRICE_CENTS = {
    "SIDEWALL_SHEET": 4200,
    "STIFFENER": 9800,
    "ROOF_PANEL": 3600,
    "ANCHOR_BOLT": 450,
    "BOLT_PACK": 1900,
    "AERATION_FAN": 285000,
    "UNLOAD_SYSTEM": 412000,
}
COMPONENT_WEIGHT_KG = {
    "SIDEWALL_SHEET": Decimal("12.5"),
    "STIFFENER": Decimal("41.0"),
    "ROOF_PANEL": Decimal("9.4"),
    "ANCHOR_BOLT": Decimal("1.2"),
    "BOLT_PACK": Decimal("6.0"),
    "AERATION_FAN": Decimal("120.0"),
    "UNLOAD_SYSTEM": Decimal("340.0"),
}
COMPONENT_CUBE_M3 = {
    "SIDEWALL_SHEET": Decimal("0.038"),
    "STIFFENER": Decimal("0.055"),
    "ROOF_PANEL": Decimal("0.031"),
    "ANCHOR_BOLT": Decimal("0.002"),
    "BOLT_PACK": Decimal("0.012"),
    "AERATION_FAN": Decimal("1.900"),
    "UNLOAD_SYSTEM": Decimal("3.400"),
}

# --- pricing ---------------------------------------------------------------
SEASON_UPLIFT_PCT = {
    "PRESEASON": Decimal("-0.05"),
    "HARVEST_PEAK": Decimal("0.07"),
    "OFFSEASON": Decimal("0.00"),
}
PROGRAM_DISCOUNT_PCT = {
    "BASE": Decimal("0.00"),
    "PREFERRED": Decimal("0.03"),
    "ELITE": Decimal("0.06"),
}
FREIGHT_SURCHARGE_TIERS = [
    (2000000, Decimal("0.060")),
    (6000000, Decimal("0.045")),
    (None, Decimal("0.030")),
]
DEPOSIT_PCT = Decimal("0.20")

# --- freight ---------------------------------------------------------------
TRAILER_CUBE_M3 = {
    "FLATBED": Decimal("62.0"),
    "HIGH_CUBE_VAN": Decimal("95.0"),
    "STEP_DECK": Decimal("74.0"),
}
TRAILER_WEIGHT_KG = {"FLATBED": 21000, "HIGH_CUBE_VAN": 28000, "STEP_DECK": 22500}
LINEHAUL_BASE_CENTS = {"FLATBED": 145000, "HIGH_CUBE_VAN": 198000, "STEP_DECK": 172000}
LINEHAUL_PER_KG_CENTS = Decimal("3")
MIN_CUBE_UTILIZATION_PCT = Decimal("75.0")

# --- crews and failures ----------------------------------------------------
CREW_TIER_MAX_DIAMETER_M = {"T1": Decimal("9.5"), "T2": Decimal("15.5"), "T3": Decimal("30.0")}
CORROSION_LOSS_LIMIT = {
    "C2": Decimal("25.0"),
    "C3": Decimal("40.0"),
    "C4": Decimal("55.0"),
    "C5": Decimal("70.0"),
}
ZINC_CLASS_BREAKS_G_PER_M2 = [300, 400, 550]

# --- seasons ---------------------------------------------------------------
SEASON_MONTHS = {
    "PRESEASON": [1, 2, 3, 4, 5, 6],
    "HARVEST_PEAK": [9, 10, 11],
    "OFFSEASON": [7, 8, 12],
}


# ---------------------------------------------------------------------------
# coating_corrosion_class
# ---------------------------------------------------------------------------
def corrosion_class(zinc_mass_g_per_m2):
    z = zinc_mass_g_per_m2
    if z < 300:
        return "C2"
    if z < 400:
        return "C3"
    if z < 550:
        return "C4"
    return "C5"


# ---------------------------------------------------------------------------
# order_season_window
# ---------------------------------------------------------------------------
def derived_season(instant):
    month = instant.month
    for season, months in SEASON_MONTHS.items():
        if month in months:
            return season
    return "OFFSEASON"


# ---------------------------------------------------------------------------
# bin_geometry_and_capacity
# ---------------------------------------------------------------------------
def bin_geometry(diameter_m, eave_height_m, roof_pitch_deg):
    diameter_m = D(diameter_m)
    eave_height_m = D(eave_height_m)
    circumference_m = rhu(PI * diameter_m, 3)
    sheets_per_course = dceil(circumference_m / SHEET_WIDTH_M)
    sheet_courses = dceil(eave_height_m / SHEET_COURSE_HEIGHT_M)
    sidewall_sheet_count = sheet_courses * sheets_per_course
    roof_panel_count = dceil(circumference_m / ROOF_PANEL_ARC_M)
    radius_m = diameter_m / D(2)
    cylinder_m3 = PI * radius_m * radius_m * eave_height_m
    roof_rise_m = radius_m * ROOF_RISE_RATIO[int(roof_pitch_deg)]
    cone_m3 = PI * radius_m * radius_m * roof_rise_m / D(3)
    capacity_m3 = rhu(cylinder_m3 + cone_m3, 2)
    return {
        "circumference_m": circumference_m,
        "sheets_per_course": sheets_per_course,
        "sheet_courses": sheet_courses,
        "sidewall_sheet_count": sidewall_sheet_count,
        "roof_panel_count": roof_panel_count,
        "capacity_m3": capacity_m3,
    }


# ---------------------------------------------------------------------------
# structural_stiffener_requirement
# ---------------------------------------------------------------------------
def allowable_kpa_m(design_method):
    if design_method == "ASD":
        return STIFFENER_NOMINAL_KPA_M / ASD_SAFETY_FACTOR
    return STIFFENER_NOMINAL_KPA_M * LRFD_RESISTANCE_FACTOR / LRFD_LOAD_FACTOR


def load_demands(eave_height_m, diameter_m, design_wind_speed_mph, moisture_pct,
                 bulk_density_kg_per_m3, janssen_k_ratio, max_safe_moisture_pct,
                 seismic_design_category):
    eave_height_m = D(eave_height_m)
    diameter_m = D(diameter_m)
    moisture_pct = D(moisture_pct)
    bulk_density = D(bulk_density_kg_per_m3)
    janssen_k = D(janssen_k_ratio)
    safe_moisture = D(max_safe_moisture_pct)
    mph = D(design_wind_speed_mph)

    depth_m = eave_height_m if eave_height_m < JANSSEN_DEPTH_CAP_M else JANSSEN_DEPTH_CAP_M
    grain_lateral_kpa = rhu(bulk_density * G * janssen_k * depth_m / D(1000), 3)
    excess = moisture_pct - safe_moisture
    if excess < 0:
        excess = D(0)
    moisture_factor = D(1) + MOISTURE_SURCHARGE_PER_PCT * excess
    grain_demand_kpa = rhu(grain_lateral_kpa * moisture_factor, 3)
    wind_demand_kpa = rhu(WIND_COEFF * mph * mph * eave_height_m / (diameter_m * D(1000)), 3)
    seismic_demand_kpa = rhu(
        SEISMIC_FACTOR[seismic_design_category] * bulk_density * G * depth_m / D(1000), 3
    )
    governing_demand_kpa = max(grain_demand_kpa, wind_demand_kpa, seismic_demand_kpa)
    if grain_demand_kpa == governing_demand_kpa:
        governing_load_case = "GRAIN_LATERAL"
    elif wind_demand_kpa == governing_demand_kpa:
        governing_load_case = "WIND_UPLIFT"
    else:
        governing_load_case = "SEISMIC_BASE_SHEAR"
    return {
        "grain_lateral_kpa": grain_lateral_kpa,
        "moisture_factor": moisture_factor,
        "grain_demand_kpa": grain_demand_kpa,
        "wind_demand_kpa": wind_demand_kpa,
        "seismic_demand_kpa": seismic_demand_kpa,
        "governing_demand_kpa": governing_demand_kpa,
        "governing_load_case": governing_load_case,
    }


def stiffener_envelope(governing_demand_kpa, circumference_m, design_wind_speed_mph, design_method):
    allowable = allowable_kpa_m(design_method)
    high_wind = int(design_wind_speed_mph) >= HIGH_WIND_THRESHOLD_MPH
    demand_moment = D(governing_demand_kpa) * D(circumference_m)
    raw_required = max(STIFFENER_MIN_COUNT, dceil(demand_moment / allowable))
    if high_wind:
        raw_required = raw_required + HIGH_WIND_STIFFENER_BONUS
    required_stiffener_count = min(raw_required, STIFFENER_MAX_COUNT)
    utilization_ratio = rhu(demand_moment / (D(required_stiffener_count) * allowable), 4)
    verdict = "PASS" if utilization_ratio <= D("1.0") else "FAIL"
    threshold = D(governing_demand_kpa) * GAUGE_KPA_TO_MM
    sheet_gauge_mm = None
    for candidate in SHEET_GAUGE_LADDER:
        if candidate >= threshold:
            sheet_gauge_mm = candidate
            break
    if sheet_gauge_mm is None:
        sheet_gauge_mm = Decimal("3.0")
    return {
        "allowable_kpa_m": allowable,
        "required_stiffener_count": required_stiffener_count,
        "utilization_ratio": utilization_ratio,
        "verdict": verdict,
        "sheet_gauge_mm": sheet_gauge_mm,
        "roof_ring_required": high_wind,
    }


# ---------------------------------------------------------------------------
# aeration_and_drying_capacity
# ---------------------------------------------------------------------------
def aeration_sizing(capacity_m3, eave_height_m, moisture_pct, bulk_density_kg_per_m3,
                    max_safe_moisture_pct, aeration_cfm_per_m3_base, drying_multiplier,
                    aeration_package, unload_system):
    capacity = D(capacity_m3)
    eave = D(eave_height_m)
    moisture = D(moisture_pct)
    safe = D(max_safe_moisture_pct)

    grain_mass_kg = rhu(capacity * D(bulk_density_kg_per_m3), 2)
    moisture_excess = moisture - safe
    if moisture_excess < 0:
        moisture_excess = D(0)

    if aeration_package == "NONE":
        package_mult = D("0.0")
    elif aeration_package == "AERATION":
        package_mult = D("1.0")
    else:
        package_mult = D(drying_multiplier)

    base_cfm = capacity * D(aeration_cfm_per_m3_base)
    depth_excess = eave - DEPTH_PENALTY_FREE_M
    if depth_excess < 0:
        depth_excess = D(0)
    depth_penalty = D(1) + DEPTH_PENALTY_PER_M * depth_excess
    moisture_penalty = D(1) + MOISTURE_CFM_PER_PCT * moisture_excess
    raw_cfm = base_cfm * package_mult * depth_penalty * moisture_penalty

    capped = raw_cfm if raw_cfm < MAX_FAN_CFM else MAX_FAN_CFM
    required_fan_cfm = dceil(capped)

    if aeration_package == "NONE":
        drying_hours_estimate = 0
    else:
        denominator = D(required_fan_cfm) * DRY_RATE_KG_PER_CFM_HR
        if moisture_excess == 0:
            drying_hours_estimate = dceil(grain_mass_kg / denominator)
        else:
            inflated = grain_mass_kg * (D(1) + moisture_excess * WET_HOUR_PER_PCT)
            drying_hours_estimate = dceil(inflated / denominator)

    if unload_system == "GRAVITY":
        unload_rate_bph = dfloor(capacity * GRAVITY_BPH_PER_M3)
    elif unload_system == "SWEEP_AUGER":
        unload_rate_bph = SWEEP_BPH
    else:
        unload_rate_bph = POWER_SWEEP_BPH

    return {
        "grain_mass_kg": grain_mass_kg,
        "moisture_excess": moisture_excess,
        "raw_cfm": raw_cfm,
        "required_fan_cfm": required_fan_cfm,
        "drying_hours_estimate": drying_hours_estimate,
        "unload_rate_bph": unload_rate_bph,
    }


# ---------------------------------------------------------------------------
# kit_bill_of_materials
# ---------------------------------------------------------------------------
def kit_quantities(design, aeration_package, unload_system, required_fan_cfm):
    per_course_packs = dceil(D(design["sheets_per_course"]) * BOLTS_PER_SEAM / BOLTS_PER_PACK)
    quantities = {
        "SIDEWALL_SHEET": design["sidewall_sheet_count"],
        "STIFFENER": design["required_stiffener_count"],
        "ROOF_PANEL": design["roof_panel_count"],
        "ANCHOR_BOLT": design["required_stiffener_count"] * ANCHOR_BOLTS_PER_STIFFENER,
        "BOLT_PACK": per_course_packs * design["sheet_courses"],
        "AERATION_FAN": 0
        if aeration_package == "NONE"
        else dceil(D(required_fan_cfm) / FAN_UNIT_CFM),
        "UNLOAD_SYSTEM": 0 if unload_system == "GRAVITY" else 1,
    }
    return quantities


def kit_lines_for(design, quantities, coating_cost_per_kg_cents):
    """Emit one line per component whose quantity is at least 1, in fixed order."""
    lines = []
    for component_code in COMPONENT_ORDER:
        quantity = quantities[component_code]
        if quantity < 1:
            continue
        base_price = COMPONENT_BASE_PRICE_CENTS[component_code]
        if component_code in STEEL_COMPONENTS:
            adder = money(COMPONENT_WEIGHT_KG[component_code] * D(coating_cost_per_kg_cents))
        else:
            adder = 0
        unit_price_cents = base_price + adder
        lines.append(
            {
                "component_code": component_code,
                "quantity": quantity,
                "unit_price_cents": unit_price_cents,
                "extended_cents": quantity * unit_price_cents,
                "weight_kg": rhu(D(quantity) * COMPONENT_WEIGHT_KG[component_code], 2),
                "cube_m3": rhu(D(quantity) * COMPONENT_CUBE_M3[component_code], 3),
            }
        )
    kit_subtotal_cents = sum(line["extended_cents"] for line in lines)
    kit_weight_kg = rhu(sum((line["weight_kg"] for line in lines), D(0)), 2)
    kit_cube_m3 = rhu(sum((line["cube_m3"] for line in lines), D(0)), 3)
    return lines, kit_subtotal_cents, kit_weight_kg, kit_cube_m3


# ---------------------------------------------------------------------------
# order_price_and_credit -- steps S1 through S8 in the pinned order
# ---------------------------------------------------------------------------
def freight_surcharge_pct(net_subtotal_cents):
    for ceiling, rate in FREIGHT_SURCHARGE_TIERS:
        if ceiling is None or net_subtotal_cents < ceiling:
            return rate
    return FREIGHT_SURCHARGE_TIERS[-1][1]


def price_order(kit_subtotal_cents, order_season, program_tier):
    season_uplift_cents = money(D(kit_subtotal_cents) * SEASON_UPLIFT_PCT[order_season])
    program_discount_cents = money(
        D(kit_subtotal_cents + season_uplift_cents) * PROGRAM_DISCOUNT_PCT[program_tier]
    )
    net_subtotal_cents = kit_subtotal_cents + season_uplift_cents - program_discount_cents
    pct = freight_surcharge_pct(net_subtotal_cents)
    freight_surcharge_cents = money(D(net_subtotal_cents) * pct)
    total_cents = net_subtotal_cents + freight_surcharge_cents
    required_deposit_cents = money(D(total_cents) * DEPOSIT_PCT)
    credit_hold_cents = total_cents - required_deposit_cents
    return {
        "season_uplift_cents": season_uplift_cents,
        "program_discount_cents": program_discount_cents,
        "net_subtotal_cents": net_subtotal_cents,
        "freight_surcharge_pct": pct,
        "freight_surcharge_cents": freight_surcharge_cents,
        "total_cents": total_cents,
        "required_deposit_cents": required_deposit_cents,
        "credit_hold_cents": credit_hold_cents,
    }


# ---------------------------------------------------------------------------
# freight: linehaul cost and the per-order share split
# ---------------------------------------------------------------------------
def linehaul_cost_cents(trailer_type, assigned_weight_kg):
    per_kg = money(D(assigned_weight_kg) * LINEHAUL_PER_KG_CENTS)
    return LINEHAUL_BASE_CENTS[trailer_type] + per_kg


def cube_utilization_pct(assigned_cube_m3, max_cube_m3):
    return rhu(D(assigned_cube_m3) / D(max_cube_m3) * 100, 2)


def freight_shares(orders, allocation_basis, total_cents, assigned_weight_kg, assigned_cube_m3):
    """orders is the attached set already ordered by created_at ascending.

    Returns a list of allocated_freight_cents aligned with orders; the residual
    lands entirely on freight_sequence 1 (the earliest-created order).
    """
    if not orders:
        return []
    shares = []
    for order in orders:
        if allocation_basis == "WEIGHT":
            numerator = D(total_cents) * D(order["kit_weight_kg"])
            denominator = D(assigned_weight_kg)
        else:
            numerator = D(total_cents) * D(order["kit_cube_m3"])
            denominator = D(assigned_cube_m3)
        if denominator == 0:
            shares.append(0)
        else:
            shares.append(money(numerator / denominator))
    residual = total_cents - sum(shares)
    shares[0] = shares[0] + residual
    return shares


# ---------------------------------------------------------------------------
# field failure verdicts and the determination branches
# ---------------------------------------------------------------------------
def structural_verdict(observed_load_kpa, governing_demand_kpa):
    if D(observed_load_kpa) > D(governing_demand_kpa):
        return "EXCEEDS_DESIGN"
    return "WITHIN_DESIGN"


def corrosion_verdict(measured_coating_loss_pct, corrosion_class_code):
    limit = CORROSION_LOSS_LIMIT[corrosion_class_code]
    if D(measured_coating_loss_pct) > limit:
        return "EXCEEDS_CLASS"
    return "WITHIN_CLASS"


def determined_cause(failure_mode, structural, corrosion):
    if failure_mode == "CORROSION_PERFORATION":
        return "COATING_INADEQUATE" if corrosion == "EXCEEDS_CLASS" else "OVERLOAD_MISUSE"
    if failure_mode == "ANCHOR_PULLOUT":
        return "INSTALLATION_DEFECT"
    # SIDEWALL_BUCKLE or ROOF_COLLAPSE
    if structural == "WITHIN_DESIGN":
        return "STRUCTURAL_UNDERDESIGN"
    return "OVERLOAD_MISUSE"


def crew_downgrade(certification_tier):
    """One tier deep. Returns (new_tier, new_status)."""
    if certification_tier == "T3":
        return "T2", "PROBATION"
    if certification_tier == "T2":
        return "T1", "PROBATION"
    return "T1", "REVOKED"
