"""Every derived field and every calculation of PRD section 3.

Nothing here reads the wall clock: all temporal rules are evaluated against the
logical clock held in db.S.clock.
"""

from datetime import timedelta
from decimal import Decimal

from db import S, ordered
from util import D0, D100, add_days, ceil_div, median2, r2, whole_minutes

# ---------------------------------------------------------------- constants

MIN_HEARING_NOTICE_DAYS = 10
APPEAL_WINDOW_DAYS = 10
APPEAL_MAX_PER_CASE = 2
ADVISOR_LIMIT_PER_CASE = 2
ATTORNEY_ADVISOR_MIN_RANK = 6
TRAINING_VALID_DAYS = 730
NOTATION_MIN_RANK = 4
INFORMAL_MAX_RANK = 3
REMAND_MAX_HEARING_ROUND = 1
MEETING_MIN_MINUTES = 15
MEETING_MAX_MINUTES = 240
RESPONSE_WINDOW_MIN_DAYS = 5
RESPONSE_WINDOW_MAX_DAYS = 30
RESPONSE_WINDOW_DEFAULT_DAYS = 7
PATTERN_WINDOW_DAYS = 730
REPORTING_WINDOW_DAYS = 365
TRIAGE_ACCEPT_MIN_EVIDENCE_SCORE = Decimal("20.00")
DECISION_FLOOR_DAYS = 365

LADDER_KIND = {
    1: "WARNING",
    2: "GRADE_PENALTY_ASSIGNMENT",
    3: "GRADE_PENALTY_COURSE",
    4: "TRANSCRIPT_NOTATION_ONLY",
    5: "DISCIPLINARY_PROBATION",
    6: "SUSPENSION_ONE_TERM",
    7: "SUSPENSION_ONE_YEAR",
    8: "EXPULSION_RECOMMENDATION",
}
SANCTION_KINDS = tuple(LADDER_KIND[rank] for rank in range(1, 9))
GRADE_PENALTY_KINDS = ("GRADE_PENALTY_ASSIGNMENT", "GRADE_PENALTY_COURSE")

BASE_POINTS = {
    "PLAGIARISM": 20,
    "UNAUTHORIZED_COLLABORATION": 18,
    "EXAM_CHEATING": 28,
    "FABRICATION_OF_DATA": 32,
    "CONTRACT_CHEATING": 40,
    "FACILITATION": 24,
}
VIOLATION_TYPES = tuple(BASE_POINTS.keys())

EVIDENCE_KIND_WEIGHT = {
    "SIMILARITY_REPORT": Decimal("1.00"),
    "PROCTOR_LOG": Decimal("0.60"),
    "WITNESS_STATEMENT": Decimal("0.40"),
    "DOCUMENT": Decimal("0.20"),
}
EVIDENCE_KINDS = tuple(EVIDENCE_KIND_WEIGHT.keys())

QUOTE_ALLOWANCE = Decimal("5.00")
PAGE_CAP = 20
PAGE_POINTS_PER_PAGE = Decimal("0.50")
DIVERSITY_SCALE = Decimal("10")
CORROBORATION_BONUS = Decimal("15.00")
EVIDENCE_SCORE_CAP = D100
EVIDENCE_CONTRIBUTION_WEIGHT = Decimal("0.40")
SEVERITY_CAP = Decimal("120.00")
ESCALATION_PIVOT = Decimal("50.00")

ELIGIBILITY_DAYS = {4: 365, 5: 365, 6: 730, 7: 1095, 8: None}

NOTATION_KINDS = ("ALLEGATION_NOTICE", "REHEARING_NOTICE")
GOVERNING_NOTICE_KINDS = ("ALLEGATION_NOTICE", "REHEARING_NOTICE")

ROOM_ACTIVE_SESSION_STATES = ("SCHEDULED", "CONVENED", "DECIDED", "ADJOURNED")
ROOM_CONFLICT_SESSION_STATES = ("SCHEDULED", "CONVENED")
CALENDAR_BUSY_MEETING_STATES = ("SCHEDULED", "HELD", "NO_SHOW")
OPEN_CASE_EXCLUDED_STATES = ("CLOSED", "DISMISSED")
PRIOR_UPHELD_STATES = ("SANCTION_IMPOSED", "CLOSED")


# ---------------------------------------------------------------- lookups

