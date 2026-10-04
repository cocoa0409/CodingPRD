"""Calculation rules (SCAFFOLD §1.3 / PRD §3). Pinned formulas, precision and
rounding order — do not "improve"."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

from constants import (
    INCENTIVE_HOLD_PENALTY_PER_DAY,
    INCENTIVE_APPT_PENALTY_PER_DAY,
    INCENTIVE_CONGESTION_HIGH,
    INCENTIVE_CONGESTION_MED,
    CONGESTION_HIGH_RATIO,
    CONGESTION_MED_RATIO,
    PORT_WEEKLY_BERTH_CAPACITY_HOURS,
    INCENTIVE_DAY_CAP,
    FLUIDITY_METHOD_THRESHOLD,
    OOP_INTEREST_RATE,
    FLUIDITY_SURCHARGE_RATE,
    PER_VIOLATION_CENTS,
    WILLFUL_MULTIPLIER,
    PROCEEDING_PENALTY_CAP_CENTS,
    SCORE_PENALTY_UNREASONABLE_PER_VIOLATION,
    SCORE_PENALTY_OTHER_PER_VIOLATION,
    SCORE_CAP_UNREASONABLE,
    SCORE_CAP_OTHER,
)

_CENT = Decimal("1")
_4DP = Decimal("0.0001")
_2DP = Decimal("0.01")


def invoice_billable_days(free_time_days, accrual_method, availability_date, return_date):
    """calculations.invoice_charge_amount — the day-count half."""
    free_time_end = availability_date + timedelta(days=free_time_days)
    if return_date <= free_time_end:
        return 0
    if accrual_method == "CALENDAR":
        # window (free_time_end, return_date]; partial days round up
        days, rem = divmod(return_date - free_time_end, timedelta(days=1))
        return int(days) + (1 if rem > timedelta(0) else 0)
    # WORKING_DAY: calendar dates strictly after date(free_time_end) up to and
    # including date(return_date), Mon-Fri only.
    d0 = free_time_end.date()
    d1 = return_date.date()
    count = 0
    d = d0 + timedelta(days=1)
    while d <= d1:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


def invoice_amount_cents(billable_days, per_diem_rate_cents):
    return billable_days * per_diem_rate_cents


def incentive_principle_score(invoices, congestion_reports):
    """calculations.incentive_principle_score — computed once at intake, frozen."""
    score = 100
    for inv in invoices:
        score -= INCENTIVE_HOLD_PENALTY_PER_DAY * min(inv["government_hold_days"],
                                                      INCENTIVE_DAY_CAP)
        score -= INCENTIVE_APPT_PENALTY_PER_DAY * min(inv["appointment_unavailable_days"],
                                                      INCENTIVE_DAY_CAP)
        matched = [
            r for r in congestion_reports
            if r["port_code"] == inv["port_code"]
            and r["week_start"] <= inv["last_accrual_date"]
            and r["week_start"] + timedelta(days=7) > inv["availability_date"]
        ]
        per_week = {}
        for r in matched:
            per_week[r["week_start"]] = (
                per_week.get(r["week_start"], 0) + r["berth_occupancy_hours"]
            )
        max_occupancy = Fraction(0)
        for hours in per_week.values():
            occ = Fraction(hours, PORT_WEEKLY_BERTH_CAPACITY_HOURS)
            if occ > max_occupancy:
                max_occupancy = occ
        if max_occupancy >= CONGESTION_HIGH_RATIO:
            score -= INCENTIVE_CONGESTION_HIGH
        elif max_occupancy >= CONGESTION_MED_RATIO:
            score -= INCENTIVE_CONGESTION_MED
    return max(0, score)


def reparation_award(incentive_score, reparations_claimed_cents, invoices):
    """calculations.reparation_award. Returns (reparation_method, award_cents).

    Pinned order: method selection first, per-invoice components rounded
    half-up to whole cents THEN summed, cap applied last."""
    if incentive_score < FLUIDITY_METHOD_THRESHOLD:
        method = "FLUIDITY_WEIGHTED"
        raw = 0
        for inv in invoices:
            comp = (Decimal(inv["amount_cents"]) * (Decimal(1) + FLUIDITY_SURCHARGE_RATE)
                    ).quantize(_CENT, rounding=ROUND_HALF_UP)
            raw += int(comp)
    else:
        method = "OUT_OF_POCKET"
        raw = 0
        for inv in invoices:
            if inv["invoice_status"] == "PAID":
                interest = (Decimal(inv["amount_cents"]) * OOP_INTEREST_RATE
                            ).quantize(_CENT, rounding=ROUND_HALF_UP)
                raw += inv["amount_cents"] + int(interest)
    return method, min(reparations_claimed_cents, raw)


def monitoring_hhi(member_volumes, total_market_teus):
    """calculations.monitoring_hhi — pinned nested rounding: per-member share
    4dp round-half-up, square 2dp round-half-up, sum, final 2dp round-half-up."""
    total = Decimal(0)
    for entry in member_volumes:
        share_pct = (Decimal(entry["carried_teus"]) / Decimal(total_market_teus) * 100
                     ).quantize(_4DP, rounding=ROUND_HALF_UP)
        contribution = (share_pct * share_pct).quantize(_2DP, rounding=ROUND_HALF_UP)
        total += contribution
    return total.quantize(_2DP, rounding=ROUND_HALF_UP)


def civil_penalty_assessment(violation_count, willful, repeat_offender):
    """Pinned order: per-violation base, willful doubling, repeat 1.5x in exact
    integer arithmetic (multiply by 3, then divide by 2), then the cap."""
    base = violation_count * PER_VIOLATION_CENTS
    if willful:
        base = base * WILLFUL_MULTIPLIER
    if repeat_offender:
        base = (base * 3) // 2
    return min(base, PROCEEDING_PENALTY_CAP_CENTS)


def violation_score_delta(basis, violation_count):
    if basis == "UNREASONABLE_PRACTICE":
        return -min(SCORE_PENALTY_UNREASONABLE_PER_VIOLATION * violation_count,
                    SCORE_CAP_UNREASONABLE)
    return -min(SCORE_PENALTY_OTHER_PER_VIOLATION * violation_count,
                SCORE_CAP_OTHER)
