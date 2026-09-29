"""Derived figures and the nine named calculations."""

from decimal import Decimal
from fractions import Fraction

from db import by_created, db, mark, set_field
from util import (add_days, add_seconds, ceil_dec, day_end, floor_dec, pct, q2,
                  round_half_up_int)

ZERO = Decimal("0.00")

# --- 3.1 retention calendar -------------------------------------------------

RETENTION_DAYS = {"STANDARD": 365, "EXTENDED": 1825, "LEGAL_HOLD": None}


def retention_calendar(term):
    """student_access_end_at = the calendar date reached by advancing
    term_end_at by access_grace_days whole days, at 23:59:59 UTC.
    retention_purge_at = that instant advanced by the class horizon, or null
    under LEGAL_HOLD (PRD 3.1)."""
    access_end = day_end(add_days(term["term_end_at"], term["access_grace_days"]))
    horizon = RETENTION_DAYS.get(term["retention_class"])
    purge_at = None if horizon is None else day_end(add_days(access_end, horizon))
    set_field(term, "student_access_end_at", access_end)
    set_field(term, "retention_purge_at", purge_at)


# --- 3.2 rollover completion percentage ------------------------------------

def eligible_shells(term_id):
    return [
        s for s in db.shells.values()
        if s["term_id"] == term_id
        and s["shell_type"] == "OFFICIAL"
        and s["provisioning_state"] not in ("REJECTED", "MERGED", "PURGED")
    ]


def recompute_rollover_pct(term):
    eligible = eligible_shells(term["id"])
    if not eligible:
        set_field(term, "rollover_completion_pct", q2(Decimal(100)))
        return term["rollover_completion_pct"]
    completed_targets = set(
        j["target_shell_id"] for j in db.jobs.values() if j["job_state"] == "COMPLETED"
    )
    completed = sum(1 for s in eligible if s["id"] in completed_targets)
    set_field(term, "rollover_completion_pct", pct(Decimal(completed), Decimal(len(eligible))))
    return term["rollover_completion_pct"]


# --- 3.3 sandbox storage chargeback ----------------------------------------

FREE_ALLOWANCE_MB = Decimal("100.00")
RATE_USD_PER_MB = Decimal("0.0150")
CLASS_MULTIPLIER = {"SANDBOX": Decimal("1.00"), "DEV": Decimal("0.50")}
SANDBOX_STORAGE_QUOTA_MB = Decimal("500.00")
SANDBOX_EXPIRY_DAYS = 60
MAX_LIVE_SANDBOX_SHELLS = 3


def billable_shells(person_id):
    return by_created([
        s for s in db.shells.values()
        if s["owner_person_id"] == person_id
        and s["shell_type"] in ("SANDBOX", "DEV")
        and s["provisioning_state"] not in ("REJECTED", "PURGED")
    ])


def recompute_chargeback(person):
    """Rounds once per shell and never on the accumulated sum (PRD 3.3)."""
    if person is None:
        return
    total = ZERO
    for shell in billable_shells(person["id"]):
        billable = shell["storage_mb"] - FREE_ALLOWANCE_MB
        if billable < 0:
            billable = ZERO
        charge = q2(billable * RATE_USD_PER_MB * CLASS_MULTIPLIER[shell["shell_type"]])
        total = total + charge
    set_field(person, "sandbox_storage_charge_usd", q2(total))


# --- 3.4 seat capacity -----------------------------------------------------

OVERFLOW_RATIO = {
    "NORMAL": Decimal("0.00"),
    "ELEVATED": Decimal("0.10"),
    "CONTINUITY_MODE": Decimal("0.20"),
}


def frozen_seat_cap(shell, term):
    """Steps one and two: the ratio comes from the term's posture and from
    nothing else; the allowance rounds down to a whole seat."""
    ratio = OVERFLOW_RATIO[term["continuity_posture"]]
    allowance = floor_dec(Decimal(shell["base_seat_cap"]) * ratio)
    return shell["base_seat_cap"] + allowance


def active_rows(shell_id):
    return [
        e for e in db.enrollments.values()
        if e["shell_id"] == shell_id
        and e["role"] == "STUDENT"
        and e["enrollment_state"] == "ACTIVE"
    ]


def waitlisted_rows(shell_id):
    return [
        e for e in db.enrollments.values()
        if e["shell_id"] == shell_id and e["enrollment_state"] == "WAITLISTED"
    ]


