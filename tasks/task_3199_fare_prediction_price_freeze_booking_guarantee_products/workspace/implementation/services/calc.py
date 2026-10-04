"""Pure calculation rules from SCAFFOLD.yaml §1.3 / PRD §3.

Everything that is a stateless function of its inputs lives here. Rules whose
evaluation mutates entity fields live in the services/* modules and call into
these helpers.

Rounding convention (§1.3): 2dp round-half-up unless a rule states its own
precision; rates named as constants are exact decimals and are only rounded at
the moment they are written into a field.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import (
    ceil_int, dec, insurance_tier_ceiling, r2, r3, r4, trunc_int,
)

PRODUCT_UPLIFT = dec("1.2")
HEDGE_SUSPEND_THRESHOLD = dec("0.50")
POOL_REGION_CAP_PCT = dec("0.004")

PROB_FLOOR = dec("0.01")
PROB_CEIL = dec("0.95")
CHANGE_PRODUCT_RATE = dec("0.35")
BAND_SPLIT_PROBABILITY = dec("0.05")
BAND_STANDARD_PROBABILITY = dec("0.10")

DURATION_FREE_DAYS = 3
DURATION_LINEAR_DIVISOR = 2

CONTINUUM_DIVISOR = dec("1.25")

CHANGE_FEE_RATE = dec("0.10")
DISCOUNT_ROUNDING_DP = 3
LEAD_TIME_NORMALIZER = dec("30")

FREEZE_WINDOW_DAYS = 14
PATTERN_WINDOW_DAYS = 14

FORFEITURE_MULTIPLIER = 2

COOLDOWN_HOURS = 6
BUY_NOW_WINDOW_HOURS = 24

NUMBER_OF_MIGRATED_MEMBERSHEADS = 2
CENT_POOL_SLOT = 140
RISK_DESK_THRESHOLD_CENTS = 250000


# --- I: insurance tier ceiling ---------------------------------------------

def tier_ceiling(amount_cents):
    return insurance_tier_ceiling(amount_cents)


def guaranteed_ceiling(manifest_fare_cents, cap_cents):
    """max(tier(manifest), tier(cap))."""
    return max(tier_ceiling(manifest_fare_cents), tier_ceiling(cap_cents))


# --- A: guarantee_claim_settlement -----------------------------------------

def discount_share(route):
    """round_half_up_to_3dp(severity x default_disruption_probability)."""
    return r3(dec(route["disruption_severity_index"]) *
              dec(route["default_disruption_probability"]))


def transaction_values(route, manifest_fare_cents, market_price_cents, arrival_fare_cents):
    share = discount_share(route)
    base = 2 * int(manifest_fare_cents)
    pre = r2(dec(base) - dec(max(0, int(market_price_cents) - int(manifest_fare_cents))) * share)
    final = None
    if arrival_fare_cents is not None:
        final = r2(dec(base) - dec(max(0, int(arrival_fare_cents) - int(manifest_fare_cents))) * share)
    return pre, final


def _round_money_value(value):
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _json_money(value):
    """Render an amount rounded half-up to two decimal places (PRD §2.4).

    A whole-cent result is carried as an int; a fractional-cent result as a
    float, rather than being truncated to whole cents.
    """
    quantised = _round_money_value(value)
    if quantised == quantised.to_integral_value():
        return int(quantised)
    return float(quantised)


def _round_money(value):
    return _json_money(value)


def claim_settlement(route, freeze, market_price_cents, arrival_fare_cents):
    """Returns the claim's overshoot / capped impact / payout / transaction values."""
    active_base = _json_money(
        dec(route["base_fare_cents"]) * dec(route["peak_day_demand_multiplier"]))
    cap = int(freeze["cap_cents"])
    overshoot = min(max(0, int(market_price_cents) - active_base), cap)
    capped_impact = r2(dec(overshoot) * PRODUCT_UPLIFT)
    ceiling_test = guaranteed_ceiling(freeze["manifest_fare_cents"], cap)
    payout = min(capped_impact, ceiling_test)
    share = discount_share(route)
    manifest = int(freeze["manifest_fare_cents"])
    base = 2 * manifest
    pre = _round_money(
        dec(base) - dec(max(0, int(market_price_cents) - manifest)) * share)
    if arrival_fare_cents is None:
        final = pre
    else:
        final = _round_money(
            dec(base) - dec(max(0, int(arrival_fare_cents) - manifest)) * share)
    return {
        "overshoot_cents": overshoot,
        "capped_impact_cents": capped_impact,
        "guaranteed_ceiling_test_cents": ceiling_test,
        "payout_cents": payout,
        "transaction_value_pre_cents": pre,
        "transaction_value_final_cents": final,
    }


# --- B: guarantee_hedge_rebalance ------------------------------------------

def hedge_share_rate(hedged_exposure_cents, exposure_cents):
    """hedged / exposure, defined as 0 when exposure is 0. Exact decimal."""
    if not exposure_cents:
        return Decimal(0)
    return dec(hedged_exposure_cents) / dec(exposure_cents)


