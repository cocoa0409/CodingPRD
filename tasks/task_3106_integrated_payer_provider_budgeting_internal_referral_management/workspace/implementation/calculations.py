"""Pure calculation rules (PRD section 3.1 - 3.11).

Each function here is a verbatim translation of a rule in PRD.md. All monetary
arithmetic is integer cents through Decimal with round-half-up.
"""

from constants import (
    ANNUAL_DEDUCTIBLE_CENTS,
    BASE_RATE_CENTS,
    CAPITATION_CEIL_MULTIPLIER,
    CAPITATION_FLOOR_MULTIPLIER,
    COINSURANCE_RATE,
    DEFAULT_VENDOR_ALLOWABLE_PCT,
    EMERGENCY_PAY_RATE,
    FTE_COST_CENTS,
    INTEGRATION_CREDIT_RATE,
    INTERIM_CLAIM_THRESHOLD,
    INTERIM_HIGH_MULTIPLIER,
    OUT_OF_POCKET_CAP_CENTS,
    PANEL_RATE_CENTS,
    PANEL_TARGET_MEMBERS_PER_SLOT,
    QUALITY_BONUS_RATE,
    QUALITY_BONUS_THRESHOLD,
    VENDOR_ALLOWABLE_PCT,
    WEIGHT_BY_METRIC,
)
from rounding import clamp, dec, round_half_up_dp, round_half_up_int


# --- PRD 3.1 capitation_rate_cents ----------------------------------------

def capitation_rate_cents(plan_product, risk_score, capitation_index):
    base_rate = BASE_RATE_CENTS[plan_product]
    adjusted_base = round_half_up_int(dec(base_rate) * dec(capitation_index))
    risk_component = round_half_up_int(dec(adjusted_base) * dec(risk_score))
    raw_rate = adjusted_base + risk_component
    lower = round_half_up_int(dec(adjusted_base) * CAPITATION_FLOOR_MULTIPLIER)
    upper = round_half_up_int(dec(adjusted_base) * CAPITATION_CEIL_MULTIPLIER)
    return clamp(raw_rate, lower, upper)


# --- PRD 3.2 provider_comp_total_cents ------------------------------------

def panel_capitation_component_cents(panel_size_assigned, specialty):
    panel_rate = PANEL_RATE_CENTS.get(specialty, 0)
    return round_half_up_int(dec(panel_size_assigned) * dec(panel_rate))


def quality_bonus_cents(base_component_cents, panel_component_cents,
                        quality_score):
    if dec(quality_score) >= QUALITY_BONUS_THRESHOLD:
        basis = dec(base_component_cents) + dec(panel_component_cents)
        return round_half_up_int(basis * QUALITY_BONUS_RATE)
    return 0


def provider_comp_total_cents(base_component_cents, panel_component_cents,
                              quality_bonus, volume_component_cents=0):
    return (int(base_component_cents) + int(panel_component_cents)
            + int(quality_bonus) + int(volume_component_cents))


# --- PRD 3.3 capacity_supply_balance --------------------------------------

def supply_shortfall_slots(committed_slots, budgeted_slots):
    return max(0, int(committed_slots) - int(budgeted_slots))


def utilization_pct(committed_slots, budgeted_slots):
    if not budgeted_slots:
        return round_half_up_dp(0, 2)
    ratio = dec(100) * dec(committed_slots) / dec(budgeted_slots)
    return round_half_up_dp(ratio, 2)


def meets_commissioning_ratio(budgeted_slots, panel_target):
    """PRD 3.3: review requires budgeted_slots >= panel_target / 1.5."""
    required = dec(panel_target) / PANEL_TARGET_MEMBERS_PER_SLOT
    return dec(budgeted_slots) >= required


# --- PRD 3.6 outside_services_liability -----------------------------------

def provisional_liability_cents(billed_amount_cents, vendor_name,
                                emergency_flag):
    billed = dec(billed_amount_cents)
    if emergency_flag:
        return round_half_up_int(billed * EMERGENCY_PAY_RATE)
    pct = VENDOR_ALLOWABLE_PCT.get(vendor_name, DEFAULT_VENDOR_ALLOWABLE_PCT)
    return round_half_up_int(billed * pct)


def line_sort_key(line):
    return (int(line.get("line_number", 0)), str(line.get("created_at", "")))


def final_liability_cents(lines):
    """Chronological deductible consumption across the claim's own lines."""
    running_total = 0
    running_liability = 0
    for line in sorted(lines, key=line_sort_key):
        line_amount = int(line.get("line_amount_cents", 0))
        running_total += line_amount
        if running_total <= ANNUAL_DEDUCTIBLE_CENTS:
            line_liability = 0
        else:
            excess = running_total - ANNUAL_DEDUCTIBLE_CENTS
            if excess >= line_amount:
                line_liability = round_half_up_int(
                    dec(line_amount) * COINSURANCE_RATE)
            else:
                line_liability = round_half_up_int(
                    dec(excess) * COINSURANCE_RATE)
        running_liability += line_liability
    return min(running_liability, OUT_OF_POCKET_CAP_CENTS)