def rows_where(collection, **filters):
    matches = []
    for row in ordered(collection):
        keep = True
        for key, expected in filters.items():
            if row.get(key) != expected:
                keep = False
                break
        if keep:
            matches.append(row)
    return matches


def offering_of_case(case):
    return S.offerings.get(case["offering_id"])


def department_of_offering(offering):
    if offering is None:
        return None
    return S.departments.get(offering["department_id"])


def department_of_case(case):
    return department_of_offering(offering_of_case(case))


def report_of_case(case):
    return S.reports.get(case["report_id"])


def case_for_report(report_id):
    for case in ordered(S.cases):
        if case["report_id"] == report_id:
            return case
    return None


def sanctions_of_case(case_id):
    return rows_where(S.sanctions, case_id=case_id)


def notifications_of_case(case_id):
    return rows_where(S.notifications, case_id=case_id)


def engagements_of_case(case_id):
    return rows_where(S.engagements, case_id=case_id)


def appeals_of_case(case_id):
    return rows_where(S.appeals, case_id=case_id)


def votes_of_session(session_id):
    return rows_where(S.votes, session_id=session_id)


def evidence_of_report(report_id):
    return rows_where(S.evidence_items, report_id=report_id)


# ---------------------------------------------------------------- faculty

def training_completions_of(faculty_id):
    return rows_where(S.training_completions, faculty_id=faculty_id)


def newest_training_completion(faculty_id):
    """Newest means the greatest completed_at, ties broken by the most recently
    created row (PRD 3.1)."""
    newest = None
    for row in training_completions_of(faculty_id):
        if newest is None:
            newest = row
        elif (row["completed_at"], row["_seq"]) > (newest["completed_at"], newest["_seq"]):
            newest = row
    return newest


def faculty_training(member):
    """(training_status, training_completed_at, training_module_code)."""
    newest = newest_training_completion(member["id"])
    if newest is None:
        return "LAPSED", None, None
    valid_until = add_days(newest["completed_at"], TRAINING_VALID_DAYS)
    status = "CURRENT" if valid_until >= S.clock else "LAPSED"
    return status, newest["completed_at"], newest["module_code"]


def faculty_training_status(member):
    return faculty_training(member)[0]


def faculty_reports_submitted_count(member):
    count = 0
    for report in S.reports.values():
        if report["reporter_id"] == member["id"] and report["status"] != "DRAFT":
            count += 1
    return count


# ---------------------------------------------------------------- department

def department_open_case_count(department):
    count = 0
    for case in S.cases.values():
        offering = S.offerings.get(case["offering_id"])
        if offering is None or offering["department_id"] != department["id"]:
            continue
        if case["adjudication_status"] not in OPEN_CASE_EXCLUDED_STATES:
            count += 1
    return count


def department_faculty(department_id):
    return rows_where(S.faculty_members, department_id=department_id)


def department_faculty_current_count(department):
    count = 0
    for member in department_faculty(department["id"]):
        if faculty_training_status(member) == "CURRENT":
            count += 1
    return count


def department_training_completion_pct(department):
    current = department_faculty_current_count(department)
    headcount = department["faculty_headcount"]
    if headcount <= 0:
        return D0
    return r2(Decimal(current) * 100 / Decimal(headcount))


def department_reporting_numerator(department, basis, as_of):
    window_start = add_days(as_of, -REPORTING_WINDOW_DAYS)
    count = 0
    if basis == "ADJUDICATED":
        for case in S.cases.values():
            offering = S.offerings.get(case["offering_id"])
            if offering is None or offering["department_id"] != department["id"]:
                continue
            if case["responsibility_finding"] != "RESPONSIBLE":
                continue
            if case["overturned"]:
                continue
            decided_at = case["decided_at"]
            if decided_at is None:
                continue
            if window_start <= decided_at <= as_of:
                count += 1
        return count
    for report in S.reports.values():
        offering = S.offerings.get(report["offering_id"])
        if offering is None or offering["department_id"] != department["id"]:
            continue
        if report["status"] == "DRAFT":
            continue
        submitted_at = report["submitted_at"]
        if submitted_at is None:
            continue
        if window_start <= submitted_at <= as_of:
            count += 1
    return count


def department_reporting_rate(department, basis, as_of):
    numerator = department_reporting_numerator(department, basis, as_of)
    enrolled = department["enrolled_student_count"]
    if enrolled <= 0:
        return numerator, D0
    return numerator, r2(Decimal(numerator) * 1000 / Decimal(enrolled))


