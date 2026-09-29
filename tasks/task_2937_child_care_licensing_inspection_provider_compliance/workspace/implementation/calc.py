"""Every calculation of PRD §2.6 and §3, with the normative rounding stages."""

from decimal import Decimal, ROUND_HALF_UP

import constants as K

ZERO = Decimal("0")
HUNDRED = Decimal("100")


def rhu(value, places):
    """Round half up to `places` decimal places."""
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def as_number(value):
    """Render a Decimal as a JSON number carrying its 2-decimal scale."""
    if value is None:
        return None
    return float(value)


def ceil_div(numerator, denominator):
    if numerator <= 0:
        return 0
    return -((-numerator) // denominator)


# --- violation_point_assessment -------------------------------------------


def assessed_points(severity, infant_exposure, repeat_chain_depth):
    base = Decimal(K.SEVERITY_BASE_POINTS[severity])
    step1 = base + (base * Decimal(K.INFANT_AGGRAVATION_PCT) if infant_exposure else ZERO)
    step2 = step1 * Decimal(K.REPEAT_MULTIPLIER[repeat_chain_depth])
    rounded = int(rhu(step2, 0))
    return min(rounded, K.MAX_POINTS_PER_VIOLATION)


# --- inspection_compliance_score ------------------------------------------


def score_input_set(rows, variant):
    if variant == "PRELIMINARY":
        return [v for v in rows if v["status"] != "VACATED"]
    return list(rows)


def compliance_score(rows, variant):
    """Returns (compliance_score, raw_deduction, violation_count) as Decimals/int."""
    included = score_input_set(rows, variant)
    total = ZERO
    for v in included:
        weight = Decimal(K.AGE_GROUP_EXPOSURE_WEIGHT[v["primary_age_group"]])
        if variant == "PRELIMINARY":
            factor = Decimal("1.000")
        else:
            factor = Decimal(K.STATUS_FACTOR[v["status"]])
        total += rhu(Decimal(v["assessed_points"]) * weight * factor, 2)
    raw = rhu(total, 2)
    score = rhu(max(ZERO, Decimal(K.SCORE_CEILING) - raw), 2)
    return score, raw, len(included)


# --- provider_risk_assessment ---------------------------------------------


def risk_score(provider, variant):
    points = Decimal(K.W_POINTS) * Decimal(
        min(int(provider["open_violation_points"]), K.POINTS_CAP)
    )
    substantiated = Decimal(K.W_SUBSTANTIATED) * Decimal(
        provider["substantiated_complaint_count_24mo"]
    )
    inconclusive = Decimal(K.W_INCONCLUSIVE[variant]) * Decimal(
        provider["inconclusive_complaint_count_24mo"]
    )
    critical = (
        Decimal(K.CRITICAL_FLOOR_BONUS)
        if provider["critical_violation_count_24mo"] >= 1
        else ZERO
    )
    standing = (
        Decimal(K.PROBATION_STATE_BONUS)
        if provider["license_status"] in ("PROBATION", "SUSPENDED")
        else ZERO
    )
    total = points + substantiated + inconclusive + critical + standing
    return rhu(min(Decimal(K.RISK_CEILING), total), 2)


def risk_tier(score):
    if score < Decimal(K.RISK_TIER_MODERATE_FLOOR):
        return "LOW"
    if score < Decimal(K.RISK_TIER_HIGH_FLOOR):
        return "MODERATE"
    if score < Decimal(K.RISK_TIER_SEVERE_FLOOR):
        return "HIGH"
    return "SEVERE"


# --- enforcement_ladder_step ----------------------------------------------


def recommended_action_type(points):
    if points >= K.REVOCATION_THRESHOLD:
        return "REVOCATION"
    if points >= K.SUSPENSION_THRESHOLD:
        return "SUSPENSION"
    if points >= K.PROBATION_THRESHOLD:
        return "PROBATION"
    if points >= K.WARNING_THRESHOLD:
        return "WARNING"
    return None


# --- enforcement_fine_amount ----------------------------------------------


def fine_amount_cents(action_type, basis_points):
    gross = Decimal(K.FINE_BASE_CENTS[action_type]) + Decimal(K.PER_POINT_CENTS) * Decimal(
        int(basis_points)
    )
    if gross < Decimal(K.FINE_TIER_T2_FLOOR):
        tier = "T1"
    elif gross < Decimal(K.FINE_TIER_T3_FLOOR):
        tier = "T2"
    else:
        tier = "T3"
    surcharge = rhu(gross * Decimal(K.SURCHARGE_PCT[tier]), 0)
    net = gross + surcharge
    credit = rhu(net * Decimal(K.CREDIT_PCT[tier]), 0)
    return int(net - credit)


# --- ratio, group size and supervision ------------------------------------


def required_staff_count(age_group, enrolled_count):
    if enrolled_count <= 0:
        return 0
    return ceil_div(enrolled_count, K.AGE_GROUP_RATIO[age_group])


def effective_group_cap(age_group, approved_group_size):
    return min(approved_group_size, K.AGE_GROUP_MAX_SIZE[age_group])


# --- complaint_priority_and_deadline --------------------------------------


def complaint_priority(allegation_category, affected_age_group, license_status):
    band = "INFANT_TODDLER" if affected_age_group in ("INFANT", "TODDLER") else "OLDER"
    priority = K.COMPLAINT_PRIORITY_MATRIX[allegation_category][band]
    if license_status in ("PROBATION", "SUSPENDED"):
        priority = K.PRIORITY_ESCALATION[priority]
    return priority


# --- public_display_score -------------------------------------------------


def display_score(final_compliance_score, current_ladder_step):
    banner = K.POSTING_BANNER_BY_STEP[current_ladder_step]
    base = Decimal(str(final_compliance_score if final_compliance_score is not None else 0))
    penalty = Decimal(K.POSTING_BANNER_PENALTY[banner])
    return banner, rhu(max(ZERO, base - penalty), 2)


# --- licence number minting ------------------------------------------------


def license_number(county_code, sequence):
    return "LIC-%s-%04d" % (county_code[len("CTY-") :], sequence)
