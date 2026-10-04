"""Calculation rules (scaffold section 1.3 / PRD sections 2.9, 3.5-3.8).

Every monetary step floors independently to a whole cent; no step re-rounds a
value an earlier step produced. Floor is truncation toward the lower integer.
"""

import math

from core import clock, constants as C
from core import store


def floor_cents(value):
    """Floor truncation to a whole cent, tolerant of IEEE-754 representation error."""
    return int(math.floor(value + 1e-9))


# ---------------------------------------------------------------------------
# enrollment_discounted_price_cents — evaluation order pinned
# ---------------------------------------------------------------------------
def enrollment_price(listing, learner, coupon_code):
    list_price = listing["list_price_cents"]
    sub_pct = C.SUB_DISCOUNT.get(learner.get("subscription_tier") or "NONE", 0.00)
    step1 = floor_cents(list_price * sub_pct)
    after_subscription = list_price - step1
    step3 = 0
    if coupon_code:
        coupon = C.CATALOG_COUPONS[coupon_code]
        if coupon["type"] == "PERCENT":
            step3 = floor_cents(after_subscription * coupon["value"])
        else:
            step3 = int(coupon["value"])
    price = max(0, list_price - step1 - step3)
    return {
        "subscription_discount_cents": step1,
        "coupon_discount_cents": step3,
        "discounted_price_cents": price,
    }


# ---------------------------------------------------------------------------
# refund_amount_cents — TIMING selector (the applied one)
# ---------------------------------------------------------------------------
def refund_tier(section, listing, current, learner_fault):
    hours = int(math.floor((section["start_utc_dt"] - current).total_seconds() / 3600.0))
    fmt = listing["format"]
    if hours >= C.REFUND_FULL_CUTOFF_HOURS[fmt]:
        tier = "FULL"
    elif learner_fault and hours >= C.REFUND_HALF_CUTOFF_HOURS[fmt]:
        tier = "PARTIAL_HALF"
    else:
        tier = "NONE"
    if section.get("timezone") == C.SPECIAL_REFUND_TIMEZONE and tier == "PARTIAL_HALF":
        tier = "NONE"
    return tier


def refund_cents_for(tier, discounted_price_cents):
    if tier == "NONE":
        return 0
    if tier == "PARTIAL_HALF":
        return floor_cents(discounted_price_cents * C.REFUND_PARTIAL_RATE)
    return discounted_price_cents


# ---------------------------------------------------------------------------
# section_seat_occupancy — aggregation with an explicit status filter
# ---------------------------------------------------------------------------
SEAT_COUNTING_STATUSES = ("CONFIRMED", "RESERVED")


def enrollments_of_section(section_id):
    return [e for e in store.all_of("enrollments") if e["section_id"] == section_id]


def occupancy(section):
    rows = enrollments_of_section(section["id"])
    enrolled = len([e for e in rows if e["status"] == "CONFIRMED"])
    reserved = len([e for e in rows if e["status"] == "RESERVED"])
    remaining = section["capacity"] - enrolled - reserved
    if remaining < 0:
        remaining = 0
    return {
        "enrolled_count": enrolled,
        "reserved_count": reserved,
        "seats_remaining": remaining,
        # The floor counts seats taken (confirmed plus reserved). Confirmation itself
        # requires the section to have reached MIN_ENROLLMENT_MET, so a confirmed-only
        # count could never reach the floor and the section could never be declared met.
        "enrollment_min_met": (enrolled + reserved) >= section["min_learners"],
        "settled": reserved == 0,
    }


def section_discounted_total(section_id):
    return sum(
        e["discounted_price_cents"]
        for e in enrollments_of_section(section_id)
        if e["status"] == "CONFIRMED"
    )


def listing_of_section(section):
    return store.find("listings", section["class_listing_id"])


def teacher_of_listing(listing):
    if listing is None:
        return None
    return store.find("teachers", listing["teacher_id"])


# ---------------------------------------------------------------------------
# expected_payout_gross_cents — ACCRUAL selector (the applied one)
# ---------------------------------------------------------------------------
def accrual_sections(teacher_id, period_start, period_end):
    """Sections owned by the teacher with outcome null/HELD in [start, end)."""
    picked = []
    for section in store.all_of("sections"):
        listing = listing_of_section(section)
        if listing is None or listing["teacher_id"] != teacher_id:
            continue
        if section.get("outcome") not in (None, "HELD"):
            continue
        start = section["start_utc_dt"]
        if start >= period_start and start < period_end:
            picked.append(section)
    return picked


