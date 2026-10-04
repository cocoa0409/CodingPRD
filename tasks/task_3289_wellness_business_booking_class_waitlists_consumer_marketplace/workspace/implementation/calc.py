"""Pure calculation rules (SCAFFOLD §1.3).

Every function here is side-effect free: it takes entity dicts (or plain
numbers) and returns integer cents / credits / posture strings, exactly as the
scaffold's formula blocks describe.  The rounding direction travels with each
calculation: floor for the channel price and discount paths, ceil for the
marketplace gross-up.
"""

from core import (
    CHANNEL_BONUS_THRESHOLD_CENTS,
    DAYS_PER_CYCLE,
    INSTRUCTOR_DEPUTY_COMMISSION_BPS,
    INSTRUCTOR_TEACH_COMMISSION_BPS,
    MARKETPLACE_CHANNEL_BONUS_BPS,
    OFF_PEAK_BPS,
    PAYROLL_ACCRUAL_CEILING_CENTS,
    PAYROLL_TIER_MULTIPLIER,
    TIER_PRICE_BPS,
    TIER_PRICE_FLOOR_CENTS,
    UNUSED_CREDIT_RETURN_DENOMINATOR,
    ceil_div,
)


# ---------------------------------------------------------------------------
# Seat availability / fullness posture
# ---------------------------------------------------------------------------


def promo_reserved(session):
    if session.get("promo_offer_state") == "ACTIVE":
        return session.get("promo_seats_allocated", 0) - session.get("promo_seats_used", 0)
    return 0


def fullness_posture(session, marketplace_basis=False):
    if session.get("status") == "CANCELLED_BY_STUDIO":
        return "CANCELLED"
    capacity = session.get("capacity", 0)
    if marketplace_basis:
        capacity = capacity - promo_reserved(session)
    occupied = session.get("seats_taken", 0) + session.get("seats_held", 0)
    open_seats = capacity - occupied
    studio_seats = max(0, open_seats - promo_reserved(session))
    if open_seats <= 0:
        return "FULL"
    if studio_seats <= 0:
        return "WAITLIST_ONLY"
    return "OPEN"


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------


def off_peak_bps(is_off_peak):
    return OFF_PEAK_BPS if is_off_peak else 10000


def session_list_price(base_price_cents, is_off_peak, tier):
    raw = (base_price_cents * off_peak_bps(is_off_peak) * TIER_PRICE_BPS[tier]) // 100000000
    return max(raw, TIER_PRICE_FLOOR_CENTS[tier])


def marketplace_price(list_price_cents, commission_bps):
    return ceil_div(list_price_cents * 10000, 10000 - commission_bps)


def promo_price(list_price_cents, discount_bps):
    return (list_price_cents * (10000 - discount_bps)) // 10000


def effective_seat_price(session, channel, commission_bps):
    """STUDIO floor path, MARKETPLACE ceil gross-up path."""
    if channel == "MARKETPLACE":
        return marketplace_price(session.get("list_price_cents", 0), commission_bps)
    return promo_price(session.get("list_price_cents", 0), session.get("promo_discount_bps", 0))


def booking_gross(booking, session, commission_bps, attended):
    """channel_total_cents for a booking, under the booked or attended variant."""
    if booking.get("payment_source") == "BENEFIT_NETWORK":
        return session.get("list_price_cents", 0)
    if not attended and booking.get("payment_source") in ("CLASS_PACK", "MEMBERSHIP"):
        return 0
    return effective_seat_price(session, booking.get("channel", "STUDIO"), commission_bps)


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------


def no_show_fee(prior_strike_count, list_price_cents, payment_source):
    """Strike count is the value BEFORE this no-show is recorded."""
    if prior_strike_count < 2:
        return 0
    if payment_source == "BENEFIT_NETWORK":
        return 0
    multiplier_tenths = 10 + 5 * min(2, prior_strike_count - 1)
    return (list_price_cents * multiplier_tenths) // 10


def cancellation_fee(session, booking, client, late_cancel_count):
    if booking.get("payment_source") == "BENEFIT_NETWORK":
        return 0
    if booking.get("payment_source") == "CLASS_PACK":
        return 0
    if (
        booking.get("payment_source") == "MEMBERSHIP"
        and late_cancel_count < 3
    ):
        return 0
    return session.get("list_price_cents", 0)


# ---------------------------------------------------------------------------
# Commission
# ---------------------------------------------------------------------------


def commission_cents(base_cents, rate_bps, tier, bonus_eligible, payroll_cap_mode):
    commission = (base_cents * rate_bps) // 10000
    ceiling = int(PAYROLL_ACCRUAL_CEILING_CENTS * PAYROLL_TIER_MULTIPLIER[tier])
    bonus = (base_cents * MARKETPLACE_CHANNEL_BONUS_BPS) // 10000
    if bonus_eligible and bonus >= CHANNEL_BONUS_THRESHOLD_CENTS:
        if payroll_cap_mode == "BONUS_OUTSIDE_CAP":
            commission = min(commission, ceiling)
            commission = commission + bonus
        else:
            commission = commission + bonus
            commission = min(commission, ceiling)
    else:
        commission = min(commission, ceiling)
    return commission


