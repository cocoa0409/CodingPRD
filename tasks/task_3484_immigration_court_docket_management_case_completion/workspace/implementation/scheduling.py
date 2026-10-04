# scheduling.py — hearing duration math, judge/interpreter scheduling checks,
# interpreter selection, and the deterministic forward-search that auto-creates
# replacement / remand / reopen hearings (SCAFFOLD §1.3, PRD §3.3-§3.6).
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING

import db
from constants import (
    CUSTODY_DETAINED, REP_PRO_SE, HEARING_MASTER, HEARING_SCHEDULED,
    HEARING_CANCELLED,
    MASTER_BASE_MINUTES, MERITS_BASE_MINUTES, DETAINED_MERITS_FACTOR,
    REPRESENTED_MERITS_FACTOR, LOP_MASTER_FACTOR, LOP_COVERAGE_THRESHOLD_PCT,
    SLOT_MINUTES, JUDGE_DAILY_MINUTE_CAP, INTERPRETER_BUFFER_MINUTES,
    AUTO_HEARING_MAX_ADVANCE_DAYS,
)
from errors import ApiError


# ---------------------------------------------------------------------------
# Duration (calculations.hearing_duration_and_daily_load)
# ---------------------------------------------------------------------------

def compute_duration_minutes(case, hearing_type):
    """Raw minutes from the case's court LOP rows / custody / representation,
    then ceil UP to a 15-minute block. Per-hearing rounding happens BEFORE any
    aggregation (pinned rounding order)."""
    if hearing_type == HEARING_MASTER:
        factor = Decimal("1")
        for p in db.programs.values():
            if (p["court_id"] == case["court_id"] and p["active"]
                    and p["coverage_pct"] >= LOP_COVERAGE_THRESHOLD_PCT):
                factor = Decimal(LOP_MASTER_FACTOR)
                break
        raw = Decimal(MASTER_BASE_MINUTES) * factor
    else:  # INDIVIDUAL_MERITS
        raw = Decimal(MERITS_BASE_MINUTES)
        if case["custody_status"] == CUSTODY_DETAINED:
            raw *= Decimal(DETAINED_MERITS_FACTOR)
        if case["representation_status"] != REP_PRO_SE:
            raw *= Decimal(REPRESENTED_MERITS_FACTOR)
    blocks = (raw / Decimal(SLOT_MINUTES)).to_integral_value(rounding=ROUND_CEILING)
    return int(blocks * SLOT_MINUTES)


# ---------------------------------------------------------------------------
# Judge load checks (operate on the judge's SCHEDULED hearings)
# ---------------------------------------------------------------------------

def scheduled_hearings_of_judge(judge_id):
    return [h for h in db.hearings.values()
            if h["judge_id"] == judge_id and h["status"] == HEARING_SCHEDULED]


def judge_has_conflict(judge_id, start, end):
    """Half-open [start, end) overlap; adjacency (end == start) is allowed."""
    for h in scheduled_hearings_of_judge(judge_id):
        if start < h["scheduled_end"] and h["scheduled_start"] < end:
            return True
    return False


def judge_day_minutes(judge_id, day):
    """Sum of ALREADY-ROUNDED duration_minutes on the given UTC date."""
    return sum(h["duration_minutes"] for h in scheduled_hearings_of_judge(judge_id)
               if h["scheduled_start"].date() == day)


def judge_day_minutes_ok(judge_id, day, new_duration):
    # equality (exactly the cap) is ALLOWED
    return judge_day_minutes(judge_id, day) + new_duration <= JUDGE_DAILY_MINUTE_CAP


def detained_day_count(court_id, day):
    n = 0
    for h in db.hearings.values():
        if h["status"] != HEARING_SCHEDULED:
            continue
        if h["scheduled_start"].date() != day:
            continue
        c = db.cases.get(h["case_id"])
        if c is not None and c["court_id"] == court_id \
                and c["custody_status"] == CUSTODY_DETAINED:
            n += 1
    return n


def detained_capacity_ok(court, day):
    """Rejected when the count already equals the cap (count < cap passes)."""
    return detained_day_count(court["id"], day) < court["detained_daily_hearing_capacity"]


# ---------------------------------------------------------------------------
# Interpreter selector (calculations.interpreter_assignment_selector)
# ---------------------------------------------------------------------------

