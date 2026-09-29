"""Derived fields, calculations, cascades and enum vocabularies.

Every formula here is transcribed from PRD.md sections 2.7, 2.9 and 3.1 - 3.9.
All money and score arithmetic runs through Decimal with ROUND_HALF_UP.
"""

from decimal import Decimal, ROUND_HALF_UP

from store import db, now, now_str, touch

# --------------------------------------------------------------------------
# enum vocabularies
# --------------------------------------------------------------------------

RECORD_CATEGORIES = [
    "DRUG_OFFENSE", "PROPERTY_OFFENSE", "VIOLENT_OFFENSE",
    "FINANCIAL_OFFENSE", "DUI", "OTHER",
]
DOCUMENT_TYPES = [
    "STATE_ID", "SSN_CARD", "BIRTH_CERTIFICATE", "WORK_HISTORY",
    "MEDICAID_APPLICATION", "DD214",
]
DOMAIN_SCORE_KEYS = [
    "housing_score", "transportation_score", "health_score",
    "work_history_score", "documentation_score",
]
HOUSING_PLAN_TYPES = [
    "FAMILY_REUNIFICATION", "TRANSITIONAL_HOUSING", "SHELTER",
    "INDEPENDENT_LEASE",
]
TRANSPORTATION_PLAN_TYPES = [
    "TRANSIT_PASS", "OWN_VEHICLE", "EMPLOYER_SHUTTLE",
    "RIDE_SHARE_STIPEND", "NONE",
]
HEALTH_COVERAGE_TARGETS = ["MEDICAID", "MARKETPLACE", "EMPLOYER_PLAN", "VA", "NONE"]
PARTICIPANT_STAGES = [
    "PRE_RELEASE", "RELEASE_READY", "POST_RELEASE", "PLACED", "RETENTION",
    "EXITED",
]
BARRIER_TIERS = ["LOW", "MODERATE", "HIGH"]
ENGAGEMENT_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
SUSPENSION_TO_STATUSES = ["SUSPENDED", "LIFTED"]
LICENSE_RELIEF_STATES = [
    "NONE", "PETITION_SUBMITTED", "INFO_REQUESTED", "RELIEF_GRANTED",
    "PETITION_DENIED", "PETITION_WITHDRAWN",
]
EXIT_REASONS = [
    "EMPLOYED_STABLE", "PROGRAM_COMPLETE", "DISENGAGED",
    "RETURNED_TO_CUSTODY", "OTHER",
]
SUPERVISION_TYPES = ["PROBATION", "PAROLE", "POST_RELEASE_CONTROL"]
SUPERVISION_STATUSES = ["PENDING_CONTACT", "ACTIVE", "DISCHARGED", "REVOKED"]
WORK_AUTH_STATUSES = ["NOT_REQUESTED", "APPROVED", "SUSPENDED", "DENIED"]
WORK_AUTH_DECISIONS = ["APPROVED", "DENIED", "SUSPENDED"]
INDUSTRIES = [
    "MANUFACTURING", "CONSTRUCTION", "HOSPITALITY", "LOGISTICS", "HEALTHCARE",
    "RETAIL", "SKILLED_TRADES",
]
PARTNERSHIP_STATUSES = ["PROSPECT", "ENGAGED", "ACTIVE", "SUSPENDED", "TERMINATED"]
JOB_OPENING_STATUSES = ["OPEN", "FILLED", "CLOSED"]
SUBSIDY_TRACKS = ["NONE", "SUBSIDIZED_WORK_EXPERIENCE"]
EMPLOYMENT_STATUSES = ["OFFERED", "ACTIVE", "DECLINED", "SEPARATED"]
BONDING_STATUSES = ["NONE", "REQUESTED", "BONDED", "CLAIMED", "EXPIRED"]
SCHEDULE_COMPLIANCES = ["COMPLIANT", "OUT_OF_COMPLIANCE"]
OFFER_RESPONSES = ["ACCEPTED", "DECLINED"]
SEPARATION_REASONS = [
    "VOLUNTARY_QUIT", "TERMINATED_FOR_CAUSE", "LAYOFF", "SCHEDULE_CONFLICT",
    "RETURNED_TO_CUSTODY", "CONTRACT_END",
]
RETENTION_OUTCOMES = ["RETAINED", "SEPARATED", "UNREACHABLE"]
RECIDIVISM_EVENTS = [
    "NONE", "NEW_ARREST", "TECHNICAL_VIOLATION", "REVOCATION",
    "RETURN_TO_CUSTODY",
]
MILESTONE_DAYS = [30, 60, 90]
WORK_SHIFT_STATUSES = ["SCHEDULED", "WORKED", "CANCELLED", "CONFLICTED"]
CONFLICT_REASONS = ["WORK_AUTHORIZATION_SUSPENDED", "SUPERVISION_REVOKED"]
GRANT_CATEGORIES = [
    "TOOLS", "UNIFORM", "TRANSIT_PASS", "ID_FEE", "LICENSE_FEE", "WAGE_SUBSIDY",
]
SUPPORT_CATEGORIES = ["TOOLS", "UNIFORM", "TRANSIT_PASS", "ID_FEE", "LICENSE_FEE"]
FUNDING_POSTURES = ["OPEN", "RESTRICTED", "EXHAUSTED"]
SUPPORT_STATUSES = [
    "SUBMITTED", "INFO_REQUESTED", "APPROVED", "DEFERRED", "DISBURSED",
    "DENIED", "VOIDED",
]
REVIEW_DECISIONS = ["APPROVED", "DENIED", "INFO_REQUESTED"]
SETTLE_STATUSES = ["DISBURSED", "VOIDED"]
SESSION_TYPES = [
    "DISCLOSURE_COACHING", "INTERVIEW_PRACTICE", "RESUME_LAB",
    "DIGITAL_LITERACY",
]
SESSION_STATUSES = ["SCHEDULED", "HELD", "CANCELLED"]
ENROLLMENT_STATUSES = ["ENROLLED", "ATTENDED", "NO_SHOW", "WITHDRAWN"]
OUTCOME_VARIANTS = ["COHORT", "EXIT_BASED"]