def peer_median_rate():
    rates = [d["reporting_rate_per_1k_submitted"] for d in S.departments.values()]
    return median2(rates)


def elevated_threshold(median):
    return r2(median * Decimal(2))


def monitoring_flag_for(department, training_pct=None):
    """Four branches in a pinned order, first match winning (PRD 3.1)."""
    rate = department["reporting_rate_per_1k_submitted"]
    if training_pct is None:
        training_pct = department_training_completion_pct(department)
    if rate == D0:
        return "UNDER_REPORTING"
    if rate > elevated_threshold(peer_median_rate()):
        return "ELEVATED"
    if training_pct < Decimal("80.00"):
        return "TRAINING_DEFICIT"
    return "NORMAL"


def recompute_department_metrics(department):
    """Recompute and persist the submitted-basis rate and the monitoring flag.

    Returns True when a persisted value actually changed.
    """
    _, rate = department_reporting_rate(department, "SUBMITTED", S.clock)
    changed = False
    if department["reporting_rate_per_1k_submitted"] != rate:
        department["reporting_rate_per_1k_submitted"] = rate
        changed = True
    flag = monitoring_flag_for(department)
    if department["monitoring_flag"] != flag:
        department["monitoring_flag"] = flag
        changed = True
    return changed


# ---------------------------------------------------------------- student

def cases_of_student(student_id):
    return rows_where(S.cases, student_id=student_id)


def sanctions_of_student(student_id):
    matches = []
    for sanction in ordered(S.sanctions):
        case = S.cases.get(sanction["case_id"])
        if case is not None and case["student_id"] == student_id:
            matches.append(sanction)
    return matches


def student_prior_upheld_count(student_id, exclude_case_id=None):
    count = 0
    for case in cases_of_student(student_id):
        if exclude_case_id is not None and case["id"] == exclude_case_id:
            continue
        if case["responsibility_finding"] != "RESPONSIBLE":
            continue
        if case["overturned"]:
            continue
        if case["adjudication_status"] not in PRIOR_UPHELD_STATES:
            continue
        count += 1
    return count


def student_active_sanction_points(student_id):
    total = 0
    for sanction in sanctions_of_student(student_id):
        if sanction["status"] == "IMPOSED":
            total += sanction["ladder_rank"]
    return total


def student_standing(student_id):
    ranks = [s["ladder_rank"] for s in sanctions_of_student(student_id)
             if s["status"] == "IMPOSED"]
    for rank in ranks:
        if rank >= 6:
            return "SUSPENDED"
    for rank in ranks:
        if rank == 5:
            return "PROBATION"
    return "GOOD_STANDING"


def student_transcript_notation(student_id):
    statuses = [c["notation_status"] for c in cases_of_student(student_id)]
    if "POSTED" in statuses:
        return "POSTED"
    if "EXPUNGED" in statuses:
        return "EXPUNGED"
    return "NONE"


# ---------------------------------------------------------------- evidence

def evidence_strength_score(report_id):
    items = evidence_of_report(report_id)
    similarities = [i["similarity_pct"] for i in items
                    if i["kind"] == "SIMILARITY_REPORT" and i["similarity_pct"] is not None]
    if similarities:
        adjusted = max(similarities) - QUOTE_ALLOWANCE
        if adjusted < D0:
            adjusted = D0
    else:
        adjusted = D0
    if adjusted >= Decimal("40.00"):
        band = Decimal("1.20")
    elif adjusted >= Decimal("20.00"):
        band = Decimal("1.00")
    else:
        band = Decimal("0.70")
    similarity_points = r2(adjusted * band)
    pages = 0
    for item in items:
        pages += item["page_count"]
    if pages > PAGE_CAP:
        pages = PAGE_CAP
    page_points = r2(Decimal(pages) * PAGE_POINTS_PER_PAGE)
    kinds = set(item["kind"] for item in items)
    weight_sum = D0
    for kind in kinds:
        weight_sum += EVIDENCE_KIND_WEIGHT[kind]
    diversity_points = r2(weight_sum * DIVERSITY_SCALE)
    non_document = False
    for kind in kinds:
        if kind != "DOCUMENT":
            non_document = True
    corroboration = CORROBORATION_BONUS if (len(kinds) >= 2 and non_document) else D0
    total = r2(similarity_points + page_points + diversity_points + corroboration)
    if total > EVIDENCE_SCORE_CAP:
        total = EVIDENCE_SCORE_CAP
    return r2(total)


