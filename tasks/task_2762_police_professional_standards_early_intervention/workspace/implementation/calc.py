"""Calculation rules (PRD section 3 / scaffold section 1.3)."""
from decimal import Decimal

from core import (
    D,
    add_days,
    db,
    floor_days,
    floor_div_seconds,
    rhu,
    rhu_int,
    sort_created,
)

# --- complaint_classification_and_routing ----------------------------------
SEVERE_ALLEGATION_TYPES = ("EXCESSIVE_FORCE", "UNLAWFUL_SEARCH", "UNTRUTHFULNESS")
MODERATE_ALLEGATION_TYPES = ("NEGLECT_OF_DUTY", "PURSUIT_VIOLATION")
MINOR_ALLEGATION_TYPES = ("DISCOURTESY",)
ALLEGATION_TYPES = (
    "EXCESSIVE_FORCE",
    "UNLAWFUL_SEARCH",
    "UNTRUTHFULNESS",
    "NEGLECT_OF_DUTY",
    "PURSUIT_VIOLATION",
    "DISCOURTESY",
)
PRIORITY_BY_CLASSIFICATION = {"CLASS_I": 1, "CLASS_II": 2, "CLASS_III": 3}
MAX_RECLASSIFICATIONS = 2
CLASSIFICATIONS = ("CLASS_I", "CLASS_II", "CLASS_III")

# --- investigation_window --------------------------------------------------
STATUTORY_DAYS_BY_CLASSIFICATION = {"CLASS_I": 180, "CLASS_II": 121, "CLASS_III": 90}
REQUIRED_CERTIFICATION_BY_CLASSIFICATION = {"CLASS_I": 3, "CLASS_II": 2, "CLASS_III": 1}
STATUTE_DAYS = 365

# --- interview windows -----------------------------------------------------
OFFICER_REST_BUFFER_MINUTES = 60
MIN_NOTICE_HOURS = 48
MAX_POSTPONEMENTS = 2
APPEAL_WINDOW_DAYS = 15

# --- preponderance ---------------------------------------------------------
PREPONDERANCE_THRESHOLD_PCT = Decimal("50.00")

# --- discipline matrix -----------------------------------------------------
MATRIX_BASE_DAYS = {
    "A": [30, 60, 120],
    "B": [10, 20, 45],
    "C": [3, 7, 15],
    "D": [1, 2, 5],
}
AGGRAVATOR_DAYS_EACH = 5
MITIGATION_PCT_BY_PRE_CREDIT_TIER = (
    (10, Decimal("0.10")),
    (30, Decimal("0.20")),
    (60, Decimal("0.25")),
    (None, Decimal("0.30")),
)
MAX_CREDITED_MITIGATORS = 2
CLASS_A_FLOOR_DAYS = 30
GLOBAL_CAP_DAYS = 180
PRIOR_LOOKBACK_DAYS = 1095

# --- back pay --------------------------------------------------------------
PAY_PERIOD_DAYS = 10
ANNUAL_WORK_DAYS = 260
INTEREST_ANNUAL_PCT = Decimal("0.05")
INTEREST_YEAR_DAYS = 365

# --- EIS -------------------------------------------------------------------
EVENT_BASE_WEIGHTS = {
    "USE_OF_FORCE": Decimal(3),
    "PURSUIT": Decimal(2),
    "SICK_LEAVE_DAY": Decimal(1),
    "COMPLAINT_INTAKE": Decimal(1),
    "COMPLAINT_SUSTAINED": Decimal(4),
}
EVENT_TYPES = tuple(EVENT_BASE_WEIGHTS.keys())
SEVERITY_MULTIPLIERS = {
    "LEVEL_1": Decimal("1.0"),
    "LEVEL_2": Decimal("1.5"),
    "LEVEL_3": Decimal("2.0"),
    "NA": Decimal("1.0"),
}
SEVERITY_CODES = tuple(SEVERITY_MULTIPLIERS.keys())
WINDOW_DAYS = 365
DECAY_FRESH_DAYS = 180
DECAY_STALE_FACTOR = Decimal("0.5")
ASSIGNMENT_MULTIPLIERS = {
    "PATROL": Decimal("1.0"),
    "INVESTIGATIVE": Decimal("0.8"),
    "ADMIN": Decimal("0.6"),
}
ASSIGNMENT_TYPES = tuple(ASSIGNMENT_MULTIPLIERS.keys())
INDICATOR_ORDER = ("FORCE_COUNT", "PURSUIT_COUNT", "COMPLAINT_COUNT", "SICK_LEAVE_DAYS")
INDICATOR_THRESHOLDS = {
    "FORCE_COUNT": 3,
    "PURSUIT_COUNT": 2,
    "COMPLAINT_COUNT": 3,
    "SICK_LEAVE_DAYS": 12,
}
SCORE_SCALE = Decimal("2.5")
INDICATOR_BONUS_EACH = 10
SCORE_CEILING = 100
PEER_RELATIVE_SCALE = Decimal("40")
ALERT_LEVEL_THRESHOLDS = {"WATCH": 30, "ALERT": 50, "CRITICAL": 75}
ALERT_REVIEW_DAYS = 30
BAND_ORDER = ("NONE", "WATCH", "ALERT", "CRITICAL")
SCORE_VARIANTS = ("ROLLING_12M", "PEER_RELATIVE")

