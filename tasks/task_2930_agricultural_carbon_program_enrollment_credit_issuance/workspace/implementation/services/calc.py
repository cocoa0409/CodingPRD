"""Every programme calculation, in Decimal with round-half-up throughout."""

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

D = Decimal

ZERO = D("0")
ONE = D("1")

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
SQUARE_UNITS_PER_ACRE = D("4000")

EVIDENCE_WEIGHT = {
    "FARM_RECORD": D("1.0"),
    "EQUIPMENT_TELEMETRY": D("1.0"),
    "REMOTE_SENSING": D("0.8"),
    "ATTESTATION": D("0.5"),
}

SOIL_FACTOR = {"LOAM": D("1.00"), "CLAY": D("0.90"), "SAND": D("1.15")}

HISTORICAL_UNCERTAINTY_PER_YEAR = D("2.0")
HISTORICAL_UNCERTAINTY_FLOOR = D("5.00")
MODELED_UNCERTAINTY_ADDER = D("10.0")
MODELED_UNCERTAINTY_PER_YEAR = D("1.5")
MODELED_UNCERTAINTY_FLOOR = D("12.00")

QC_SOURCE_WEIGHT = {
    "FARM_RECORD": D("0.6"),
    "EQUIPMENT_TELEMETRY": D("1.0"),
    "REMOTE_SENSING": D("0.8"),
}
QC_WEIGHT_COMPLETENESS = D("0.5")
QC_WEIGHT_PLAUSIBILITY = D("0.3")
QC_WEIGHT_SOURCE = D("0.2")
QC_PASS_MIN_SCORE = D("70.00")
COMPLETENESS_MIN_PCT = D("85.00")

MODEL_UNCERTAINTY_ADDER_PCT = D("5.00")
SAMPLING_UNCERTAINTY_INTERCEPT_PCT = D("30.0")
SAMPLING_COVERAGE_SLOPE = D("0.25")
SAMPLING_UNCERTAINTY_FLOOR_PCT = D("5.00")
MEASUREMENT_MIN_COVERAGE_PCT = D("60.00")

MATERIAL_DISCREPANCY_MAX_PCT = D("5.00")
SAMPLE_MIN_PCT = D("5.00")

TIER_LOW_MIN_CREDITS = 5000
TIER_MEDIUM_MIN_CREDITS = 1000
TIER_ADDER = {"LOW": D("2.0"), "MEDIUM": D("4.0"), "HIGH": D("8.0")}
REVERSAL_HISTORY_ADDER_PCT = D("5.0")
BUFFER_PCT_CEILING = D("25.00")

CREDIT_PRICE_CENTS = D("2750")
BAND_1_CAP = D("500.00")
BAND_2_CAP = D("2000.00")
BAND_MULTIPLIERS = (D("1.000"), D("0.925"), D("0.850"))
HOLDBACK_LONG_PCT = D("20.00")
HOLDBACK_SHORT_PCT = D("10.00")
HOLDBACK_LONG_MIN_YEARS = 3

FULL_CLAWBACK_SHARE_PCT = D("100.00")
CLAWBACK_SUSPENSION_THRESHOLD_CENTS = 250000

EXIT_NOTICE_MIN_YEARS = 1
PRACTICE_COOLDOWN_YEARS = 2

MIN_RESERVE_RATIO = D("0.05")