def capacity_probe(shell, term):
    """Steps one to three.  Freezes effective_seat_cap and reports the open
    seats and the promotable head count."""
    cap = frozen_seat_cap(shell, term)
    set_field(shell, "effective_seat_cap", cap)
    active = len(active_rows(shell["id"]))
    waiting = len(waitlisted_rows(shell["id"]))
    open_seats = cap - active
    if open_seats < 0:
        open_seats = 0
    return cap, open_seats, min(open_seats, waiting)


def renumber_waitlist(shell_id):
    queue = sorted(
        waitlisted_rows(shell_id),
        key=lambda e: (e["waitlist_position"] if e["waitlist_position"] is not None else 0,
                       e["created_at"], e["_seq"]),
    )
    for index, row in enumerate(queue, start=1):
        set_field(row, "waitlist_position", index)


def run_capacity(shell, term, promote=True):
    """The full pinned run: freeze the cap, promote the head of the queue while
    seats remain, renumber the survivors, then recompute the observables."""
    cap, open_seats, promotable = capacity_probe(shell, term)
    promoted = 0
    if promote and promotable > 0:
        queue = sorted(
            waitlisted_rows(shell["id"]),
            key=lambda e: (e["waitlist_position"] if e["waitlist_position"] is not None else 0,
                           e["created_at"], e["_seq"]),
        )
        for row in queue[:promotable]:
            set_field(row, "enrollment_state", "ACTIVE")
            set_field(row, "waitlist_position", None)
            promoted += 1
    renumber_waitlist(shell["id"])
    recompute_shell(shell)
    recompute_term(term)
    return promoted


# --- derived record figures ------------------------------------------------

def recompute_shell(shell):
    absorbed = sum(1 for s in db.shells.values()
                   if s.get("merged_into_shell_id") == shell["id"])
    set_field(shell, "absorbed_child_count", absorbed)

    items = [i for i in db.items.values() if i["shell_id"] == shell["id"]]
    live_items = [i for i in items if i["copy_state"] != "SKIPPED"]
    storage = ZERO
    for item in items:
        storage = storage + item["storage_mb"]
    if shell["provisioning_state"] == "REJECTED":
        storage = ZERO
    set_field(shell, "storage_mb", q2(storage))
    set_field(shell, "content_item_count", len(live_items))
    points = ZERO
    for item in live_items:
        if item["item_type"] in ("ASSIGNMENT", "QUIZ"):
            points = points + item["points_possible"]
    set_field(shell, "total_points_possible", q2(points))

    placements = [p for p in db.placements.values() if p["shell_id"] == shell["id"]]
    blocked = sum(1 for p in placements if p["placement_state"] == "BLOCKED")
    set_field(shell, "blocked_placement_count", blocked)
    # PRD 3.7: a shell is publish-ready exactly when blocked_placement_count is 0.
    set_field(shell, "publish_readiness", blocked == 0)

    if shell["provisioning_state"] == "MERGED":
        set_field(shell, "active_enrollment_count", 0)
        set_field(shell, "waitlisted_enrollment_count", 0)
        set_field(shell, "seat_utilization_pct", ZERO)
        set_field(shell, "overflow_flag", False)
        return
    active = len(active_rows(shell["id"]))
    set_field(shell, "active_enrollment_count", active)
    set_field(shell, "waitlisted_enrollment_count", len(waitlisted_rows(shell["id"])))
    set_field(shell, "seat_utilization_pct",
              pct(Decimal(active), Decimal(shell["base_seat_cap"])))
    set_field(shell, "overflow_flag", active > shell["base_seat_cap"])


def recompute_term(term):
    shells = [s for s in db.shells.values() if s["term_id"] == term["id"]]
    set_field(term, "published_shell_count",
              sum(1 for s in shells if s["provisioning_state"] == "PUBLISHED"))
    set_field(term, "overflow_shell_count",
              sum(1 for s in shells if s["overflow_flag"]))
    total = 0
    for shell in shells:
        if shell["provisioning_state"] in ("REJECTED", "PURGED"):
            continue
        total += shell["active_enrollment_count"]
    set_field(term, "total_active_enrollments", total)
    set_field(term, "open_amendment_count", sum(
        1 for p in db.passbacks.values()
        if p["term_id"] == term["id"] and p["passback_state"] in ("DISPUTED", "AMENDED")
    ))


def recompute_shell_and_term(shell):
    recompute_shell(shell)
    recompute_term(db.terms[shell["term_id"]])


# --- 3.8 grade percentages -------------------------------------------------

def grade_records_of(enrollment_id):
    return [r for key, r in db.grade_records.items() if key[0] == enrollment_id]


