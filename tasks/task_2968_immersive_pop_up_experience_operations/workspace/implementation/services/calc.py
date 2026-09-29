"""The fourteen calculations (PRD §2.5, §3.x).

All arithmetic runs through decimal.Decimal with ROUND_HALF_UP.  Divisions that
derive a capacity floor; every other derived figure is rounded half up exactly
where the PRD says and nowhere else.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, getcontext

getcontext().prec = 60

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------
CM_PER_OCCUPANT = Decimal("2.03")

TIER_MULT = {
    "OFFPEAK": Decimal("0.80"),
    "STANDARD": Decimal("1.00"),
    "PEAK": Decimal("1.30"),
    "PREMIUM": Decimal("1.60"),
}
LEAD_EARLY_DAYS = 30
LEAD_EARLY_MULT = Decimal("0.90")
LEAD_LATE_DAYS = 7
LEAD_NORMAL_MULT = Decimal("1.00")
LEAD_LATE_MULT = Decimal("1.15")
PRICE_FLOOR_CENTS = 1000
PRICE_CEILING_CENTS = 100000

LOYALTY_DISCOUNT_PCT = {
    "VISITOR": Decimal("0"),
    "MEMBER": Decimal("5"),
    "PATRON": Decimal("12"),
}
GROUP_DISCOUNT_MIN_PARTY = 6
GROUP_DISCOUNT_PCT = Decimal("5")
ACCESSIBLE_COMPANION_MAX = 1
SINGLE_MAX_PARTY = 4
BUYOUT_PREMIUM_MULT = Decimal("1.25")

BPS_DIVISOR = Decimal("10000")

W_TRAINING = Decimal("0.40")
W_CERT = Decimal("0.35")
W_REHEARSAL = Decimal("0.25")
PENALTY_PER_INCIDENT = Decimal("5.00")
REHEARSAL_TARGET = Decimal("4")
READINESS_CLEAR_MIN = Decimal("78.00")
INCIDENT_CLEAR_MAX = 2
REQUIRED_CERTS = {
    "PERFORMER": ("SCRIPTED_INTERACTION", "SENSORY_DEESCALATION"),
    "AMBASSADOR": ("SCRIPTED_INTERACTION", "ADA_ASSIST", "EVACUATION_MARSHAL"),
    "TECHNICIAN": ("RIGGING", "ELECTRICAL"),
}

REFUND_PENALTY_WEIGHT = Decimal("0.50")
EXTENSION_DEMAND_MIN = Decimal("70.00")

REFUND_FULL_HOURS = Decimal("72")
REFUND_HALF_HOURS = Decimal("24")

BASE_WEAR_PER_CLOSE = Decimal("4.00")
PER_MODULE_WEAR = Decimal("0.30")
CITY_MOVE_WEAR = Decimal("9.00")
REFURB_THRESHOLD = Decimal("60.00")
REFURB_GAIN = Decimal("30.00")
REFURB_CAP = 2

LOCALIZATION_BASE_CENTS = 400000
LOCALIZATION_PER_MODULE_CENTS = 3300
REUSE_DISCOUNT_PCT_PER_CYCLE = Decimal("2.70")
REUSE_DISCOUNT_CYCLE_CAP = 5

FINDINGS_PASS_MAX = 2
FINDINGS_MAJOR_MAX = 5
EGRESS_TOLERANCE_PCT = Decimal("90")

NO_SHOW_STRIKE_CAP = 3
CHECKIN_GRACE_MIN = 15

REST_BUFFER_MIN = 30
MAX_SHIFT_MINUTES = 600

KIT_CONDITION_RUN_MIN = Decimal("60.00")


# --------------------------------------------------------------------------
# numeric primitives
# --------------------------------------------------------------------------

def dec(value):
    """Coerce anything numeric into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def floor_div(numerator, denominator):
    """Integer floor of an exact decimal division."""
    return int((dec(numerator) / dec(denominator)).to_integral_value(rounding=ROUND_FLOOR))


def money(value):
    """Whole-cent integer."""
    return rhu_int(value)


def two_dp(value):
    """A non-monetary derived figure carried to two decimal places."""
    return float(rhu(value, 2))


def clamp(value, low, high):
    if value < low:
        return low
    if value > high:
        return high
    return value