# ---------------------------------------------------------------------------
# rounding helpers
# ---------------------------------------------------------------------------
def rhu(value, places):
    """Round half up to ``places`` decimal places."""
    quantum = D(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def clamp(value, low, high):
    if value < low:
        return D(low)
    if value > high:
        return D(high)
    return value


def cents(value):
    """Round a monetary expression half up to whole cents (an integer)."""
    return int(rhu(value, 0))


# ---------------------------------------------------------------------------
# 1. field mapped acreage
# ---------------------------------------------------------------------------
def mapped_acres(min_x, min_y, max_x, max_y):
    width = D(max_x - min_x)
    height = D(max_y - min_y)
    return rhu(width * height / SQUARE_UNITS_PER_ACRE, 2)


def rectangles_overlap(a, b):
    """True when two boundary boxes share positive area."""
    ix = min(a["boundary_max_x"], b["boundary_max_x"]) - max(a["boundary_min_x"], b["boundary_min_x"])
    iy = min(a["boundary_max_y"], b["boundary_max_y"]) - max(a["boundary_min_y"], b["boundary_min_y"])
    return ix > 0 and iy > 0


# ---------------------------------------------------------------------------
# 2. additionality screening
# ---------------------------------------------------------------------------
def lookback_window(start_crop_year, lookback_years):
    return start_crop_year - lookback_years, start_crop_year - 1


def screening_input_set(history_rows, field_id, practice_code, start_crop_year, lookback_years):
    low, high = lookback_window(start_crop_year, lookback_years)
    return [
        row for row in history_rows
        if row["field_id"] == field_id
        and row["practice_code"] == practice_code
        and low <= row["crop_year"] <= high
    ]


def additionality(rows, field_mapped_acres, lookback_years, telemetry_required):
    weighted = ZERO
    for row in rows:
        if row["adopted"]:
            weighted += D(row["acres"]) * EVIDENCE_WEIGHT[row["evidence_source"]]
    denominator = D(field_mapped_acres) * D(lookback_years)
    if denominator == 0:
        prior_adoption_pct = D("0.00")
    else:
        prior_adoption_pct = rhu(weighted / denominator * D(100), 2)

    documented_years = len(set(row["crop_year"] for row in rows))

    telemetry_gap = bool(telemetry_required) and not any(
        row["evidence_source"] == "EQUIPMENT_TELEMETRY" for row in rows
    )

    raw = (
        D(100)
        - D("1.5") * prior_adoption_pct
        - (D(20) if telemetry_gap else ZERO)
        + D(2) * D(min(documented_years, lookback_years))
    )
    score = clamp(rhu(raw, 2), D("0.00"), D("100.00"))
    return prior_adoption_pct, rhu(score, 2), documented_years


# ---------------------------------------------------------------------------
# 3. baseline establishment
# ---------------------------------------------------------------------------
BASELINE_EVIDENCE_SOURCES = ("FARM_RECORD", "EQUIPMENT_TELEMETRY")


def baseline_qualifying_rows(history_rows, field_id, practice_code, start_crop_year, lookback_years):
    rows = screening_input_set(
        history_rows, field_id, practice_code, start_crop_year, lookback_years
    )
    return [row for row in rows if row["evidence_source"] in BASELINE_EVIDENCE_SOURCES]


def baseline_figures(method, rows, field_row, standard):
    qualifying_years = len(set(row["crop_year"] for row in rows))
    out = {"qualifying_years": qualifying_years}
    acres = D(field_row["mapped_acres"])
    base = D(standard["uncertainty_base_pct"])
    if method == "HISTORICAL_DATA":
        total = ZERO
        for row in rows:
            total += D(row["observed_emissions_per_acre"] or 0)
        historical_mean_rate = rhu(total / D(qualifying_years), 4)
        out["historical_mean_rate"] = historical_mean_rate
        out["baseline_emissions_t"] = rhu(acres * historical_mean_rate, 3)
        uncertainty = rhu(base - HISTORICAL_UNCERTAINTY_PER_YEAR * D(qualifying_years), 2)
        if uncertainty < HISTORICAL_UNCERTAINTY_FLOOR:
            uncertainty = HISTORICAL_UNCERTAINTY_FLOOR
        out["uncertainty_pct"] = uncertainty
    else:
        out["historical_mean_rate"] = None
        factor = SOIL_FACTOR[field_row["soil_group"]]
        out["baseline_emissions_t"] = rhu(
            acres * D(standard["modeled_baseline_rate_per_acre"]) * factor, 3
        )
        uncertainty = rhu(
            base + MODELED_UNCERTAINTY_ADDER - MODELED_UNCERTAINTY_PER_YEAR * D(qualifying_years), 2
        )
        if uncertainty < MODELED_UNCERTAINTY_FLOOR:
            uncertainty = MODELED_UNCERTAINTY_FLOOR
        out["uncertainty_pct"] = uncertainty
    return out


# ---------------------------------------------------------------------------
# 4. data packet quality score
# ---------------------------------------------------------------------------
def qc_score(coverage_pct, reported_acres, source, enrolled_acres):
    completeness_ratio = rhu(D(coverage_pct) / D(100), 4)
    if completeness_ratio > ONE:
        completeness_ratio = D("1.0000")
    enrolled = D(enrolled_acres)
    if enrolled == 0:
        acre_gap_ratio = D("1.0000")
    else:
        acre_gap_ratio = rhu(abs(D(reported_acres) - enrolled) / enrolled, 4)
        if acre_gap_ratio > ONE:
            acre_gap_ratio = D("1.0000")
    plausibility_ratio = rhu(ONE - acre_gap_ratio, 4)
    weight = QC_SOURCE_WEIGHT[source]
    total = (
        QC_WEIGHT_COMPLETENESS * completeness_ratio
        + QC_WEIGHT_PLAUSIBILITY * plausibility_ratio
        + QC_WEIGHT_SOURCE * weight
    )
    return rhu(total * D(100), 2)


def completeness_status(coverage_pct):
    return "COMPLETE" if D(coverage_pct) >= COMPLETENESS_MIN_PCT else "PARTIAL"


# ---------------------------------------------------------------------------
# 5. net removals quantification
# ---------------------------------------------------------------------------
MEASUREMENT_SOURCES = ("EQUIPMENT_TELEMETRY", "REMOTE_SENSING")


def quantify(method, passed_packets, enrollment, baseline, standard, raise_error):
    """Returns the computed run figures.  ``raise_error(error_id)`` aborts."""
    if not passed_packets:
        raise_error("ERR_NO_QUALIFYING_DATA")
    if standard["telemetry_required"] and not any(
        p["source"] == "EQUIPMENT_TELEMETRY" for p in passed_packets
    ):
        raise_error("ERR_TELEMETRY_EVIDENCE_REQUIRED")

    if method == "MODEL":
        included = list(passed_packets)
    else:
        included = [p for p in passed_packets if p["source"] in MEASUREMENT_SOURCES]
        if not included:
            raise_error("ERR_NO_QUALIFYING_DATA")

    acres_sum = ZERO
    coverage_sum = ZERO
    for packet in included:
        acres_sum += D(packet["reported_acres"])
        coverage_sum += D(packet["coverage_pct"])
    enrolled = D(enrollment["enrolled_acres"])
    verified_acres = rhu(acres_sum if acres_sum < enrolled else enrolled, 2)
    mean_coverage_pct = rhu(coverage_sum / D(len(included)), 2)

    out = {
        "verified_acres": verified_acres,
        "mean_coverage_pct": mean_coverage_pct,
        "packet_count": len(included),
    }

    if method == "MODEL":
        adoption_factor = rhu(mean_coverage_pct / D(100), 4)
        if adoption_factor > ONE:
            adoption_factor = D("1.0000")
        gross = rhu(
            D(standard["sequestration_rate_per_acre"]) * verified_acres * adoption_factor, 3
        )
        deduction = rhu(
            (D(baseline["uncertainty_pct"]) + MODEL_UNCERTAINTY_ADDER_PCT) / D(100) * gross, 3
        )
        out["adoption_factor"] = adoption_factor
        out["sampling_uncertainty_pct"] = None
    else:
        if mean_coverage_pct < MEASUREMENT_MIN_COVERAGE_PCT:
            raise_error("ERR_COVERAGE_BELOW_MINIMUM")
        measured = ZERO
        for packet in included:
            measured += D(packet["measured_value"] or 0) * D(packet["reported_acres"])
        measured = rhu(measured, 3)
        gross = rhu(measured - D(baseline["baseline_emissions_t"]), 3)
        if gross < 0:
            gross = D("0.000")
        sampling = rhu(
            SAMPLING_UNCERTAINTY_INTERCEPT_PCT - SAMPLING_COVERAGE_SLOPE * mean_coverage_pct, 2
        )
        if sampling < SAMPLING_UNCERTAINTY_FLOOR_PCT:
            sampling = SAMPLING_UNCERTAINTY_FLOOR_PCT
        deduction = rhu(gross * sampling / D(100), 3)
        out["adoption_factor"] = None
        out["sampling_uncertainty_pct"] = sampling

    net = rhu(gross - deduction, 3)
    if net < 0:
        net = D("0.000")
    out["gross_removals_t"] = gross
    out["uncertainty_deduction_t"] = deduction
    out["net_removals_t"] = net
    return out


# ---------------------------------------------------------------------------
# 6. verification discrepancy
# ---------------------------------------------------------------------------
def material_discrepancy_pct(restated, net_removals_t):
    if restated is None:
        return D("0.00")
    net = D(net_removals_t)
    restated = D(restated)
    if net == 0:
        return D("100.00") if restated > 0 else D("0.00")
    return rhu(abs(restated - net) / net * D(100), 2)


# ---------------------------------------------------------------------------
# 7. credit issuance split (pinned evaluation order)
# ---------------------------------------------------------------------------
def issuance_split(net_removals_t, standard, grower):
    gross_credits = floor_int(net_removals_t)
    tier_basis = int(grower["lifetime_credits_issued"]) + gross_credits
    if tier_basis >= TIER_LOW_MIN_CREDITS:
        risk_tier = "LOW"
    elif tier_basis >= TIER_MEDIUM_MIN_CREDITS:
        risk_tier = "MEDIUM"
    else:
        risk_tier = "HIGH"
    adder = TIER_ADDER[risk_tier]
    reversal_adder = REVERSAL_HISTORY_ADDER_PCT if int(grower["reversal_count"]) >= 1 else ZERO
    buffer_pct = rhu(D(standard["buffer_base_pct"]) + adder + reversal_adder, 2)
    if buffer_pct > BUFFER_PCT_CEILING:
        buffer_pct = BUFFER_PCT_CEILING
    buffer_credits = ceil_int(D(gross_credits) * buffer_pct / D(100))
    issued_credits = gross_credits - buffer_credits
    return {
        "gross_credits": gross_credits,
        "tier_basis": tier_basis,
        "risk_tier": risk_tier,
        "buffer_pct": buffer_pct,
        "buffer_credits": buffer_credits,
        "issued_credits": issued_credits,
    }


# ---------------------------------------------------------------------------
# 8. grower payment amount
# ---------------------------------------------------------------------------
def holdback_pct(enrollment, current_crop_year):
    elapsed = current_crop_year - int(enrollment["start_crop_year"])
    remaining = int(enrollment["commitment_years"]) - elapsed
    if remaining >= HOLDBACK_LONG_MIN_YEARS:
        return HOLDBACK_LONG_PCT
    if remaining >= 1:
        return HOLDBACK_SHORT_PCT
    return D("0.00")


def per_acre_gross_cents(payable_acres, per_acre_rate_cents):
    acres = D(payable_acres)
    rate = D(per_acre_rate_cents)
    band_1 = acres if acres < BAND_1_CAP else BAND_1_CAP
    band_2 = acres - BAND_1_CAP
    if band_2 < 0:
        band_2 = ZERO
    ceiling_2 = BAND_2_CAP - BAND_1_CAP
    if band_2 > ceiling_2:
        band_2 = ceiling_2
    band_3 = acres - BAND_2_CAP
    if band_3 < 0:
        band_3 = ZERO
    total = 0
    for band, multiplier in zip((band_1, band_2, band_3), BAND_MULTIPLIERS):
        total += cents(band * rate * multiplier)
    return total


def per_credit_gross_cents(issued_credits, per_credit_share_pct):
    return cents(D(issued_credits) * D(per_credit_share_pct) / D(100) * CREDIT_PRICE_CENTS)


def settle_payment(gross_amount_cents, holdback_percentage):
    holdback_cents = cents(D(gross_amount_cents) * D(holdback_percentage) / D(100))
    return holdback_cents, int(gross_amount_cents) - holdback_cents


# ---------------------------------------------------------------------------
# 9. reversal assessment
# ---------------------------------------------------------------------------
def reversal_assessment(batch, enrollment, pool_balance, reversal_type, affected_acres):
    issued = int(batch["issued_credits"])
    enrolled = D(enrollment["enrolled_acres"])
    if enrolled == 0:
        affected_credits = 0
    else:
        affected_credits = ceil_int(D(issued) * D(affected_acres) / enrolled)
    if affected_credits > issued:
        affected_credits = issued
    if reversal_type == "UNINTENTIONAL":
        buffer_draw = min(int(pool_balance), affected_credits)
        if buffer_draw < 0:
            buffer_draw = 0
    else:
        buffer_draw = 0
    unbacked = affected_credits - buffer_draw
    if enrollment["payment_model"] == "PER_CREDIT" and enrollment["per_credit_share_pct"] is not None:
        share = D(enrollment["per_credit_share_pct"])
    else:
        share = FULL_CLAWBACK_SHARE_PCT
    clawback = cents(D(unbacked) * CREDIT_PRICE_CENTS * share / D(100))
    return {
        "affected_credits": affected_credits,
        "buffer_draw_credits": buffer_draw,
        "unbacked_credits": unbacked,
        "grower_clawback_cents": clawback,
    }


# ---------------------------------------------------------------------------
# 10. contract exit fee
# ---------------------------------------------------------------------------
def exit_fee_cents(enrollment, settled_cents, current_crop_year):
    elapsed = current_crop_year - int(enrollment["start_crop_year"])
    commitment_years = int(enrollment["commitment_years"])
    if enrollment.get("exit_reason") == "FORCE_MAJEURE":
        return 0
    if elapsed >= commitment_years:
        return 0
    served_ratio = D(elapsed) / D(commitment_years)
    if served_ratio > ONE:
        served_ratio = ONE
    return cents(D(settled_cents) * (ONE - served_ratio))


# ---------------------------------------------------------------------------
# buffer pool reserve derivation
# ---------------------------------------------------------------------------
def required_reserve(ratio, outstanding_issued_credits):
    return int(rhu(D(ratio) * D(outstanding_issued_credits), 0))
