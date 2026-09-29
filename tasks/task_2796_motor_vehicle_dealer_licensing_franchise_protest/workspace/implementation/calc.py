"""Every arithmetic rule in the specification (PRD sections 2.6, 3.2, 3.5-3.9).

All money and percentage arithmetic runs through decimal.Decimal with ROUND_HALF_UP.
Python's built-in round() is never used because it rounds half to even.
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal("0")
TWO_PLACES = Decimal("0.01")
WHOLE = Decimal("1")
HUNDRED = Decimal("100")


def rh_cents(value):
    """Round half up to a whole cent and return an int."""
    return int(Decimal(value).quantize(WHOLE, rounding=ROUND_HALF_UP))


def rh2(value):
    """Round half up to exactly two decimal places."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def as_number(value):
    """Render a two-place Decimal for the JSON body."""
    if value is None:
        return None
    return float(value)


# ---------------------------------------------------------------------------
# 3.2 -- the statutory sufficiency scan
# ---------------------------------------------------------------------------
DEALER_TYPE_MINIMUMS = {
    "NEW_MOTOR_VEHICLE": {
        "facility_sqft": 8000,
        "display_spaces": 10,
        "service_bays": 3,
        "bond_amount_cents": 5000000,
        "insurance_liability_cents": 100000000,
    },
    "USED_ONLY": {
        "facility_sqft": 2000,
        "display_spaces": 3,
        "service_bays": 0,
        "bond_amount_cents": 2500000,
        "insurance_liability_cents": 50000000,
    },
}

_DEFICIENCY_CODE_BY_FIELD = {
    "facility_sqft": "FACILITY_TOO_SMALL",
    "display_spaces": "DISPLAY_SPACES_INSUFFICIENT",
    "service_bays": "SERVICE_BAYS_INSUFFICIENT",
    "bond_amount_cents": "BOND_INSUFFICIENT",
    "insurance_liability_cents": "INSURANCE_INSUFFICIENT",
}

_ZONING_CONDITIONAL_TYPES = ("RENEWAL", "RELOCATION")


def sufficiency_scan(application, dealer):
    """Return deficiency_codes sorted ascending lexicographically."""
    minimums = DEALER_TYPE_MINIMUMS[dealer["dealer_type"]]
    codes = []
    for field, code in _DEFICIENCY_CODE_BY_FIELD.items():
        if application[field] < minimums[field]:
            codes.append(code)
    zoning = application["zoning_certificate_status"]
    zoning_ok = zoning == "APPROVED" or (
        zoning == "CONDITIONAL" and application["application_type"] in _ZONING_CONDITIONAL_TYPES
    )
    if not zoning_ok:
        codes.append("ZONING_NOT_APPROVED")
    return sorted(codes)


# ---------------------------------------------------------------------------
# 3.2 -- the licence fee
# ---------------------------------------------------------------------------
BASE_FEE_CENTS = {
    "INITIAL": 120000,
    "RENEWAL": 90000,
    "CHANGE_OF_OWNERSHIP": 150000,
    "RELOCATION": 75000,
}

COUNTY_TIER_MULTIPLIER = {
    "TIER_1": Decimal("1.25"),
    "TIER_2": Decimal("1.00"),
    "TIER_3": Decimal("0.80"),
}

LINE_MAKE_SURCHARGE_PER_MAKE = 25000
LINE_MAKE_SURCHARGE_CAP = 100000
FACILITY_CREDIT_BASELINE_SQFT = 8000
FACILITY_CREDIT_PER_THOUSAND = 4000
FACILITY_CREDIT_CAP = 30000
LATE_RENEWAL_PENALTY_PER_DAY = 5000
LATE_RENEWAL_PENALTY_CAP = 50000