# --- plan compliance ------------------------------------------------------
CONCERN_PENALTY_EACH = 15
PLAN_SUCCESS_SCORE = Decimal(80)
INTERVENTION_TYPES = (
    "RETRAINING",
    "COUNSELING",
    "PEER_REVIEW",
    "REASSIGNMENT",
    "EAP_REFERRAL",
)
DURATION_DAYS_CHOICES = (30, 60, 90)

# --- retention ------------------------------------------------------------
RETENTION_DAYS_BY_DISPOSITION = {
    "SUSTAINED": 2555,
    "NOT_SUSTAINED": 1825,
    "UNFOUNDED": 1095,
    "EXONERATED": 1095,
    "POLICY_FAILURE": 1825,
    "WITHDRAWN": 730,
}
GOVERNING_PRECEDENCE = (
    "SUSTAINED",
    "POLICY_FAILURE",
    "NOT_SUSTAINED",
    "EXONERATED",
    "UNFOUNDED",
    "WITHDRAWN",
)
DISCLOSURE_RETENTION_DAYS = 2555

# --- report ---------------------------------------------------------------
SUPPRESSION_MIN_CELL = 3
SUSTAIN_RATE_DECIMALS = 1

# --- enums shared with routes ---------------------------------------------
UNIT_ROLES = ("INTERNAL_AFFAIRS", "PATROL_DIVISION", "SPECIAL_OPERATIONS")
RANKS = ("OFFICER", "SERGEANT", "LIEUTENANT", "CAPTAIN")
DEMOGRAPHIC_CODES = ("DG_A", "DG_B", "DG_C", "DG_D")
COMPLAINANT_DEMOGRAPHIC_CODES = ("DG_A", "DG_B", "DG_C", "DG_D", "UNKNOWN")
EMPLOYMENT_STATUSES = ("ACTIVE", "SUSPENDED", "RELIEVED_OF_DUTY", "SEPARATED")
INTAKE_CHANNELS = ("PUBLIC", "SUPERVISOR", "ANONYMOUS")
COMPLAINT_STATUSES = (
    "INTAKE_RECEIVED",
    "SCREENING",
    "CLASSIFIED",
    "UNDER_INVESTIGATION",
    "ADJUDICATION",
    "CLOSED",
    "REJECTED_INTAKE",
    "WITHDRAWN",
    "PURGED",
)
OFFENSE_CLASSES = ("A", "B", "C", "D")
DISPOSITIONS = (
    "PENDING",
    "SUSTAINED",
    "NOT_SUSTAINED",
    "UNFOUNDED",
    "EXONERATED",
    "POLICY_FAILURE",
    "WITHDRAWN",
    "OVERTURNED_ON_APPEAL",
)
COMMANDER_DISPOSITIONS = (
    "SUSTAINED",
    "NOT_SUSTAINED",
    "UNFOUNDED",
    "EXONERATED",
    "POLICY_FAILURE",
)
INVESTIGATION_STATUSES = (
    "UNASSIGNED",
    "ASSIGNED",
    "IN_PROGRESS",
    "TOLLED",
    "PENDING_REVIEW",
    "CLOSED",
    "VOIDED",
)
INVESTIGATION_OPEN_STATUSES = ("ASSIGNED", "IN_PROGRESS", "TOLLED", "PENDING_REVIEW")
REPRESENTATION_STATUSES = ("WAIVED", "REP_REQUESTED", "REP_PRESENT")
SESSION_STATUSES = ("SCHEDULED", "HELD", "POSTPONED", "CANCELLED")
DISCIPLINE_STATUSES = ("PROPOSED", "IMPOSED", "APPEALED", "UPHELD", "MODIFIED", "OVERTURNED")
FORUMS = ("ARBITRATION", "CIVIL_SERVICE")
APPEAL_STATUSES = ("FILED", "HEARD", "DECIDED")
APPEAL_OUTCOMES = ("PENDING", "UPHELD", "MODIFIED", "OVERTURNED")
DECIDE_OUTCOMES = ("UPHELD", "MODIFIED", "OVERTURNED")
REINSTATEMENT_STATUSES = ("PENDING", "FINALIZED")
TRIGGER_SOURCES = ("EVENT_INGEST", "EIS_RUN", "PLAN_ESCALATION", "DISPOSITION_CASCADE")
ALERT_LEVELS = ("WATCH", "ALERT", "CRITICAL")
OFFICER_ALERT_LEVELS = ("NONE", "WATCH", "ALERT", "CRITICAL")
ALERT_STATUSES = (
    "OPEN",
    "PLAN_REQUIRED",
    "PLAN_ACTIVE",
    "CLOSED_SUCCESS",
    "ESCALATED",
    "DISMISSED",
)
ALERT_OPEN_STATUSES = ("OPEN", "PLAN_REQUIRED", "PLAN_ACTIVE", "ESCALATED")
PLAN_STATUSES = ("DRAFT", "ACTIVE", "CLOSED_SUCCESS", "ESCALATED")
CHECKIN_OUTCOMES = ("PENDING", "SATISFACTORY", "CONCERN")
CHECKIN_COMPLETE_OUTCOMES = ("SATISFACTORY", "CONCERN")
CHECKIN_STATUSES = ("PENDING", "COMPLETED", "MISSED")
DISCLOSURE_BASES = (
    "UNTRUTHFULNESS_SUSTAINED",
    "BIAS_SUSTAINED",
    "EVIDENCE_MISHANDLING_SUSTAINED",
)
DISCLOSURE_STATUSES = ("ACTIVE", "EXPUNGED", "EXPIRED")
BREAKDOWNS = ("DEMOGRAPHIC", "CHANNEL")