def evidence_complete(report):
    items = evidence_of_report(report["id"])
    if not items:
        return False
    if report["alleged_violation_type"] == "PLAGIARISM":
        for item in items:
            if item["kind"] == "SIMILARITY_REPORT":
                return True
        return False
    return True


# ---------------------------------------------------------------- grade book

def component_scores_map(report):
    scores = {}
    for entry in report["component_scores"]:
        scores[entry["code"]] = entry["earned_points"]
    return scores


def component_scores_join_ok(offering, component_scores):
    """Exactly one entry per declared code, no unknown and no duplicate code."""
    declared = [component["code"] for component in offering["grade_components"]]
    supplied = [entry["code"] for entry in component_scores]
    if len(supplied) != len(set(supplied)):
        return False
    if sorted(supplied) != sorted(declared):
        return False
    return True


def course_grade_pct(offering, scores, zero_code=None, zero_all=False):
    """PRD 3.8: round each component percentage first, weight the rounded value,
    round the weighted total exactly once at the end."""
    if zero_all:
        return D0
    total = Decimal(0)
    for component in offering["grade_components"]:
        earned = scores.get(component["code"], 0)
        if zero_code is not None and component["code"] == zero_code:
            earned = 0
        pct = r2(Decimal(earned) * 100 / Decimal(component["max_points"]))
        total += pct * Decimal(component["weight_pct"]) / Decimal(100)
    return r2(total)


def grade_penalty_figures(case, sanction_kind, grade_component_code):
    """(baseline, adjusted, delta) for a sanction on this case."""
    offering = offering_of_case(case)
    report = report_of_case(case)
    scores = component_scores_map(report)
    baseline = course_grade_pct(offering, scores)
    if sanction_kind == "GRADE_PENALTY_ASSIGNMENT":
        adjusted = course_grade_pct(offering, scores, zero_code=grade_component_code)
    elif sanction_kind == "GRADE_PENALTY_COURSE":
        adjusted = D0
    else:
        adjusted = baseline
    return baseline, adjusted, r2(baseline - adjusted)


# ---------------------------------------------------------------- severity

def cross_course_pattern(case):
    """(points, distinct_other_course_codes) -- PRD 3.4 pattern detector."""
    window_start = add_days(S.clock, -PATTERN_WINDOW_DAYS)
    own_offering = offering_of_case(case)
    own_code = own_offering["course_code"] if own_offering else None
    codes = set()
    for other in cases_of_student(case["student_id"]):
        if other["id"] == case["id"]:
            continue
        if other["responsibility_finding"] != "RESPONSIBLE":
            continue
        if other["overturned"]:
            continue
        if other["adjudication_status"] == "DISMISSED":
            continue
        decided_at = other["decided_at"]
        if decided_at is None:
            continue
        if not (window_start <= decided_at <= S.clock):
            continue
        offering = S.offerings.get(other["offering_id"])
        if offering is None:
            continue
        code = offering["course_code"]
        if own_code is not None and code == own_code:
            continue
        codes.add(code)
    distinct = len(codes)
    if distinct == 0:
        points = 0
    elif distinct == 1:
        points = 4
    else:
        points = 10
    return points, distinct


def escalation_points(prior_count, provisional_index):
    """Selected from the PROVISIONAL index, never the final one (PRD 3.4)."""
    if prior_count <= 0:
        return 0
    below_pivot = provisional_index < ESCALATION_PIVOT
    if prior_count == 1:
        return 8 if below_pivot else 14
    return 18 if below_pivot else 26


def tier_rank(index):
    if index < Decimal("25.00"):
        return 1
    if index < Decimal("40.00"):
        return 2
    if index < Decimal("55.00"):
        return 3
    if index < Decimal("70.00"):
        return 5
    if index < Decimal("85.00"):
        return 6
    if index < D100:
        return 7
    return 8


def office_band(recommended_rank):
    low = recommended_rank - 1
    if low < 1:
        low = 1
    high = recommended_rank + 1
    if high > 8:
        high = 8
    return low, high


def required_panel_size(recommended_rank):
    return 5 if recommended_rank >= ATTORNEY_ADVISOR_MIN_RANK else 3


