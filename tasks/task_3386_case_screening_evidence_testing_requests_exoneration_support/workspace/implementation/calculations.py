"""Calculation rules (SCAFFOLD 1.3 / PRD 2.10 and section 3).

Covers: screening_priority_score, compensation_award, sample_ledger bounds,
testing_status_derivation, contact_overdue_evaluation interval map,
evidence_posture_derivation, provider_capacity_check, policy_pattern_count.
All rounding follows the pinned orders; money is integer cents; screening
scores round each weighted product to 2 decimals HALF_UP then sum without a
final re-round.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from clock import parse_iso

# --- constants pinned by the scaffold ---
MIN_TESTABLE_NG = 5
POLICY_PATTERN_THRESHOLD = 3
FLAT_RATE_CENTS_PER_YEAR = 5000000
TIER1_YEARS = 5
TIER1_RATE_CENTS = 5000000
TIER2_RATE_CENTS = 7500000
FEE_REIMBURSEMENT_CAP_CENTS = 2500000
DAYS_PER_YEAR = 365

CLAIM_STRENGTH_POINTS = {"WEAK": 25, "MODERATE": 55, "STRONG": 80, "COMPELLING": 95}
EVIDENCE_POTENTIAL_POINTS = {
    "NONE_KNOWN": 0, "UNCERTAIN": 35, "LIKELY_STORED": 65, "CONFIRMED_STORED": 95,
}
HEALTH_URGENCY_POINTS = {"NONE": 0, "MODERATE": 45, "CRITICAL": 90}
YEARS_SATURATION = 30

WEIGHT_PROFILES = {
    "STANDARD": (Decimal("0.425"), Decimal("0.275"), Decimal("0.185"), Decimal("0.115")),
    "EXPEDITED": (Decimal("0.260"), Decimal("0.240"), Decimal("0.155"), Decimal("0.345")),
}

CONTACT_INTERVALS = {
    "OPEN": 90,
    "INVESTIGATION": 90,
    "TESTING": 60,
    "LITIGATION": 30,
    "EXONERATED": 14,
}


def _round2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _years_factor(years_served):
    raw = Decimal(years_served) * Decimal(100) / Decimal(YEARS_SATURATION)
    return _round2(min(raw, Decimal(100)))


def screening_score(intake_request, profile):
    """screening_priority_score under one weight profile; returns a float
    rendered from the exact Decimal sum of the four rounded products."""
    f_claim = Decimal(CLAIM_STRENGTH_POINTS[intake_request["claim_strength"]])
    f_evid = Decimal(EVIDENCE_POTENTIAL_POINTS[intake_request["evidence_potential"]])
    f_time = _years_factor(intake_request["years_served"])
    f_urg = Decimal(HEALTH_URGENCY_POINTS[intake_request["health_urgency"]])
    w_claim, w_evid, w_time, w_urg = WEIGHT_PROFILES[profile]
    score = (_round2(w_claim * f_claim) + _round2(w_evid * f_evid)
             + _round2(w_time * f_time) + _round2(w_urg * f_urg))
    return float(score)


def provisional_compensation_estimate(jurisdiction, years_incarcerated_claimed):
    """compensation_award PROVISIONAL variant: flat rate on declared years,
    capped by the jurisdiction cap; no enhancement, no fees."""
    base = FLAT_RATE_CENTS_PER_YEAR * years_incarcerated_claimed
    cap = jurisdiction["compensation_cap_cents"]
    return min(base, cap) if cap is not None else base


def final_verified_compensation_award(claim, case, intake_request, jurisdiction):
    """compensation_award FINAL_VERIFIED variant; pinned evaluation order:
    verified years -> tiered base -> exculpatory enhancement (floored) ->
    cap before fees -> fees after cap."""
    conviction_dt = parse_iso(intake_request["conviction_date"])
    exoneration_dt = parse_iso(case["exoneration_date"])
    days = (exoneration_dt.date() - conviction_dt.date()).days
    verified_years = max(0, days) // DAYS_PER_YEAR
    tiered_base = (TIER1_RATE_CENTS * min(verified_years, TIER1_YEARS)
                   + TIER2_RATE_CENTS * max(0, verified_years - TIER1_YEARS))
    pct = jurisdiction["actual_innocence_enhancement_pct"]
    if case["exculpatory_evidence_flag"] and pct and pct > 0:
        tiered_base = (tiered_base * (100 + pct)) // 100
    cap = jurisdiction["compensation_cap_cents"]
    award_before_fees = min(tiered_base, cap) if cap is not None else tiered_base
    fees = min(claim["documented_legal_fees_cents"], FEE_REIMBURSEMENT_CAP_CENTS)
    return award_before_fees + fees


def derive_testing_status(item):
    """testing_status_derivation: top-down, first match wins."""
    if item["remaining_sample_ng"] < MIN_TESTABLE_NG:
        return "SAMPLE_EXHAUSTED"
    analyses = [a for a in db.lab_analyses.values()
                if a["evidence_item_id"] == item["id"]]
    if any(a["status"] in ("SCHEDULED", "SAMPLE_SHIPPED") for a in analyses):
        return "SAMPLE_RESERVED"
    if any(a["status"] in ("RESULT_RECORDED", "INTERPRETED") for a in analyses):
        return "TESTED"
    if any(t["evidence_item_id"] == item["id"] and t["status"] in ("SIGNED", "GRANTED")
           for t in db.testing_authorizations.values()):
        return "TESTING_AUTHORIZED"
    return "UNTESTED"


def refresh_testing_status(item):
    """Re-derive testing_status; returns True when the value changed."""
    new = derive_testing_status(item)
    if new != item["testing_status"]:
        item["testing_status"] = new
        return True
    return False


def derive_evidence_posture(case):
    """evidence_posture_derivation: top-down, first match wins."""
    if case["exculpatory_evidence_flag"]:
        return "EXCULPATORY"
    items = [i for i in db.evidence_items.values() if i["case_id"] == case["id"]]
    if not items:
        return "NO_EVIDENCE"
    destroyed = sum(1 for i in items
                    if i["location_status"] in ("REPORTED_DESTROYED", "DESTRUCTION_VERIFIED"))
    confirmed = sum(1 for i in items if i["location_status"] == "CUSTODY_CONFIRMED")
    if confirmed >= 1 and destroyed == 0:
        return "SECURED"
    if confirmed >= 1 and destroyed >= 1:
        return "PARTIALLY_COMPROMISED"
    if confirmed == 0 and destroyed >= 1:
        return "FULLY_COMPROMISED"
    return "SEEKING"


def whole_days_between(later_dt, earlier_dt):
    """Floor of the UTC day difference (contact_overdue_evaluation)."""
    return (later_dt - earlier_dt).days


def lab_window_overlaps(lab_name, new_start_dt, new_end_dt):
    """Strict pairwise overlap of half-open lab bench windows on one lab,
    excluding CANCELLED analyses."""
    for a in db.lab_analyses.values():
        if a["lab_name"] != lab_name or a["status"] == "CANCELLED":
            continue
        existing_start = parse_iso(a["scheduled_start"])
        existing_end = parse_iso(a["scheduled_end"])
        if existing_start < new_end_dt and existing_end > new_start_dt:
            return True
    return False


def overlapping_live_referrals(provider_id, new_start_dt, new_end_dt):
    """Count of a provider's PENDING/ACTIVE referrals whose half-open service
    windows strictly overlap the new window."""
    count = 0
    for r in db.reentry_referrals.values():
        if r["provider_id"] != provider_id or r["status"] not in ("PENDING", "ACTIVE"):
            continue
        r_start = parse_iso(r["service_start"])
        r_end = parse_iso(r["service_end"])
        if r_start < new_end_dt and r_end > new_start_dt:
            count += 1
    return count


def policy_pattern_count(topic, jurisdiction_id):
    """policy_pattern_count: distinct Cases of the jurisdiction (any status)
    matching the topic pattern."""
    count = 0
    for case in db.cases.values():
        ir = db.intake_requests.get(case["intake_request_id"])
        if ir is None or ir["jurisdiction_id"] != jurisdiction_id:
            continue
        if topic == "EVIDENCE_PRESERVATION":
            match = case["destroyed_evidence_count"] >= 1
        elif topic == "COMPENSATION_REFORM":
            match = any(c["case_id"] == case["id"] and c["status"] in ("DENIED", "APPEALED")
                        for c in db.compensation_claims.values())
        elif topic == "DATABASE_ACCESS":
            item_ids = {i["id"] for i in db.evidence_items.values()
                        if i["case_id"] == case["id"]}
            match = any(a["evidence_item_id"] in item_ids
                        and a["db_comparison_status"] == "COMPLETED_HIT"
                        for a in db.lab_analyses.values())
        elif topic == "RECORDS_TRANSPARENCY":
            match = any(r["case_id"] == case["id"] and r["status"] == "DENIED"
                        for r in db.records_requests.values())
        else:
            match = False
        if match:
            count += 1
    return count


def anniversary_deadline(conviction_date_raw, years):
    """conviction_date + N calendar years, as a UTC datetime at 00:00:00.
    A Feb 29 conviction clamps to Feb 28 in non-leap target years."""
    d = parse_iso(conviction_date_raw).date()
    try:
        target = d.replace(year=d.year + years)
    except ValueError:
        target = d.replace(year=d.year + years, day=28)
    return datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
