"""Calculation rules per SCAFFOLD §1.3 / PRD §3.2, §3.5, §3.7.

Precision rules:
- Burden scores: integer points, never rounded.
- Composite performance score: 4-decimal round-half-up per component, then
  4-decimal round-half-up on the weighted sum (two-stage — do not collapse).
- Monetary: integer cents, round-half-up at the aggregate level only.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.clock import parse_ts

# --- chronic_condition_burden_provisional constants ---
CONDITION_WEIGHT = {
    "CHF": 6,
    "COPD": 5,
    "CKD": 4,
    "DIABETES": 3,
    "DEMENTIA": 7,
    "DEPRESSION": 2,
    "HTN": 1,
}
ED_VISIT_WEIGHT = 3
IP_ADMIT_WEIGHT = 5

# --- chronic_condition_burden_final constants ---
MED_DISCREPANCY_WEIGHT = 1
HIGH_RISK_MED_WEIGHT = 2
FALL_RISK_WEIGHT = 1
HOME_HAZARD_WEIGHT = 1
ADL_WEIGHT = 2
FOOD_INSECURITY_WEIGHT = 2
HOUSING_WEIGHT = 3
TRANSPORT_WEIGHT = 1
ISOLATION_WEIGHT = 1

# --- risk tier thresholds (shared between provisional and final) ---
TIER_MEDIUM_MIN = 8
TIER_HIGH_MIN = 15
TIER_VERY_HIGH_MIN = 25

# --- composite_performance_score weights ---
SLA_WEIGHT = Decimal("0.40")
ED_AVOID_WEIGHT = Decimal("0.30")
VISIT_COMPLETION_WEIGHT = Decimal("0.20")
PCP_COORDINATION_WEIGHT = Decimal("0.10")

CHRONIC_CONDITION_CODES = set(CONDITION_WEIGHT.keys())


def risk_tier_for(score):
    if score is None:
        return None
    if score >= TIER_VERY_HIGH_MIN:
        return "VERY_HIGH"
    if score >= TIER_HIGH_MIN:
        return "HIGH"
    if score >= TIER_MEDIUM_MIN:
        return "MEDIUM"
    return "LOW"


def compute_provisional_burden(member):
    """PRD §3.2: claims-history-only provisional burden score (integer)."""
    codes = member.get("chronic_condition_codes") or []
    chronic_points = sum(CONDITION_WEIGHT[c] for c in codes)
    ed_points = int(member.get("prior_ed_visits_12mo") or 0) * ED_VISIT_WEIGHT
    ip_points = int(member.get("prior_inpatient_admits_12mo") or 0) * IP_ADMIT_WEIGHT
    return chronic_points + ed_points + ip_points


def compute_final_burden(member):
    """PRD §3.5: final burden = provisional base + med-rec + safety + social.

    Uses the latest VisitAssessment whose parent visit is a COMPLETED
    INITIAL_ASSESSMENT — most recent by visit.actual_end, ties broken by
    visit.created_at ascending.
    """
    base = compute_provisional_burden(member)

    # Find the latest COMPLETED INITIAL_ASSESSMENT visit for this member
    # with a LOCKED assessment.
    candidates = []
    for visit in db.visits.values():
        if visit.get("member_id") != member.get("id"):
            continue
        if visit.get("visit_type") != "INITIAL_ASSESSMENT":
            continue
        if visit.get("status") != "COMPLETED":
            continue
        assessment = None
        for a in db.assessments.values():
            if a.get("visit_id") == visit["id"] and a.get("status") == "LOCKED":
                assessment = a
                break
        if assessment is None:
            continue
        actual_end = parse_ts(visit.get("actual_end")) if visit.get("actual_end") else None
        created_at = parse_ts(visit.get("created_at")) if visit.get("created_at") else None
        candidates.append((actual_end, created_at, assessment))

    if not candidates:
        return None

    # Most recent actual_end; ties broken by created_at ascending. Sorting by
    # (actual_end, created_at) and taking the last gives us: latest actual_end,
    # and among ties, the largest created_at — but the spec wants the earliest
    # created_at among ties. Sort by actual_end descending then created_at
    # ascending and take the first.
    candidates.sort(key=lambda t: (
        # negate by using reverse for the first element only — do a stable
        # two-key sort: created_at ascending first, then actual_end descending
        t[1] or parse_ts("1970-01-01T00:00:00Z"),
    ))
    candidates.sort(key=lambda t: (t[0] or parse_ts("1970-01-01T00:00:00Z")),
                    reverse=True)
    assessment = candidates[0][2]

    med_rec = assessment.get("medication_reconciliation") or {}
    safety = assessment.get("safety_evaluation") or {}
    social = assessment.get("social_needs_screening") or {}

    med_rec_bonus = (
        int(med_rec.get("discrepancies_found") or 0) * MED_DISCREPANCY_WEIGHT
        + int(med_rec.get("high_risk_med_changes") or 0) * HIGH_RISK_MED_WEIGHT
    )
    safety_bonus = (
        int(safety.get("fall_risk_score") or 0) * FALL_RISK_WEIGHT
        + int(safety.get("home_hazard_count") or 0) * HOME_HAZARD_WEIGHT
        + int(safety.get("adl_impairment_count") or 0) * ADL_WEIGHT
    )
    social_bonus = (
        (FOOD_INSECURITY_WEIGHT if social.get("food_insecurity") else 0)
        + (HOUSING_WEIGHT if social.get("housing_instability") else 0)
        + (TRANSPORT_WEIGHT if social.get("transportation_barrier") else 0)
        + int(social.get("social_isolation_score") or 0) * ISOLATION_WEIGHT
    )
    return base + med_rec_bonus + safety_bonus + social_bonus


def refresh_member_risk(member):
    """Derive risk_tier from burden_score_final if set, else provisional."""
    if member.get("burden_score_final") is not None:
        member["risk_tier"] = risk_tier_for(member["burden_score_final"])
    else:
        member["risk_tier"] = risk_tier_for(member.get("burden_score_provisional"))


def round4(value):
    """Round a Decimal (or numeric) to 4 decimal places, round-half-up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round to integer cents, round-half-up (aggregate level only)."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_composite_score(m):
    """PRD §3.7: four components in [0,1], two-stage 4-dp round-half-up."""
    trig = int(m.get("urgent_episodes_triggered") or 0)
    sla_met = int(m.get("urgent_episodes_sla_met") or 0)
    avoided = int(m.get("urgent_episodes_avoided_ed") or 0)
    completed = int(m.get("visits_completed") or 0)
    no_show = int(m.get("visits_no_show") or 0)
    cancelled = int(m.get("visits_cancelled") or 0)
    pcp_rate = m.get("pcp_coordination_rate")

    if trig > 0:
        sla_component = Decimal(sla_met) / Decimal(trig)
        ed_avoid_component = Decimal(avoided) / Decimal(trig)
    else:
        sla_component = Decimal("1.0")
        ed_avoid_component = Decimal("1.0")

    visit_denom = completed + no_show + cancelled
    if visit_denom > 0:
        visit_completion_component = Decimal(completed) / Decimal(visit_denom)
    else:
        visit_completion_component = Decimal("1.0")

    pcp_component = Decimal(str(pcp_rate)) if pcp_rate is not None else Decimal("0")

    weighted = (
        SLA_WEIGHT * round4(sla_component)
        + ED_AVOID_WEIGHT * round4(ed_avoid_component)
        + VISIT_COMPLETION_WEIGHT * round4(visit_completion_component)
        + PCP_COORDINATION_WEIGHT * round4(pcp_component)
    )
    return float(round4(weighted))


def overlaps(start_a, end_a, start_b, end_b):
    """Half-open [start, end) interval overlap per PRD §2.10."""
    return start_a < end_b and start_b < end_a