def assess_case(case):
    """Both variants of the two-algorithm severity assessment (PRD 3.4)."""
    report = report_of_case(case)
    base_points = BASE_POINTS[report["alleged_violation_type"]] if report else 0
    score = case["evidence_strength_score"]
    contribution = r2(score * EVIDENCE_CONTRIBUTION_WEIGHT)
    points, distinct = cross_course_pattern(case)
    provisional = r2(Decimal(base_points) + contribution + Decimal(points))
    priors = student_prior_upheld_count(case["student_id"], exclude_case_id=case["id"])
    escalation = escalation_points(priors, provisional)
    severity = r2(provisional + Decimal(escalation))
    if severity > SEVERITY_CAP:
        severity = SEVERITY_CAP
    tier = tier_rank(severity)
    panel_rec = case["panel_severity_recommendation"]
    recommended = tier if panel_rec is None else max(tier, panel_rec)
    informal_index = r2(Decimal(base_points) + contribution)
    informal_rank = min(tier_rank(informal_index), INFORMAL_MAX_RANK)
    return {
        "base_points": base_points,
        "evidence_contribution": contribution,
        "cross_course_pattern_points": points,
        "distinct_other_course_codes": distinct,
        "prior_upheld_count_at_assessment": priors,
        "provisional_severity_index": provisional,
        "prior_escalation_points": escalation,
        "severity_index": severity,
        "tier_rank": tier,
        "panel_severity_recommendation": panel_rec,
        "recommended_ladder_rank": recommended,
        "informal_severity_index": informal_index,
        "informal_recommended_ladder_rank": informal_rank,
    }


ASSESSMENT_PERSISTED_FIELDS = (
    "cross_course_pattern_points",
    "prior_upheld_count_at_assessment",
    "prior_escalation_points",
    "provisional_severity_index",
    "severity_index",
    "recommended_ladder_rank",
    "informal_severity_index",
    "informal_recommended_ladder_rank",
)


def apply_assessment(case):
    """Write the assessment onto the case row. Returns the assessment."""
    assessment = assess_case(case)
    for field in ASSESSMENT_PERSISTED_FIELDS:
        case[field] = assessment[field]
    return assessment


def informal_band(case):
    return 1, case["informal_recommended_ladder_rank"]


# ---------------------------------------------------------------- panels

def quorum_required(panel_size):
    """Panel size times two, divided by three, rounded UP."""
    return ceil_div(panel_size * 2, 3)


