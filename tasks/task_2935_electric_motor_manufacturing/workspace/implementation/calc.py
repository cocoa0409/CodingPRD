"""Every calculation the PRD pins down, with its rounding order.

PRD 2.7 — every rounding operation uses round half up; there is no banker's
rounding anywhere in the system.
"""

import datetime
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

D = Decimal
ZERO = D(0)


def rhu(value, places):
    """Round half up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = D(str(value))
    quant = D(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


# ---------------------------------------------------------------------------
# PRD 3.2 — the predicted loss model
# ---------------------------------------------------------------------------

BASE_LOSS_FRACTION = {2: D("0.070"), 4: D("0.060"), 6: D("0.075"), 8: D("0.090")}
LAMINATION_FACTOR = {
    "M400_50A": D("1.30"), "M330_35A": D("1.12"),
    "M270_35A": D("1.00"), "M235_35A": D("0.92"),
}
WINDING_FACTOR = {"CONCENTRIC": D("1.06"), "LAP": D("1.00")}
ROTOR_FACTOR = {"DIE_CAST_ALUMINUM": D("1.15"), "FABRICATED_COPPER": D("0.88")}
STACK_REF_MM = D(180)
COPPER_REF_KG = D("12.0")
SHARE_CORE = D("0.30")
SHARE_COPPER = D("0.35")
SHARE_ROTOR = D("0.20")
SHARE_FRICTION_WINDAGE = D("0.10")
SHARE_STRAY = D("0.05")
TOLERANCE_COEFF = D("0.15")

CLASS_ORDER = ["BELOW_IE2", "IE2", "IE3", "IE4", "IE5"]
DESIGN_CLASS_FLOOR_PCT = {
    "IE2": {2: D("89.60"), 4: D("90.40"), 6: D("89.80"), 8: D("88.60")},
    "IE3": {2: D("91.40"), 4: D("92.10"), 6: D("91.60"), 8: D("90.50")},
    "IE4": {2: D("93.00"), 4: D("93.60"), 6: D("93.10"), 8: D("92.20")},
    "IE5": {2: D("94.30"), 4: D("94.80"), 6: D("94.40"), 8: D("93.60")},
}


def class_ordinal(name):
    return CLASS_ORDER.index(name)


def classify(efficiency_pct, poles):
    """The highest class among IE2..IE5 whose floor for this pole count is less
    than or equal to the efficiency; BELOW_IE2 when even the IE2 floor is not
    reached.  A value exactly equal to a floor attains that class."""
    verdict = "BELOW_IE2"
    for name in ("IE2", "IE3", "IE4", "IE5"):
        if efficiency_pct >= DESIGN_CLASS_FLOOR_PCT[name][poles]:
            verdict = name
    return verdict


def design_predicted_efficiency(design):
    """PRD 3.2 — five components, each rounded to 0.1 W BEFORE summation."""
    p_out_w = design["rated_output_kw"] * D(1000)
    base = p_out_w * BASE_LOSS_FRACTION[design["poles"]]

    core = rhu(base * SHARE_CORE * LAMINATION_FACTOR[design["lamination_grade"]]
               * (STACK_REF_MM / D(design["lamination_stack_length_mm"])), 1)
    copper = rhu(base * SHARE_COPPER * WINDING_FACTOR[design["winding_type"]]
                 * (COPPER_REF_KG / design["winding_copper_kg"]), 1)
    rotor = rhu(base * SHARE_ROTOR * ROTOR_FACTOR[design["rotor_construction"]], 1)
    friction = rhu(base * SHARE_FRICTION_WINDAGE, 1)
    stray = rhu(base * SHARE_STRAY, 1)

    total = core + copper + rotor + friction + stray
    predicted = rhu(D(100) * p_out_w / (p_out_w + total), 2)
    guaranteed = rhu(D(100) - (D(100) - predicted) * (D(1) + TOLERANCE_COEFF), 2)

    design["total_predicted_loss_w"] = total
    design["predicted_efficiency_pct"] = predicted
    design["guaranteed_efficiency_pct"] = guaranteed
    design["design_estimate_class"] = classify(predicted, design["poles"])
    design["predicted_class"] = classify(guaranteed, design["poles"])


# ---------------------------------------------------------------------------
# PRD 3.4 — order lead time
# ---------------------------------------------------------------------------

BASE_LEAD_DAYS = {"STOCK_REPLENISH": 5, "MADE_TO_ORDER": 28, "ENGINEERED_SPECIAL": 56}
TIER_LEAD_REDUCTION_DAYS = {"PLATINUM": 4, "GOLD": 2, "SILVER": 0}
SPECIAL_ADDER_ORDER = [
    ("non_standard_mounting", 7),
    ("hazardous_environment", 14),
    ("non_standard_duty", 5),
    ("marine_certification", 21),
]
JURISDICTION_CERT_ADDER_DAYS = {"EU": 3, "US": 5, "CN": 9}
STOCK_BUFFER_SHORTFALL_ADDER_DAYS = 11
MIN_LEAD_DAYS = 3


def order_lead_time(order, distributor, clock_instant):
    base_days = BASE_LEAD_DAYS[order["order_type"]]
    special = order.get("special_requirements") or {}
    special_days = 0
    for key, adder in SPECIAL_ADDER_ORDER:
        if special.get(key) is True:
            special_days += adder
    shortfall_days = 0
    if (order["order_type"] == "STOCK_REPLENISH"
            and order["quantity"] > distributor["stock_buffer_units"]):
        shortfall_days = STOCK_BUFFER_SHORTFALL_ADDER_DAYS
    cert_days = JURISDICTION_CERT_ADDER_DAYS[order["jurisdiction"]]
    total = (base_days + special_days + shortfall_days + cert_days
             - TIER_LEAD_REDUCTION_DAYS[distributor["tier"]])
    days = max(MIN_LEAD_DAYS, total)
    ship_date = clock_instant.date() + datetime.timedelta(days=days)
    return days, ship_date.isoformat()


# ---------------------------------------------------------------------------
# PRD 3.5 — work order cost
# ---------------------------------------------------------------------------

MATERIAL_COST_PER_KG_COPPER_CENTS = D(1150)
LAM_COST_PER_MM_CENTS = {"M400_50A": 420, "M330_35A": 510, "M270_35A": 640, "M235_35A": 780}
ROTOR_PROCESS_COST_CENTS = {"DIE_CAST_ALUMINUM": 18000, "FABRICATED_COPPER": 47500}
LABOR_COST_CENTS_PER_UNIT = 26000
COMPLEX_BAND_MIN_CENTS = 1500000
ENGINEERED_BAND_MIN_CENTS = 4000000
OVERHEAD_RATE_BY_BAND = {"STANDARD": D("0.22"), "COMPLEX": D("0.31"), "ENGINEERED": D("0.44")}
REWORK_SURCHARGE_CENTS_PER_REJECT = 62500


def per_unit_direct_cost_cents(design):
    copper = rhu_int(design["winding_copper_kg"] * MATERIAL_COST_PER_KG_COPPER_CENTS)
    lamination = design["lamination_stack_length_mm"] * LAM_COST_PER_MM_CENTS[design["lamination_grade"]]
    rotor = ROTOR_PROCESS_COST_CENTS[design["rotor_construction"]]
    return copper + lamination + rotor + LABOR_COST_CENTS_PER_UNIT


def work_order_cost(work_order, design):
    """Cost at creation and on every rework_reject_count change."""
    per_unit = per_unit_direct_cost_cents(design)
    direct = per_unit * work_order["unit_count"]
    if direct >= ENGINEERED_BAND_MIN_CENTS:
        band = "ENGINEERED"
    elif direct >= COMPLEX_BAND_MIN_CENTS:
        band = "COMPLEX"
    else:
        band = "STANDARD"
    overhead = rhu_int(D(direct) * OVERHEAD_RATE_BY_BAND[band])
    standard = direct + overhead
    actual = standard + work_order["rework_reject_count"] * REWORK_SURCHARGE_CENTS_PER_REJECT
    work_order["direct_cost_cents"] = direct
    work_order["overhead_band"] = band
    work_order["overhead_cents"] = overhead
    work_order["standard_cost_cents"] = standard
    work_order["actual_cost_cents"] = actual
    work_order["cost_variance_cents"] = actual - standard
    return per_unit


def unit_standard_cost_cents(work_order):
    return rhu_int(D(work_order["standard_cost_cents"]) / D(work_order["unit_count"]))


# ---------------------------------------------------------------------------
# PRD 3.6 — the surge envelope
# ---------------------------------------------------------------------------

SURGE_BASE_V = D(1000)
SURGE_MULTIPLIER = D("2.0")
INSULATION_SYSTEM_CLASS = {
    "CLASS_B_POLYESTER": "B",
    "CLASS_F_POLYESTERIMIDE": "F",
    "CLASS_H_POLYAMIDEIMIDE": "H",
}
INSULATION_CLASS_FACTOR = {"B": D("1.00"), "F": D("1.15"), "H": D("1.30")}
VARNISH_PROCESS_FACTOR = {"DIP_BAKE": D("1.00"), "TRICKLE": D("1.05"), "VPI": D("1.20")}
CYCLE_BONUS_PER_EXTRA_CYCLE = D("0.04")
MAX_CYCLE_BONUS = D("0.12")
MIN_SLOT_FILL_PCT = D("78.00")
MAX_SLOT_FILL_PCT = D("86.00")


def required_surge_kv(rated_voltage_v, thermal_class):
    raw = ((SURGE_MULTIPLIER * D(rated_voltage_v) + SURGE_BASE_V)
           * INSULATION_CLASS_FACTOR[thermal_class] / D(1000))
    return rhu(raw, 2)


def achieved_capability_kv(required_kv, varnish_process, varnish_cycles):
    bonus = min(MAX_CYCLE_BONUS, CYCLE_BONUS_PER_EXTRA_CYCLE * D(max(0, varnish_cycles - 1)))
    return rhu(required_kv * VARNISH_PROCESS_FACTOR[varnish_process] * (D(1) + bonus), 2)


def insulation_margin_kv(surge_test_kv, required_kv):
    return rhu(surge_test_kv - required_kv, 2)


# ---------------------------------------------------------------------------
# PRD 3.7 — rotor cage, air gap and balance
# ---------------------------------------------------------------------------

CAGE_CONDUCTIVITY_RATIO = {"DIE_CAST_ALUMINUM": D("0.62"), "FABRICATED_COPPER": D("1.00")}
SLIP_PENALTY_PCT = {"DIE_CAST_ALUMINUM": D("1.8"), "FABRICATED_COPPER": D("0.6")}
BALANCE_CONSTANT = D(9549)
BALANCE_GRADE_MM_PER_S = {"G1_0": D("1.0"), "G2_5": D("2.5"), "G6_3": D("6.3")}
SYNC_SPEED_RPM_BY_POLES = {2: 3000, 4: 1500, 6: 1000, 8: 750}


def rotor_air_gap(design, measured_rotor_od_mm):
    measured = rhu((design["stator_bore_id_mm"] - measured_rotor_od_mm) / D(2), 3)
    deviation = rhu(measured - design["design_air_gap_mm"], 3)
    return measured, deviation


def permissible_unbalance_g_mm(balance_grade, rotor_mass_kg, poles):
    sync = D(SYNC_SPEED_RPM_BY_POLES[poles])
    return rhu(BALANCE_CONSTANT * BALANCE_GRADE_MM_PER_S[balance_grade]
               * rotor_mass_kg / sync, 1)


# ---------------------------------------------------------------------------
# PRD 3.8 — assembly metrology
# ---------------------------------------------------------------------------

SHAFT_FIT_LIMITS_UM = {"k6": (2, 18), "m6": (7, 25), "j6": (-5, 11)}
GREASE_FILL_PCT_RANGE = {
    "GREASE_LIFETIME": (D(30), D(40)),
    "GREASE_REGREASABLE": (D(40), D(60)),
    "OIL_MIST": (D(0), D(0)),
}


def shaft_fit_deviation_um(shaft_measured_diameter_mm, design_shaft_diameter_mm):
    return rhu_int((shaft_measured_diameter_mm - design_shaft_diameter_mm) * D(1000))


# ---------------------------------------------------------------------------
# PRD 3.8 — measured efficiency
# ---------------------------------------------------------------------------

STRAY_LOAD_FRACTION_OF_INPUT = D("0.005")
TEMP_CORRECTION_PER_C = D("0.0035")
AMBIENT_REF_C = D("25.0")


def test_measured_efficiency(test, poles):
    p_in_w = test["input_power_kw"] * D(1000)
    excess = test["ambient_temp_c"] - AMBIENT_REF_C
    if excess < 0:
        excess = ZERO
    corrected = rhu(test["stator_loss_w"] * (D(1) + TEMP_CORRECTION_PER_C * excess), 1)
    stray = rhu(p_in_w * STRAY_LOAD_FRACTION_OF_INPUT, 1)
    total = (corrected + rhu(test["rotor_loss_w"], 1) + rhu(test["core_loss_w"], 1)
             + rhu(test["friction_windage_w"], 1) + stray)
    if test["test_method"] == "IEC_60034_2_1_SUMMATION":
        efficiency = rhu(D(100) * (p_in_w - total) / p_in_w, 2)
    else:
        efficiency = rhu(D(100) * test["output_power_kw"] / test["input_power_kw"], 2)
    test["stator_loss_corrected_w"] = corrected
    test["stray_load_loss_w"] = stray
    test["total_loss_w"] = total
    test["measured_efficiency_pct"] = efficiency
    test["achieved_class"] = classify(efficiency, poles)


# ---------------------------------------------------------------------------
# PRD 3.10 — the misuse index
# ---------------------------------------------------------------------------

OVERLOAD_REF_PCT = D("100.0")
OVERLOAD_SPAN_PCT = D(40)
WARRANTY_AMBIENT_REF_C = D("40.0")
AMBIENT_SPAN_C = D(25)
VOLTAGE_UNBALANCE_REF_PCT = D("1.0")
VOLTAGE_UNBALANCE_SPAN_PCT = D(3)
STARTS_PER_HOUR_REF = {"S1": D(6), "S2": D(12), "S3": D(30)}
W_FIELD = {"overload": D("0.34"), "thermal": D("0.26"), "voltage": D("0.22"), "starts": D("0.18")}
W_TEARDOWN = {"overload": D("0.20"), "thermal": D("0.18"), "voltage": D("0.14"), "starts": D("0.10")}
W_TEARDOWN_EVIDENCE = D("0.38")
MISUSE_THRESHOLD = D("0.50")


def _clamp01(value):
    if value < 0:
        return ZERO
    if value > 1:
        return D(1)
    return value


def warranty_misuse_index(claim, duty_type, analysis_basis, evidence_pct):
    starts_ref = STARTS_PER_HOUR_REF[duty_type]
    s_overload = _clamp01((claim["measured_load_pct"] - OVERLOAD_REF_PCT) / OVERLOAD_SPAN_PCT)
    s_thermal = _clamp01((claim["measured_ambient_c"] - WARRANTY_AMBIENT_REF_C) / AMBIENT_SPAN_C)
    s_voltage = _clamp01((claim["measured_voltage_unbalance_pct"] - VOLTAGE_UNBALANCE_REF_PCT)
                         / VOLTAGE_UNBALANCE_SPAN_PCT)
    s_starts = _clamp01((D(claim["measured_starts_per_hour"]) - starts_ref) / starts_ref)
    if analysis_basis == "FIELD_DATA":
        raw = (W_FIELD["overload"] * s_overload + W_FIELD["thermal"] * s_thermal
               + W_FIELD["voltage"] * s_voltage + W_FIELD["starts"] * s_starts)
    else:
        raw = (W_TEARDOWN["overload"] * s_overload + W_TEARDOWN["thermal"] * s_thermal
               + W_TEARDOWN["voltage"] * s_voltage + W_TEARDOWN["starts"] * s_starts
               + W_TEARDOWN_EVIDENCE * (D(1) - evidence_pct / D(100)))
    index = rhu(raw, 4)
    adjudication = "MISUSE_DETERMINED" if index >= MISUSE_THRESHOLD else "DEFECT_CONFIRMED"
    return index, adjudication


# ---------------------------------------------------------------------------
# PRD 3.10 — the credit waterfall
# ---------------------------------------------------------------------------

PRO_RATA_MONTHS = 60
CREDIT_CEILING_FRACTION = D("0.85")
PARTS_CAP_FRACTION = D("0.60")
LABOR_CAP_CENTS = 45000
FREIGHT_CAP_CENTS = 18000


def _add_months(base, months):
    year = base.year + (base.month - 1 + months) // 12
    month = (base.month - 1 + months) % 12 + 1
    day = base.day
    while True:
        try:
            return datetime.date(year, month, day)
        except ValueError:
            day -= 1


def service_age_months(shipped_at, clock_instant):
    """The count of whole months m for which the shipped date advanced by m
    months still falls on or before the current date."""
    if shipped_at is None:
        return 0
    shipped_date = shipped_at.date()
    today = clock_instant.date()
    months = 0
    while _add_months(shipped_date, months + 1) <= today:
        months += 1
        if months > 10000:
            break
    return months


def warranty_credit_waterfall(claim_unit_cost_cents, shipped_at, clock_instant,
                              claimed_parts, claimed_labor, claimed_freight):
    age = service_age_months(shipped_at, clock_instant)
    capped_age = min(age, PRO_RATA_MONTHS)
    factor = D(PRO_RATA_MONTHS - capped_age) / D(PRO_RATA_MONTHS)
    if factor < 0:
        factor = ZERO
    ceiling = rhu_int(D(claim_unit_cost_cents) * CREDIT_CEILING_FRACTION * factor)
    remaining = ceiling
    parts_cap = rhu_int(D(claim_unit_cost_cents) * PARTS_CAP_FRACTION)
    parts = min(claimed_parts, parts_cap, remaining)
    remaining -= parts
    labor = min(claimed_labor, LABOR_CAP_CENTS, remaining)
    remaining -= labor
    freight = min(claimed_freight, FREIGHT_CAP_CENTS, remaining)
    remaining -= freight
    return parts + labor + freight
