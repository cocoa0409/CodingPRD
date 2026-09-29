"""Derived calculations. Every aggregate here is rebuilt from its current
inputs on demand -- nothing in this module accumulates (PRD sec 2.13)."""
from decimal import Decimal

from store import (ADMIN_CAP_PCT, ARTICULATION_FLOOR, BREADTH_BONUS, BRIDGE_WEIGHT,
                   CONCENTRATOR_CREDIT_MIN, DEPTH_WEIGHT, FEDERAL_SHARE_BY_CATEGORY,
                   INDIRECT_RATE_TIER_1, INDIRECT_RATE_TIER_2, INDIRECT_RATE_TIER_3,
                   INDIRECT_TIER_1_CEILING, INDIRECT_TIER_2_CEILING,
                   MIN_SECONDARY_CREDITS, PERFORMANCE_TOLERANCE, SMALL_COHORT_MIN,
                   db, dec, parse_date, rhu, rhu_int)

ONE = Decimal("1.0")
ZERO = Decimal("0")

# ------------------------------------------------------------------ courses
INCLUDE_SET = {
    "PROVISIONAL_LOCAL": ("DRAFT", "ACTIVE"),
    "FEDERAL_CERTIFIED": ("ACTIVE",),
}


def program_courses(pos_id):
    return [c for c in db.courses.values() if c["pos_id"] == pos_id]


def depth_from_root(course):
    """Prerequisite hops back to a course with a null prerequisite_course_id."""
    depth = 0
    seen = {course["id"]}
    current = course
    while current.get("prerequisite_course_id"):
        parent = db.courses.get(current["prerequisite_course_id"])
        if parent is None or parent["id"] in seen:
            return depth
        seen.add(parent["id"])
        depth += 1
        current = parent
    return depth


def credit_subtotals(pos_id, variant):
    """The three sums, in the fixed order of PRD sec 3.1, for one variant."""
    include = INCLUDE_SET[variant]
    secondary = ZERO
    postsecondary = ZERO
    articulated = ZERO
    for course in program_courses(pos_id):
        if course["status"] not in include:
            continue
        hours = dec(course["credit_hours"])
        if course["segment"] == "SECONDARY":
            secondary += hours
            continue
        postsecondary += hours
        if variant == "FEDERAL_CERTIFIED" and not course["articulation_verified"]:
            continue
        articulated += dec(course["articulated_credit_hours"])
    return (rhu(secondary, 2), rhu(postsecondary, 2), rhu(articulated, 2))


def alignment_index(secondary, postsecondary, articulated):
    """No intermediate rounding; one round-half-up to 4dp after the clamp."""
    depth_factor = dec(secondary) / MIN_SECONDARY_CREDITS
    if depth_factor > ONE:
        depth_factor = ONE
    denominator = dec(postsecondary)
    if denominator < ONE:
        denominator = ONE
    bridge_factor = dec(articulated) / denominator
    if bridge_factor > ONE:
        bridge_factor = ONE
    bonus = BREADTH_BONUS if (
        dec(secondary) > 0 and dec(postsecondary) > 0
        and dec(articulated) >= ARTICULATION_FLOOR
    ) else ZERO
    combined = depth_factor * DEPTH_WEIGHT + bridge_factor * BRIDGE_WEIGHT + bonus
    if combined > ONE:
        combined = ONE
    return rhu(combined, 4)


def apply_variant(program, variant):
    """Recompute the program's three subtotals and its index under `variant`."""
    secondary, postsecondary, articulated = credit_subtotals(program["id"], variant)
    program["secondary_credit_total"] = secondary
    program["postsecondary_credit_total"] = postsecondary
    program["articulated_credit_total"] = articulated
    index = alignment_index(secondary, postsecondary, articulated)
    program["alignment_index"] = index
    program["alignment_index_variant"] = variant
    return index


def refresh_subtotals(program):
    """Course writes rebuild the subtotals under the program's current variant."""
    variant = program.get("alignment_index_variant") or "PROVISIONAL_LOCAL"
    secondary, postsecondary, articulated = credit_subtotals(program["id"], variant)
    program["secondary_credit_total"] = secondary
    program["postsecondary_credit_total"] = postsecondary
    program["articulated_credit_total"] = articulated
    if program.get("alignment_index_variant") is not None:
        program["alignment_index"] = alignment_index(secondary, postsecondary,
                                                     articulated)


# ------------------------------------------------------------------ credentials
def verified_attainment_count(credential_id):
    return sum(1 for a in db.attainments.values()
               if a["credential_id"] == credential_id
               and a["verification_status"] == "VERIFIED")


# ------------------------------------------------------------------ students
def student_postings(student_id):
    return [p for p in db.postings.values() if p["student_id"] == student_id]


def student_credits(student_id):
    total = ZERO
    for posting in student_postings(student_id):
        total += dec(posting["credit_delta"])
    return rhu(total, 2)


def qualifying_attainment_count(student_id):
    return sum(1 for a in db.attainments.values()
               if a["student_id"] == student_id and a["counted_for_indicator"])


def classify_student(student):
    """PRD sec 3.6 three-way ladder, evaluated top to bottom."""
    credits = student_credits(student["id"])
    qualifying = qualifying_attainment_count(student["id"])
    student["cte_credits_earned"] = credits
    student["verified_qualifying_attainment_count"] = qualifying
    if (credits >= CONCENTRATOR_CREDIT_MIN and student.get("exited_on") is not None
            and qualifying >= 1):
        status = "COMPLETER"
    elif credits >= CONCENTRATOR_CREDIT_MIN:
        status = "CONCENTRATOR"
    else:
        status = "PARTICIPANT"
    student["concentrator_status"] = status
    return status