# ===========================================================================
# 1. Complaint classification and routing
# ===========================================================================
def severity_band(reported_types, alleged_injury):
    if alleged_injury or any(t in SEVERE_ALLEGATION_TYPES for t in reported_types):
        return "CLASS_I"
    if any(t in MODERATE_ALLEGATION_TYPES for t in reported_types):
        return "CLASS_II"
    return "CLASS_III"


def internal_affairs_unit():
    pool = [u for u in db.units.values() if u["unit_role"] == "INTERNAL_AFFAIRS"]
    if not pool:
        return None
    return sort_created(pool)[0]


def routing_target(classification, screening_required, subject_unit_id):
    ia_unit = internal_affairs_unit()
    if classification == "CLASS_I" or screening_required:
        return ia_unit["id"] if ia_unit else None
    subject_unit = db.units.get(subject_unit_id)
    if subject_unit is not None and subject_unit.get("intake_enabled"):
        return subject_unit_id
    return ia_unit["id"] if ia_unit else None


def classify_and_route(reported_types, alleged_injury, intake_channel, subject_unit_id,
                       classification_override=None):
    """Runs the five-step rule. Returns (classification, priority,
    screening_required, assigned_unit_id)."""
    classification = severity_band(reported_types, alleged_injury)
    if classification_override:
        classification = classification_override
    priority = PRIORITY_BY_CLASSIFICATION[classification]
    screening_required = classification == "CLASS_III" and intake_channel == "ANONYMOUS"
    assigned_unit_id = routing_target(classification, screening_required, subject_unit_id)
    return classification, priority, screening_required, assigned_unit_id


def intake_reference_code(sequence):
    return "CMP-%06d" % sequence


# ===========================================================================
# 2. Investigation window
# ===========================================================================
def investigation_window(classification, received_at, tolled_days):
    statutory_days = STATUTORY_DAYS_BY_CLASSIFICATION[classification]
    required_cert = REQUIRED_CERTIFICATION_BY_CLASSIFICATION[classification]
    due_at = add_days(received_at, statutory_days + tolled_days)
    return statutory_days, required_cert, due_at


def is_overdue(investigation):
    if investigation["status"] in ("CLOSED", "VOIDED"):
        return False
    due_at = investigation.get("due_at")
    if due_at is None:
        return False
    return db.clock > due_at