def gross_and_fee(teacher, period_start, period_end):
    sections = accrual_sections(teacher["id"], period_start, period_end)
    gross = sum(section_discounted_total(s["id"]) for s in sections)
    rate = fee_rate_for(teacher, gross, sections)
    fee = sum(floor_cents(section_discounted_total(s["id"]) * rate) for s in sections)
    return {
        "sections": sections,
        "gross_earnings_cents": gross,
        "fee_rate_applied": rate,
        "platform_fee_cents": fee,
        "net_payout_cents": gross - fee,
    }


def band_rate(gross):
    rate = C.FEE_BANDS[0]["rate"]
    for band in C.FEE_BANDS:
        if gross >= band["min_gross"]:
            rate = band["rate"]
    return rate


def posted_lifetime_gross(teacher_id):
    total = 0
    for payout in store.all_of("payouts"):
        if payout["teacher_id"] != teacher_id:
            continue
        if payout["status"] in ("SENT", "PAID"):
            total += payout["gross_earnings_cents"]
    return total


def fee_rate_for(teacher, gross, sections):
    rate = band_rate(gross)
    formats = {listing_of_section(s)["format"] for s in sections if listing_of_section(s)}
    if formats:
        rate += min(C.FORMAT_ADJUSTMENT[f] for f in formats)
    if posted_lifetime_gross(teacher["id"]) >= C.VOLUME_DISCOUNT_THRESHOLD_CENTS:
        rate -= C.VOLUME_DISCOUNT
    if rate < C.FEE_RATE_FLOOR:
        rate = C.FEE_RATE_FLOOR
    return rate


# ---------------------------------------------------------------------------
# payout_approval_cap — waterfall allocation
# ---------------------------------------------------------------------------
def approval_cap_figures(payout):
    already = 0
    for other in store.all_of("payouts"):
        if other["id"] == payout["id"]:
            continue
        if other["teacher_id"] != payout["teacher_id"]:
            continue
        if other["status"] in ("SENT", "PAID"):
            already += payout_net_after_refunds(other)
    headroom = C.PAYOUT_APPROVAL_CAP_CENTS - already
    if headroom < 0:
        headroom = 0
    denominator = payout_net_after_refunds(payout) + already
    if denominator < 1:
        denominator = 1
    factor = headroom / float(denominator)
    if factor > 1.0:
        factor = 1.0
    return {"already_approved_sent_cents": already, "payout_proration_factor": factor}


def payout_net_after_refunds(payout):
    return (
        payout["gross_earnings_cents"]
        - payout["platform_fee_cents"]
        - payout["platform_fee_reversed_cents"]
    )


# ---------------------------------------------------------------------------
# teacher_risk_score — weighted scoring, both readings maintained
# ---------------------------------------------------------------------------
def reports_of_teacher(teacher_id):
    return [r for r in store.all_of("reports") if r["teacher_id"] == teacher_id]


def severity_weight(category, severity):
    return C.CATEGORY_WEIGHT[category] + C.SEVERITY_POINTS[severity]


def risk_scores(teacher_id):
    rows = reports_of_teacher(teacher_id)
    open_score = sum(r["severity_weight"] for r in rows if r["status"] == "OPEN")
    upheld_score = sum(
        r["severity_weight"] for r in rows if r.get("disposition") in ("WARNING", "MORE_SEVERE")
    )
    open_count = len([r for r in rows if r["status"] not in ("CLOSED", "RESOLVED")])
    return {
        "open_report_count": open_count,
        "open_report_risk_score": open_score,
        "upheld_report_risk_score": upheld_score,
        "actionable_risk_score": max(open_score, upheld_score),
    }


# ---------------------------------------------------------------------------
# tax_document_status — pure function of lifetime net earnings
# ---------------------------------------------------------------------------
def tax_document_status(lifetime_net_earnings_cents):
    if lifetime_net_earnings_cents <= C.TAX_DOC_REQUIRED_CENTS:
        return "ON_FILE"
    if lifetime_net_earnings_cents <= C.TAX_DOC_VALIDITY_CEILING_CENTS:
        return "REQUIRED_UPDATE"
    return "EXPIRED"


def lifetime_net_earnings(teacher_id):
    return sum(
        p["net_payout_cents"]
        for p in store.all_of("payouts")
        if p["teacher_id"] == teacher_id and p["status"] != "VOIDED"
    )


def unpaid_earnings(teacher_id):
    return sum(
        p["net_payout_cents"]
        for p in store.all_of("payouts")
        if p["teacher_id"] == teacher_id and p["status"] not in ("PAID", "VOIDED")
    )


# ---------------------------------------------------------------------------
# application helpers
# ---------------------------------------------------------------------------
def screening_is_stale(application):
    stamp = application.get("screening_completed_period_index")
    if stamp is None:
        return False
    return (clock.period() - stamp) > C.SCREENING_VALIDITY_PERIODS


def eligible_for_appeal(application):
    return (
        application["status"] == "REJECTED"
        and application["revision_count"] < C.APPLICATION_MAX_REVISIONS
    )
