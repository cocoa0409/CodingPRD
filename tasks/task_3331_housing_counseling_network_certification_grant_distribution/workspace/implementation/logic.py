from datetime import datetime, timedelta, timezone
from decimal import Decimal

from store import DB
from util import (
    CLOCK, add_months, ceil_cents, floor_cents, round_half_up_2,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

W_GOVERNANCE = Decimal("0.40")
W_FINANCE = Decimal("0.35")
W_PROGRAM = Decimal("0.25")
STRONG_FLOOR = Decimal("85")
ADEQUATE_FLOOR = Decimal("70")
MARGINAL_FLOOR = Decimal("50")

CE_WINDOW_MONTHS = 24
CE_REQUIRED_CREDITS = 30
LAPSE_GRACE_DAYS = 90
LAPSE_POSTURE_THRESHOLD = 2
POSTURE_RESTRICTED_FINDINGS = 3

MATCH_STANDARD_RATE = Decimal("0.25")
MATCH_REDUCED_RATE = Decimal("0.10")
MATCH_REDUCED_MONTHS = 24

COMPETITIVE_SCORE_FLOOR = 60
TIER1_FLOOR = 90
TIER2_FLOOR = 75
TIER2_RATE = Decimal("0.80")
TIER3_RATE = Decimal("0.50")

PERFORMANCE_PASS_SCORE = 70
CORRECTIVE_PLAN_DAYS = 60
MIN_HOURS_NO_OUTCOME = 2.0
PASS_THRESHOLD = 70
REGIONAL_NEED_FACTOR_DEFAULT = Decimal("1.0")

# Failed-review ratio threshold (named FILE_FAIL_RATIO_THRESHOLD in design):
# failed reviews / total reviews for the member; flag set when strictly above.
FILE_FAIL_RATIO_THRESHOLD = 0.5

PROGRAM_AREAS = {
    "HOMEOWNERSHIP", "RENTAL", "COMMUNITY_DEVELOPMENT",
    "FINANCIAL_CAPABILITY", "FORECLOSURE_PREVENTION",
}

OUTCOME_CODES = {
    "PURCHASED_HOME", "MORTGAGE_READY", "RENTAL_STABILIZED",
    "FORECLOSURE_AVERTED", "BUDGET_PLAN_ADOPTED", "NO_OUTCOME",
}


# ---------------------------------------------------------------------------
# Assessment composite
# ---------------------------------------------------------------------------


def rating_for(composite):
    c = Decimal(str(composite))
    if c >= STRONG_FLOOR:
        return "STRONG"
    if c >= ADEQUATE_FLOOR:
        return "ADEQUATE"
    if c >= MARGINAL_FLOOR:
        return "MARGINAL"
    return "DEFICIENT"


def assessment_base(g, f, p):
    return W_GOVERNANCE * g + W_FINANCE * f + W_PROGRAM * p


def provisional_composite(g, f, p):
    return round_half_up_2(assessment_base(g, f, p))


def final_composite(g, f, p, site_visit_adjustment):
    base = assessment_base(g, f, p) + Decimal(site_visit_adjustment)
    if base > 100:
        base = Decimal(100)
    return round_half_up_2(base)


# ---------------------------------------------------------------------------
# Households served rollup
# ---------------------------------------------------------------------------


def fy_window(fiscal_year):
    start = datetime(fiscal_year - 1, 10, 1, tzinfo=timezone.utc)
    end = datetime(fiscal_year, 10, 1, tzinfo=timezone.utc)
    return start, end


def households_served(member_id, fiscal_year):
    start, end = fy_window(fiscal_year)
    count = 0
    for f in DB.client_files.values():
        if f["member_id"] != member_id:
            continue
        if f["file_status"] not in ("OUTCOME_RECORDED", "CLOSED"):
            continue
        oc = f.get("outcome_code")
        if oc is None or oc == "NO_OUTCOME":
            continue
        opened = f["opened_on"]
        if opened is None or opened < start or opened >= end:
            continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Member posture recompute
# ---------------------------------------------------------------------------


def member_awards(member_id):
    return [a for a in DB.awards.values() if a["member_id"] == member_id]


def recompute_member(member):
    """Recompute open_finding_count, failed_review_flag, compliance_posture
    (in that propagation order). Bumps member version only when a value changes."""
    mid = member["id"]
    changed = False

    # 1. open_finding_count
    failed_reviews = [
        r for r in DB.file_reviews.values()
        if r["review_status"] == "FAILED"
        and DB.client_files.get(r["client_file_id"], {}).get("member_id") == mid
    ]
    award_ids = {a["id"] for a in member_awards(mid)}
    open_audits = [
        a for a in DB.audits.values()
        if a["audit_status"] == "FINDINGS_ISSUED" and a["award_id"] in award_ids
    ]
    open_findings = len(failed_reviews) + len(open_audits)
    if member.get("open_finding_count") != open_findings:
        member["open_finding_count"] = open_findings
        changed = True

    # 2. failed_review_flag (derived: corrective-action review or fail ratio)
    in_corrective = any(
        r["review_status"] == "CORRECTIVE_ACTION" and r["member_id"] == mid
        for r in DB.perf_reviews.values()
    )
    member_reviews = [
        r for r in DB.file_reviews.values()
        if DB.client_files.get(r["client_file_id"], {}).get("member_id") == mid
    ]
    total_reviews = len(member_reviews)
    failed_ratio = (len(failed_reviews) / total_reviews) if total_reviews else 0.0
    ratio_flag = total_reviews > 0 and failed_ratio > FILE_FAIL_RATIO_THRESHOLD
    flag = in_corrective or ratio_flag
    if member.get("failed_review_flag") != flag:
        member["failed_review_flag"] = flag
        changed = True

    # 3. posture
    escalated = any(
        a["audit_status"] == "ESCALATED" and a["award_id"] in award_ids
        for a in DB.audits.values()
    )
    lapsed = 0
    for c in DB.counselors.values():
        if c["member_id"] != mid:
            continue
        lapsed += sum(
            1 for cert in DB.certifications.values()
            if cert["counselor_id"] == c["id"]
            and cert["certification_status"] == "LAPSED"
        )
    if escalated:
        posture = "FROZEN"
    elif open_findings >= POSTURE_RESTRICTED_FINDINGS or member["charter_status"] == "PROBATION":
        posture = "RESTRICTED"
    elif open_findings >= 1 or member["failed_review_flag"] or lapsed > LAPSE_POSTURE_THRESHOLD:
        posture = "WATCH"
    else:
        posture = "CLEAR"
    if member.get("compliance_posture") != posture:
        member["compliance_posture"] = posture
        changed = True

    if changed:
        DB.touch(member)
    return member


# ---------------------------------------------------------------------------
# Formula allocation (water-filling with caps, floor + waterfall remainder)
# ---------------------------------------------------------------------------


def eligible_applications(cycle_id):
    """Applications of the cycle in UNDER_REVIEW or AWARDED whose member is
    CHARTERED; DECLINED/WITHDRAWN excluded."""
    apps = []
    for app in DB.applications.values():
        if app["cycle_id"] != cycle_id:
            continue
        if app["application_status"] not in ("UNDER_REVIEW", "AWARDED"):
            continue
        member = DB.members.get(app["member_id"])
        if member is None or member["charter_status"] != "CHARTERED":
            continue
        apps.append(app)
    return apps


def app_weight(app, cycle):
    member = DB.members[app["member_id"]]
    hh = households_served(member["id"], cycle["fiscal_year"] - 1)
    return (1 + hh) * REGIONAL_NEED_FACTOR_DEFAULT


def compute_formula_shares(cycle):
    """Water-filling allocation of the formula pool across eligible apps.
    Returns dict application_id -> allocated cents (int)."""
    apps = eligible_applications(cycle["id"])
    pool = cycle["formula_pool_cents"]
    if not apps or pool <= 0:
        return {a["id"]: 0 for a in apps}

    weights = {a["id"]: app_weight(a, cycle) for a in apps}
    caps = {a["id"]: a["requested_formula_cents"] for a in apps}
    total_weight = sum(weights.values())

    # Exact (Decimal) water-filling with caps.
    exact = {a["id"]: Decimal(0) for a in apps}
    remaining_pool = Decimal(pool)
    uncapped = set(a["id"] for a in apps if caps[a["id"]] > 0)
    # members capped at exactly their request
    for aid in list(uncapped):
        if caps[aid] <= 0:
            uncapped.discard(aid)
    while remaining_pool > 0 and uncapped:
        w_sum = sum(weights[aid] for aid in uncapped)
        if w_sum <= 0:
            break
        progressed = False
        spent = Decimal(0)
        shares = {}
        for aid in uncapped:
            shares[aid] = remaining_pool * weights[aid] / w_sum
        for aid in list(uncapped):
            headroom = Decimal(caps[aid]) - exact[aid]
            if shares[aid] >= headroom:
                exact[aid] = Decimal(caps[aid])
                spent += headroom
                uncapped.discard(aid)
                progressed = True
        if not progressed:
            for aid in uncapped:
                exact[aid] += shares[aid]
                spent += shares[aid]
            uncapped.clear()
        remaining_pool -= spent
        if remaining_pool <= 0:
            break

    # Floor to whole cents, then waterfall remainder.
    floored = {aid: floor_cents(v) for aid, v in exact.items()}
    target = min(pool, sum(caps.values()))
    residual = target - sum(floored.values())
    if residual > 0:
        order = sorted(
            apps,
            key=lambda a: (-weights[a["id"]], a["created_at"], a["_seq"]),
        )
        # distribute one cent at a time, respecting caps
        while residual > 0:
            gave = False
            for a in order:
                aid = a["id"]
                if floored[aid] < caps[aid]:
                    floored[aid] += 1
                    residual -= 1
                    gave = True
                    if residual == 0:
                        break
            if not gave:
                break
    return floored


# ---------------------------------------------------------------------------
# Competitive allocation
# ---------------------------------------------------------------------------


def competitive_component(review_score, requested_competitive_cents):
    if requested_competitive_cents == 0:
        return 0
    if review_score is None:
        return 0
    if review_score >= TIER1_FLOOR:
        return requested_competitive_cents
    if review_score >= TIER2_FLOOR:
        return floor_cents(Decimal(requested_competitive_cents) * TIER2_RATE)
    if review_score >= COMPETITIVE_SCORE_FLOOR:
        return floor_cents(Decimal(requested_competitive_cents) * TIER3_RATE)
    return 0


# ---------------------------------------------------------------------------
# Match requirement
# ---------------------------------------------------------------------------


def required_match(member, total_cents):
    now = CLOCK.now()
    chartered_at = member.get("chartered_at")
    rate = MATCH_STANDARD_RATE
    if chartered_at is not None and add_months(chartered_at, MATCH_REDUCED_MONTHS) > now:
        rate = MATCH_REDUCED_RATE
    return ceil_cents(Decimal(total_cents) * rate)


# ---------------------------------------------------------------------------
# Course seats
# ---------------------------------------------------------------------------


def seats_taken(course_id):
    return sum(
        1 for e in DB.enrollments.values()
        if e["course_id"] == course_id
        and e["enrollment_status"] in ("REGISTERED", "COMPLETED")
    )


# ---------------------------------------------------------------------------
# Clock-driven system transitions
# ---------------------------------------------------------------------------


def fire_clock_transitions():
    now = CLOCK.now()
    # 1. Courses SCHEDULED -> IN_SESSION when clock reaches delivery_start.
    for course in sorted(DB.courses.values(), key=lambda c: (c["created_at"], c["_seq"])):
        if course["course_status"] == "SCHEDULED" and now >= course["delivery_start"]:
            course["course_status"] = "IN_SESSION"
            DB.touch(course)
    # 2. Courses IN_SESSION -> CONCLUDED when clock reaches delivery_end.
    for course in sorted(DB.courses.values(), key=lambda c: (c["created_at"], c["_seq"])):
        if course["course_status"] == "IN_SESSION" and now >= course["delivery_end"]:
            course["course_status"] = "CONCLUDED"
            DB.touch(course)
            for e in sorted(DB.enrollments.values(), key=lambda x: (x["created_at"], x["_seq"])):
                if e["course_id"] == course["id"] and e["enrollment_status"] == "REGISTERED":
                    e["enrollment_status"] = "FAILED"
                    e["score"] = None
                    DB.touch(e)
    # 3. Certifications LAPSED -> EXPIRED beyond grace window.
    for cert in sorted(DB.certifications.values(), key=lambda c: (c["created_at"], c["_seq"])):
        if cert["certification_status"] == "LAPSED" and cert.get("lapse_deadline") is not None:
            if now > cert["lapse_deadline"] + timedelta(days=LAPSE_GRACE_DAYS):
                cert["certification_status"] = "EXPIRED"
                DB.touch(cert)