# ===========================================================================
# 3. Investigator selection
# ===========================================================================
def _subject_officers(complaint_id):
    ids = set()
    for allegation in db.allegations.values():
        if allegation["complaint_id"] == complaint_id:
            ids.add(allegation["subject_officer_id"])
    return ids


def eligibility_failures(officer, investigation, complaint_id, acting_user_id):
    """Returns the set of failing condition numbers (1..8)."""
    failures = set()
    subject_ids = _subject_officers(complaint_id)
    subject_units = {
        db.officers[oid]["unit_id"] for oid in subject_ids if oid in db.officers
    }
    if not officer.get("is_investigator"):
        failures.add(1)
    if officer["employment_status"] != "ACTIVE":
        failures.add(2)
    if officer["certification_level"] < investigation["required_certification_level"]:
        failures.add(3)
    if not (officer["open_case_load"] < officer["max_case_load"]):
        failures.add(4)
    if officer["id"] in subject_ids:
        failures.add(5)
    if officer["unit_id"] in subject_units:
        failures.add(6)
    if officer["id"] == acting_user_id:
        failures.add(7)
    if officer["id"] == investigation.get("assigned_investigator_officer_id"):
        failures.add(8)
    return failures


def select_investigator(investigation, complaint_id, acting_user_id):
    pool = [
        officer
        for officer in db.officers.values()
        if not eligibility_failures(officer, investigation, complaint_id, acting_user_id)
    ]
    if not pool:
        return None
    pool.sort(
        key=lambda o: (
            o["open_case_load"],
            -o["certification_level"],
            o["badge_number"],
            o["created_at"],
            o["_seq"],
        )
    )
    return pool[0]


# ===========================================================================
# 4. Interview interval rules
# ===========================================================================
def officer_buffer_conflict(subject_officer_id, start, end, exclude_session_id=None):
    from datetime import timedelta

    buffer_delta = timedelta(minutes=OFFICER_REST_BUFFER_MINUTES)
    a1 = start - buffer_delta
    a2 = end + buffer_delta
    for session in db.sessions.values():
        if session["id"] == exclude_session_id:
            continue
        if session["subject_officer_id"] != subject_officer_id:
            continue
        if session["status"] not in ("SCHEDULED", "POSTPONED"):
            continue
        b1 = session["scheduled_start"]
        b2 = session["scheduled_end"]
        if a1 <= b2 and b1 <= a2:
            return True
    return False


def room_overlap_count(hearing_room_id, start, end, exclude_session_id=None):
    count = 0
    for session in db.sessions.values():
        if session["id"] == exclude_session_id:
            continue
        if session["hearing_room_id"] != hearing_room_id:
            continue
        if session["status"] not in ("SCHEDULED", "POSTPONED"):
            continue
        b1 = session["scheduled_start"]
        b2 = session["scheduled_end"]
        if start < b2 and b1 < end:
            count += 1
    return count


def notice_hours(notice_served_at, scheduled_start):
    return floor_div_seconds(scheduled_start - notice_served_at, 3600)


def duration_minutes(start, end):
    return floor_div_seconds(end - start, 60)


# ===========================================================================
# 5. Preponderance
# ===========================================================================
def preponderance(weight_for, weight_against):
    total = D(weight_for) + D(weight_against)
    if total == 0:
        return Decimal("0.00"), False
    support_pct = rhu(D(100) * D(weight_for) / total, 2)
    return support_pct, support_pct > PREPONDERANCE_THRESHOLD_PCT


# ===========================================================================
# 6. Discipline matrix
# ===========================================================================
def prior_sustained_allegations(subject_officer_id, exclude_allegation_id,
                                reference_instant, imposed_only=False):
    lower = add_days(reference_instant, -PRIOR_LOOKBACK_DAYS)
    result = []
    for allegation in db.allegations.values():
        if allegation["id"] == exclude_allegation_id:
            continue
        if allegation["subject_officer_id"] != subject_officer_id:
            continue
        if allegation["disposition"] != "SUSTAINED":
            continue
        disposed_at = allegation.get("disposed_at")
        if disposed_at is None:
            continue
        if not (lower <= disposed_at <= reference_instant):
            continue
        if imposed_only:
            discipline = discipline_for_allegation(allegation["id"])
            if discipline is None:
                continue
            if discipline["status"] not in ("IMPOSED", "UPHELD", "MODIFIED"):
                continue
            effective = discipline.get("effective_days")
            if effective is None or effective < 1:
                continue
        result.append(allegation)
    return result


