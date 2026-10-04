"""Calculation rules (§1.3 of the scaffold, §2.7 and §3 of the PRD).

Every money figure is an integer number of cents.  Where a computed figure does
not divide evenly it is rounded half up, and the two ordering rules the PRD
makes normative are honoured here explicitly:

  * a ceiling expressed as the smaller of two figures is taken after each arm
    has itself been rounded (`guarantee_ceiling`), never before;
  * per-screening credits are rounded individually and only the rounded values
    are summed (`makegood_credit`), never the raw products.
"""
from decimal import Decimal

from core import (
    D,
    add_hours,
    floor_days,
    floor_int,
    now,
    rhu_int,
)

# --- guarantee_floor_derivation constants ----------------------------------
BASE_RATE_CENTS = {"A": 45000, "B": 35000, "C": 25000}
VOLUME_TIER_1_MAX = 50
VOLUME_TIER_2_MAX = 150
VOLUME_TIER_3_MAX = 400
VOLUME_FACTOR_1 = Decimal("1.00")
VOLUME_FACTOR_2 = Decimal("0.90")
VOLUME_FACTOR_3 = Decimal("0.80")
VOLUME_FACTOR_4 = Decimal("0.70")
ADMISSION_MULTIPLE = 12

# --- presale_threshold_assessment constants --------------------------------
CHECKPOINT_OFFSET_DAYS = 14

# --- delivery_lead_verification constants ----------------------------------
LEAD_HOURS_SATELLITE = 48
LEAD_HOURS_FILE = 24
LEAD_HOURS_BOTH = 48
LIVE_EVENT_SURCHARGE_HOURS = 12

# --- makegood_credit_derivation constants ----------------------------------
RATE_TIER_1_MIN_MINUTES = 90
RATE_TIER_2_MIN_MINUTES = 30
RATE_TIER_3_MIN_MINUTES = 5
RATE_TIER_1 = Decimal("1.00")
RATE_TIER_2 = Decimal("0.60")
RATE_TIER_3 = Decimal("0.25")
RATE_TIER_4 = Decimal("0.00")
CAP_FRACTION = Decimal("0.5")

# --- settlement_split constants --------------------------------------------
ALLOCATION_ORDER_TERMS = ("NET_30", "NET_60")
NET_OFF_TOP_TERMS = ("GROSS_ON_GROSS", "FOUR_WALL")
GATE_RATIO_MAX_TIER = Decimal("1.5")
GATE_RATIO_MID_TIER = Decimal("1.0")
PAYMENT_RATE_TIER_1 = Decimal("1.00")
PAYMENT_RATE_TIER_2 = Decimal("0.75")
PAYMENT_RATE_TIER_3 = Decimal("0.50")

# --- encore_price_derivation constants -------------------------------------
ABSOLUTE_DISCOUNT_CENTS = 500
RELATIVE_DISCOUNT = Decimal("0.55")
ENCORE_ATTENDANCE_MIN = Decimal("0.5")


def ticket_price_cents(title, distributor):
    """The admission price: the title's own price, else the distributor default."""
    if title is not None and title.get("ticket_price_cents") is not None:
        return int(title["ticket_price_cents"])
    return int(distributor["ticket_price_default_cents"])


def volume_factor(total_committed):
    """One factor, selected from the BOOKING-LEVEL total, applied to every screen."""
    if total_committed <= VOLUME_TIER_1_MAX:
        return VOLUME_FACTOR_1
    if total_committed <= VOLUME_TIER_2_MAX:
        return VOLUME_FACTOR_2
    if total_committed <= VOLUME_TIER_3_MAX:
        return VOLUME_FACTOR_3
    return VOLUME_FACTOR_4


