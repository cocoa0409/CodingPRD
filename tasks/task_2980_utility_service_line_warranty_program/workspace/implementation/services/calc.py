"""The eleven calculations of PRD 2.7 / section 3, kept free of side effects."""

from decimal import Decimal

import config
import derive
import timeutil
from money import floor_ratio, round_half_up_2dp, round_half_up_ratio

# --------------------------------------------------------------- proration


def earned_premium_cents(monthly_price_cents, term_start, end_exclusive):
    """Sum of per-month prorated shares over the half-open covered interval.

    Each month's share is rounded half up individually before the shares are
    summed - rounding the total instead would drift by a cent or two.
    """
    total = 0
    if end_exclusive <= term_start:
        return 0
    cursor = timeutil.month_start(term_start)
    while cursor < end_exclusive:
        following = timeutil.next_month_start(cursor)
        segment_start = max(term_start, cursor)
        segment_end = min(end_exclusive, following)
        covered_days = (segment_end - segment_start).days
        if covered_days > 0:
            month_days = timeutil.days_in_month(cursor)
            total += round_half_up_ratio(monthly_price_cents * covered_days, month_days)
        cursor = following
    return total


def cancellation_settlement(enrollment, monthly_price_cents, term_start, effective_date):
    """Earned premium, fee, and the refund or credit that settles the policy."""
    earned = earned_premium_cents(monthly_price_cents, term_start, effective_date)
    elapsed_days = timeutil.whole_days_between(term_start, effective_date)
    fee = 0 if elapsed_days < config.CANCELLATION_FEE_FREE_DAYS else config.CANCELLATION_FEE_CENTS
    result = {"earned_premium_cents": earned, "cancellation_fee_cents": fee}
    if enrollment["billing_mode"] == "DIRECT_BILL":
        result["refund_cents"] = enrollment["prepaid_amount_cents"] - earned - fee
        result["credit_cents"] = 0
    else:
        month_days = timeutil.days_in_month(effective_date)
        days_remaining = month_days - effective_date.day + 1
        result["credit_cents"] = round_half_up_ratio(monthly_price_cents * days_remaining, month_days)
        result["refund_cents"] = 0
    return result


# ------------------------------------------------------------ renewal notice


def renewal_change_pct(old_price_cents, new_price_cents):
    """Signed percentage change, rounded half up to two decimal places."""
    delta = Decimal(new_price_cents - old_price_cents) * Decimal(100)
    return round_half_up_2dp(delta / Decimal(old_price_cents))


def required_notice_days(pct):
    for bound, days in config.RENEWAL_NOTICE_TIERS:
        if bound is None or pct <= Decimal(bound):
            return days
    return config.RENEWAL_NOTICE_TIERS[-1][1]


# ------------------------------------------------------- contractor selection


def selection_score(contractor, urgency):
    weights = config.WEIGHTS_EMERGENCY if urgency == "EMERGENCY" else config.WEIGHTS_STANDARD
    total = (
        Decimal(weights["sla"]) * Decimal(contractor["sla_compliance_pct"])
        + Decimal(weights["headroom"]) * Decimal(derive.capacity_headroom_pct(contractor))
        + Decimal(weights["rate"]) * Decimal(derive.rate_score(contractor))
    )
    return round_half_up_2dp(total)


def visit_window_end(window_start, line_type):
    return timeutil.add_minutes(window_start, config.VISIT_MINUTES[line_type])


def windows_conflict(candidate_start, candidate_end, existing_start, existing_end):
    """Overlap test with the mandatory 45-minute travel buffer on both sides."""
    buffer_minutes = config.DISPATCH_BUFFER_MINUTES
    return candidate_start < timeutil.add_minutes(existing_end, buffer_minutes) and existing_start < timeutil.add_minutes(
        candidate_end, buffer_minutes
    )


def estimated_benefit_cents(pool_cents, line_type, hourly_rate_cents):
    estimate = config.ESTIMATE_HOURS[line_type] * hourly_rate_cents + config.ESTIMATE_MATERIALS_CENTS[line_type]
    return min(pool_cents, estimate)


# ------------------------------------------------------------ benefit waterfall


def settle_invoice(product, pool_cents, labor_cents, materials_cents, permit_fee_cents, restoration_cents, restoration_scope):
    """Fill LABOR, MATERIALS, PERMIT then RESTORATION until the pool runs dry."""
    covered_restoration = min(restoration_cents, config.RESTORATION_ALLOWANCE_CENTS[restoration_scope])
    covered_permit = permit_fee_cents if product.get("permit_covered") else 0
    remaining = max(0, pool_cents)
    allocations = {}
    for bucket, amount in (
        ("LABOR", labor_cents),
        ("MATERIALS", materials_cents),
        ("PERMIT", covered_permit),
        ("RESTORATION", covered_restoration),
    ):
        allocated = min(remaining, max(0, amount))
        allocations[bucket] = allocated
        remaining -= allocated
    benefit_paid = sum(allocations.values())
    invoice_total = labor_cents + materials_cents + permit_fee_cents + restoration_cents
    return {
        "allocations": allocations,
        "benefit_paid_cents": benefit_paid,
        "invoice_total_cents": invoice_total,
        "customer_responsibility_cents": invoice_total - benefit_paid,
    }


# ------------------------------------------------------------------- misc


def response_minutes(assigned_at, responded_at):
    return timeutil.floor_minutes_between(assigned_at, responded_at)


def complaint_response_days(regulator, cited_claim):
    base = config.COMPLAINT_BASE_DAYS[regulator]
    if cited_claim is not None and cited_claim["status"] in config.COMPLAINT_EXPEDITING_CLAIM_STATUSES:
        return min(base, config.COMPLAINT_EXPEDITED_DAYS)
    return base


def capacity_headroom_pct(maximum, open_count):
    return floor_ratio(100 * (maximum - open_count), maximum)