def teaching_rate(staff, tier):
    rate = staff.get("commission_rate_bps", 0)
    if rate and rate > 0:
        return rate
    return INSTRUCTOR_TEACH_COMMISSION_BPS[tier]


def deputy_rate(tier):
    return INSTRUCTOR_DEPUTY_COMMISSION_BPS[tier]


# ---------------------------------------------------------------------------
# Marketplace platform commission
# ---------------------------------------------------------------------------


def per_booking_commission(commission_base_cents, commission_bps):
    return (commission_base_cents * commission_bps) // 10000


def settlement_commission(bookings, commission_bps):
    """Running-accumulator walk: floor the accumulator, not each row."""
    running_raw_numer = 0  # sum of base*bps, denominator 10000
    running_floor = 0
    for booking in bookings:
        running_raw_numer += booking.get("commission_base_cents", 0) * commission_bps
        running_floor = running_raw_numer // 10000
    return running_floor, running_raw_numer // 10000


def settlement_pair(bookings, commission_bps):
    """Return (accumulator_floor, sum_of_individual_floors).

    PRD §3.7: the settlement form accumulates a running *un-rounded* total of
    each booking's raw commission and floors the running total as it goes.  The
    accumulator therefore carries the raw numerator across rows; flooring it
    between rows would discard each row's fraction to the next row's total.
    """
    raw_numerator = 0
    per_row = 0
    for booking in bookings:
        raw_numerator += booking.get("commission_base_cents", 0) * commission_bps
        per_row += per_booking_commission(
            booking.get("commission_base_cents", 0), commission_bps
        )
    return raw_numerator // 10000, per_row


# ---------------------------------------------------------------------------
# Benefit networks
# ---------------------------------------------------------------------------


def benefit_claim_amount(network, list_price_cents):
    if network.get("reimburse_full_list_price"):
        return list_price_cents
    return min(network.get("per_visit_allowance_cents", 0), list_price_cents)


# ---------------------------------------------------------------------------
# Membership freeze proration
# ---------------------------------------------------------------------------


def freeze_proration(monthly_fee_cents, freeze_days, planned_freeze_days, max_days_per_cycle):
    """Returns (prorated_fee_cents, counted_days)."""
    counted = freeze_days
    if counted > planned_freeze_days:
        counted = max(0, planned_freeze_days - 5)
    capped = min(counted, max_days_per_cycle)
    factor_num = DAYS_PER_CYCLE - capped
    prorated = (monthly_fee_cents * factor_num) // DAYS_PER_CYCLE
    return prorated, counted


# ---------------------------------------------------------------------------
# Pack credit expiry
# ---------------------------------------------------------------------------


def credits_returned_to_studio(credits_at_expiry):
    return credits_at_expiry + credits_at_expiry // UNUSED_CREDIT_RETURN_DENOMINATOR


# ---------------------------------------------------------------------------
# Instructor substitution priority ladder
# ---------------------------------------------------------------------------


def overlapping_taught_minutes(instructor_id, target_session, sessions):
    total = 0
    start = target_session.get("start_at")
    end = target_session.get("end_at")
    for other in sessions:
        if other.get("instructor_staff_id") != instructor_id:
            continue
        if other.get("id") == target_session.get("id"):
            continue
        if other.get("status") not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        o_start = other.get("start_at")
        o_end = other.get("end_at")
        if o_start is None or o_end is None:
            continue
        if o_start < end and start < o_end:
            total += int((o_end - o_start).total_seconds() // 60)
    return total


def substitution_score(instructor, session, tier, overlap_minutes):
    template_match = (
        1
        if session.get("class_template_id")
        in (instructor.get("substitute_class_template_ids") or [])
        else 0
    )
    level_fit = 1.0 if instructor.get("status") == "ACTIVE" else 0.5
    overlap_penalty = 1.0 - min(1.0, overlap_minutes / 60.0)
    history = 1.0 if instructor.get("substitution_count", 0) > 0 else 0.0
    early = 1.0 if instructor.get("status") in ("ACTIVE", "SUBSTITUTE_ONLY") else 0.0
    distance = (
        1.0
        if instructor.get("primary_class_template_id") == session.get("class_template_id")
        else 0.0
    )
    rating = 1.0

    if tier == "STARTER":
        # legacy_flat_weights: template match and overlap penalty are fused.
        score = (
            30.0 * template_match * overlap_penalty
            + 20.0 * level_fit
            + 10.0 * history
            + 5.0 * early
            + 3.0 * distance
            + 2.0 * rating
        )
    else:
        score = (
            30.0 * template_match
            + 20.0 * level_fit
            + 15.0 * overlap_penalty
            + 10.0 * history
            + 5.0 * early
            + 3.0 * distance
            + 2.0 * rating
        )
    # one decimal place, halves rounded up
    return int(score * 10 + 0.5) / 10.0