# --------------------------------------------------------------------------
# 1. egress geometry
# --------------------------------------------------------------------------

def egress_capacity(egress_width_cm):
    """floor(egress_width_cm / CM_PER_OCCUPANT)."""
    return floor_div(egress_width_cm, CM_PER_OCCUPANT)


def egress_floor_cm(venue_egress_width_cm):
    """The 90% tolerance floor a measured EGRESS width must reach."""
    return rhu(dec(venue_egress_width_cm) * EGRESS_TOLERANCE_PCT / Decimal("100"), 2)


def room_throughput_per_slot(room_occupancy_cap, timed_slot_minutes, target_dwell_minutes):
    return floor_div(dec(room_occupancy_cap) * dec(timed_slot_minutes),
                     dec(target_dwell_minutes))


# --------------------------------------------------------------------------
# 2. slot_dynamic_price
# --------------------------------------------------------------------------

def exact_seconds(delta):
    """timedelta -> exact Decimal seconds (no float round-trip)."""
    return (dec(delta.days) * Decimal("86400") + dec(delta.seconds)
            + dec(delta.microseconds) / Decimal("1000000"))


def lead_days_between(slot_start, clock_instant):
    return floor_div(exact_seconds(slot_start - clock_instant), Decimal("86400"))


def lead_multiplier(lead_days):
    if lead_days >= LEAD_EARLY_DAYS:
        return LEAD_EARLY_MULT
    if lead_days >= LEAD_LATE_DAYS:
        return LEAD_NORMAL_MULT
    return LEAD_LATE_MULT


def slot_unit_price_cents(base_ticket_price_cents, pricing_tier, lead_days):
    raw = dec(base_ticket_price_cents) * TIER_MULT[pricing_tier] * lead_multiplier(lead_days)
    return clamp(rhu_int(raw), PRICE_FLOOR_CENTS, PRICE_CEILING_CENTS)


# --------------------------------------------------------------------------
# 3. ticket_order_total
# --------------------------------------------------------------------------

def order_money(unit_price_cents, order_type, loyalty_tier, party_size,
                wheelchair_party_count):
    unit = dec(unit_price_cents)
    if order_type == "PRIVATE_BUYOUT":
        per_guest = int(unit_price_cents)
        gross = rhu_int(unit * dec(party_size) * BUYOUT_PREMIUM_MULT)
        group_discount = 0
        companion_waiver = 0
    else:
        pct = LOYALTY_DISCOUNT_PCT[loyalty_tier]
        per_guest = rhu_int(unit * (Decimal("100") - pct) / Decimal("100"))
        gross = per_guest * int(party_size)
        if order_type == "GROUP" and int(party_size) >= GROUP_DISCOUNT_MIN_PARTY:
            group_discount = rhu_int(dec(gross) * GROUP_DISCOUNT_PCT / Decimal("100"))
        else:
            group_discount = 0
        companion_waiver = per_guest * min(int(wheelchair_party_count),
                                           ACCESSIBLE_COMPANION_MAX)
    discount = group_discount + companion_waiver
    net = max(gross - discount, 0)
    return {
        "unit_price_cents": int(unit_price_cents),
        "per_guest_after_loyalty_cents": per_guest,
        "gross_amount_cents": gross,
        "group_discount_cents": group_discount,
        "companion_waiver_cents": companion_waiver,
        "discount_cents": discount,
        "net_amount_cents": net,
    }


# --------------------------------------------------------------------------
# 4. staff_readiness_score
# --------------------------------------------------------------------------

def cert_coverage_pct(staff_role, certifications):
    required = REQUIRED_CERTS[staff_role]
    held = set(certifications or ()) & set(required)
    return rhu(Decimal("100") * dec(len(held)) / dec(len(required)), 2)


def rehearsal_pct(counted_rehearsals):
    value = rhu(Decimal("100") * dec(counted_rehearsals) / REHEARSAL_TARGET, 2)
    return min(value, Decimal("100.00"))


def readiness_score(training_score, coverage_pct, counted_rehearsals, incident_count):
    raw = (W_TRAINING * dec(training_score)
           + W_CERT * dec(coverage_pct)
           + W_REHEARSAL * rehearsal_pct(counted_rehearsals)
           - PENALTY_PER_INCIDENT * dec(incident_count))
    return clamp(rhu(raw, 2), Decimal("0.00"), Decimal("100.00"))


