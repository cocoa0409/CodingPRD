"""The nine derived calculations of PRD section 2.6 and their constants."""

import math
from decimal import Decimal, ROUND_HALF_UP

import store

# ------------------------------------------------------------------- constants
ROLE_MIN_WITNESS_DAYS = {
    "LEAD_ASSESSOR": 4,
    "TECHNICAL_ASSESSOR": 2,
    "TECHNICAL_EXPERT": 0,
}
QUALIFICATION_VALID_DAYS = 1460

ON_SITE_DAY_RATE_CENTS = 145000
REMOTE_DAY_RATE_CENTS = 96500
WITNESS_DAY_RATE_CENTS = 132500
TRAVEL_DAY_RATE_CENTS = 87500

WITNESS_HOURS_PER_DAY = 8
SITE_BUFFER_DAYS = 14
MIN_NOTICE_DAYS = 14
MIN_PANEL_VOTES = 3
COMPLAINT_LOOKBACK_DAYS = 730

MIN_EFFECTIVENESS_EVIDENCE = {"CRITICAL": 3, "MAJOR": 2, "MINOR": 1, "OBSERVATION": 0}

SEVERITY_BY_RELATIONSHIP = {
    "EMPLOYMENT": "STRUCTURAL",
    "OWNERSHIP": "STRUCTURAL",
    "FAMILY": "STRUCTURAL",
    "CONSULTANCY": "SERVICE",
    "TRAINING_DELIVERY": "SERVICE",
    "NONE": "NONE",
}
COOLING_OFF_MONTHS = {"STRUCTURAL": 24, "SERVICE": 12, "NONE": 0}

CENT = Decimal("1")
TWO_PLACES = Decimal("0.01")


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places) if places else CENT
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def to_number(value):
    """Serialise a Decimal for JSON output."""
    if value is None:
        return None
    return float(value)


# ------------------------------------------------- 1. assessor competence points
def recency_factor(last_witness_on, reference_date):
    if not last_witness_on:
        return Decimal("0.75")
    from validators import parse_date

    last = parse_date(last_witness_on, "last_witness_on")
    gap = (reference_date - last).days
    if gap <= 365:
        return Decimal("1.00")
    if gap <= 730:
        return Decimal("0.90")
    return Decimal("0.75")


def competence_points(years_experience, witness_days, training_modules,
                      employment_type, recency):
    experience = min(40, 4 * int(years_experience))
    witnessing = min(30, 5 * int(witness_days))
    training = min(20, 10 * int(training_modules))
    integrity = 10 if employment_type == "INTERNAL" else 6
    raw = experience + witnessing + training + integrity
    return round_half_up(Decimal(raw) * Decimal(recency), 2)


def declared_points(qualification, assessor):
    return competence_points(
        qualification["years_experience"],
        qualification["declared_witness_days"],
        qualification["declared_training_modules"],
        assessor["employment_type"],
        Decimal("1.00"),
    )


def verified_points(qualification, assessor, reference_date):
    factor = recency_factor(qualification.get("last_witness_on"), reference_date)
    return competence_points(
        qualification["verified_years_experience"] or 0,
        qualification["verified_witness_days"] or 0,
        qualification["verified_training_modules"] or 0,
        assessor["employment_type"],
        factor,
    )


# --------------------------------------------------- 2. organization risk score
def _qualifying_upheld_complaints(organization_id, reference_date):
    from validators import parse_date

    horizon = reference_date - _timedelta(COMPLAINT_LOOKBACK_DAYS)
    count = 0
    for case in store.rows("complaints"):
        if case["organization_id"] != organization_id:
            continue
        if case["status"] not in ("UPHELD", "ESCALATED_MRA"):
            continue
        if not case.get("resolved_on"):
            continue
        if parse_date(case["resolved_on"], "resolved_on") >= horizon:
            count += 1
    return count


def _timedelta(days):
    from datetime import timedelta

    return timedelta(days=days)


def cycle_raw_risk(application_id, organization_id, reference_date):
    from validators import parse_date

    critical = major = minor = late = escalated = 0
    for finding in store.rows("nonconformities"):
        if application_id is None or finding["application_id"] != application_id:
            continue
        if finding["classification"] == "OBSERVATION":
            continue
        if finding["classification"] == "CRITICAL":
            critical += 1
        elif finding["classification"] == "MAJOR":
            major += 1
        elif finding["classification"] == "MINOR":
            minor += 1
        if finding["status"] == "ESCALATED":
            escalated += 1
        closed_on = finding.get("closed_on")
        due_on = finding.get("due_on")
        if closed_on and due_on:
            if parse_date(closed_on, "closed_on") > parse_date(due_on, "due_on"):
                late += 1
    upheld = _qualifying_upheld_complaints(organization_id, reference_date)
    return (5 * critical) + (3 * major) + (1 * minor) + (4 * late) + (6 * escalated) + (2 * upheld)


def risk_at_decision(application_id, organization_id, reference_date):
    return min(100, cycle_raw_risk(application_id, organization_id, reference_date))


def risk_at_surveillance_planning(granting_application_id, surveillance_application_id,
                                  organization, reference_date):
    prior = cycle_raw_risk(granting_application_id, organization["id"], reference_date)
    current = cycle_raw_risk(surveillance_application_id, organization["id"], reference_date)
    total = (Decimal("0.5") * Decimal(prior)) + Decimal(current) \
        + (Decimal(3) * Decimal(organization["mra_escalation_count"]))
    return min(100, int(math.ceil(total)))


