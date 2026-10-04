"""Business logic: slot accounting, review scoring, grant award terms,
placement cascades, grant lifecycle cascades, residency accrual, alumni
engagement indices. Every formula follows PRD 3 / calculations table exactly,
with the pinned evaluation orders and round-half-up steps."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    DEPENDENT_CAP,
    DEP_CAP_PCT_OF_BASE,
    DAYS_PER_MONTH,
    INTERIM_REPORT_DUE_MONTHS,
    FINAL_REPORT_DUE_DAYS,
    NATIONAL_QUORUM,
    WEIGHT_FEASIBILITY,
    WEIGHT_COUNTRY_FIT,
    WEIGHT_LANGUAGE,
    ENGAGEMENT_BASE_POINTS,
    REPORT_ACCEPT_POINTS,
    STRIKE_PENALTY_POINTS,
    MAX_COMPLIANCE_STRIKES,
    SLOT_CONSUMING_STATES,
)
from store import STORE, stamp_new, bump, now, now_iso
from timeutil import parse_iso, fmt, add_months

TWO_PLACES = Decimal("0.01")
WHOLE_CENT = Decimal("1")


def q2(value):
    """Round a Decimal half-up to exactly 2 decimal places."""
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    """Round a Decimal half-up to whole cents (integer)."""
    return int(value.quantize(WHOLE_CENT, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Ownership chains (Applicant-role ownership reaches through FK chains)
# ---------------------------------------------------------------------------

def applicant_of_application(application):
    return application["applicant_id"]


def applicant_of_round(rnd):
    return STORE.applications[rnd["application_id"]]["applicant_id"]


def applicant_of_grant(grant):
    return STORE.applications[grant["application_id"]]["applicant_id"]


def grant_of_application(application_id):
    for g in STORE.grants.values():
        if g["application_id"] == application_id:
            return g
    return None


def visa_of_grant(grant_id):
    for v in STORE.visas.values():
        if v["grant_id"] == grant_id:
            return v
    return None


def ledger_of_visa(visa_id):
    for led in STORE.ledgers.values():
        if led["visa_sponsorship_id"] == visa_id:
            return led
    return None


def applicant_of_visa(visa):
    return applicant_of_grant(STORE.grants[visa["grant_id"]])


def applicant_of_ledger(ledger):
    return applicant_of_visa(STORE.visas[ledger["visa_sponsorship_id"]])


def applicant_of_report(report):
    return applicant_of_grant(STORE.grants[report["grant_id"]])


# ---------------------------------------------------------------------------
# Slot accounting (live aggregation; never a stored counter)
# ---------------------------------------------------------------------------

def slots_remaining(program):
    consuming = sum(
        1
        for a in STORE.applications.values()
        if a["country_program_id"] == program["id"] and a["status"] in SLOT_CONSUMING_STATES
    )
    return program["slot_quota"] - consuming


# ---------------------------------------------------------------------------
# Grant creation / provisional award (PRD 3.6 provisional variant)
# ---------------------------------------------------------------------------

def create_provisional_grant(application):
    program = STORE.programs[application["country_program_id"]]
    p_monthly = program["monthly_stipend_standard_cents"]
    dep_monthly = program["dependent_allowance_monthly_cents"] * min(
        application["dependents_count"], DEPENDENT_CAP
    )
    provisional_total = (
        (p_monthly + dep_monthly + program["health_benefit_monthly_cents"])
        * application["proposed_duration_months"]
        + program["travel_allowance_cents"]
    )
    grant = {
        "application_id": application["id"],
        "status": "PROVISIONAL",
        "awarded_band": None,
        "provisional_monthly_stipend_cents": p_monthly,
        "provisional_total_cents": provisional_total,
        "final_monthly_stipend_cents": None,
        "final_total_cents": None,
        "duration_months": None,
        "start_date": None,
        "end_date": None,
        "orientation_completed_at": None,
        "interim_report_due_date": None,
        "final_report_due_date": None,
        "suspension_days_total": 0,
        "compliance_strikes": 0,
        "earned_cents": None,
        "repayment_cents": None,
        "reconciliation_adjustment_cents": None,
        "termination_reason": None,
    }
    stamp_new(grant)
    STORE.grants[grant["id"]] = grant
    return grant


# ---------------------------------------------------------------------------
# Alternate auto-promotion (PRD 3.4)
# ---------------------------------------------------------------------------

def promote_alternate(program_id):
    """Exactly one promotion per released slot: the ALTERNATE application of
    this program with the lowest recommend_seq (fallback created_at asc)."""
    candidates = [
        a
        for a in STORE.applications.values()
        if a["country_program_id"] == program_id and a["status"] == "ALTERNATE"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["recommend_seq"], a["created_at"], a["_seq"]))
    winner = candidates[0]
    winner["status"] = "SELECTED"
    bump(winner)
    create_provisional_grant(winner)
    return winner


def decline_application(application):
    """SELECTED/PLACEMENT -> DECLINED: collapse any OFFERED round, release the
    slot (implicit via status), and run alternate auto-promotion."""
    program_id = application["country_program_id"]
    if application["status"] == "PLACEMENT":
        for rnd in STORE.rounds.values():
            if rnd["application_id"] == application["id"] and rnd["status"] == "OFFERED":
                rnd["status"] = "DECLINED"
                rnd["responded_at"] = now_iso()
                bump(rnd)
    application["status"] = "DECLINED"
    bump(application)
    promote_alternate(program_id)


def fail_placement(application):
    """PLACEMENT -> PLACEMENT_FAILED: release the slot and auto-promote."""
    program_id = application["country_program_id"]
    application["status"] = "PLACEMENT_FAILED"
    bump(application)
    promote_alternate(program_id)


# ---------------------------------------------------------------------------
# Weighted national screening score (PRD 3.3)
# ---------------------------------------------------------------------------

def national_scores(application_id):
    return [
        s
        for s in STORE.scores.values()
        if s["application_id"] == application_id and s["stage"] == "NATIONAL"
    ]


def national_averages(application_id):
    """avg_f/avg_c/avg_l each rounded half-up to 2dp independently, then the
    weighted sum rounded half-up to 2dp. Requires at least one score."""
    scores = national_scores(application_id)
    n = len(scores)
    avg_f = q2(Decimal(sum(s["feasibility_score"] for s in scores)) / n)
    avg_c = q2(Decimal(sum(s["country_fit_score"] for s in scores)) / n)
    avg_l = q2(Decimal(sum(s["language_score"] for s in scores)) / n)
    weighted = q2(
        Decimal(WEIGHT_FEASIBILITY) * avg_f
        + Decimal(WEIGHT_COUNTRY_FIT) * avg_c
        + Decimal(WEIGHT_LANGUAGE) * avg_l
    )
    return avg_f, avg_c, avg_l, weighted


def maybe_store_weighted(application):
    """Once the national quorum is reached, (re)compute and store the
    application.national_weighted_score over all NATIONAL-stage scores."""
    if len(national_scores(application["id"])) >= NATIONAL_QUORUM:
        _, _, _, weighted = national_averages(application["id"])
        application["national_weighted_score"] = float(weighted)
        bump(application)


# ---------------------------------------------------------------------------
# Grant confirmation (PRD 3.6 final variant + dependent allowance cap)
# ---------------------------------------------------------------------------

def confirm_grant(grant, application, start_dt, end_dt):
    program = STORE.programs[application["country_program_id"]]
    band = None
    accepted = [
        r
        for r in STORE.rounds.values()
        if r["application_id"] == application["id"] and r["status"] == "ACCEPTED"
    ]
    if accepted:
        band = accepted[0]["institution_band"]
    duration = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    f_monthly = (
        program["monthly_stipend_high_cents"]
        if band == "HIGH"
        else program["monthly_stipend_standard_cents"]
    )
    # Pinned order: base total EXCLUDES the dependent allowance.
    base_total = (f_monthly + program["health_benefit_monthly_cents"]) * duration + program[
        "travel_allowance_cents"
    ]
    dep_raw = (
        program["dependent_allowance_monthly_cents"]
        * min(application["dependents_count"], DEPENDENT_CAP)
        * duration
    )
    dep_cap = round_half_up_int(Decimal(DEP_CAP_PCT_OF_BASE) * Decimal(base_total))
    dep_final = min(dep_raw, dep_cap)
    grant["awarded_band"] = band
    grant["duration_months"] = duration
    grant["start_date"] = fmt(start_dt)
    grant["end_date"] = fmt(end_dt)
    grant["final_monthly_stipend_cents"] = f_monthly
    grant["final_total_cents"] = base_total + dep_final
    grant["status"] = "CONFIRMED"
    bump(grant)
    application["status"] = "AWARDED"
    bump(application)


# ---------------------------------------------------------------------------
# Grant lifecycle cascades (PRD 3.7 / 3.8)
# ---------------------------------------------------------------------------

def activate_grant(grant):
    start = parse_iso(grant["start_date"])
    end = parse_iso(grant["end_date"])
    grant["interim_report_due_date"] = fmt(add_months(start, INTERIM_REPORT_DUE_MONTHS))
    grant["final_report_due_date"] = fmt(end + timedelta(days=FINAL_REPORT_DUE_DAYS))
    grant["status"] = "ACTIVE"
    bump(grant)
    visa = visa_of_grant(grant["id"])
    if visa is not None and visa["status"] == "ISSUED":
        visa["status"] = "ACTIVE"
        bump(visa)


def _open_residency_accrual(grant, accrual_start_iso):
    """Ledger PENDING -> ACCRUING, only when subject to home residency (the
    NOT_REQUIRED ledger never passes through PENDING)."""
    visa = visa_of_grant(grant["id"])
    if visa is None:
        return
    ledger = ledger_of_visa(visa["id"])
    if ledger is not None and ledger["status"] == "PENDING":
        ledger["status"] = "ACCRUING"
        ledger["accrual_start_date"] = accrual_start_iso
        bump(ledger)


def create_alumni_profile(grant, terminated_early):
    application = STORE.applications[grant["application_id"]]
    profile = {
        "applicant_id": application["applicant_id"],
        "grant_id": grant["id"],
        "terminated_early": terminated_early,
        "compliance_strikes": grant["compliance_strikes"],
    }
    stamp_new(profile)
    STORE.alumni[profile["id"]] = profile
    return profile


def complete_grant(grant):
    grant["status"] = "COMPLETED"
    bump(grant)
    visa = visa_of_grant(grant["id"])
    if visa is not None and visa["status"] == "ACTIVE":
        visa["status"] = "COMPLETED"
        bump(visa)
    _open_residency_accrual(grant, grant["end_date"])
    create_alumni_profile(grant, terminated_early=False)


def terminate_grant(grant, reason=None):
    """Early termination reconciliation (pinned rounding order: round the
    monthly rate first, then multiply; the adjustment absorbs the remainder)."""
    clock = now()
    start_date = parse_iso(grant["start_date"]).date()
    served_days = (clock.date() - start_date).days
    served_months = served_days // DAYS_PER_MONTH
    duration = grant["duration_months"]
    unserved_months = duration - served_months
    monthly_rate = round_half_up_int(
        Decimal(grant["final_total_cents"]) / Decimal(duration)
    )
    repayment = unserved_months * monthly_rate
    earned = served_months * monthly_rate
    grant["earned_cents"] = earned
    grant["repayment_cents"] = repayment
    grant["reconciliation_adjustment_cents"] = (
        grant["final_total_cents"] - earned - repayment
    )
    if reason is not None:
        grant["termination_reason"] = reason
    grant["status"] = "TERMINATED_EARLY"
    bump(grant)
    visa = visa_of_grant(grant["id"])
    if visa is not None and visa["status"] == "ACTIVE":
        visa["status"] = "ENDED_EARLY"
        bump(visa)
    _open_residency_accrual(grant, fmt(clock))
    create_alumni_profile(grant, terminated_early=True)
    # Any still-OPEN incident of this grant is resolved with outcome TERMINATE.
    for incident in STORE.incidents.values():
        if incident["grant_id"] == grant["id"] and incident["status"] == "OPEN":
            incident["status"] = "RESOLVED"
            incident["resolved_at"] = now_iso()
            incident["outcome"] = "TERMINATE"
            bump(incident)


def resolve_incident(incident, outcome):
    """Resolve an OPEN incident. RESUME shifts the grant end_date and recomputes
    the final report due date; TERMINATE runs the full termination cascade."""
    clock = now()
    incident["status"] = "RESOLVED"
    incident["resolved_at"] = fmt(clock)
    incident["outcome"] = outcome
    grant = STORE.grants[incident["grant_id"]]
    if outcome == "RESUME":
        days = (clock.date() - parse_iso(incident["opened_at"]).date()).days
        incident["suspension_days"] = days
        bump(incident)
        new_end = parse_iso(grant["end_date"]) + timedelta(days=days)
        grant["end_date"] = fmt(new_end)
        grant["final_report_due_date"] = fmt(
            new_end + timedelta(days=FINAL_REPORT_DUE_DAYS)
        )
        grant["suspension_days_total"] = grant.get("suspension_days_total", 0) + days
        if grant["status"] == "SUSPENDED":
            grant["status"] = "ACTIVE"
        bump(grant)
    else:  # TERMINATE
        bump(incident)
        terminate_grant(grant)


# ---------------------------------------------------------------------------
# Alumni engagement (PRD 3.9; recomputed on every read)
# ---------------------------------------------------------------------------

def residency_status_of_grant(grant_id):
    visa = visa_of_grant(grant_id)
    if visa is None:
        return "NOT_REQUIRED"
    ledger = ledger_of_visa(visa["id"])
    if ledger is None:
        return "NOT_REQUIRED"
    return ledger["status"]


def _clamp_points(points):
    return max(0, min(100, points))


def alumni_live_fields(profile):
    """Live-computed surface of an AlumniProfile: both engagement-index
    variants, the mirrored residency status, and follow-on eligibility."""
    reports = [r for r in STORE.reports.values() if r["grant_id"] == profile["grant_id"]]
    n_provisional = sum(1 for r in reports if r["status"] in ("SUBMITTED", "ACCEPTED"))
    n_certified = sum(1 for r in reports if r["status"] == "ACCEPTED")
    strikes = profile["compliance_strikes"]
    provisional = _clamp_points(
        ENGAGEMENT_BASE_POINTS + REPORT_ACCEPT_POINTS * n_provisional - STRIKE_PENALTY_POINTS * strikes
    )
    certified = _clamp_points(
        ENGAGEMENT_BASE_POINTS + REPORT_ACCEPT_POINTS * n_certified - STRIKE_PENALTY_POINTS * strikes
    )
    residency = residency_status_of_grant(profile["grant_id"])
    eligible = (
        not profile["terminated_early"]
        and strikes < MAX_COMPLIANCE_STRIKES
        and residency in ("FULFILLED", "WAIVED", "NOT_REQUIRED")
    )
    return {
        "engagement_index_provisional": provisional,
        "engagement_index_certified": certified,
        "residency_status": residency,
        "follow_on_eligible": "ELIGIBLE" if eligible else "INELIGIBLE",
    }


def latest_follow_on_eligible(applicant_id):
    """follow_on_eligible of the applicant's latest AlumniProfile by
    created_at (insertion order breaks same-instant ties); None if none."""
    profiles = [p for p in STORE.alumni.values() if p["applicant_id"] == applicant_id]
    if not profiles:
        return None
    profiles.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return alumni_live_fields(profiles[-1])["follow_on_eligible"]