def guarantee_ceiling(booking, circuit, title, distributor):
    """guarantee_floor_derivation -- the largest guarantee allowed for this booking.

    Dual variant: while the booking is DRAFT / PENDING_APPROVAL / COUNTERED /
    APPROVED the provisional (uncapped) variant is live; once it reaches ON_SALE,
    ON_HOLD, CONFIRMED or SETTLED the aggregate-capped variant takes over.
    """
    total_committed = booking["committed_screens_total"]
    if total_committed <= 0:
        return 0
    if total_committed > title["max_screen_commitment"]:
        return 0

    rating = circuit["credit_rating"]
    base = BASE_RATE_CENTS.get(rating, 0)
    per_screen_loaded = rhu_int(D(total_committed) * D(base) * volume_factor(total_committed))

    capped_variant = booking["status"] in ("ON_SALE", "ON_HOLD", "CONFIRMED", "SETTLED")
    if not capped_variant:
        return per_screen_loaded

    price = ticket_price_cents(title, distributor)
    aggregate_cap = price * total_committed * ADMISSION_MULTIPLE
    return min(per_screen_loaded, aggregate_cap)


def guarantee_allocation(booking, lines):
    """guarantee_allocation -- waterfall split of the guarantee across COMMITTED lines.

    Total order: expected_attendance DESC, created_at ASC, theater_id ASC.
    Truncated pro-rata shares, then the residual distributed one cent at a time,
    walking the ordered lines and wrapping back to the head.
    """
    eligible = [ln for ln in lines if ln["exhibit_state"] == "COMMITTED"]
    for ln in lines:
        if ln["exhibit_state"] != "COMMITTED":
            ln["guarantee_applied_cents"] = 0
    if not eligible:
        return

    order = sorted(
        eligible,
        key=lambda ln: (
            -int(ln["expected_attendance"]),
            ln["created_at"],
            ln["_seq"],
            ln["theater_id"],
        ),
    )

    guarantee = int(booking["guarantee_cents"])
    total_expected = sum(int(ln["expected_attendance"]) for ln in order)

    if total_expected == 0:
        share = floor_int(D(guarantee) / D(len(order)))
        shares = [share] * len(order)
    else:
        shares = [
            floor_int(D(guarantee) * D(int(ln["expected_attendance"])) / D(total_expected))
            for ln in order
        ]

    remainder = guarantee - sum(shares)
    i = 0
    while remainder > 0:
        shares[i % len(order)] += 1
        remainder -= 1
        i += 1

    for ln, share in zip(order, shares):
        ln["guarantee_applied_cents"] = int(share)


def presale_passes(booking):
    """presale_threshold_assessment -- the comparison is at-or-above."""
    return int(booking["pre_sale_tickets"]) >= int(booking["pre_sale_threshold"])


def checkpoint_instant(booking):
    return booking["on_sale_at"] + _days(CHECKPOINT_OFFSET_DAYS)


def _days(count):
    from datetime import timedelta

    return timedelta(days=int(count))


def delivery_lead_ok(delivery, title, scheduled_screenings):
    """delivery_lead_verification -- exact equality passes, no screening fails."""
    lead_hours = {
        "SATELLITE": LEAD_HOURS_SATELLITE,
        "FILE": LEAD_HOURS_FILE,
        "BOTH": LEAD_HOURS_BOTH,
    }.get(delivery["delivery_method"], LEAD_HOURS_FILE)
    if title.get("is_live"):
        lead_hours += LIVE_EVENT_SURCHARGE_HOURS

    starts = [s["starts_at"] for s in scheduled_screenings if s["state"] == "SCHEDULED"]
    if not starts:
        return False
    earliest_start = min(starts)
    return add_hours(delivery["scheduled_delivery_utc"], lead_hours) <= earliest_start


def key_aligned(key, screening):
    """key_window_alignment -- both boundaries inclusive."""
    return (
        key["not_valid_before_utc"] <= screening["starts_at"]
        and key["not_valid_after_utc"] >= screening["ends_at"]
    )


def validity_state(key, instant=None):
    """key_window_alignment -- derived purely from the instant and the key interval."""
    instant = instant or now()
    if instant < key["not_valid_before_utc"]:
        return "NOT_YET_VALID"
    if instant <= key["not_valid_after_utc"]:
        return "VALID"
    return "EXPIRED"