# --------------------------------------------------------------------------
# numeric constants
# --------------------------------------------------------------------------

READINESS_DOC_THRESHOLD_PCT = Decimal("80.0")
TIER_HIGH_MIN = Decimal("65.0")
TIER_MODERATE_MIN = Decimal("35.0")
BARRIER_WEIGHTS = {
    "housing_score": Decimal("0.30"),
    "transportation_score": Decimal("0.20"),
    "health_score": Decimal("0.15"),
    "work_history_score": Decimal("0.25"),
    "documentation_score": Decimal("0.10"),
}
WAGE_TARGET_CENTS = Decimal(2000)
MATCH_SCORE_MAX = 100
SUBSIDY_TIER1_HOURS = Decimal(80)
SUBSIDY_TIER2_HOURS = Decimal(160)
SUBSIDY_TIER1_RATE = Decimal("0.50")
SUBSIDY_TIER2_RATE = Decimal("0.25")
SUBSIDY_TIER3_RATE = Decimal("0.00")
SUBSIDY_PLACEMENT_CAP_CENTS = 120000
COMMUTE_BUFFER_MINUTES = 45
COVERAGE_RATES = {
    "TOOLS": Decimal("0.85"),
    "UNIFORM": Decimal("0.90"),
    "TRANSIT_PASS": Decimal("1.00"),
    "ID_FEE": Decimal("1.00"),
    "LICENSE_FEE": Decimal("0.60"),
}
ADMIN_FEE_T1_MAX_CENTS = 5000
ADMIN_FEE_T2_MAX_CENTS = 20000
ADMIN_FEE_RATE_T1 = Decimal("0.00")
ADMIN_FEE_RATE_T2 = Decimal("0.03")
ADMIN_FEE_RATE_T3 = Decimal("0.05")
RESTRICTED_FLOOR_RATE = Decimal("0.15")
INFO_MAX_ROUNDS = 2
PETITION_MAX_ROUNDS = 2
SUPPORT_MAX_LINE_ITEMS = 6


# --------------------------------------------------------------------------
# rounding helpers
# --------------------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    return int(rhu(value, 0))


