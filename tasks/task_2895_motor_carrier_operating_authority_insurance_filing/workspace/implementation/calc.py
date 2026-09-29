"""Calculation rules (PRD sections 3.2, 3.6, 3.7, 3.9).

Every rounding step is ROUND_HALF_UP; exact rational arithmetic (Fraction) is
used throughout so no binary floating point error can leak into a cent.
"""

from fractions import Fraction

import clock

# ---- required insurance minimums (PRD 3.2)
BIPD_PROPERTY_BASE_CENTS = 75000000
BIPD_PASSENGER_SMALL_CENTS = 150000000
BIPD_PASSENGER_LARGE_CENTS = 500000000
BIPD_HAZMAT_NONBULK_CENTS = 100000000
BIPD_HAZMAT_BULK_CENTS = 500000000
CARGO_HOUSEHOLD_GOODS_CENTS = 1000000
BROKER_BOND_CENTS = 7500000
PASSENGER_SEAT_BREAK = 15
MULTISTATE_UPLIFT_THRESHOLD = 25
MULTISTATE_UPLIFT_CENTS = 25000000

# ---- filing fee (PRD 3.2)
DOCKET_BASE_CENTS = 30000
PER_STATE_SURCHARGE_CENTS = 137
HAZMAT_ENDORSEMENT_FEE_CENTS = 10500
ADMIN_SURCHARGE_FACTOR = Fraction(10725, 10000)  # 1 + 7.25 percent
TYPE_FEE_CENTS = {
    "FOR_HIRE_PROPERTY": 30000,
    "HOUSEHOLD_GOODS": 45000,
    "PASSENGER": 45000,
    "PROPERTY_BROKER": 30000,
    "FREIGHT_FORWARDER": 30000,
}
KIND_MULTIPLIER = {
    "NEW": Fraction(1),
    "NAME_CHANGE": Fraction(1, 2),
    "REINSTATEMENT": Fraction(5, 4),
    "SUCCESSOR_IN_INTEREST": Fraction(3, 4),
}

# ---- compliance risk score (PRD 3.6, 3.7)
W_OOS = Fraction(45, 100)
W_DRIVER = Fraction(30, 100)
W_VEHICLE = Fraction(25, 100)
FLEET_NORMALIZER = 10
ACUTE_VIOLATION_PENALTY = Fraction(12)
SCORE_FLOOR = Fraction(0)
SCORE_CEILING = Fraction(100)
AUDIT_FAILURE_SCORE_THRESHOLD = Fraction(40)

# ---- windows and periods
ACTIVATION_WAITING_PERIOD_DAYS = 21
NEW_ENTRANT_AUDIT_WINDOW_MONTHS = 18
CURE_PERIOD_DAYS = 30
BIENNIAL_PERIOD_DAYS = 730
DESIGNATION_TRANSITION_BUFFER_DAYS = 1

# ---- disruption liability (PRD 3.9)
DAILY_DIVISOR = 30
EMBARGO_PENALTY_PCT = Fraction(15, 100)
GOODWILL_TIER_CENTS = 5000000
GOODWILL_WAIVER_PCT = Fraction(10, 100)


def round_half_up(value):
    """Round an exact rational to a whole integer, half away from zero."""
    frac = Fraction(value)
    if frac >= 0:
        return int((frac + Fraction(1, 2)).__floor__())
    return -int((-frac + Fraction(1, 2)).__floor__())


def round_half_up_2dp(value):
    """Round an exact rational to two decimal places, half away from zero.

    Returned as a float so it serialises as a JSON number with two decimals.
    """
    hundredths = round_half_up(Fraction(value) * 100)
    return hundredths / 100


def to_fraction(number):
    return Fraction(str(number))


# ------------------------------------------------- required insurance minimums

def required_insurance_minimums(transportation_type, passenger_seating_capacity,
                                hazmat_endorsement_requested, hazmat_bulk_capable,
                                requested_operating_states):
    if transportation_type == "PASSENGER":
        seats = passenger_seating_capacity or 0
        base = (BIPD_PASSENGER_SMALL_CENTS if seats <= PASSENGER_SEAT_BREAK
                else BIPD_PASSENGER_LARGE_CENTS)
    elif transportation_type == "PROPERTY_BROKER":
        base = 0
    else:
        base = BIPD_PROPERTY_BASE_CENTS

    if hazmat_endorsement_requested:
        haz = BIPD_HAZMAT_BULK_CENTS if hazmat_bulk_capable else BIPD_HAZMAT_NONBULK_CENTS
        base = max(base, haz)

    if base > 0 and len(requested_operating_states) >= MULTISTATE_UPLIFT_THRESHOLD:
        base = base + MULTISTATE_UPLIFT_CENTS

    cargo = CARGO_HOUSEHOLD_GOODS_CENTS if transportation_type == "HOUSEHOLD_GOODS" else 0
    bond = (BROKER_BOND_CENTS
            if transportation_type in ("PROPERTY_BROKER", "FREIGHT_FORWARDER") else 0)
    return base, cargo, bond


