"""Calculation rules and derived-field logic (scaffold 1.3, PRD section 3).

All rounding is Decimal ROUND_HALF_UP. Pinned rounding orders are honored:
finding weighted_score rounds each per-criterion contribution FIRST then sums;
final award score rounds the mean first, then applies the budget clean bonus,
then caps at 100.00; dues key the discount tier off the PRE-discount total.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from clock import parse_iso
from store import store

# --- Named constants (PRD / scaffold 1.3) -----------------------------------
BAND_BASE_CENTS = {"SMALL": 15000, "MEDIUM": 30000, "LARGE": 60000}
AFFILIATION_FEE_CENTS = 5000
DISCOUNT_TIER_LOW_MIN_CENTS = 30000
DISCOUNT_TIER_HIGH_MIN_CENTS = 60000
REQUIRED_FINDINGS_PER_ROUND = 3
MAX_OPEN_ASSIGNMENTS_PER_REVIEWER = 5
APPEAL_WINDOW_DAYS = 30
SCORE_CAP = Decimal("100.00")
BUDGET_CLEAN_BONUS = Decimal("1.00")
REQUIRED_WEIGHT_SUM = Decimal("1.000")
SMALL_POPULATION_LIMIT = 10000  # descriptive: SMALL band means population < 10000
BUDGET_REQUIRED_DOC_TYPES = ("POLICY", "FINANCIAL_PLAN", "COMMUNICATION")
ACTIVE_ASSIGNMENT_STATUSES = ("OFFERED", "ACCEPTED", "SUBMITTED")
LIVE_SUBMISSION_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "DECISION_READY", "APPEALED")
PURPOSE_FOR_PROGRAM_LABEL = {
    "SCHOLARSHIP": "CONFERENCE_SCHOLARSHIP",
    "TECHNICAL_ASSISTANCE": "TECHNICAL_ASSISTANCE",
}

_CENT = Decimal("0.01")
_ONE = Decimal("1")


def round2(value):
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def round0(value):
    return value.quantize(_ONE, rounding=ROUND_HALF_UP)


# --- member_annual_dues (PRD 3.2; pinned evaluation order) -------------------
def compute_dues_cents(government_size_band, independent_finance_officer):
    band_base = BAND_BASE_CENTS[government_size_band]
    affiliation = AFFILIATION_FEE_CENTS if independent_finance_officer else 0
    pre_total = band_base + affiliation
    if pre_total >= DISCOUNT_TIER_HIGH_MIN_CENTS:
        discount_pct = Decimal("0.10")
    elif pre_total >= DISCOUNT_TIER_LOW_MIN_CENTS:
        discount_pct = Decimal("0.05")
    else:
        discount_pct = Decimal("0")
    return int(round0(Decimal(pre_total) * (Decimal("1") - discount_pct)))


# --- cycle_posture (PRD 2.4; half-open bounds) -------------------------------
def posture_of(cycle, now):
    opens = parse_iso(cycle["submission_opens_at"])
    deadline = parse_iso(cycle["submission_deadline_at"])
    review_close = parse_iso(cycle["review_close_at"])
    if now < opens:
        return "SCHEDULED"
    if now < deadline:
        return "OPEN"
    if now < review_close:
        return "IN_REVIEW"
    return "PAST_REVIEW"


# --- reviewer counters (derived; version bumps still happen at write time) ---
def reviewer_open_count(reviewer_id):
    return sum(
        1
        for a in store.review_assignments.values()
        if a["reviewer_id"] == reviewer_id and a["status"] in ("OFFERED", "ACCEPTED")
    )


def reviewer_completed_count(reviewer_id):
    return sum(
        1
        for a in store.review_assignments.values()
        if a["reviewer_id"] == reviewer_id and a["status"] == "SUBMITTED"
    )


def reviewer_declined_count(reviewer_id):
    return sum(
        1
        for a in store.review_assignments.values()
        if a["reviewer_id"] == reviewer_id and a["status"] == "DECLINED"
    )


# --- findings / scoring ------------------------------------------------------
def findings_for_round(submission_id, appeal_round):
    """Current-round findings for a submission, in finding submission order."""
    out = []
    for f in store.review_findings.values():
        assignment = store.review_assignments.get(f["assignment_id"])
        if (
            assignment is not None
            and assignment["submission_id"] == submission_id
            and f["appeal_round"] == appeal_round
        ):
            out.append(f)
    out.sort(key=lambda f: f["_seq"])
    return out


def provisional_and_majors(submission):
    """provisional_award_score: mean of current-round findings' weighted_score,
    half-up 2dp, null when none; major_deficiency_total sums MAJOR counts."""
    findings = findings_for_round(submission["id"], submission["appeal_round"])
    if not findings:
        return None, 0
    total = sum((f["weighted_score"] for f in findings), Decimal("0"))
    mean = round2(total / Decimal(len(findings)))
    majors = sum(f["major_deficiency_count"] for f in findings)
    return mean, majors


def weights_by_code(checklist):
    return {c["criterion_code"]: Decimal(str(c["weight"])) for c in checklist["criteria"]}


def finding_weighted_score(criterion_scores, checklist):
    """Pinned rounding order: round each score*weight contribution half-up to
    2dp FIRST, then sum exactly (PRD 3.5 worked example: 5.01 + 10.01 = 15.02)."""
    weights = weights_by_code(checklist)
    total = Decimal("0")
    for entry in criterion_scores:
        contribution = round2(entry["_score_decimal"] * weights[entry["criterion_code"]])
        total += contribution
    return total


def final_award_score(submission, checklist):
    """final_award_score (PRD 3.6): base = rounded mean of the 3 current-round
    findings. FINANCIAL_REPORTING: final = base. BUDGET_PRESENTATION: if the
    round has zero MAJOR and zero MINOR comments across all findings, add 1.00
    AFTER the mean rounding, then cap at 100.00."""
    findings = findings_for_round(submission["id"], submission["appeal_round"])
    total = sum((f["weighted_score"] for f in findings), Decimal("0"))
    base = round2(total / Decimal(len(findings)))
    if submission["program_type"] == "BUDGET_PRESENTATION":
        has_any_comment = any(len(f["comments"]) > 0 for f in findings)
        if not has_any_comment:
            return min(SCORE_CAP, base + BUDGET_CLEAN_BONUS)
    return base


# --- blind_reviewer_selection (PRD 3.5; deterministic total order) -----------
def reviewer_ever_assigned(reviewer_id, submission_id):
    return any(
        a["reviewer_id"] == reviewer_id and a["submission_id"] == submission_id
        for a in store.review_assignments.values()
    )


def select_reviewer(submission):
    candidates = []
    for p in store.reviewer_profiles.values():
        if p["status"] != "ELIGIBLE":
            continue
        if p["employer_government_id"] == submission["government_id"]:
            continue
        if submission["government_id"] in p["conflicted_government_ids"]:
            continue
        if reviewer_open_count(p["id"]) >= MAX_OPEN_ASSIGNMENTS_PER_REVIEWER:
            continue
        if reviewer_ever_assigned(p["id"], submission["id"]):
            continue
        candidates.append(p)
    candidates.sort(
        key=lambda p: (
            reviewer_open_count(p["id"]),
            -reviewer_completed_count(p["id"]),
            parse_iso(p["trained_at"]),
            p["_seq"],
        )
    )
    return candidates[0] if candidates else None


def active_assignments_in_round(submission):
    return sum(
        1
        for a in store.review_assignments.values()
        if a["submission_id"] == submission["id"]
        and a["appeal_round"] == submission["appeal_round"]
        and a["status"] in ACTIVE_ASSIGNMENT_STATUSES
    )


def next_alias_seq(submission):
    """Reviewer alias sequence: count of assignments EVER created for this
    submission in this appeal round, +1; never reused."""
    return (
        sum(
            1
            for a in store.review_assignments.values()
            if a["submission_id"] == submission["id"]
            and a["appeal_round"] == submission["appeal_round"]
        )
        + 1
    )


# --- scholarship_grant_amount (PRD 3.9) --------------------------------------
def fund_remaining_cents(fund):
    granted = sum(
        a["granted_cents"]
        for a in store.scholarship_applications.values()
        if a["fund_id"] == fund["id"] and a["status"] == "GRANTED"
    )
    return fund["pool_total_cents"] - granted


def fund_status(fund):
    return "ALLOCATING" if fund_remaining_cents(fund) > 0 else "EXHAUSTED"


def grant_amount(fund, application):
    remaining = fund_remaining_cents(fund)
    if fund["allocation_policy"] == "PRO_RATA":
        total_pending = sum(
            a["requested_cents"]
            for a in store.scholarship_applications.values()
            if a["fund_id"] == fund["id"] and a["status"] == "PENDING"
        )
        scaled = round0(
            Decimal(remaining) * Decimal(application["requested_cents"]) / Decimal(total_pending)
        )
        return min(fund["per_applicant_cap_cents"], int(scaled), remaining)
    # FLAT_CAP: first-come waterfall
    return min(application["requested_cents"], fund["per_applicant_cap_cents"], remaining)


# --- overlap helpers ----------------------------------------------------------
def windows_overlap(windows):
    """CLOSED intervals: touching endpoints already count as overlapping."""
    intervals = []
    for w in windows:
        intervals.append((w["_start_date"], w["_end_date"]))
    intervals.sort()
    for i in range(len(intervals)):
        for j in range(i + 1, len(intervals)):
            s1, e1 = intervals[i]
            s2, e2 = intervals[j]
            if s1 <= e2 and s2 <= e1:
                return True
    return False


def cycle_window_overlaps(opens_a, deadline_a, opens_b, deadline_b):
    """HALF-OPEN [opens, deadline) windows: back-to-back is permitted."""
    return opens_a < deadline_b and opens_b < deadline_a


def appeal_deadline(decided_at_iso):
    return parse_iso(decided_at_iso) + timedelta(days=APPEAL_WINDOW_DAYS)
