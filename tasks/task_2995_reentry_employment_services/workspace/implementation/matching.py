"""Job-match scoring and the placement eligibility ladder (PRD section 3.6)."""

from decimal import Decimal

from domain import (
    MATCH_SCORE_MAX, WAGE_TARGET_CENTS, dec, enrollments_of_participant,
    placements_of_opening, rhu,
)


def _wage_component(opening):
    raw = rhu(Decimal(30) * Decimal(int(opening["hourly_wage_cents"]))
              / WAGE_TARGET_CENTS, 0)
    return min(30, int(raw))


def _hours_component(opening):
    hours = dec(opening["weekly_hours"])
    if hours >= 30:
        return 20
    if hours >= 20:
        return 14
    if hours >= 10:
        return 8
    return 0


def _barrier_fit_component(participant):
    score = participant.get("barrier_score")
    score = Decimal(0) if score is None else dec(score)
    return int(rhu(Decimal(20) * (Decimal(100) - score) / Decimal(100), 0))


def _access_component(participant, opening):
    plan = participant.get("transportation_plan_type")
    if plan == "OWN_VEHICLE":
        return 15
    if plan == "EMPLOYER_SHUTTLE":
        return 15
    if plan == "TRANSIT_PASS":
        return 15 if opening.get("transit_accessible") else 5
    if plan == "RIDE_SHARE_STIPEND":
        return 10
    return 0


def _readiness_component(participant):
    attended = [e for e in enrollments_of_participant(participant["id"])
                if e["status"] == "ATTENDED"]
    value = 5 * len(attended)
    if any(e.get("disclosure_script_reviewed") for e in attended):
        value += 5
    return min(15, value)


def match_breakdown(participant, opening, partnership):
    return {
        "wage_component": _wage_component(opening),
        "hours_component": _hours_component(opening),
        "barrier_fit_component": _barrier_fit_component(participant),
        "access_component": _access_component(participant, opening),
        "readiness_component": _readiness_component(participant),
        "wotc_bonus": 5 if (partnership and partnership.get("wotc_certified")) else 0,
    }


def match_score(breakdown):
    return min(MATCH_SCORE_MAX, sum(breakdown.values()))


def score_match(participant, opening, partnership):
    breakdown = match_breakdown(participant, opening, partnership)
    return match_score(breakdown), breakdown


# --------------------------------------------------------------------------
# the eligibility ladder, shared by creation and the dry-run preview
# --------------------------------------------------------------------------

def blocking_error(participant, opening, partnership):
    """The first refusal a placement creation would report, or None."""
    if participant["suspension_status"] == "SUSPENDED":
        return "ERR_PARTICIPANT_SUSPENDED"
    if partnership is None or partnership["status"] != "ACTIVE":
        return "ERR_PARTNERSHIP_NOT_ACTIVE"
    barred = set(opening.get("barred_record_categories") or [])
    barred |= set(partnership.get("excluded_record_categories") or [])
    if barred & set(participant.get("record_categories") or []):
        return "ERR_RECORD_CATEGORY_BARRED"
    if opening.get("requires_license"):
        if (participant["license_relief_status"] != "RELIEF_GRANTED"
                or participant["license_relief_occupation_code"]
                != opening.get("license_occupation_code")):
            return "ERR_LICENSE_RELIEF_REQUIRED"
    if opening.get("requires_fidelity_bond") and not partnership.get(
            "fidelity_bond_enabled"):
        return "ERR_FIDELITY_BOND_UNAVAILABLE"
    for placement in placements_of_opening(opening["id"]):
        if (placement["participant_id"] == participant["id"]
                and placement["employment_status"] in ("OFFERED", "ACTIVE")):
            return "ERR_DUPLICATE_PLACEMENT"
    if opening["status"] != "OPEN" or int(opening["remaining_openings"]) <= 0:
        return "ERR_JOB_OPENING_NOT_OPEN"
    return None