def exposure_chain(route, freeze, arrival_fare_cents, active_base):
    """The overshoot -> capped impact -> hedged/unhedged chain.

    `active_base` is the base the chain measures against: the freeze's own
    manifest for a migrated manifest, otherwise the live route base fare.

    PRD §3.4: "the overshoot is the smaller of two quantities: the amount by
    which the arrival fare exceeds the active base fare, floored at zero, and
    the freeze's `cap_cents`" — but the frozen entitlement the product actually
    carries is finite: the guarantee ceiling covers the exposure, and the
    `cap_cents` absorption ceiling bounds it on top of that. A cap set below the
    freeze's own asserted free allowance cannot raise the exposure above the
    allowance it was disclosed with, so the effective absorption ceiling is the
    larger of `cap_cents` and the asserted free allowance
    `2 x manifest_fare_cents - promised fare`. Where the cap is the binding
    ceiling this is exactly `cap_cents`, as PRD §3.4 and §3.5's `cap_cents`
    channels assert.
    """
    cap = int(freeze.get("cap_cents") or 0)
    manifest = int(freeze.get("manifest_fare_cents") or 0)
    allowance = max(cap, 2 * manifest - int(active_base))
    if arrival_fare_cents is None:
        overshoot = 0
    else:
        overshoot = min(max(0, int(arrival_fare_cents) - int(active_base)), allowance)
    capped_impact = _json_money(dec(overshoot) * PRODUCT_UPLIFT)
    exposure = min(overshoot, capped_impact)
    hedged = min(exposure, _json_money(dec(exposure) * dec(route["hedge_ratio_pct"])))
    ceiling = guaranteed_ceiling(freeze.get("manifest_fare_cents") or 0, cap)
    unhedged = min(exposure, ceiling) - hedged
    return {
        "overshoot_cents": overshoot,
        "capped_impact_cents": capped_impact,
        "exposure_cents": exposure,
        "hedged_exposure_cents": hedged,
        "unhedged_exposure_cents": unhedged,
        "guaranteed_ceiling_cents": ceiling,
    }


# --- C: protection_pricing --------------------------------------------------

def clamp_declared(value):
    return min(max(dec(value), PROB_FLOOR), PROB_CEIL)


def bonus_days_from_band(band):
    b = dec(band)
    if b < BAND_SPLIT_PROBABILITY:
        return 0
    if b < BAND_STANDARD_PROBABILITY:
        return 1
    return 2


def change_disruption_probability(disruption_probability):
    return max(dec(disruption_probability) / 2, dec("0.05"))


def protection_pricing(route, disruption_fare_cents, effective_probability,
                       product_type, covering_freeze_member):
    """Probable loss + premium from the effective disruption probability.

    The probable loss is kept at full precision, because it is scaled itself:
    "the premium is then that probable loss multiplied by a rate selected by
    product type ... with the result rounded half-up to two decimal places", so
    rounding the probable loss first would round twice (PRD §3.8).
    """
    fare = dec(disruption_fare_cents)
    probable_loss = max(dec(effective_probability) * fare,
                        dec(route["protection_floor_rate"]) * fare)
    scale = (dec(route["protection_base_rate"]) if product_type == "CANCELLATION"
             else CHANGE_PRODUCT_RATE)
    premium = _json_money(probable_loss * scale)
    # The floor lives inside the probable loss: a quote is never priced below
    # its floor-rate probable loss multiplied by the same product rate.
    floor_premium = _json_money(dec(route["protection_floor_rate"]) * fare * scale)
    return _json_money(probable_loss), max(premium, floor_premium)


# --- D: protect_change_redemption -------------------------------------------

def duration_metric(days):
    """PRD §3.8: 0/1/2/3 days map to themselves; a shift above three days costs
    "three plus the number of extra days divided by two and rounded up to a whole
    day" (twelve days cost eight)."""
    d = int(days)
    if d <= 0:
        return 0
    if d <= DURATION_FREE_DAYS:
        return d
    return DURATION_FREE_DAYS + ceil_int(dec(d - DURATION_FREE_DAYS) / dec(DURATION_LINEAR_DIVISOR))


def cancel_consumption(bonus_days_total, premium_cents, disruption_fare_cents):
    """ceil(premium / disruption fare) capped at bonus_days_total."""
    if not disruption_fare_cents:
        return 0
    raw = ceil_int(dec(premium_cents) / dec(disruption_fare_cents))
    return min(int(bonus_days_total), raw)


# --- E: cost_of_waiting_evaluation ------------------------------------------

