"""Pure calculation rules from SCAFFOLD.yaml §1.3.

Nothing here mutates the store; every function is a pure projection so it can be
recomputed from the underlying rows at any time (§2.4: derived values are
read-only projections).
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from math import floor

import constants as C


def round_half_up(value, places=0):
    """Round half up (never banker's rounding)."""
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


def ceil_to_multiple(value, increment):
    """Ceiling once to the next whole multiple of `increment`."""
    if increment <= 0:
        return int(value)
    value = int(value)
    if value == 0:
        return 0
    return -(-value // increment) * increment


def floor_int(value):
    return int(Decimal(value).to_integral_value(rounding="ROUND_FLOOR"))


# ---------------------------------------------------------------------------
# Settlement (§1.3 settlement) — dual variant
# ---------------------------------------------------------------------------
def combination_set(reservation, all_reservations, clock):
    """T: distinct reservations sharing this episode's non-null invite_code.

    NO_SHOW, ABANDONED and CLOSED rows are excluded.
    """
    code = reservation.get("invite_code")
    if not code:
        return []
    out = []
    for row in all_reservations:
        if row.get("invite_code") != code:
            continue
        if row.get("venue_id") != reservation.get("venue_id"):
            continue
        if row.get("status") in ("NO_SHOW", "ABANDONED", "CLOSED"):
            continue
        hold_until = row.get("hold_until")
        if hold_until is None or hold_until <= clock:
            continue
        out.append(row)
    return out


def _celebration_multiplier(reservation, rows_in_t):
    """Highest celebration multiplier present across the booking and every booking in T.

    The scaffold's `highest multiplier among them` is read as a maximum over the
    multipliers, so a pairing of BIRTHDAY (1.0) with CORPORATE (1.5) takes the 1.5
    scale rather than the last value seen.
    """
    multiplier = C.CELEBRATION_TIER_MULTIPLIER.get(reservation.get("celebration", "NONE"), 0.0)
    for row in rows_in_t:
        m = C.CELEBRATION_TIER_MULTIPLIER.get(row.get("celebration", "NONE"), 0.0)
        if m > multiplier:
            multiplier = m
    return multiplier


def settlement(reservation, tier, sushi_amount, seat_surcharge, credit_applied,
               trueup_cents, rows_in_t, tier_by_id, parties_by_id, variant):
    """Return (final_bill_cents, check_cents) for the requested variant.

    variant == "quote": P_fee dropped (quote_final_cents)
    variant == "final": P_fee added (final_bill_cents / check_cents)

    `rows_in_t` is the precomputed combination set T for this booking.
    """
    party_size = reservation.get("party_size", 0)
    base_rate = tier.get("base_rate_per_guest_cents", 0)

    entitlement = party_size * base_rate
    p_cap = tier.get("seat_capacity", 0) * base_rate
    if variant == "quote":
        p_fee = 0
    else:
        multiplier = _celebration_multiplier(reservation, rows_in_t)
        p_fee = int(round_half_up(
            Decimal(C.CELEBRATION_FEE_CENTS) * Decimal(str(multiplier)), 0))
    p = min(p_cap, entitlement + p_fee)

    secured = 0
    other = 0
    for row in rows_in_t:
        row_tier = tier_by_id.get(row.get("tier_id"))
        if row_tier is None:
            continue
        secured += row_tier.get("minimum_bill_cents", 0)
        if row.get("id") != reservation.get("id"):
            other += row_tier.get("base_rate_per_guest_cents", 0) * min(
                row.get("party_size", 0), C.GUESTS_BILLED_CAP)

    # The compliment is a combination-set courtesy: it settles once separate
    # parties are actually paired at one grill, so a booking that forms a set of
    # one (its own row alone, or an empty T) carries no compliment.
    compliment = 0
    if len(rows_in_t) >= 2:
        all_platinum = True
        for row in rows_in_t:
            party = parties_by_id.get(row.get("party_id"))
            if party is None or party.get("loyalty_tier") != "PLATINUM":
                all_platinum = False
                break
        if all_platinum:
            compliment = C.COMPLIMENT_CREDIT_CENTS

    if not rows_in_t:
        base = max(0, p)
    elif secured < p:
        base = max(0, max(secured + sushi_amount + other, p))
    else:
        base = max(0, min(secured, p))

    final_bill = base - compliment
    check = final_bill + seat_surcharge - credit_applied + trueup_cents
    return final_bill, check


# ---------------------------------------------------------------------------
# Protein cost
# ---------------------------------------------------------------------------
def protein_ticket_cost(issued_grams):
    return round_half_up(Decimal(issued_grams) * Decimal(str(C.PROTEIN_COST_CENTS_PER_GRAM)), 0)


def venue_protein_cost(protein_tickets, venue_id):
    total = 0
    for ticket in protein_tickets:
        if ticket.get("venue_id") != venue_id or ticket.get("status") != "POSTED":
            continue
        total += int(ticket.get("cost_cents", 0))
    return total


def pounds_protein_issued(protein_tickets, chef_id):
    grams = 0
    for ticket in protein_tickets:
        if ticket.get("chef_assignment_id") != chef_id or ticket.get("status") != "POSTED":
            continue
        grams += ticket.get("issued_grams", 0)
    return float(round_half_up(Decimal(grams) / Decimal("453.6"), 2))


# ---------------------------------------------------------------------------
# Table minimum true-up
# ---------------------------------------------------------------------------
def table_minimum_trueup(final_bill_cents, minimum_bill_cents):
    shortfall = max(0, minimum_bill_cents - final_bill_cents)
    if shortfall == 0:
        band = Decimal(0)
    elif shortfall <= C.SHORTFALL_BAND_1_CENTS:
        band = Decimal(str(C.SHORTFALL_FACTOR_BAND_1)) * Decimal(shortfall)
    elif shortfall <= C.SHORTFALL_BAND_2_CENTS:
        band = Decimal(str(C.SHORTFALL_FACTOR_BAND_2)) * Decimal(shortfall)
    else:
        band = Decimal(str(C.SHORTFALL_FACTOR_BAND_3)) * Decimal(C.SHORTFALL_BAND_2_CENTS)
    band_int = int(round_half_up(band, 0))
    inc = C.TABLE_MINIMUM_TRUEUP_ROUND_INCREMENT_CENTS
    if band_int == 0:
        return 0
    return -(-band_int // inc) * inc


# ---------------------------------------------------------------------------
# Seat surcharge
# ---------------------------------------------------------------------------
def seat_surcharge(party_size, base_rate_per_guest_cents):
    guests_billed = min(party_size, C.GUESTS_BILLED_CAP)
    raw = Decimal(base_rate_per_guest_cents * guests_billed) / Decimal(party_size + 1)
    inc = C.SURCHARGE_ROUNDING_INCREMENT_CENTS
    raw_int = int(round_half_up(raw, 0))
    if raw_int == 0:
        return 0
    return -(-raw_int // inc) * inc


# ---------------------------------------------------------------------------
# Credit application
# ---------------------------------------------------------------------------
def credit_cap(check_before_credit_cents):
    return floor_int(min(Decimal(C.CREDIT_CAP_CENTS),
                         Decimal(str(C.CREDIT_CAP_PCT)) * Decimal(check_before_credit_cents)))


def credit_applied(party_credit_cents, credit_to_apply_cents, check_before_credit_cents):
    cap = credit_cap(check_before_credit_cents)
    return max(0, min(party_credit_cents, credit_to_apply_cents, cap))


# ---------------------------------------------------------------------------
# Chef rotation
# ---------------------------------------------------------------------------
def rotation_key(chef, minutes_since_show, target_tier_code):
    """Composite rotation key: (-station bonus, minutes_since_show DESC,
    sequence_index ASC, chef_name ASC).

    The bonus is negated so a larger bonus ranks earlier; the remaining
    comparators are the canonical tie-breaks the PRD pins (sequence_index then
    chef_name, never id).
    """
    bonus = C.SHORT_TABLE_BONUS if target_tier_code in C.SHORT_TABLE_TIERS else 0
    return (-bonus, -(minutes_since_show or 0), chef.get("sequence_index") or 0,
            chef.get("chef_name") or "")


def select_chef(candidates, target_tier_code, minutes_since_show_by_id):
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda c: rotation_key(c, minutes_since_show_by_id.get(c.get("id"), 0),
                                   target_tier_code),
    )
    return ranked[0]


# ---------------------------------------------------------------------------
# Protein portion standard
# ---------------------------------------------------------------------------
def protein_portion_standard(guest_count, protein_gram_standard):
    standard = guest_count * protein_gram_standard
    held_back = floor(standard / C.PROTEIN_PORTS_PER_GUEST / C.GUEST_PORT_SHARE_DIVISOR)
    issued = standard - held_back
    ports = floor(issued / C.PROTEIN_GRAM_PORT_SIZE)
    return standard, issued, ports


# ---------------------------------------------------------------------------
# Sushi plating
# ---------------------------------------------------------------------------
def sushi_advance_delta():
    return max(
        C.SUSHI_ADVANCE_MINUTES,
        C.GRILL_START_LEAD_MINUTES - floor(C.GRILL_START_LEAD_MINUTES / C.SUSHI_LEAD_DIVISOR),
        C.LATE_GRILL_THRESHOLD_MINUTES + C.LATE_EARLY_GRILL_DEBT_MINUTES,
    )


def sushi_plate_interval(requested_at):
    """Closed interval [requested_at, requested_at + PLATE_DWELL_MINUTES]; both ends inclusive."""
    from datetime import timedelta
    return requested_at, requested_at + timedelta(minutes=C.PLATE_DWELL_MINUTES)


def plate_intervals_touch(a_start, a_end, b_start, b_end):
    """Closed-interval overlap: touching at a single instant counts as conflict."""
    return not (a_end < b_start or b_end < a_start)


# ---------------------------------------------------------------------------
# Course timing
# ---------------------------------------------------------------------------
def planned_start_at(scheduled_time):
    minute = C.PLANNED_EARLY_MINUTE if scheduled_time.minute < C.HOURLY_TRIGGER_MINUTE \
        else C.HOURLY_TRIGGER_MINUTE
    return scheduled_time.replace(minute=minute, second=0, microsecond=0), minute


def course_plan_valid(scheduled_time):
    planned, minute = planned_start_at(scheduled_time)
    hard_cap = scheduled_time.minute + C.EARLY_GRILL_TOLERANCE_MINUTES
    return minute <= hard_cap


def late_minutes(actual_start_at, planned):
    if actual_start_at is None or planned is None:
        return 0
    return max(0, int((actual_start_at - planned).total_seconds() // 60))


# ---------------------------------------------------------------------------
# Turn-over window
# ---------------------------------------------------------------------------
def snap_to_grid(instant, width=C.GRID_SNAP_MINUTES):
    """Snap to the nearest earlier instant on the grid."""
    from datetime import timedelta
    epoch_minute = int(instant.timestamp() // 60)
    snapped = (epoch_minute // width) * width
    return instant - timedelta(minutes=(epoch_minute - snapped),
                               seconds=instant.second, microseconds=instant.microsecond)


def turn_over_window(scheduled_time, tier, celebration):
    from datetime import timedelta
    start_instant = snap_to_grid(scheduled_time) + timedelta(
        minutes=(C.GRID_SNAP_MINUTES // C.TURN_DEBT_BUCKET_WIDTH_MINUTES)
        * C.TURN_DEBT_BUCKET_WIDTH_MINUTES)
    if celebration == "NONE":
        minutes = tier.get("turn_time_standard_minutes", 0)
    else:
        minutes = tier.get("turn_time_celebration_minutes", 0)
    return start_instant + timedelta(minutes=minutes)


# ---------------------------------------------------------------------------
# Turn debt
# ---------------------------------------------------------------------------
def turn_debt_bucket(shortfall_minutes):
    index = min(C.SHORTFALL_LETTER_COUNT - 1,
                floor(shortfall_minutes / C.TURN_DEBT_BUCKET_WIDTH_MINUTES))
    if index < 0:
        index = 0
    return index


def turn_debt_allocation(shortfall_minutes, burst):
    index = turn_debt_bucket(shortfall_minutes)
    base = C.SHORTFALL_BUCKET_MINUTES[index]
    multiplier = Decimal(str(C.BURST_TURN_DEBT_FACTOR_PCT)) / Decimal(100) if burst else Decimal(1)
    return round_half_up_int(Decimal(base) * multiplier)


# ---------------------------------------------------------------------------
# Restaurant charge
# ---------------------------------------------------------------------------
def billable_guest_count(tables):
    return sum(min(t.get("seat_capacity", 0), C.ASSIGNABLE_GUEST_CAP) for t in tables)


def assignment_fee_band(count):
    if count < 50:
        return "LOW"
    if count <= 70:
        return "MEDIUM"
    return "HIGH"


def restaurant_charge_cents(tables):
    """billable_guest_count * ASSIGNMENT_FEE_CENTS, scaled by the band multiplier.

    The band is LOW below 50 (0.90), MEDIUM 50..70 (1.00), HIGH above 70 (1.20); a
    venue of twelve billable guests therefore lands in LOW and is charged
    12 * 299 * 0.90.
    """
    count = billable_guest_count(tables)
    band = assignment_fee_band(count)
    multiplier = C.ASSIGNMENT_FEE_MULTIPLIER[band]
    return count * C.ASSIGNMENT_FEE_CENTS * multiplier


# ---------------------------------------------------------------------------
# Venue cost report
# ---------------------------------------------------------------------------
def venue_cost_report(tables, tiers_by_id):
    total = 0
    for table in tables:
        tier = tiers_by_id.get(table.get("tier_id"))
        if tier is None:
            tier = _tier_by_code(tiers_by_id, table.get("venue_id"), table.get("tier_code"))
        if tier is None:
            continue
        code = (tier.get("tier_code") or "").split("_")[0]
        if code not in C.READY_TIER_CODES:
            continue
        total += tier.get("base_rate_per_guest_cents", 0) * tier.get("protein_gram_standard", 0)
    inc = C.ROUNDING_INCREMENT_CENTS
    if total == 0:
        return 0
    return -(-total // inc) * inc


def _tier_by_code(tiers_by_id, venue_id, tier_code):
    for tier in tiers_by_id.values():
        if tier.get("venue_id") == venue_id and tier.get("tier_code") == tier_code:
            return tier
    return None