"""The programme's arithmetic (PRD 2.5, 3.2, 3.3, 3.5, 3.7, 3.8, 3.9).

Every amount is an integer number of cents.  Divisions that land on a fractional
cent round half up -- a residue of exactly one half cent rounds away from zero.
Basis-point ratios are truncated (floored) where the PRD says so.
"""
from decimal import ROUND_HALF_UP, Decimal

import clock
from constants import (
    ADMIN_FEE_EARLY_CANCELLATION_CENTS, ADMIN_FEE_UPGRADE_ROLLOVER_CENTS,
    BATTERY_DEDUCTION_CENTS, COND_EXCELLENT, COND_FAIR, COND_GOOD, COND_POOR,
    CONDITION_MULTIPLIER_BPS, CONDITION_SEVERITY, CONDITIONAL_BAND_BPS,
    CREDIT_LIMITS, DIAG_FAIL, DIAG_PASS, DQ_CURRENT, DQ_DEFAULT, DQ_DELINQUENT,
    DQ_GRACE, FAILED_DIAGNOSTIC_BPS, INST_PARTIALLY_PAID, INST_PAST_DUE,
    ORIGINATION_FEE_TIER_1, ORIGINATION_FEE_TIER_1_CEILING, ORIGINATION_FEE_TIER_2,
    ORIGINATION_FEE_TIER_2_CEILING, ORIGINATION_FEE_TIER_3, PRO_RATA_REBATE_BPS,
    QUOTE_EARLY_CANCELLATION, QUOTE_UPGRADE_ROLLOVER, SCREEN_DEDUCTION_CENTS,
    SCREEN_IMPLIED_CONDITION,
)


def round_half_up(numerator, denominator):
    """Exact integer round-half-up division (denominator must be positive)."""
    if denominator == 0:
        return 0
    quantised = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantised)


def floor_div(numerator, denominator):
    if denominator == 0:
        return 0
    return numerator // denominator


def bps_of(amount, bps):
    """round_half_up(amount * bps / 10000)."""
    return round_half_up(amount * bps, 10000)


# --- 3.2 credit decision ---

def conditional_ceiling(credit_limit_cents):
    return bps_of(credit_limit_cents, CONDITIONAL_BAND_BPS)


def credit_decision(band, requested_principal_cents, customer_outstanding_cents):
    """Returns (status_key, exposure, approved_principal, conditional_down_payment)."""
    limit = CREDIT_LIMITS[band]
    exposure = customer_outstanding_cents + requested_principal_cents
    ceiling = conditional_ceiling(limit)
    if exposure <= limit:
        return "APPROVED", exposure, requested_principal_cents, 0
    if exposure <= ceiling:
        conditional = exposure - limit
        return "CONDITIONAL_APPROVED", exposure, requested_principal_cents - conditional, conditional
    return "DECLINED", exposure, 0, 0


# --- 3.3 amortisation schedule ---

def base_principal_component(principal_cents, term_months):
    return round_half_up(principal_cents, term_months)


def schedule_rows(principal_cents, term_months, monthly_premium_cents, origination_date):
    """The term_months rows of an installment schedule, 1-indexed."""
    base = base_principal_component(principal_cents, term_months)
    rows = []
    for number in range(1, term_months + 1):
        if number == term_months:
            principal_component = principal_cents - base * (term_months - 1)
        else:
            principal_component = base
        due_date = clock.at_midnight(clock.add_months(origination_date, number))
        rows.append({
            "installment_number": number,
            "due_date": due_date,
            "principal_component_cents": principal_component,
            "premium_component_cents": monthly_premium_cents,
            "amount_due_cents": principal_component + monthly_premium_cents,
        })
    return rows


# --- 3.6 delinquency ladder ---

def delinquency_label(days_past_due):
    if days_past_due == 0:
        return DQ_CURRENT
    if days_past_due <= 10:
        return DQ_GRACE
    if days_past_due <= 89:
        return DQ_DELINQUENT
    return DQ_DEFAULT


# --- 3.7 payoff pricing ---