def recompute_enrollment_grades(enrollment):
    earned = ZERO
    possible = ZERO
    for record in grade_records_of(enrollment["id"]):
        earned = earned + record["earned_points"]
        item = db.items.get(record["content_item_id"])
        if item is not None:
            possible = possible + item["points_possible"]
    set_field(enrollment, "earned_points_total", q2(earned))
    set_field(enrollment, "graded_points_possible", q2(possible))
    set_field(enrollment, "provisional_grade_pct",
              pct(enrollment["earned_points_total"], enrollment["graded_points_possible"]))


def staged_rows(shell_id):
    """Only STUDENT rows that are ACTIVE or COMPLETED are graded (PRD 3.8)."""
    return by_created([
        e for e in db.enrollments.values()
        if e["shell_id"] == shell_id
        and e["role"] == "STUDENT"
        and e["enrollment_state"] in ("ACTIVE", "COMPLETED")
    ])


def provisional_pct(enrollment):
    return pct(enrollment["earned_points_total"], enrollment["graded_points_possible"])


def final_pct(enrollment, shell):
    return pct(enrollment["earned_points_total"], shell["total_points_possible"])


# --- 3.7 tool risk score ---------------------------------------------------

SCOPE_POINTS = {
    "NONE": Decimal("0"),
    "ROSTER_ONLY": Decimal("10"),
    "ROSTER_AND_GRADES": Decimal("25"),
    "FULL_PROFILE": Decimal("40"),
}
WCAG_POINTS = {
    "NONE": Decimal("20"),
    "A": Decimal("10"),
    "AA": Decimal("0"),
    "AAA": Decimal("-5"),
}
RISK_APPROVE_BELOW = Decimal("40.00")
RISK_REJECT_AT = Decimal("70.00")


def risk_score(tool):
    """Five addends, clamped into [0.00, 100.00], rounded half up once after
    clamping (PRD 3.7)."""
    raw = Decimal(tool["pii_tier"]) * Decimal(10)
    raw += SCOPE_POINTS[tool["data_sharing_scope"]]
    raw += (Decimal(100) - tool["vpat_score"]) * Decimal("0.30")
    raw += WCAG_POINTS[tool["wcag_level"]]
    exposure = Decimal(tool["active_placement_count"]) * Decimal(3)
    if exposure > Decimal(15):
        exposure = Decimal(15)
    raw += exposure
    if raw < 0:
        raw = Decimal(0)
    if raw > Decimal(100):
        raw = Decimal(100)
    return q2(raw)


def recompute_tool_placements(tool):
    active = sum(1 for p in db.placements.values()
                 if p["tool_id"] == tool["id"] and p["placement_state"] == "ACTIVE")
    set_field(tool, "active_placement_count", active)


def rescore_tool(tool):
    recompute_tool_placements(tool)
    set_field(tool, "risk_score", risk_score(tool))


# --- 3.6 due-date projection ----------------------------------------------

WEEK_SECONDS = 604800


def project_due_at(due_at, source_term, target_term, mode):
    source_span = int((source_term["term_end_at"] - source_term["term_start_at"]).total_seconds())
    target_span = int((target_term["term_end_at"] - target_term["term_start_at"]).total_seconds())
    if mode == "FIXED_OFFSET":
        delta = int((target_term["term_start_at"] - source_term["term_start_at"]).total_seconds())
        # Rounded down to a whole number of weeks (PRD 3.6); Python's floor
        # division already rounds toward negative infinity.
        whole_weeks = delta // WEEK_SECONDS
        shifted = add_seconds(due_at, whole_weeks * WEEK_SECONDS)
        if shifted < target_term["term_start_at"]:
            return target_term["term_start_at"]
        if shifted > target_term["term_end_at"]:
            return target_term["term_end_at"]
        return shifted
    offset = int((due_at - source_term["term_start_at"]).total_seconds())
    if source_span <= 0:
        ratio = Fraction(0)
    else:
        ratio = Fraction(offset, source_span)
    if ratio < 0:
        ratio = Fraction(0)
    if ratio > 1:
        ratio = Fraction(1)
    seconds = round_half_up_int(ratio * Fraction(target_span))
    return add_seconds(target_term["term_start_at"], seconds)


# --- 3.9 continuity windows -----------------------------------------------

def extension_days(window_start, window_end):
    seconds = Decimal(int((window_end - window_start).total_seconds()))
    return ceil_dec(seconds / Decimal(86400))