def license_fee_cents(application, dealer, reference_date):
    """The fee assembled in the load-bearing order of PRD 3.2."""
    base = BASE_FEE_CENTS[application["application_type"]]
    multiplier = COUNTY_TIER_MULTIPLIER[dealer["county_tier"]]
    tiered = rh_cents(Decimal(base) * multiplier)

    surcharge = min(
        LINE_MAKE_SURCHARGE_PER_MAKE * application["line_make_count"],
        LINE_MAKE_SURCHARGE_CAP,
    )

    excess = application["facility_sqft"] - FACILITY_CREDIT_BASELINE_SQFT
    if excess < 0:
        excess = 0
    credit = min(FACILITY_CREDIT_PER_THOUSAND * (excess // 1000), FACILITY_CREDIT_CAP)

    penalty = 0
    if application["application_type"] == "RENEWAL" and dealer.get("license_expires_on") is not None:
        late_days = (reference_date - dealer["license_expires_on"]).days
        if late_days < 0:
            late_days = 0
        penalty = min(LATE_RENEWAL_PENALTY_PER_DAY * late_days, LATE_RENEWAL_PENALTY_CAP)

    total = tiered + surcharge - credit + penalty
    return total if total > 0 else 0


# ---------------------------------------------------------------------------
# 3.5 -- the relevant-market distance
# ---------------------------------------------------------------------------
RELEVANT_MARKET_RADIUS_KM = Decimal("24.00")


def planar_distance_km(x1, y1, x2, y2):
    dx = dec(x1) - dec(x2)
    dy = dec(y1) - dec(y2)
    return rh2((dx * dx + dy * dy).sqrt())


# ---------------------------------------------------------------------------
# 3.7 -- market penetration
# ---------------------------------------------------------------------------
def actual_penetration(total_registrations, line_make_registrations):
    """Returns (actual_penetration_pct, is_probative)."""
    if total_registrations == 0:
        return Decimal("0.00"), False
    return rh2(HUNDRED * Decimal(line_make_registrations) / Decimal(total_registrations)), True


def expected_penetration(basis, statewide_share, comparable_shares):
    if basis == "STATEWIDE_AVERAGE":
        return rh2(dec(statewide_share))
    total = sum((dec(share) for share in comparable_shares), ZERO)
    return rh2(total / Decimal(len(comparable_shares)))


def shortfall_points(expected, actual):
    value = rh2(dec(expected) - dec(actual))
    return value if value > ZERO else Decimal("0.00")


# ---------------------------------------------------------------------------
# 3.7 -- the good-cause weighting
# ---------------------------------------------------------------------------
INADEQUACY_MULTIPLIER = Decimal("8")
INVESTMENT_DIVISOR = Decimal("500000")
ACCESS_NEUTRAL = Decimal("50.00")
ACCESS_MINUTE_MULTIPLIER = Decimal("4")
GROWTH_MULTIPLIER = Decimal("5")
COMPONENT_CAP = Decimal("100.00")
COMPONENT_FLOOR = Decimal("0.00")

WEIGHT_INADEQUACY = Decimal("0.40")
WEIGHT_INVESTMENT = Decimal("0.25")
WEIGHT_ACCESS = Decimal("0.20")
WEIGHT_GROWTH = Decimal("0.15")

THRESHOLD_TERMINATION = Decimal("40.00")
THRESHOLD_OTHER = Decimal("60.00")


def controlling_study(studies):
    """Rank probative candidates by created_at desc, shortfall desc, total desc.

    The row identifier is never a ranking key; Python's stable sort keeps the
    earliest-inserted row first among rows that tie on all three keys.
    """
    probative = [s for s in studies if s["is_probative"]]
    if not probative:
        return None
    ranked = sorted(
        probative,
        key=lambda s: (s["created_at"], s["shortfall_pts"], s["total_market_registrations"]),
        reverse=True,
    )
    return ranked[0]


def net_shortfall(protestant_study, manufacturer_study):
    subtrahend = manufacturer_study["shortfall_pts"] if manufacturer_study else Decimal("0.00")
    value = rh2(dec(protestant_study["shortfall_pts"]) - dec(subtrahend))
    return value if value > ZERO else Decimal("0.00")


def _cap(value):
    return value if value < COMPONENT_CAP else COMPONENT_CAP


def _clamp(value):
    if value < COMPONENT_FLOOR:
        return COMPONENT_FLOOR
    return _cap(value)


def good_cause_components(protestant_study, manufacturer_study):
    net = net_shortfall(protestant_study, manufacturer_study)
    inadequacy = _cap(rh2(net * INADEQUACY_MULTIPLIER))
    investment = _cap(
        rh2(Decimal(protestant_study["permanency_investment_cents"]) / INVESTMENT_DIVISOR)
    )
    if manufacturer_study is None:
        access = ACCESS_NEUTRAL
    else:
        difference = Decimal(manufacturer_study["consumer_access_drive_minutes"]) - Decimal(
            protestant_study["consumer_access_drive_minutes"]
        )
        access = _clamp(rh2(difference * ACCESS_MINUTE_MULTIPLIER + ACCESS_NEUTRAL))
    growth = _cap(rh2(dec(protestant_study["market_growth_pct"]) * GROWTH_MULTIPLIER))
    score = rh2(
        WEIGHT_INADEQUACY * inadequacy
        + WEIGHT_INVESTMENT * investment
        + WEIGHT_ACCESS * access
        + WEIGHT_GROWTH * growth
    )
    return {
        "net_shortfall_pts": net,
        "inadequacy_component": inadequacy,
        "investment_component": investment,
        "access_component": access,
        "growth_component": growth,
        "good_cause_score": score,
    }


def good_cause_threshold(filing_type):
    return THRESHOLD_TERMINATION if filing_type == "TERMINATION" else THRESHOLD_OTHER


# ---------------------------------------------------------------------------
# 3.7 -- the hearing cost assessment
# ---------------------------------------------------------------------------
SESSION_COST_CENTS = 45000
TRANSCRIPT_COST_PER_PAGE_CENTS = 350
PREVAILING_SHARE_RATE = Decimal("0.30")

_SURCHARGE_BANDS = (
    (100000, Decimal("0.05")),
    (250000, Decimal("0.08")),
    (None, Decimal("0.12")),
)


def hearing_cost_assessment(session_count, accepted_pages, late_evidence_count):
    sessions = SESSION_COST_CENTS * (session_count or 0)
    transcript = TRANSCRIPT_COST_PER_PAGE_CENTS * (accepted_pages or 0)
    subtotal = sessions + transcript
    surcharge = 0
    if (late_evidence_count or 0) > 0:
        rate = _SURCHARGE_BANDS[-1][1]
        for ceiling, banded_rate in _SURCHARGE_BANDS:
            if ceiling is None or subtotal <= ceiling:
                rate = banded_rate
                break
        surcharge = rh_cents(Decimal(subtotal) * rate)
    return subtotal + surcharge


def assessment_split(total_cents, prevailing_party):
    """Returns (protestant_share_cents, manufacturer_share_cents)."""
    prevailing_share = rh_cents(Decimal(total_cents) * PREVAILING_SHARE_RATE)
    remainder = total_cents - prevailing_share
    if prevailing_party == "PROTESTANT":
        return prevailing_share, remainder
    return remainder, prevailing_share


# ---------------------------------------------------------------------------
# 3.8 -- warranty reimbursement rates
# ---------------------------------------------------------------------------
QUALIFYING_REPAIR_TYPE = "CUSTOMER_PAID"
QUALIFYING_MIN_LABOR_HOURS = Decimal("0.5")
MINIMUM_QUALIFYING_LINES = 5
RATE_SPREAD_SPLIT_THRESHOLD = Decimal("5.00")


def is_qualifying_line(line):
    return (
        line["repair_type"] == QUALIFYING_REPAIR_TYPE
        and dec(line["labor_hours"]) >= QUALIFYING_MIN_LABOR_HOURS
    )


def qualifying_indexes(lines):
    return [index for index, line in enumerate(lines) if is_qualifying_line(line)]


def declared_rate_cents(lines):
    """Per-order mean: round each per-order rate first, then average and round."""
    indexes = qualifying_indexes(lines)
    if not indexes:
        return None
    per_order = [
        Decimal(rh_cents(Decimal(lines[i]["labor_charge_cents"]) / dec(lines[i]["labor_hours"])))
        for i in indexes
    ]
    return rh_cents(sum(per_order, ZERO) / Decimal(len(per_order)))


def counter_rate_cents(lines, excluded_indexes):
    """Aggregate weighted: pool charges and hours, divide once, round once."""
    excluded = set(excluded_indexes or [])
    charge_total = ZERO
    hour_total = ZERO
    surviving = 0
    for index in qualifying_indexes(lines):
        if index in excluded:
            continue
        charge_total += Decimal(lines[index]["labor_charge_cents"])
        hour_total += dec(lines[index]["labor_hours"])
        surviving += 1
    if surviving == 0 or hour_total == ZERO:
        return None
    return rh_cents(charge_total / hour_total)


def spread_pct(declared, counter):
    if declared is None or counter is None or counter == 0:
        return None
    return rh2(HUNDRED * (Decimal(declared) - Decimal(counter)) / Decimal(counter))


def approved_rate_cents(response_type, declared, counter, spread):
    if response_type == "ACCEPT" or spread is None or spread <= RATE_SPREAD_SPLIT_THRESHOLD:
        return declared
    return rh_cents((Decimal(declared) + Decimal(counter)) / Decimal(2))


# ---------------------------------------------------------------------------
# 3.9 -- complaint sanctions and the rolling point window
# ---------------------------------------------------------------------------
SANCTION_POINTS = {
    "WARNING": 0,
    "CIVIL_PENALTY": 3,
    "PROBATION": 6,
    "SUSPENSION_RECOMMENDED": 9,
}

ALLEGATION_PENALTY_BASE_CENTS = {
    "ODOMETER_MISREPRESENTATION": 200000,
    "FAILURE_TO_TRANSFER_TITLE": 100000,
    "ADVERTISING_VIOLATION": 50000,
    "DEPOSIT_RETENTION": 75000,
    "UNLICENSED_SALESPERSON": 150000,
}

RESTITUTION_CAP_CENTS = 1500000
CIVIL_PENALTY_CAP_CENTS = 500000
RESTITUTION_LOSS_RATE = Decimal("0.05")
RESTITUTION_DUE_DAYS = 30

POINT_WINDOW_DAYS = 730
DEALER_SUSPENSION_POINTS = 12
DEALER_REVOCATION_POINTS = 18
SALESPERSON_PROBATION_POINTS = 6
SALESPERSON_SUSPENSION_POINTS = 9


def restitution_ordered_cents(alleged_loss_cents):
    return min(alleged_loss_cents, RESTITUTION_CAP_CENTS)


def civil_penalty_cents(sanction_type, allegation_code, restitution_ordered):
    if sanction_type == "WARNING":
        return 0
    base = ALLEGATION_PENALTY_BASE_CENTS[allegation_code]
    loss_component = rh_cents(Decimal(restitution_ordered) * RESTITUTION_LOSS_RATE)
    return min(base + loss_component, CIVIL_PENALTY_CAP_CENTS)


def sanction_date(complaint):
    """Date part of resolved_at where present, else 30 days before restitution_due_on."""
    resolved_at = complaint.get("resolved_at")
    if resolved_at is not None:
        return resolved_at.date()
    due_on = complaint.get("restitution_due_on")
    if due_on is None:
        return None
    return due_on - _timedelta(RESTITUTION_DUE_DAYS)


def _timedelta(days):
    from datetime import timedelta

    return timedelta(days=days)


CONTRIBUTING_COMPLAINT_STATES = ("SANCTIONED", "CLOSED_SATISFIED")


def rolling_points(complaints, reference_date):
    """Sum points over contributing complaints inside the inclusive 730-day window."""
    lower_bound = reference_date - _timedelta(POINT_WINDOW_DAYS)
    total = 0
    for complaint in complaints:
        if complaint["status"] not in CONTRIBUTING_COMPLAINT_STATES:
            continue
        dated = sanction_date(complaint)
        if dated is None or dated < lower_bound:
            continue
        total += complaint.get("points_assessed") or 0
    return total


# ---------------------------------------------------------------------------
# licence terms (PRD 3.2 / 3.3)
# ---------------------------------------------------------------------------
DEALER_TERM_DAYS = 730
SALESPERSON_TERM_DAYS = 365
RENEWAL_WINDOW_OPENS_DAYS_BEFORE = 60
RENEWAL_GRACE_DAYS_AFTER = 30


def dealer_term_expiry(effective_on):
    return effective_on + _timedelta(DEALER_TERM_DAYS - 1)


def salesperson_term_expiry(effective_on):
    return effective_on + _timedelta(SALESPERSON_TERM_DAYS - 1)