def pct1(value):
    return float(rhu(value, 1))


def hours2(value):
    return float(rhu(value, 2))


# --------------------------------------------------------------------------
# time helpers on stored values
# --------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402


def as_dt(value):
    """Parse a stored ISO instant (always ...sssZ) into an aware datetime."""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
        tzinfo=timezone.utc)


def as_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def exact_minutes(dt):
    """Minutes from UTC midnight as a Decimal, keeping seconds precision."""
    return (Decimal(dt.hour * 60 + dt.minute)
            + Decimal(dt.second) / Decimal(60)
            + Decimal(dt.microsecond) / Decimal(60000000))


# --------------------------------------------------------------------------
# collection accessors
# --------------------------------------------------------------------------

def rows(collection):
    return sorted(collection.values(), key=lambda row: row["_seq"])


def placements_of_participant(participant_id):
    return [p for p in rows(db.placements)
            if p["participant_id"] == participant_id]


def placements_of_opening(job_opening_id):
    return [p for p in rows(db.placements)
            if p["job_opening_id"] == job_opening_id]


def openings_of_partnership(partnership_id):
    return [o for o in rows(db.job_openings)
            if o["partnership_id"] == partnership_id]


def placements_of_partnership(partnership_id):
    opening_ids = {o["id"] for o in openings_of_partnership(partnership_id)}
    return [p for p in rows(db.placements) if p["job_opening_id"] in opening_ids]


def shifts_of_placement(placement_id):
    return [s for s in rows(db.work_shifts) if s["placement_id"] == placement_id]


def shifts_of_participant(participant_id):
    placement_ids = {p["id"] for p in placements_of_participant(participant_id)}
    return [s for s in rows(db.work_shifts) if s["placement_id"] in placement_ids]


def enrollments_of_session(session_id):
    return [e for e in rows(db.enrollments) if e["session_id"] == session_id]


def enrollments_of_participant(participant_id):
    return [e for e in rows(db.enrollments)
            if e["participant_id"] == participant_id]


def support_requests_of_grant(grant_id):
    return [r for r in rows(db.support_requests) if r["grant_id"] == grant_id]


def support_requests_of_participant(participant_id):
    return [r for r in rows(db.support_requests)
            if r["participant_id"] == participant_id]


def placements_of_grant(grant_id):
    return [p for p in rows(db.placements) if p["grant_id"] == grant_id]


def opening_of_placement(placement):
    return db.job_openings.get(placement["job_opening_id"])


def partnership_of_opening(opening):
    return db.partnerships.get(opening["partnership_id"])


def partnership_of_placement(placement):
    opening = opening_of_placement(placement)
    return partnership_of_opening(opening) if opening else None


def supervision_cases_of_participant(participant_id):
    return [c for c in rows(db.supervision_cases)
            if c["participant_id"] == participant_id]


def apply(row, field, value):
    """Assign a field, reporting whether the stored value actually moved."""
    if row.get(field) == value:
        return False
    row[field] = value
    return True


# --------------------------------------------------------------------------
# participant derived fields
# --------------------------------------------------------------------------

def recompute_doc_completeness(participant):
    required = participant.get("required_document_types") or []
    verified = participant.get("verified_document_types") or []
    if not required:
        return apply(participant, "doc_completeness_pct", 0.0)
    matched = len([t for t in verified if t in required])
    value = pct1(Decimal(100) * Decimal(matched) / Decimal(len(required)))
    return apply(participant, "doc_completeness_pct", value)


def recompute_barrier(participant):
    scores = participant.get("assessment_domain_scores")
    if not scores:
        changed = apply(participant, "barrier_score", None)
        return apply(participant, "barrier_tier", None) or changed
    raw = Decimal(0)
    for key, weight in BARRIER_WEIGHTS.items():
        raw += weight * Decimal(int(scores[key]))
    score = rhu(raw / Decimal(4) * Decimal(100), 1)
    if score >= TIER_HIGH_MIN:
        tier = "HIGH"
    elif score >= TIER_MODERATE_MIN:
        tier = "MODERATE"
    else:
        tier = "LOW"
    changed = apply(participant, "barrier_score", float(score))
    return apply(participant, "barrier_tier", tier) or changed