# ------------------------------------------------------------- the filing fee

def filing_fee_assessment(application_kind, transportation_type,
                          requested_operating_states, hazmat_endorsement_requested):
    m = KIND_MULTIPLIER[application_kind]
    f = ADMIN_SURCHARGE_FACTOR

    line_docket = round_half_up(Fraction(DOCKET_BASE_CENTS) * m * f)
    line_states = round_half_up(
        Fraction(PER_STATE_SURCHARGE_CENTS) * len(requested_operating_states) * f)
    line_type = round_half_up(Fraction(TYPE_FEE_CENTS[transportation_type]) * m * f)
    line_hazmat = (round_half_up(Fraction(HAZMAT_ENDORSEMENT_FEE_CENTS) * f)
                   if hazmat_endorsement_requested else 0)

    total = line_docket + line_states + line_type + line_hazmat
    breakdown = {
        "line_docket_cents": line_docket,
        "line_states_cents": line_states,
        "line_type_cents": line_type,
        "line_hazmat_cents": line_hazmat,
    }
    return total, breakdown


# --------------------------------------------------- compliance risk scoring

def _weighted(oos_component, driver_component, vehicle_component, penalty):
    raw = (W_OOS * oos_component + W_DRIVER * driver_component
           + W_VEHICLE * vehicle_component + penalty)
    clamped = min(SCORE_CEILING, max(SCORE_FLOOR, raw))
    return round_half_up_2dp(clamped)


def self_reported_risk_score(carrier):
    oos = min(Fraction(100), to_fraction(carrier["self_reported_oos_rate_pct"]) * 2)
    vehicles = carrier["self_reported_vehicle_count"]
    drivers = carrier["self_reported_driver_count"]
    divisor = vehicles if vehicles >= 1 else 1
    driver = min(Fraction(100), Fraction(drivers, divisor) * 20)
    vehicle = min(Fraction(100), Fraction(vehicles, FLEET_NORMALIZER) * 10)
    return _weighted(oos, driver, vehicle, Fraction(0))


def audited_risk_score(oos_rate_pct, driver_violations, vehicle_defects, acute_violations):
    oos = min(Fraction(100), to_fraction(oos_rate_pct) * 2)
    driver = min(Fraction(100), Fraction(driver_violations) * 5)
    vehicle = min(Fraction(100), Fraction(vehicle_defects) * 4)
    penalty = ACUTE_VIOLATION_PENALTY * acute_violations
    return _weighted(oos, driver, vehicle, penalty)


def safety_audit_outcome(audit_score, acute_violation_count):
    if to_fraction(audit_score) >= AUDIT_FAILURE_SCORE_THRESHOLD or acute_violation_count >= 1:
        return "FAILED"
    return "PASSED"


# ------------------------------------------------------- disruption liability

def _daily_cents(contract):
    return Fraction(contract["monthly_committed_revenue_cents"], DAILY_DIVISOR)


def suspension_estimate(contract):
    daily = _daily_cents(contract)
    remaining_days = clock.ceil_days(contract["suspended_at"], contract["term_end_at"])
    return round_half_up(daily * remaining_days * EMBARGO_PENALTY_PCT)


def settled_actual(contract):
    daily = _daily_cents(contract)
    elapsed_days = clock.ceil_days(contract["suspended_at"], contract["resumed_at"])
    base_cents = round_half_up(daily * elapsed_days * EMBARGO_PENALTY_PCT)
    shipment_penalty_cents = round_half_up(
        daily * contract["embargoed_shipment_count"] * EMBARGO_PENALTY_PCT)
    pre_waiver_subtotal = base_cents + shipment_penalty_cents
    waiver_pct = (GOODWILL_WAIVER_PCT if pre_waiver_subtotal >= GOODWILL_TIER_CENTS
                  else Fraction(0))
    return pre_waiver_subtotal - round_half_up(Fraction(pre_waiver_subtotal) * waiver_pct)


# --------------------------------------------------------------------- windows

def activation_eligible_at(publication_at):
    return clock.add_days(publication_at, ACTIVATION_WAITING_PERIOD_DAYS)


def new_entrant_audit_window(activated_at):
    return clock.add_months(activated_at, NEW_ENTRANT_AUDIT_WINDOW_MONTHS)


def cure_deadline(notice_issued_at):
    return clock.add_days(notice_issued_at, CURE_PERIOD_DAYS)


def biennial_due(from_instant):
    return clock.add_days(from_instant, BIENNIAL_PERIOD_DAYS)