def payoff_figures(loan, installments, quote_type, moment):
    """The priced figures for a payoff quote of ``quote_type`` on ``loan``."""
    remaining_principal = loan["principal_cents"] - loan["paid_principal_cents"]
    outstanding_late_fee = loan["outstanding_late_fee_cents"]
    term = loan["term_months"]
    paid_count = loan["paid_installment_count"]
    premium_total = loan["monthly_protection_premium_cents"] * term
    remaining_term = term - paid_count
    if quote_type == QUOTE_UPGRADE_ROLLOVER:
        unearned = round_half_up(
            premium_total * (remaining_term * (remaining_term + 1)),
            term * (term + 1))
        rebate = unearned
        admin_fee = ADMIN_FEE_UPGRADE_ROLLOVER_CENTS
    else:
        unearned = premium_total - loan["paid_premium_cents"]
        rebate = bps_of(unearned, PRO_RATA_REBATE_BPS)
        admin_fee = ADMIN_FEE_EARLY_CANCELLATION_CENTS
    past_due = 0
    for installment in installments:
        if installment["status"] in (INST_PAST_DUE, INST_PARTIALLY_PAID) and \
                clock.parse_iso8601(installment["due_date"]) <= moment:
            past_due += installment["amount_due_cents"] - installment["paid_amount_cents"]
    total = remaining_principal + outstanding_late_fee + admin_fee - rebate
    return {
        "remaining_principal_cents": remaining_principal,
        "outstanding_late_fee_cents": outstanding_late_fee,
        "unearned_premium_cents": unearned,
        "premium_rebate_cents": rebate,
        "admin_fee_cents": admin_fee,
        "total_payoff_cents": total,
        "past_due_amount_cents": past_due,
        "paid_installment_count_at_quote": paid_count,
    }


# --- 3.8 upgrade eligibility ---

def eligibility_ratio_bps(paid_installment_count, term_months):
    return floor_div(paid_installment_count * 10000, term_months)


# --- 3.9 trade-in valuation ---

def declared_credit(base_credit_cents, declared_condition):
    return bps_of(base_credit_cents, CONDITION_MULTIPLIER_BPS[declared_condition])


def battery_implied_condition(battery_health_pct):
    if battery_health_pct >= 80:
        return COND_EXCELLENT
    if battery_health_pct >= 60:
        return COND_GOOD
    return COND_FAIR


def worse_condition(left, right):
    return left if CONDITION_SEVERITY[left] <= CONDITION_SEVERITY[right] else right


def grade_diagnostic(base_credit_cents, screen_grade, battery_health_pct,
                     water_damage_flag, functional_pass):
    """Returns the graded figures for one diagnostic report."""
    screen_deduction = SCREEN_DEDUCTION_CENTS[screen_grade]
    battery_condition = battery_implied_condition(battery_health_pct)
    battery_deduction = BATTERY_DEDUCTION_CENTS[battery_condition]
    if water_damage_flag or not functional_pass:
        result = DIAG_FAIL
        derived = COND_POOR
        computed = bps_of(base_credit_cents, FAILED_DIAGNOSTIC_BPS)
    else:
        result = DIAG_PASS
        derived = worse_condition(SCREEN_IMPLIED_CONDITION[screen_grade], battery_condition)
        computed = bps_of(base_credit_cents, CONDITION_MULTIPLIER_BPS[derived])
        computed = max(0, computed - screen_deduction - battery_deduction)
    return {
        "derived_condition": derived,
        "condition_multiplier_bps": CONDITION_MULTIPLIER_BPS[derived],
        "screen_deduction_cents": screen_deduction,
        "battery_deduction_cents": battery_deduction,
        "computed_credit_cents": computed,
        "diagnostic_result": result,
    }


# --- 3.9 rollover arithmetic ---

def origination_fee_for(pre_fee_base_cents):
    if pre_fee_base_cents < ORIGINATION_FEE_TIER_1_CEILING:
        return ORIGINATION_FEE_TIER_1
    if pre_fee_base_cents < ORIGINATION_FEE_TIER_2_CEILING:
        return ORIGINATION_FEE_TIER_2
    return ORIGINATION_FEE_TIER_3


def rollover_math(total_payoff_cents, credit_final_cents, additional_down_payment_cents,
                  target_retail_price_cents):
    gross_rollover = max(0, total_payoff_cents - credit_final_cents)
    excess_credit = max(0, credit_final_cents - total_payoff_cents)
    net_rollover = max(0, gross_rollover - additional_down_payment_cents)
    pre_fee_base = target_retail_price_cents + net_rollover - excess_credit
    fee = origination_fee_for(pre_fee_base)
    return {
        "gross_rollover_cents": gross_rollover,
        "excess_credit_cents": excess_credit,
        "net_rollover_cents": net_rollover,
        "pre_fee_base_cents": pre_fee_base,
        "origination_fee_cents": fee,
        "principal_cents": pre_fee_base + fee,
    }