# --------------------------------------------------------------------------
# 5. royalty_accrual
# --------------------------------------------------------------------------

def royalty_cents(ticket_base_cents, merch_base_cents, royalty_rate_bps,
                  merch_royalty_rate_bps):
    """The two legs are rounded separately and then added."""
    ticket_leg = rhu_int(dec(ticket_base_cents) * dec(royalty_rate_bps) / BPS_DIVISOR)
    merch_leg = rhu_int(dec(merch_base_cents) * dec(merch_royalty_rate_bps) / BPS_DIVISOR)
    return ticket_leg + merch_leg


def mg_prorated_cents(minimum_guarantee_cents, period_days, term_days):
    return rhu_int(dec(minimum_guarantee_cents) * dec(period_days) / dec(term_days))


# --------------------------------------------------------------------------
# 6. run_extension_demand_index
# --------------------------------------------------------------------------

def demand_figures(released_total, sold_total, counted_order_count,
                   refunded_order_count):
    if int(released_total) == 0:
        utilisation = Decimal("0.00")
    else:
        utilisation = rhu(Decimal("100") * dec(sold_total) / dec(released_total), 2)
    if int(counted_order_count) == 0:
        refund_share = Decimal("0.00")
    else:
        refund_share = rhu(
            Decimal("100") * dec(refunded_order_count) / dec(counted_order_count), 2)
    index = rhu(utilisation - REFUND_PENALTY_WEIGHT * refund_share, 2)
    return utilisation, refund_share, index


# --------------------------------------------------------------------------
# 7. refund_and_credit_settlement
# --------------------------------------------------------------------------

def refund_pct_for_hours(hours_before):
    hours = dec(hours_before)
    if hours >= REFUND_FULL_HOURS:
        return Decimal("1.00")
    if hours >= REFUND_HALF_HOURS:
        return Decimal("0.50")
    return Decimal("0.00")


def refund_legs(net_collected_cents, refund_pct):
    refunded = rhu_int(dec(net_collected_cents) * dec(refund_pct))
    credit = int(net_collected_cents) - refunded
    return refunded, credit


# --------------------------------------------------------------------------
# 8. kit_condition_decay / kit_localization_cost
# --------------------------------------------------------------------------

def kit_wear(module_count, moved):
    return rhu(BASE_WEAR_PER_CLOSE
               + PER_MODULE_WEAR * dec(module_count)
               + (CITY_MOVE_WEAR if moved else Decimal("0.00")), 2)


def kit_decayed_score(condition_score, wear):
    return max(rhu(dec(condition_score) - dec(wear), 2), Decimal("0.00"))


def kit_localization_cost_cents(module_count, reuse_cycle_count):
    gross = LOCALIZATION_BASE_CENTS + LOCALIZATION_PER_MODULE_CENTS * int(module_count)
    cycles = min(int(reuse_cycle_count), REUSE_DISCOUNT_CYCLE_CAP)
    discount = rhu_int(dec(LOCALIZATION_BASE_CENTS) * REUSE_DISCOUNT_PCT_PER_CYCLE
                       * dec(cycles) / Decimal("100"))
    return gross - discount


# --------------------------------------------------------------------------
# 9. safety_inspection_outcome
# --------------------------------------------------------------------------

def inspection_outcome(inspection_type, severity, findings_count,
                       measured_egress_width_cm, venue_egress_width_cm):
    """First-match-wins derivation (PRD §3.7)."""
    if inspection_type == "EGRESS":
        floor_cm = egress_floor_cm(venue_egress_width_cm)
        if dec(measured_egress_width_cm) < floor_cm:
            return "FAIL"
    if severity == "CRITICAL":
        return "FAIL"
    if severity == "MAJOR":
        return "FAIL" if int(findings_count) > FINDINGS_MAJOR_MAX else "CONDITIONAL"
    if severity == "MINOR":
        return "CONDITIONAL" if int(findings_count) > FINDINGS_PASS_MAX else "PASS"
    return "PASS"


def allowed_occupancy_cap(measured_egress_width_cm):
    return floor_div(measured_egress_width_cm, CM_PER_OCCUPANT)