def makegood_rate(outage_minutes):
    if outage_minutes >= RATE_TIER_1_MIN_MINUTES:
        return RATE_TIER_1
    if outage_minutes >= RATE_TIER_2_MIN_MINUTES:
        return RATE_TIER_2
    if outage_minutes >= RATE_TIER_3_MIN_MINUTES:
        return RATE_TIER_3
    return RATE_TIER_4


def per_screening_credit(outage_minutes, price_cents, attendance, duration_minutes, seats_total):
    """One screening's make-good credit, rounded half up to a whole cent."""
    rate = makegood_rate(int(outage_minutes))
    lost_fraction = D(int(outage_minutes)) / D(int(duration_minutes))
    cap_cents = D(int(seats_total)) * D(int(price_cents)) * CAP_FRACTION
    raw = rate * D(int(price_cents)) * D(int(attendance)) * lost_fraction
    return rhu_int(min(raw, cap_cents))


def encore_price(price_cents):
    """encore_price_derivation -- the max() is taken AFTER rounding the relative arm."""
    absolute_arm = int(price_cents) - ABSOLUTE_DISCOUNT_CENTS
    relative_arm = rhu_int(D(int(price_cents)) * RELATIVE_DISCOUNT)
    return max(absolute_arm, relative_arm)


def best_attendance_ratio(lines):
    """The largest sold/expected ratio over COMMITTED lines; None when undefined."""
    ratios = []
    for ln in lines:
        if ln["exhibit_state"] != "COMMITTED":
            continue
        expected = int(ln["expected_attendance"])
        if expected <= 0:
            return None
        ratios.append(D(int(ln["sold_tickets"])) / D(expected))
    if not ratios:
        return None
    return max(ratios)


def settlement_split(settlement, booking, circuit, makegood_credit_cents):
    """settlement_split -- returns (distributor_net_cents, exhibitor_net_cents, drift).

    Evaluation order is normative: read the guarantee, select the payment rate
    from the gross/guarantee gate, compute the covered amount, compute the
    distributor's net, then take the exhibitor's net as the residual.
    """
    gross = int(settlement["gross_box_office_cents"])
    topup = int(settlement["topup_paid_cents"])
    adjustment = int(settlement["adjustment_cents"])
    share = D(booking["revenue_share_pct"])
    guarantee = int(booking["guarantee_cents"])

    # (2) select the payment rate from the gate -- the gate is expressed as a
    # fraction of the guarantee, so it cannot be evaluated before step (1).
    if guarantee > 0:
        gate_ratio = D(gross) / D(guarantee)
    else:
        gate_ratio = D(0)
    if gate_ratio >= GATE_RATIO_MAX_TIER:
        payment_rate = PAYMENT_RATE_TIER_1
    elif gate_ratio >= GATE_RATIO_MID_TIER:
        payment_rate = PAYMENT_RATE_TIER_2
    else:
        payment_rate = PAYMENT_RATE_TIER_3

    terms = circuit["settlement_terms"]
    if terms in NET_OFF_TOP_TERMS:
        net_off_top = True
    elif terms in ALLOCATION_ORDER_TERMS:
        net_off_top = False
    else:
        net_off_top = False

    if net_off_top:
        # The gate's result is discarded by this variant; only the guarantee's
        # role as the gate denominator is retained, which is why amending the
        # guarantee leaves this net untouched.
        distributor_net = (
            rhu_int(D(gross + topup) * share) + adjustment - int(makegood_credit_cents)
        )
    else:
        covered = min(rhu_int(D(guarantee) * payment_rate), gross)
        residual_cash = gross - covered
        distributor_net = (
            covered
            + rhu_int(D(residual_cash) * share)
            + topup
            + adjustment
            - int(makegood_credit_cents)
        )

    exhibitor_net = gross + topup + adjustment - distributor_net
    drift = (gross + topup + adjustment) - distributor_net - exhibitor_net
    return int(distributor_net), int(exhibitor_net), int(drift)


def bookable_window_days(title):
    """Whole days between rights_start_utc and rights_end_utc."""
    return floor_days(title["rights_end_utc"], title["rights_start_utc"])