def posture_of(participant):
    if (participant["suspension_status"] == "SUSPENDED"
            or participant["stage"] == "EXITED"):
        return "FROZEN"
    for placement in placements_of_participant(participant["id"]):
        if placement["schedule_compliance"] == "OUT_OF_COMPLIANCE":
            return "RESTRICTED"
    if participant["license_relief_status"] == "PETITION_DENIED":
        return "RESTRICTED"
    return "OPEN"


def recompute_posture(participant):
    return apply(participant, "engagement_posture", posture_of(participant))


def readiness_met(participant):
    return bool(
        dec(participant["doc_completeness_pct"]) >= READINESS_DOC_THRESHOLD_PCT
        and participant["barrier_score"] is not None
        and participant["release_plan_status"] == "APPROVED"
        and participant["suspension_status"] == "NONE"
    )


def evaluate_readiness(participant):
    """PRE_RELEASE -> RELEASE_READY when the four-part predicate holds."""
    if participant["stage"] == "PRE_RELEASE" and readiness_met(participant):
        return apply(participant, "stage", "RELEASE_READY")
    return False


def sync_participant(participant):
    """Reconcile the participant's derived fields; bump the row if it moved."""
    changed = recompute_doc_completeness(participant)
    changed = recompute_posture(participant) or changed
    if changed:
        touch(participant)
    return changed


def active_placement_count_of_participant(participant_id):
    return len([p for p in placements_of_participant(participant_id)
                if p["employment_status"] == "ACTIVE"])


# --------------------------------------------------------------------------
# wage subsidy — calculations.wage_subsidy_total
# --------------------------------------------------------------------------

def _shift_amount(shift_hours, wage, cumulative):
    """One shift's subsidy: segments summed, then rounded once."""
    total = Decimal(0)
    remaining = shift_hours
    position = cumulative
    ladder = (
        (SUBSIDY_TIER1_HOURS, SUBSIDY_TIER1_RATE),
        (SUBSIDY_TIER2_HOURS, SUBSIDY_TIER2_RATE),
        (None, SUBSIDY_TIER3_RATE),
    )
    for boundary, rate in ladder:
        if remaining <= 0:
            break
        if boundary is None:
            segment = remaining
        else:
            if position >= boundary:
                continue
            segment = min(remaining, boundary - position)
        total += segment * wage * rate
        position += segment
        remaining -= segment
    return cents(total), position


def subsidy_total(placement, statuses, extra=None):
    """(capped, uncapped) subsidy over the placement's qualifying shifts."""
    if placement["subsidy_track"] != "SUBSIDIZED_WORK_EXPERIENCE":
        return 0, 0
    opening = opening_of_placement(placement)
    if opening is None:
        return 0, 0
    wage = Decimal(int(opening["hourly_wage_cents"]))
    qualifying = [s for s in shifts_of_placement(placement["id"])
                  if s["status"] in statuses]
    if extra is not None:
        qualifying = qualifying + [extra]
    qualifying.sort(key=lambda s: (s["starts_at"], s["_seq"]))
    running = Decimal(0)
    total = 0
    for shift in qualifying:
        amount, running = _shift_amount(
            dec(shift["scheduled_hours"]), wage, running)
        total += amount
    return min(total, SUBSIDY_PLACEMENT_CAP_CENTS), total


def compliance_of(placement):
    for shift in shifts_of_placement(placement["id"]):
        if shift["status"] == "CONFLICTED":
            return "OUT_OF_COMPLIANCE"
    return "COMPLIANT"


def sync_placement(placement):
    changed = apply(placement, "schedule_compliance", compliance_of(placement))
    if placement["employment_status"] not in ("SEPARATED", "DECLINED"):
        projected = subsidy_total(placement, ("SCHEDULED", "WORKED"))[0]
        actual = subsidy_total(placement, ("WORKED",))[0]
        changed = apply(placement, "projected_subsidy_cents", projected) or changed
        changed = apply(placement, "actual_subsidy_cents", actual) or changed
    if changed:
        touch(placement)
    return changed