def claim_lines_from_body(body, claim):
    """Derive the claim's line items from the submission payload.

    PRD 3.6: `provider_type`, `claim_line_number` and `derived_claim_type`
    together determine which claim line supplies the annual-deductible
    consumption. When the payload carries an explicit `line_items` array that
    array is used verbatim; otherwise a single line is derived from
    `billed_amount_cents` and `claim_line_number`.
    """
    explicit = body.get("line_items")
    lines = []
    if isinstance(explicit, list) and explicit:
        for index, entry in enumerate(explicit):
            if not isinstance(entry, dict):
                continue
            lines.append({
                "line_number": int(entry.get("line_number", index + 1)),
                "line_amount_cents": int(entry.get("line_amount_cents", 0)),
                "provider_type": entry.get("provider_type"),
                "derived_claim_type": entry.get("derived_claim_type"),
                "created_at": entry.get("created_at") or claim["created_at"],
            })
        return lines

    line_number = body.get("claim_line_number")
    if line_number is None:
        line_number = 1
    lines.append({
        "line_number": int(line_number),
        "line_amount_cents": int(body.get("billed_amount_cents") or 0),
        "provider_type": body.get("provider_type"),
        "derived_claim_type": body.get("derived_claim_type"),
        "created_at": claim["created_at"],
    })
    return lines


# --- PRD 3.11 referential_integration_settlement --------------------------

def effective_credit_rate(risk_sharing_model, interim_claim_count):
    rate = INTEGRATION_CREDIT_RATE.get(risk_sharing_model, dec(0))
    if int(interim_claim_count or 0) > INTERIM_CLAIM_THRESHOLD:
        rate = rate * INTERIM_HIGH_MULTIPLIER
    return rate


def integration_per_diem_component_cents(per_diem_days, per_diem_rate_cents,
                                         per_diem_cap_cents):
    raw = round_half_up_int(dec(per_diem_days) * dec(per_diem_rate_cents))
    return min(raw, int(per_diem_cap_cents))


def integration_basis_component_cents(cost_reporting_basis_cents,
                                      risk_sharing_model, interim_claim_count):
    rate = effective_credit_rate(risk_sharing_model, interim_claim_count)
    return round_half_up_int(dec(cost_reporting_basis_cents) * rate)


def settlement_account_cents(per_diem_days, per_diem_rate_cents,
                             per_diem_cap_cents, cost_reporting_basis_cents,
                             risk_sharing_model, interim_claim_count):
    return (integration_per_diem_component_cents(
                per_diem_days, per_diem_rate_cents, per_diem_cap_cents)
            + integration_basis_component_cents(
                cost_reporting_basis_cents, risk_sharing_model,
                interim_claim_count))


# --- PRD 3.10 quality / access metrics ------------------------------------

def component_score(measured_value, target_value):
    if not target_value:
        ratio = dec(0)
    else:
        ratio = dec(measured_value) / dec(target_value)
    clamped = clamp(ratio, dec(0), dec(1))
    return round_half_up_int(dec(100) * clamped)


def weighted_component_score(metric_code, measured_value, target_value):
    """Round per component first, then weight, then round again (PRD 3.10)."""
    score = component_score(measured_value, target_value)
    weight = WEIGHT_BY_METRIC.get(metric_code, dec(0))
    return round_half_up_int(dec(score) * weight)


def region_quality_composite_score(metrics):
    """Weighted composite over the region's FINALIZED metrics (PRD 2.6)."""
    total = 0
    for metric in metrics:
        if metric.get("status") != "FINALIZED":
            continue
        total += int(metric.get("weighted_component_score", 0) or 0)
    return total


def access_breach_pct(breached_count, non_cancelled_count):
    if not non_cancelled_count:
        return round_half_up_dp(0, 2)
    ratio = dec(100) * dec(breached_count) / dec(non_cancelled_count)
    return round_half_up_dp(ratio, 2)


def mean_wait_days(appointments):
    waits = [dec(a.get("wait_days", 0) or 0) for a in appointments]
    if not waits:
        return round_half_up_dp(0, 1)
    total = sum(waits)
    return round_half_up_dp(total / dec(len(waits)), 1)


def wait_days_between(booking_moment, start_moment):
    return round_half_up_dp(
        dec((start_moment - booking_moment).total_seconds()) / dec(86400), 1)


# --- PRD 2.6 region rollups ----------------------------------------------

def staffing_and_facility_cents(sites):
    total = 0
    for site in sites:
        filled = dec(site.get("staffing_fte_filled", 0) or 0)
        total += round_half_up_int(filled * dec(FTE_COST_CENTS))
        total += int(site.get("facility_investment_spent_cents", 0) or 0)
    return total