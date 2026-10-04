"""Investigation priority scoring and evidence-request lazy transitions.

Implements calculations.investigation_priority_score (PRD section 3.5):
severity is the MAX basis weight, age is tiered, the overdue term is capped,
a systemic link multiplies by 1.5, rounding is a single half-up after the
multiplication, and the score is clamped to the ceiling last. The first
recompute reaching ESCALATION_THRESHOLD sets the charge's sticky
priority_escalated flag.
"""

from decimal import Decimal, ROUND_HALF_UP

import constants
import serializers
from helpers import bump, today
from store import db


def compute_priority_score(charge, overdue_request_count):
    severity = max(
        constants.BASIS_SEVERITY_WEIGHT[b] for b in charge["basis_codes"]
    )
    days = serializers.charge_days_elapsed(charge)
    if days < constants.AGE_TIER_10_MIN_DAYS:
        age_component = constants.AGE_POINTS_T0
    elif days < constants.AGE_TIER_20_MIN_DAYS:
        age_component = constants.AGE_POINTS_T10
    elif days < constants.AGE_TIER_35_MIN_DAYS:
        age_component = constants.AGE_POINTS_T20
    else:
        age_component = constants.AGE_POINTS_T35
    overdue_component = min(
        constants.OVERDUE_PER_REQUEST * overdue_request_count,
        constants.OVERDUE_COMPONENT_CAP,
    )
    multiplier = (
        Decimal(constants.SYSTEMIC_MULTIPLIER)
        if charge["systemic_case_id"] is not None
        else Decimal(1)
    )
    raw = (severity + age_component + overdue_component) * multiplier
    score = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(constants.SCORE_CEILING, score)


def refresh_evidence_request(request_row):
    """Apply the lazy PENDING -> OVERDUE transition (day granularity).

    Returns True when the row transitioned.
    """
    if (
        request_row["status"] == constants.EVIDENCE_PENDING
        and today() > request_row["due_date"]
    ):
        request_row["status"] = constants.EVIDENCE_OVERDUE
        bump(request_row)
        return True
    return False


def case_requests(investigation):
    return [
        r
        for r in db.evidence_requests.values()
        if r["investigation_case_id"] == investigation["id"]
    ]


def refresh_investigation(investigation):
    """Re-evaluate lazy evidence transitions, recompute the open/overdue
    counts and the priority score, and apply sticky priority escalation.

    Called on every investigation read and after every evidence-request
    transition, per the pinned triggers.
    """
    requests = case_requests(investigation)
    for request_row in requests:
        refresh_evidence_request(request_row)

    open_count = sum(
        1
        for r in requests
        if r["status"] in (constants.EVIDENCE_PENDING, constants.EVIDENCE_OVERDUE)
    )
    overdue_count = sum(
        1 for r in requests if r["status"] == constants.EVIDENCE_OVERDUE
    )
    investigation["open_request_count"] = open_count
    investigation["overdue_request_count"] = overdue_count

    charge = db.charges.get(investigation["charge_id"])
    score = compute_priority_score(charge, overdue_count)
    investigation["priority_score"] = score

    if (
        score >= constants.ESCALATION_THRESHOLD
        and not charge["priority_escalated"]
    ):
        # Sticky flag: set once, never auto-clears.
        charge["priority_escalated"] = True
        bump(charge)
    return investigation