# ------------------------------------------------------------------ indicators
def cohort_members(pos_id, cohort_year):
    rows = []
    for student in db.students.values():
        if student["pos_id"] != pos_id:
            continue
        if int(student["cohort_year"]) != int(cohort_year):
            continue
        if student["concentrator_status"] in ("CONCENTRATOR", "COMPLETER"):
            rows.append(student)
    return rows


def raw_actual(indicator):
    """(denominator_count, numerator_count, small_cohort_flag, raw_pct)."""
    members = cohort_members(indicator["pos_id"], indicator["cohort_year"])
    denominator = len(members)
    numerator = sum(1 for s in members
                    if int(s["verified_qualifying_attainment_count"]) >= 1)
    small = denominator < SMALL_COHORT_MIN
    if denominator == 0:
        raw = None
    else:
        raw = rhu(dec(100) * dec(numerator) / dec(denominator), 2)
    return denominator, numerator, small, raw


def preliminary(indicator):
    """PRELIMINARY_UNADJUSTED -- ignores small_cohort_flag entirely."""
    denominator, numerator, small, raw = raw_actual(indicator)
    threshold = indicator.get("met_threshold_pct")
    if raw is None or threshold is None:
        projection = "UNDEFINED"
    elif dec(raw) >= dec(threshold):
        projection = "MET"
    else:
        projection = "NOT_MET"
    return {
        "denominator_count": denominator,
        "numerator_count": numerator,
        "small_cohort_flag": small,
        "preliminary_actual_pct": raw,
        "preliminary_status_projection": projection,
    }


def met_threshold(level_pct):
    return rhu(dec(level_pct) * PERFORMANCE_TOLERANCE, 2)


# ------------------------------------------------------------------ committees
def committee_counts(committee_id):
    from auth import member_status
    active = 0
    employers = 0
    chair_id = None
    for member in db.members.values():
        if member["committee_id"] != committee_id:
            continue
        if member_status(member) != "ACTIVE":
            continue
        active += 1
        if member["sector"] == "EMPLOYER":
            employers += 1
        if member["is_chair"] and chair_id is None:
            chair_id = member["id"]
    return active, employers, chair_id


def refresh_committee(committee):
    active, employers, chair_id = committee_counts(committee["id"])
    committee["active_member_count"] = active
    committee["employer_member_count"] = employers
    committee["chair_member_id"] = chair_id
    return committee


def eligible_attendance(committee_id, attendee_ids, held_on):
    """PRD sec 3.3: an attendee is eligible only when it resolves to a member of
    this committee whose half-open term covers held_at's calendar date.
    Unresolvable identifiers are silently discarded."""
    eligible = 0
    employers = 0
    for raw in attendee_ids or []:
        member = db.members.get(raw)
        if member is None or member["committee_id"] != committee_id:
            continue
        start = parse_date(member["term_start_on"])
        end = parse_date(member["term_end_on"])
        if start is None or end is None:
            continue
        if not (start <= held_on < end):
            continue
        eligible += 1
        if member["sector"] == "EMPLOYER":
            employers += 1
    return eligible, employers


def quorum_holds(committee, eligible, employers):
    return (eligible >= int(committee["quorum_min_members"])
            and employers >= int(committee["employer_seat_min"])
            and 2 * employers >= eligible)


# ------------------------------------------------------------------ grant ledger
COUNTABLE_STATUSES = ("CERTIFIED", "OBLIGATED")


def federal_share(category):
    return FEDERAL_SHARE_BY_CATEGORY[category]


def approved_cents(gross_cents, share_pct):
    """Rounded to whole cents once, here, per expenditure line (PRD sec 2.11)."""
    return rhu_int(dec(gross_cents) * dec(share_pct))


def indirect_rate_for(direct_cents):
    """Tier lookup keyed ONLY on the direct total (PRD sec 3.7 step two)."""
    if direct_cents < INDIRECT_TIER_1_CEILING:
        return INDIRECT_RATE_TIER_1
    if direct_cents < INDIRECT_TIER_2_CEILING:
        return INDIRECT_RATE_TIER_2
    return INDIRECT_RATE_TIER_3


def award_expenditures(grant_award_id):
    return [e for e in db.expenditures.values()
            if e["grant_award_id"] == grant_award_id]


def rebuild_ledger(award, extra=None):
    """The six pinned steps, from scratch, over the award's countable lines.

    `extra` lets a pending certification be included before it is committed so
    the grant-capacity check can be evaluated on the resulting figures.
    """
    lines = []
    for expenditure in award_expenditures(award["id"]):
        if extra is not None and expenditure["id"] == extra["id"]:
            continue
        if expenditure["status"] in COUNTABLE_STATUSES:
            lines.append((expenditure["category"], expenditure["approved_cents"]))
    if extra is not None:
        lines.append((extra["category"], extra["approved_cents"]))

    direct = 0
    for _, amount in lines:
        direct += int(amount or 0)
    rate = indirect_rate_for(direct)
    pool = rhu_int(dec(direct) * rate)
    obligated = direct + pool
    allocation = int(award["allocation_cents"])
    remaining = allocation - obligated
    admin = 0
    for category, amount in lines:
        if category == "ADMINISTRATION":
            admin += int(amount or 0)
    return {
        "direct_obligated_cents": direct,
        "indirect_rate": rate,
        "indirect_pool_cents": pool,
        "obligated_cents": obligated,
        "remaining_cents": remaining,
        "admin_obligated_cents": admin,
        "admin_cap_cents": rhu_int(dec(allocation) * ADMIN_CAP_PCT),
    }


def commit_ledger(award, extra=None):
    award.update(rebuild_ledger(award, extra))
    return award


def admin_cap(allocation_cents):
    return rhu_int(dec(allocation_cents) * ADMIN_CAP_PCT)
