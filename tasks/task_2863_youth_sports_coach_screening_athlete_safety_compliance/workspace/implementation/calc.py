"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 3.1, 3.2, 3.9).

Money is integer cents throughout and every fractional cent is rounded half up
exactly where the PRD says the rounding happens - never a second time.
"""

from decimal import Decimal, ROUND_HALF_UP

import store

# ---- global constants (SCAFFOLD section 1.3 header) ------------------------
SCREENING_VALIDITY_DAYS = 730
RENEWAL_WINDOW_DAYS = 90
COMPLIANCE_PASS_SCORE = Decimal("90.00")
MANDATORY_REPORT_WINDOW_HOURS = 24
RETENTION_YEARS = 7
ROOM_SLOT_CAPACITY = 2
MEASURE_COOLING_BUFFER_DAYS = 14

# ---- screening_tier_assignment --------------------------------------------
ROLE_POINTS = {
    "HEAD_COACH": 40,
    "ASSISTANT_COACH": 30,
    "CHAPERONE": 25,
    "OFFICIAL": 20,
    "VOLUNTEER": 10,
}
MINOR_CONTACT_POINTS = 25
JURISDICTION_POINTS_PER_EXTRA = 5
JURISDICTION_POINT_CAP = 15
PRIOR_RECORD_POINTS = 12
OPEN_FINDING_POINTS = 6
HISTORY_POINT_CAP = 30
TIER_2_THRESHOLD = 45
TIER_3_THRESHOLD = 75

# ---- screening_order_charge ----------------------------------------------
TIER_BASE_CENTS = {"TIER_1": 2500, "TIER_2": 4800, "TIER_3": 9200}
JURISDICTION_SURCHARGE_CENTS = 1100
VOLUME_TIER_1_CENTS = 8000
VOLUME_TIER_2_CENTS = 12000
EXPEDITE_PCT = Decimal("0.35")

# ---- audit_sanction_fine -------------------------------------------------
BASE_FINE_CENTS = 25000
SEVERITY_MULTIPLIER = {"MINOR": Decimal("0.20"), "MAJOR": Decimal("0.55"), "CRITICAL": Decimal("1.00")}
REPEAT_UPLIFT_PCT = Decimal("0.375")
SHORTFALL_RATE_PER_POINT = Decimal("0.012")

# ---- club_compliance_posture --------------------------------------------
CRITICAL_FREEZE_THRESHOLD = 1
RESTRICT_FINDING_THRESHOLD = 3


def round_half_up(value):
    """Round a Decimal to a whole unit, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def screening_tier_assignment(member):
    """Weighted screening risk score and the tier it demands."""
    role_points = ROLE_POINTS.get(member["role_type"], 0)
    contact_points = MINOR_CONTACT_POINTS if member["has_minor_athlete_contact"] else 0
    extra = max(0, len(member["jurisdiction_codes"]) - 1)
    jurisdiction_points = min(JURISDICTION_POINT_CAP, JURISDICTION_POINTS_PER_EXTRA * extra)
    prior_nondisq = len([
        o for o in store.orders_of(member["id"])
        if o["status"] == "ADJUDICATED" and o["disposition"] == "NON_DISQUALIFYING_RECORD"
    ])
    open_member_findings = len([
        f for f in store.findings_of_member(member["id"]) if f["status"] == "OPEN"
    ])
    history_points = min(
        HISTORY_POINT_CAP,
        PRIOR_RECORD_POINTS * prior_nondisq + OPEN_FINDING_POINTS * open_member_findings,
    )
    risk_points = min(100, role_points + contact_points + jurisdiction_points + history_points)
    if risk_points >= TIER_3_THRESHOLD:
        tier = "TIER_3"
    elif risk_points >= TIER_2_THRESHOLD:
        tier = "TIER_2"
    else:
        tier = "TIER_1"
    return risk_points, tier


def apply_tier_assignment(member):
    risk_points, tier = screening_tier_assignment(member)
    member["risk_points"] = risk_points
    member["required_tier"] = tier


def screening_order_charge(tier, jurisdiction_count, expedited):
    """Eight pinned steps; rounding happens at step 5 and step 7 only."""
    base = TIER_BASE_CENTS[tier]
    surcharge = JURISDICTION_SURCHARGE_CENTS * max(0, jurisdiction_count - 1)
    gross_subtotal = base + surcharge
    if gross_subtotal >= VOLUME_TIER_2_CENTS:
        discount_pct = Decimal("0.10")
    elif gross_subtotal >= VOLUME_TIER_1_CENTS:
        discount_pct = Decimal("0.05")
    else:
        discount_pct = Decimal("0.00")
    discount_cents = round_half_up(Decimal(gross_subtotal) * discount_pct)
    net_subtotal = gross_subtotal - discount_cents
    expedite_cents = round_half_up(Decimal(net_subtotal) * EXPEDITE_PCT) if expedited else 0
    charged_cents = net_subtotal + expedite_cents
    return {
        "gross_subtotal_cents": gross_subtotal,
        "discount_cents": discount_cents,
        "expedite_cents": expedite_cents,
        "charged_cents": charged_cents,
    }


def club_compliance_score(sampled_member_count, compliant_member_count, denominator_count):
    """Three ordered clauses; two decimal places, half up, capped at 100.00."""
    if sampled_member_count == 0:
        return Decimal("100.00")
    if denominator_count == 0:
        return Decimal("0.00")
    raw = (Decimal(100) * Decimal(compliant_member_count)) / Decimal(denominator_count)
    score = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    return score


def shortfall_factor(compliance_score):
    score = Decimal(str(compliance_score if compliance_score is not None else 0))
    points = COMPLIANCE_PASS_SCORE - score
    if points < 0:
        points = Decimal("0.00")
    return Decimal(1) + SHORTFALL_RATE_PER_POINT * points


def finding_fine_cents(severity, is_repeat, factor):
    raw = (Decimal(BASE_FINE_CENTS)
           * SEVERITY_MULTIPLIER[severity]
           * (Decimal(1) + (REPEAT_UPLIFT_PCT if is_repeat else Decimal(0)))
           * factor)
    return round_half_up(raw)


def score_out(score):
    """Serialize a 2dp compliance score."""
    if score is None:
        return None
    return float(Decimal(str(score)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