def panel_tally(session):
    """(effective_vote_count, panel_finding, panel_severity_recommendation)."""
    votes = votes_of_session(session["id"])
    effective = [v for v in votes if v["verdict"] != "ABSTAIN"]
    responsible = [v for v in effective if v["verdict"] == "RESPONSIBLE"]
    if len(responsible) * 2 > len(effective):
        finding = "RESPONSIBLE"
    else:
        finding = "NOT_RESPONSIBLE"
    recommendation = None
    if finding == "RESPONSIBLE":
        values = sorted(v["severity_recommendation"] for v in responsible)
        # Even count takes the LOWER of the two middle values, never their mean.
        recommendation = values[(len(values) - 1) // 2]
    return len(effective), finding, recommendation


def conflicted_faculty_ids(case):
    """The reporter of the originating report and the offering's instructor."""
    ids = set()
    report = report_of_case(case)
    if report is not None:
        ids.add(report["reporter_id"])
    offering = offering_of_case(case)
    if offering is not None:
        ids.add(offering["instructor_id"])
    return ids


# ---------------------------------------------------------------- sanctions

def sanction_kind_for_rank(rank):
    return LADDER_KIND.get(rank)


def governing_sanction(case_id):
    """The case's sanction in IMPOSED or COMPLETED; when there is more than one,
    the most recently imposed, breaking ties by the most recently created."""
    best = None
    for sanction in sanctions_of_case(case_id):
        if sanction["status"] not in ("IMPOSED", "COMPLETED"):
            continue
        if best is None:
            best = sanction
            continue
        key = (sanction["imposed_at"], sanction["created_at"], sanction["_seq"])
        best_key = (best["imposed_at"], best["created_at"], best["_seq"])
        if key > best_key:
            best = sanction
    return best


def expungement_eligible_at(case):
    """Later of completed_at plus the ladder period and decided_at plus 365."""
    sanction = governing_sanction(case["id"])
    if sanction is None or sanction["status"] != "COMPLETED":
        return None
    days = ELIGIBILITY_DAYS.get(sanction["ladder_rank"])
    if days is None:
        return None
    ladder_end = add_days(sanction["completed_at"], days)
    if case["decided_at"] is None:
        return ladder_end
    floor = add_days(case["decided_at"], DECISION_FLOOR_DAYS)
    return ladder_end if ladder_end > floor else floor


# ---------------------------------------------------------------- intervals

def session_reserved_minutes(session, room):
    minutes = whole_minutes(session["start_at"], session["end_at"])
    return (minutes or 0) + 2 * room["buffer_minutes"]


def room_booked_minutes(room):
    """The conserved ledger of PRD 2.11, derived rather than accumulated."""
    total = 0
    for session in ordered(S.sessions):
        if session["room_id"] != room["id"]:
            continue
        if session["status"] not in ROOM_ACTIVE_SESSION_STATES:
            continue
        total += session_reserved_minutes(session, room)
    return total


def room_buffer_conflict(room, start_at, end_at):
    """CLOSED buffered intervals: touching at an endpoint DOES conflict."""
    buffer = timedelta(minutes=room["buffer_minutes"])
    low = start_at - buffer
    high = end_at + buffer
    for session in ordered(S.sessions):
        if session["room_id"] != room["id"]:
            continue
        if session["status"] not in ROOM_CONFLICT_SESSION_STATES:
            continue
        other_low = session["start_at"] - buffer
        other_high = session["end_at"] + buffer
        if low <= other_high and other_low <= high:
            return True
    return False


def room_daily_session_count(room, start_at):
    count = 0
    for session in ordered(S.sessions):
        if session["room_id"] != room["id"]:
            continue
        if session["status"] not in ROOM_CONFLICT_SESSION_STATES:
            continue
        if session["start_at"].date() == start_at.date():
            count += 1
    return count


def instructor_calendar_conflict(instructor_id, start_at, end_at):
    """HALF-OPEN intervals: back-to-back meetings do NOT conflict."""
    for meeting in ordered(S.meetings):
        if meeting["instructor_id"] != instructor_id:
            continue
        if meeting["status"] not in CALENDAR_BUSY_MEETING_STATES:
            continue
        if start_at < meeting["end_at"] and meeting["start_at"] < end_at:
            return True
    return False


def interval_problem(start_at, end_at):
    """None when well formed, else a human-readable ERR_MEETING_WINDOW_INVALID
    message: start before end, a whole number of minutes, 15 to 240 inclusive."""
    if start_at >= end_at:
        return "start_at must be strictly earlier than end_at."
    minutes = whole_minutes(start_at, end_at)
    if minutes is None:
        return "The interval is not a whole number of minutes."
    if minutes < MEETING_MIN_MINUTES or minutes > MEETING_MAX_MINUTES:
        return "The interval must last from 15 to 240 minutes inclusive."
    return None


# ---------------------------------------------------------------- notices

def allegation_notice(case_id):
    for notice in notifications_of_case(case_id):
        if notice["kind"] == "ALLEGATION_NOTICE":
            return notice
    return None


def governing_notice(case_id):
    """The case's most recent ALLEGATION_NOTICE or REHEARING_NOTICE."""
    best = None
    for notice in notifications_of_case(case_id):
        if notice["kind"] not in GOVERNING_NOTICE_KINDS:
            continue
        if best is None or (notice["sent_at"], notice["_seq"]) > (best["sent_at"], best["_seq"]):
            best = notice
    return best


def response_window_closed(case_id):
    notice = allegation_notice(case_id)
    if notice is None:
        return True
    if notice["acknowledged_at"] is not None:
        return True
    return S.clock > notice["response_deadline_at"]


# ---------------------------------------------------------------- advisors

def advisor_request_pending(case_id):
    for engagement in engagements_of_case(case_id):
        if engagement["status"] == "REQUESTED":
            return True
    return False


def advisor_live_count(case_id):
    count = 0
    for engagement in engagements_of_case(case_id):
        if engagement["status"] in ("REQUESTED", "APPROVED"):
            count += 1
    return count


def case_has_approved_advisor(case_id):
    for engagement in engagements_of_case(case_id):
        if engagement["status"] == "APPROVED":
            return True
    return False


def speaking_rights(engagement):
    """True exactly when APPROVED, ATTORNEY, and the case pathway is FORMAL."""
    if engagement["status"] != "APPROVED":
        return False
    if engagement["advisor_kind"] != "ATTORNEY":
        return False
    case = S.cases.get(engagement["case_id"])
    return case is not None and case["pathway"] == "FORMAL"