def interpreter_candidates(case, start, end):
    """Interpreters of the case's court covering the case's language, under
    their daily cap on that UTC date, and satisfying the strict 15-minute
    buffer around every existing SCHEDULED hearing (a gap of EXACTLY 15
    minutes passes). Ranked by fewest SCHEDULED hearings on that date ASC,
    tie-break created_at ASC (insertion order under the logical clock)."""
    day = start.date()
    buffer = timedelta(minutes=INTERPRETER_BUFFER_MINUTES)
    ranked = []
    for it in db.interpreters.values():
        if it["court_id"] != case["court_id"]:
            continue
        if case["primary_language_code"] not in it["language_codes"]:
            continue
        mine = [h for h in db.hearings.values()
                if h["interpreter_id"] == it["id"]
                and h["status"] == HEARING_SCHEDULED]
        day_count = sum(1 for h in mine if h["scheduled_start"].date() == day)
        if day_count >= it["daily_hearing_cap"]:
            continue
        blocked = False
        for h in mine:
            # disqualified iff existing both ends strictly after start-15min
            # AND begins strictly before end+15min
            if h["scheduled_end"] > start - buffer \
                    and h["scheduled_start"] < end + buffer:
                blocked = True
                break
        if blocked:
            continue
        ranked.append((day_count, it["created_at"], it["_seq"], it))
    ranked.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in ranked]


def select_interpreter(case, start, end):
    pool = interpreter_candidates(case, start, end)
    if not pool:
        raise ApiError("ERR_NO_INTERPRETER_AVAILABLE",
                       "No interpreter in the court's pool covers language "
                       "'%s' on that date within caps and buffers"
                       % case["primary_language_code"])
    return pool[0]


# ---------------------------------------------------------------------------
# Hearing construction
# ---------------------------------------------------------------------------

def build_hearing(case, hearing_type, start, is_remote, auto_created=False,
                  supersedes_hearing_id=None, interpreter=None,
                  judge_id=None):
    """Create and store a Hearing. `interpreter` may be pre-selected by the
    caller (direct creation selects at tier 10 so ERR_NO_INTERPRETER_AVAILABLE
    precedes the tier-11 OCC check); otherwise selection runs here when the
    case requires an interpreter."""
    duration = compute_duration_minutes(case, hearing_type)
    end = start + timedelta(minutes=duration)
    if case["interpreter_required"]:
        interpreter = interpreter or select_interpreter(case, start, end)
        interpreter_id = interpreter["id"]
    else:
        interpreter_id = None
    h = {
        "id": str(uuid.uuid4()),
        "case_id": case["id"],
        "hearing_type": hearing_type,
        "scheduled_start": start,
        "duration_minutes": duration,
        "scheduled_end": end,
        "is_remote": bool(is_remote),
        "judge_id": judge_id if judge_id is not None else case["assigned_judge_id"],
        "interpreter_id": interpreter_id,
        "supersedes_hearing_id": supersedes_hearing_id,
        "auto_created": auto_created,
        "status": HEARING_SCHEDULED,
    }
    db.stamp_new(h)
    db.stamp_common(h)
    db.hearings[h["id"]] = h
    return h


def auto_schedule_hearing(case, hearing_type, base_start, is_remote,
                          supersedes_hearing_id=None, judge_id=None):
    """System auto-created hearings (continuance replacement, remand merits,
    reopen master): exempt from the expedited filing-relative deadline, but
    still run judge overlap, judge daily-minute cap, detained daily capacity,
    and interpreter selection. The candidate slot advances +1 calendar day
    until every applicable check passes (deterministic forward search)."""
    jid = judge_id if judge_id is not None else case["assigned_judge_id"]
    court = db.courts[case["court_id"]]
    duration = compute_duration_minutes(case, hearing_type)
    start = base_start
    for _ in range(AUTO_HEARING_MAX_ADVANCE_DAYS + 1):
        end = start + timedelta(minutes=duration)
        if judge_has_conflict(jid, start, end):
            start = start + timedelta(days=1)
            continue
        if not judge_day_minutes_ok(jid, start.date(), duration):
            start = start + timedelta(days=1)
            continue
        if case["custody_status"] == CUSTODY_DETAINED \
                and not detained_capacity_ok(court, start.date()):
            start = start + timedelta(days=1)
            continue
        interpreter = None
        if case["interpreter_required"]:
            pool = interpreter_candidates(case, start, end)
            if not pool:
                start = start + timedelta(days=1)
                continue
            interpreter = pool[0]
        return build_hearing(case, hearing_type, start, is_remote,
                             auto_created=True,
                             supersedes_hearing_id=supersedes_hearing_id,
                             interpreter=interpreter, judge_id=jid)
    raise ApiError("ERR_NO_INTERPRETER_AVAILABLE",
                   "No feasible hearing slot found within the search bound")


def cancel_scheduled_hearings_of_case(case_id):
    """Conditional cascade: only SCHEDULED hearings become CANCELLED; each is
    touched independently (own version bump + updated_at refresh, PRD §2.5)."""
    for h in db.hearings.values():
        if h["case_id"] == case_id and h["status"] == HEARING_SCHEDULED:
            h["status"] = HEARING_CANCELLED
            db.touch(h)