def discipline_for_allegation(allegation_id):
    for discipline in db.disciplines.values():
        if discipline["allegation_id"] == allegation_id:
            return discipline
    return None


def prior_tier_index(count):
    if count <= 0:
        return 0
    if count == 1:
        return 1
    return 2


def mitigation_pct(pre_credit):
    for max_days, pct in MITIGATION_PCT_BY_PRE_CREDIT_TIER:
        if max_days is None or pre_credit <= max_days:
            return pct
    return MITIGATION_PCT_BY_PRE_CREDIT_TIER[-1][1]


def matrix_days(offense_class, tier_index, aggravator_count, mitigator_count):
    base = MATRIX_BASE_DAYS[offense_class][tier_index]
    pre_credit = base + AGGRAVATOR_DAYS_EACH * aggravator_count
    pct = mitigation_pct(pre_credit)
    credited = min(mitigator_count, MAX_CREDITED_MITIGATORS)
    credit_days = rhu_int(D(pre_credit) * D(credited) * pct)
    net = max(0, pre_credit - credit_days)
    if offense_class == "A":
        net = max(net, CLASS_A_FLOOR_DAYS)
    return min(net, GLOBAL_CAP_DAYS)


# ===========================================================================
# 7. Reinstatement back pay
# ===========================================================================
def back_pay(annual_salary_cents, reversed_days, interim_earnings_cents, days_elapsed):
    full_periods = reversed_days // PAY_PERIOD_DAYS
    remainder_days = reversed_days % PAY_PERIOD_DAYS
    salary = D(annual_salary_cents)
    per_full = rhu_int(salary * D(PAY_PERIOD_DAYS) / D(ANNUAL_WORK_DAYS))
    gross = full_periods * per_full
    if remainder_days > 0:
        gross += rhu_int(salary * D(remainder_days) / D(ANNUAL_WORK_DAYS))
    net = max(0, gross - interim_earnings_cents)
    interest = rhu_int(
        D(net) * INTEREST_ANNUAL_PCT * D(days_elapsed) / D(INTEREST_YEAR_DAYS)
    )
    return gross, net, interest, net + interest


# ===========================================================================
# 8. EIS composite score
# ===========================================================================
def eis_window(reference=None):
    reference = reference or db.clock
    return add_days(reference, -WINDOW_DAYS), reference


def officer_window_events(officer_id, reference=None):
    window_start, window_end = eis_window(reference)
    rows = [
        event
        for event in db.events.values()
        if event["officer_id"] == officer_id
        and window_start < event["occurred_at"] <= window_end
    ]
    rows.sort(key=lambda e: (e["occurred_at"], e["created_at"], e["_seq"]))
    return rows


def weighted_total_for(events, reference=None):
    reference = reference or db.clock
    total = Decimal(0)
    for event in events:
        age_days = floor_days(reference, event["occurred_at"])
        decay = Decimal("1.0") if age_days <= DECAY_FRESH_DAYS else DECAY_STALE_FACTOR
        total += (
            EVENT_BASE_WEIGHTS[event["event_type"]]
            * SEVERITY_MULTIPLIERS[event["severity_code"]]
            * decay
        )
    return total


def breached_indicators_for(events):
    force = sum(1 for e in events if e["event_type"] == "USE_OF_FORCE")
    pursuit = sum(1 for e in events if e["event_type"] == "PURSUIT")
    complaints = sum(
        1
        for e in events
        if e["event_type"] in ("COMPLAINT_INTAKE", "COMPLAINT_SUSTAINED")
    )
    sick = sum(1 for e in events if e["event_type"] == "SICK_LEAVE_DAY")
    counts = {
        "FORCE_COUNT": force,
        "PURSUIT_COUNT": pursuit,
        "COMPLAINT_COUNT": complaints,
        "SICK_LEAVE_DAYS": sick,
    }
    return [
        name for name in INDICATOR_ORDER if counts[name] >= INDICATOR_THRESHOLDS[name]
    ]


def band_for(score):
    value = D(score)
    if value >= ALERT_LEVEL_THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    if value >= ALERT_LEVEL_THRESHOLDS["ALERT"]:
        return "ALERT"
    if value >= ALERT_LEVEL_THRESHOLDS["WATCH"]:
        return "WATCH"
    return "NONE"


def raise_band(band):
    index = BAND_ORDER.index(band) if band in BAND_ORDER else 0
    return BAND_ORDER[min(index + 1, len(BAND_ORDER) - 1)]