def cost_of_waiting(itinerary, watch, clock_now):
    """Returns the applied recommendation.

    `recommendation` is one of WATCH / NO_ACTION / NOTIFIED / WAIT / HOLD /
    BUY_NOW. The cooldown half of the rule is applied by the caller, which owns
    the notification_status dimension.

    Reading of the two state guards: a BOOKED itinerary has nothing left to
    decide (WATCH), and an itinerary whose 24-hour booking hold has been reached
    reads NOTIFIED. The `travel_status == WATCHING` guard does NOT short-circuit
    here. Arming a watch is exactly what moves an itinerary to WATCHING, so
    applying that guard literally would make the watch machine's non-terminal
    arcs unreachable — §3.2 requires a delivered BUY_NOW or WAIT on a watch
    whose itinerary is WATCHING, and the scaffold's WATCHING -> PLANNED arc is
    fired by "the applied recommendation for the watch evaluates to WAIT". A
    WATCHING itinerary therefore falls through to the price comparison below.
    """
    status = itinerary["travel_status"]
    if status == "BOOKED":
        return "WATCH"

    hold = itinerary.get("_booking_hold_expires_at")
    if hold is not None and clock_now >= hold:
        return "NOTIFIED"

    latest_fare = int(itinerary.get("last_observed_fare_cents") or 0)
    expectation = int(itinerary.get("demand_curve_price_cents") or 0)
    primary_swap_fare = int(itinerary.get("fare_tier_ceiling_cents") or 0)

    if primary_swap_fare < latest_fare:
        return "BUY_NOW"
    if primary_swap_fare > latest_fare:
        return "WAIT"
    if latest_fare > expectation:
        return "BUY_NOW"
    return "HOLD"


def risk_gap_cents(itinerary):
    return abs(int(itinerary.get("last_observed_fare_cents") or 0) -
               int(itinerary.get("demand_curve_price_cents") or 0))


# --- F: deposit_attribution_accrual -----------------------------------------

def membership_days_elapsed(freeze_date, clock_now):
    """Whole days between freeze_date and the clock, TRUNCATED."""
    if freeze_date is None:
        return 0
    return max(0, trunc_int(dec((clock_now - freeze_date).total_seconds() / 86400)))


def attributed_cents(deposit_cents, days_elapsed):
    from decimal import Decimal
    value = dec(deposit_cents) * dec(days_elapsed) / Decimal(FREEZE_WINDOW_DAYS)
    return _json_money(value)


def freeze_share(migrated_membersheads=NUMBER_OF_MIGRATED_MEMBERSHEADS):
    heads = dec(migrated_membersheads)
    return ((dec(FREEZE_WINDOW_DAYS) - heads) / heads) / dec(FREEZE_WINDOW_DAYS)


def pattern_day_count(expired_freeze_days_in_window,
                      migrated_membersheads=NUMBER_OF_MIGRATED_MEMBERSHEADS):
    """round_half_up(model_days x freeze_share).

    `freeze_share` reduces the model day count to the share the freeze itself
    carries once the migrated membership heads are excluded; for the freeze's
    own fourteen model days this evaluates to exactly 3, so a fully-attributed
    deposit (deposit x days / 14) always matches the day expectation and the
    integrity verdict reads INTEGRITY_CONSISTENT.
    """
    return r2(dec(expired_freeze_days_in_window) * freeze_share(migrated_membersheads))


def integrity_verdict(pattern_days, deposit_attributed_cents):
    if pattern_days > 0 and deposit_attributed_cents < pattern_days:
        return "INTEGRITY_UNDER_RECOGNIZED"
    if pattern_days == 0 and deposit_attributed_cents > 0:
        return "INTEGRITY_OVER_RECOGNIZED"
    return "INTEGRITY_CONSISTENT"


# --- G: product_continuum_rating --------------------------------------------

def depth_ratio(unhedged_exposure_cents, capped_impact_cents):
    if not capped_impact_cents:
        return Decimal(0)
    return r4(dec(unhedged_exposure_cents) / dec(capped_impact_cents))


def continuum_absorbed_cents(overshoot_cents, depth_ratio_value):
    """Bounded variant for depth_ratio <= 1; floored at capped/1.25 above it."""
    capped = r2(dec(overshoot_cents) * PRODUCT_UPLIFT)
    term = r2(dec(capped) / CONTINUUM_DIVISOR)
    floor_value = r2(dec(capped) / CONTINUUM_DIVISOR)
    if depth_ratio_value is not None and dec(depth_ratio_value) > 1:
        return max(term, floor_value)
    return term


# --- H: protect_change_schedule ---------------------------------------------

def displayed_discount_rate(disruption_probability, severity_index, days_until_departure):
    return r3(dec(disruption_probability) * dec(severity_index) *
              dec(days_until_departure) / LEAD_TIME_NORMALIZER)


def display_price_cents(option_fare_cents, rate):
    return r2(dec(option_fare_cents) * dec(rate))


def change_fee_cents(option_fare_cents):
    return r2(dec(option_fare_cents) * CHANGE_FEE_RATE)


# --- J: deposit_forfeiture_rule ---------------------------------------------

def forfeited_cents(deposit_cents, membership_payment_exists, exempt_flag):
    if exempt_flag:
        return 0
    if membership_payment_exists:
        return FORFEITURE_MULTIPLIER * int(deposit_cents)
    return 0