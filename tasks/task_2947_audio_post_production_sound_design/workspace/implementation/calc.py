"""All nine calculations of the PRD, in Decimal arithmetic with round half up.

PRD §2.8: "All monetary fields are integer cents ... Hours, minutes and loudness
quantities are decimal numbers carried to exactly 2 decimal places.  Wherever a
value must be rounded, the service rounds half up ... two deliberate exceptions
... stage billing is always rounded up to the next quarter-hour ... licensed
material is charged in whole 30-second units, rounded up."
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
TWO_DP = Decimal("0.01")

MIN_SESSION_HOURS = Decimal("2.00")
BILLING_INCREMENT_HOURS = Decimal("0.25")
OVERTIME_RATE_FACTOR = Decimal("1.5")
CONFORM_RATE_CENTS_PER_MINUTE = Decimal("1500")
ADR_UNION_RATE_CENTS_PER_MINUTE = Decimal("900")
ADR_NON_UNION_RATE_CENTS_PER_MINUTE = Decimal("600")
BILLABLE_UNIT_SECONDS = 30
RM_WEIGHT = Decimal("20")
RF_WEIGHT = Decimal("5")
UNLICENSED_PENALTY = Decimal("30")
NEAR_EXPIRY_WEIGHT = Decimal("10")
NEAR_EXPIRY_WINDOW_DAYS = 30
RISK_BLOCK_THRESHOLD = Decimal("50.00")
SCORE_CAP = Decimal("100.00")

TURNAROUND_MULTIPLIER = {
    "STANDARD": Decimal("1.00"),
    "EXPEDITED": Decimal("1.25"),
    "RUSH": Decimal("1.60"),
}
RUSH_SURCHARGE_PCT = {
    "STANDARD": Decimal("0.00"),
    "EXPEDITED": Decimal("0.10"),
    "RUSH": Decimal("0.20"),
}
VOLUME_DISCOUNT_TIERS = [
    (Decimal("0"), Decimal("499999"), Decimal("0.00")),
    (Decimal("500000"), Decimal("999999"), Decimal("0.05")),
    (Decimal("1000000"), None, Decimal("0.08")),
]

REJECTION_CODE_ORDER = [
    "LOUDNESS_OUT_OF_TOLERANCE",
    "TRUE_PEAK_EXCEEDED",
    "ME_STEMS_MISSING",
]


def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    """Monetary results are integer cents, rounded half up."""
    return int(rhu(value, 0))


def q2(value):
    return Decimal(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def whole_seconds(start, end):
    return int((end - start).total_seconds())


def ceil_div(numerator, denominator):
    return -((-numerator) // denominator)


# ------------------------------------------------------------- stem conform
def cue_minutes(duration_seconds):
    """PRD §3.3: each cue's duration_seconds converted to minutes, rounded half
    up to two decimals."""
    return rhu(Decimal(duration_seconds) / Decimal(60), 2)


def stem_conform_totals(durations):
    """total_stem_minutes is the sum of the ALREADY ROUNDED per-cue minutes; the
    sum itself is not re-rounded (PRD §3.3)."""
    total = Decimal("0.00")
    for seconds in durations:
        total = total + cue_minutes(seconds)
    total = total.quantize(TWO_DP)
    fee = money(total * CONFORM_RATE_CENTS_PER_MINUTE)
    return total, fee


# ------------------------------------------------------------- asset usage
def billable_units(usage_seconds):
    """PRD §3.4: 'billable_units = ceil(usage_seconds / 30)'."""
    return ceil_div(int(usage_seconds), BILLABLE_UNIT_SECONDS)


def accrued_fee(license_type, fee_cents, usage_seconds):
    """RIGHTS_MANAGED multiplies the fee by the units; ROYALTY_FREE charges the
    flat fee once (PRD §3.4)."""
    if license_type == "RIGHTS_MANAGED":
        return money(Decimal(fee_cents) * Decimal(billable_units(usage_seconds)))
    return money(Decimal(fee_cents))


# ------------------------------------------------------------- ADR session
def adr_session_cost(start, end, union_status, min_call_minutes):
    """PRD §3.5."""
    scheduled = rhu(Decimal(whole_seconds(start, end)) / Decimal(60), 2)
    if union_status == "UNION":
        billable = max(scheduled, q2(min_call_minutes))
        rate = ADR_UNION_RATE_CENTS_PER_MINUTE
    else:
        billable = scheduled
        rate = ADR_NON_UNION_RATE_CENTS_PER_MINUTE
    billable = q2(billable)
    cost = money(billable * rate)
    return scheduled, billable, cost


# ------------------------------------------------------------- stage booking
def provisional_booking_cost(start, end, hourly_rate_cents, turnaround_class):
    """PROVISIONAL variant of stage_booking_cost (PRD §3.6)."""
    requested_hours = rhu(Decimal(whole_seconds(start, end)) / Decimal(3600), 2)
    reserved_hours = q2(max(requested_hours, MIN_SESSION_HOURS))
    base_cents = money(reserved_hours * Decimal(hourly_rate_cents))
    multiplier = TURNAROUND_MULTIPLIER[turnaround_class]
    provisional = money(Decimal(base_cents) * multiplier)
    return requested_hours, reserved_hours, provisional


def final_booking_cost(actual_start, actual_end, reserved_hours, hourly_rate_cents,
                       turnaround_class):
    """FINAL variant of stage_booking_cost (PRD §3.6): quarter-hour ceiling first,
    then the two-hour floor; overtime at 1.5x; turnaround multiplier applied once
    to the combined base."""
    seconds = whole_seconds(actual_start, actual_end)
    if seconds < 0:
        seconds = 0
    increments = ceil_div(seconds, 900)
    incremented = q2(Decimal(increments) * BILLING_INCREMENT_HOURS)
    billable = q2(max(incremented, MIN_SESSION_HOURS))
    overtime = q2(max(billable - q2(reserved_hours), Decimal("0.00")))
    regular = q2(billable - overtime)
    base = money(regular * Decimal(hourly_rate_cents)) + money(
        overtime * Decimal(hourly_rate_cents) * OVERTIME_RATE_FACTOR
    )
    multiplier = TURNAROUND_MULTIPLIER[turnaround_class]
    final_cost = money(Decimal(base) * multiplier)
    return billable, overtime, final_cost


# ------------------------------------------------------------- loudness QC
def deviation_lu(measured_integrated_lufs, target_lufs):
    """PRD §3.7: 'deviation_lu = round_half_up(abs(measured - target), 2)'."""
    return rhu(abs(Decimal(measured_integrated_lufs) - Decimal(target_lufs)), 2)


def qc_rejection_codes(measured_lufs, measured_true_peak, me_stems_present, spec):
    """Codes are emitted in the fixed order of PRD §3.7."""
    codes = []
    deviation = deviation_lu(measured_lufs, spec["target_lufs"])
    if deviation > q2(spec["tolerance_lu"]):
        codes.append("LOUDNESS_OUT_OF_TOLERANCE")
    if Decimal(measured_true_peak) > Decimal(spec["true_peak_max_dbtp"]):
        codes.append("TRUE_PEAK_EXCEEDED")
    if spec["requires_me_stems"] and not me_stems_present:
        codes.append("ME_STEMS_MISSING")
    return deviation, codes


# ------------------------------------------------------------- licence risk
def license_risk_scores(usages, assets, now):
    """Both variants of license_risk_score (PRD §3.4).

    INTAKE_SNAPSHOT counts weights over CLEARED usages only.  DELIVERY_AUDIT
    counts weights over every usage, adds 30 per UNLICENSED usage and 10 per
    CLEARED usage whose asset expires within 30 days of the logical clock.  Each
    variant sums, rounds half up, then caps at 100.00 exactly once.
    """
    intake_raw = Decimal("0")
    audit_raw = Decimal("0")
    horizon = now + _days(NEAR_EXPIRY_WINDOW_DAYS)
    for usage in usages:
        asset = assets.get(usage["library_asset_id"])
        if asset is None:
            continue
        weight = RM_WEIGHT if asset["license_type"] == "RIGHTS_MANAGED" else RF_WEIGHT
        audit_raw = audit_raw + weight
        if usage["clearance_status"] == "CLEARED":
            intake_raw = intake_raw + weight
            expires = asset.get("expires_at_utc")
            if expires is not None and expires > now and expires <= horizon:
                audit_raw = audit_raw + NEAR_EXPIRY_WEIGHT
        else:
            audit_raw = audit_raw + UNLICENSED_PENALTY
    intake = min(rhu(intake_raw, 2), SCORE_CAP)
    audit = min(rhu(audit_raw, 2), SCORE_CAP)
    return q2(intake), q2(audit)


def _days(count):
    from datetime import timedelta

    return timedelta(days=count)


# ------------------------------------------------------------- billing roll-up
def volume_discount_rate(pre_discount_total_cents):
    amount = Decimal(pre_discount_total_cents)
    for low, high, rate in VOLUME_DISCOUNT_TIERS:
        if amount >= low and (high is None or amount <= high):
            return rate
    return Decimal("0.00")


def project_billing_total(stage_cost_subtotal_cents, adr_cost_cents,
                          conform_fee_total_cents, license_fee_accrued_cents,
                          turnaround_class):
    """The nine pinned steps of PRD §3.8."""
    pre = (int(stage_cost_subtotal_cents) + int(adr_cost_cents)
           + int(conform_fee_total_cents) + int(license_fee_accrued_cents))
    rate = volume_discount_rate(pre)
    discount = money(Decimal(pre) * rate)
    discounted_base = pre - discount
    surcharge = money(Decimal(discounted_base) * RUSH_SURCHARGE_PCT[turnaround_class])
    total = discounted_base + surcharge
    return {
        "pre_discount_total_cents": pre,
        "volume_discount_cents": discount,
        "discounted_base_cents": discounted_base,
        "rush_surcharge_cents": surcharge,
        "billing_total_cents": total,
    }