def rolling_profile(officer, reference=None):
    events = officer_window_events(officer["id"], reference)
    weighted_total = weighted_total_for(events, reference)
    breached = breached_indicators_for(events)
    multiplier = ASSIGNMENT_MULTIPLIERS[officer["assignment_type"]]
    raw = weighted_total * multiplier * SCORE_SCALE + D(INDICATOR_BONUS_EACH) * D(len(breached))
    clamped = min(D(SCORE_CEILING), max(Decimal(0), raw))
    score = rhu(clamped, 2)
    window_start, window_end = eis_window(reference)
    return {
        "variant": "ROLLING_12M",
        "window_start": window_start,
        "window_end": window_end,
        "event_count": len(events),
        "weighted_total": weighted_total,
        "composite_score": score,
        "alert_level": band_for(score),
        "breached_indicators": breached,
        "peer_pool_size": 0,
        "peer_mean": Decimal(0),
    }


def peer_pool(officer):
    unit = db.units.get(officer.get("unit_id"))
    if unit is None:
        return []
    peer_group_code = unit.get("peer_group_code")
    pool = []
    for other in db.officers.values():
        if other["id"] == officer["id"]:
            continue
        if other["employment_status"] != "ACTIVE":
            continue
        other_unit = db.units.get(other.get("unit_id"))
        if other_unit is None:
            continue
        if other_unit.get("peer_group_code") != peer_group_code:
            continue
        pool.append(other)
    return pool


def peer_relative_profile(officer, reference=None):
    profile = rolling_profile(officer, reference)
    pool = peer_pool(officer)
    profile["variant"] = "PEER_RELATIVE"
    if not pool:
        profile["peer_pool_size"] = 0
        profile["peer_mean"] = Decimal(0)
        return profile
    totals = [
        weighted_total_for(officer_window_events(peer["id"], reference), reference)
        for peer in pool
    ]
    peer_mean = sum(totals, Decimal(0)) / D(len(totals))
    if peer_mean == 0:
        profile["peer_pool_size"] = 0
        profile["peer_mean"] = Decimal(0)
        return profile
    ratio = profile["weighted_total"] / peer_mean
    score = rhu(min(D(SCORE_CEILING), ratio * PEER_RELATIVE_SCALE), 2)
    profile["peer_pool_size"] = len(pool)
    profile["peer_mean"] = peer_mean
    profile["composite_score"] = score
    profile["alert_level"] = band_for(score)
    return profile


def profile_for(officer, variant, reference=None):
    if variant == "PEER_RELATIVE":
        return peer_relative_profile(officer, reference)
    return rolling_profile(officer, reference)


# ===========================================================================
# 9. Check-in schedule and plan compliance
# ===========================================================================
def checkin_due_dates(activated_at, duration_days, required_checkin_count):
    interval_days = duration_days // (required_checkin_count + 1)
    return [
        add_days(activated_at, interval_days * i)
        for i in range(1, required_checkin_count + 1)
    ]


def compliance_score(on_time_checkin_count, required_checkin_count, concern_count):
    if required_checkin_count == 0:
        return Decimal("0.00")
    raw = (
        D(100) * D(on_time_checkin_count) / D(required_checkin_count)
        - D(CONCERN_PENALTY_EACH) * D(concern_count)
    )
    return rhu(max(Decimal(0), raw), 2)


# ===========================================================================
# 10. Retention
# ===========================================================================
def governing_disposition(complaint_id):
    present = set()
    for allegation in db.allegations.values():
        if allegation["complaint_id"] != complaint_id:
            continue
        disposition = allegation["disposition"]
        if disposition == "OVERTURNED_ON_APPEAL":
            disposition = "NOT_SUSTAINED"
        present.add(disposition)
    for candidate in GOVERNING_PRECEDENCE:
        if candidate in present:
            return candidate
    return "WITHDRAWN"


def retention_until_for(complaint_id, closed_at):
    disposition = governing_disposition(complaint_id)
    return add_days(closed_at, RETENTION_DAYS_BY_DISPOSITION[disposition])


# ===========================================================================
# 11. Complaint outcome report
# ===========================================================================
def sustain_rate(sustained, total):
    if total == 0:
        return rhu(Decimal(0), SUSTAIN_RATE_DECIMALS)
    return rhu(D(100) * D(sustained) / D(total), SUSTAIN_RATE_DECIMALS)