# ---------------------------------------------------- 3. assessment effort days
def effort_days(scope_line_count, witness_min_count, on_site_days, remote_days):
    witness_days_planned = max(int(witness_min_count),
                               int(math.ceil(scope_line_count / 3.0)))
    core_days = int(on_site_days) + int(remote_days) + witness_days_planned
    if core_days <= 5:
        travel_days = 0
    elif core_days <= 10:
        travel_days = 1
    else:
        travel_days = 2
    return {
        "witness_days_planned": witness_days_planned,
        "core_days": core_days,
        "travel_days": travel_days,
        "total_effort_days": core_days + travel_days,
    }


# ------------------------------------------------------------- 4. assessment fee
def assessment_fee(on_site_days, remote_days, witness_days_planned, travel_days,
                   complexity_multiplier):
    multiplier = Decimal(complexity_multiplier)
    on_site = round_half_up(Decimal(int(on_site_days)) * Decimal(ON_SITE_DAY_RATE_CENTS) * multiplier)
    remote = round_half_up(Decimal(int(remote_days)) * Decimal(REMOTE_DAY_RATE_CENTS) * multiplier)
    witness = round_half_up(Decimal(int(witness_days_planned)) * Decimal(WITNESS_DAY_RATE_CENTS) * multiplier)
    travel = Decimal(int(travel_days)) * Decimal(TRAVEL_DAY_RATE_CENTS)
    return {
        "fee_line_on_site_cents": int(on_site),
        "fee_line_remote_cents": int(remote),
        "fee_line_witness_cents": int(witness),
        "fee_line_travel_cents": int(travel),
        "assessment_fee_cents": int(on_site + remote + witness + travel),
    }


# --------------------------------------------- 5. impartiality conflict verdict
_VERDICT_RANK = {"CLEARED": 0, "CLEARED_WITH_NOTE": 1, "BLOCKED": 2}


def _months_between(reference, ended):
    months = (reference.year - ended.year) * 12 + (reference.month - ended.month)
    if reference.day < ended.day:
        months -= 1
    return months


def declaration_verdict(declaration, reference_date):
    from validators import parse_date

    severity = declaration["severity_class"]
    if severity == "NONE":
        return "CLEARED"
    window = declaration["cooling_off_months"]
    ended_on = declaration.get("ended_on")
    if not ended_on:
        return "BLOCKED"
    months = _months_between(reference_date, parse_date(ended_on, "ended_on"))
    if months < window:
        return "BLOCKED"
    return "CLEARED" if severity == "STRUCTURAL" else "CLEARED_WITH_NOTE"


def conflict_verdict(assessor_id, organization_id, reference_date):
    """Only the newest declaration per (assessor, organization) pair governs."""
    pairs = {}
    for declaration in store.rows("declarations"):
        if declaration["assessor_id"] != assessor_id:
            continue
        if organization_id is not None and declaration["organization_id"] != organization_id:
            continue
        key = declaration["organization_id"]
        current = pairs.get(key)
        if current is None or (declaration["created_at"], declaration["_seq"]) > \
                (current["created_at"], current["_seq"]):
            pairs[key] = declaration
    verdict = "CLEARED"
    for declaration in pairs.values():
        candidate = declaration_verdict(declaration, reference_date)
        if _VERDICT_RANK[candidate] > _VERDICT_RANK[verdict]:
            verdict = candidate
    return verdict


def impartiality_standing(assessor_id):
    """SCREENED unless some pair's newest disclosure is STRUCTURAL and open-ended."""
    pairs = {}
    for declaration in store.rows("declarations"):
        if declaration["assessor_id"] != assessor_id:
            continue
        key = declaration["organization_id"]
        current = pairs.get(key)
        if current is None or (declaration["created_at"], declaration["_seq"]) > \
                (current["created_at"], current["_seq"]):
            pairs[key] = declaration
    for declaration in pairs.values():
        if declaration["severity_class"] == "STRUCTURAL" and not declaration.get("ended_on"):
            return "RESTRICTED"
    return "SCREENED"


# ----------------------------------------------------- 6. nonconformity due date
def nonconformity_due_on(classification, raised_on, pinned):
    if classification == "OBSERVATION":
        return None
    windows = {
        "CRITICAL": pinned["critical_nc_close_days"],
        "MAJOR": pinned["major_nc_close_days"],
        "MINOR": pinned["minor_nc_close_days"],
    }
    return store.add_days(raised_on, windows[classification])


# ------------------------------------------------ 7. witness session day count
def session_day_count(starts_at, ends_at):
    seconds = Decimal((ends_at - starts_at).total_seconds())
    hours = seconds / Decimal(3600)
    return int(math.ceil(hours / Decimal(WITNESS_HOURS_PER_DAY)))


# ------------------------------------------------------ 8. panel decision outcome
def panel_outcome(votes):
    total = len(votes)
    refuse = sum(1 for v in votes if v["vote"] == "REFUSE")
    grant = sum(1 for v in votes if v["vote"] == "GRANT")
    conditions = sum(1 for v in votes if v["vote"] == "GRANT_WITH_CONDITIONS")
    if refuse * 2 > total:
        return "REFUSE"
    if (grant + conditions) * 2 > total:
        return "GRANT_WITH_CONDITIONS" if conditions >= 1 else "GRANT"
    return "DEFER"


# -------------------------------------------------------- 9. surveillance schedule
def surveillance_schedule(risk_score, effective_from, surveillance_interval_days,
                          reassessment_interval_days):
    if risk_score <= 10:
        factor = Decimal("1.00")
    elif risk_score <= 30:
        factor = Decimal("0.75")
    else:
        factor = Decimal("0.50")
    effective = int(math.floor(Decimal(int(surveillance_interval_days)) * factor))
    return {
        "surveillance_interval_days_effective": effective,
        "next_surveillance_due": store.add_days(effective_from, effective),
        "next_reassessment_due": store.add_days(effective_from, int(reassessment_interval_days)),
    }
