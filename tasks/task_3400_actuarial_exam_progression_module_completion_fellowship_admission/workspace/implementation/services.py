"""Shared business logic: seating, fees/refunds, waitlist promotion, transition
credit mapping, credit totals, scaled/projected scores, enrollment bubble-up,
CPD requirement, credential evaluation. All formulas follow PRD §3 and the
scaffold calculations table exactly (Decimal, ROUND_HALF_UP where pinned).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import constants as C
from store import db, touch


def rhu(value, places):
    """Round-half-up a Decimal to the given number of places; returns Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Derived seating / attendance counters (always recomputed from children)
# ---------------------------------------------------------------------------

def window_regs(window):
    return [r for r in db.exam_registrations.values()
            if r["exam_window_id"] == window["id"]]


def seats_held(window):
    return sum(1 for r in window_regs(window)
               if r["logistics_status"] == "REGISTERED")


def waitlist_count(window):
    return sum(1 for r in window_regs(window)
               if r["logistics_status"] == "WAITLISTED")


def attendance_booked(session):
    return sum(1 for a in db.course_attendances.values()
               if a["course_session_id"] == session["id"] and a["status"] == "BOOKED")


# ---------------------------------------------------------------------------
# Fees and refunds (PRD §3.3; pinned rounding order: processing once on the
# summed subtotal, rounded half-up to whole cents, then added)
# ---------------------------------------------------------------------------

def compute_fee_cents(window, when_dt):
    late = when_dt >= (window["registration_deadline"]
                       - timedelta(days=C.LATE_FEE_WINDOW_DAYS))
    subtotal = window["base_fee_cents"] + (window["late_surcharge_cents"] if late else 0)
    processing = int(rhu(Decimal(subtotal) * Decimal(C.PROCESSING_RATE), 0))
    return subtotal + processing


def compute_refund_cents(reg, window, reason, when_dt):
    fee = reg["fee_charged_cents"]
    if reason == "DISCIPLINE_EXPULSION":
        return 0
    if reason in ("DISCIPLINE_SUSPENSION", "SYLLABUS_RETIREMENT"):
        return fee  # full refund; WAITLISTED rows carry fee None -> refund None
    # CANDIDATE voluntary cancellation: full before the deadline, half at/after.
    if fee is None:
        return None
    if when_dt < window["registration_deadline"]:
        return fee
    return int(rhu(Decimal(fee) * Decimal(C.LATE_REFUND_RATIO), 0))


def cancel_registration(reg, window, reason, when_dt, allow_promotion=True):
    was_registered = reg["logistics_status"] == "REGISTERED"
    reg["logistics_status"] = "CANCELLED"
    reg["cancel_reason"] = reason
    reg["refund_cents"] = compute_refund_cents(reg, window, reason, when_dt)
    touch(reg)
    if was_registered and allow_promotion and window["status"] == "REGISTRATION_OPEN":
        promote_waitlist(window, when_dt)


def promote_waitlist(window, when_dt):
    waiting = [r for r in window_regs(window) if r["logistics_status"] == "WAITLISTED"]
    if not waiting:
        return None

    def key(r):
        cand = db.candidates.get(r["candidate_id"])
        return (r["created_at"], cand["created_at"] if cand else "", r["_seq"])

    waiting.sort(key=key)
    promoted = waiting[0]
    promoted["logistics_status"] = "REGISTERED"
    promoted["fee_charged_cents"] = compute_fee_cents(window, when_dt)
    touch(promoted)
    return promoted


# ---------------------------------------------------------------------------
# Transition credit mapping (PRD §2.10): mapping chains evaluated in version
# activation order; unmapped credits remain historical credits on the original.
# ---------------------------------------------------------------------------

def activated_versions():
    versions = [v for v in db.syllabus_versions.values()
                if v["activated_at"] is not None]
    versions.sort(key=lambda v: (v["activated_at"], v["_seq"]))
    return versions


def map_exam_code_forward(code):
    for v in activated_versions():
        cmap = v["credit_map"] or {}
        if code in cmap:
            code = cmap[code]
    return code


def exam_by_code(code):
    for e in db.exams.values():
        if e["exam_code"] == code:
            return e
    return None


def candidate_credit_exam_ids(candidate_id):
    """Distinct exams on which the candidate holds a PASS credit, after mapping."""
    ids = set()
    for r in db.exam_registrations.values():
        if r["candidate_id"] != candidate_id or r["result"] != "PASS":
            continue
        window = db.exam_windows.get(r["exam_window_id"])
        exam = db.exams.get(window["exam_id"]) if window else None
        if exam is None:
            continue
        final = exam_by_code(map_exam_code_forward(exam["exam_code"]))
        ids.add(final["id"] if final is not None else exam["id"])
    return ids


def credit_totals(candidate_id):
    earned = 0
    for exam_id in candidate_credit_exam_ids(candidate_id):
        exam = db.exams.get(exam_id)
        if exam is not None:
            earned += exam["credit_hours"]
    transfer = sum(t["granted_hours"]
                   for t in db.transfer_credit_requests.values()
                   if t["candidate_id"] == candidate_id and t["status"] == "GRANTED")
    return earned, transfer, earned + transfer


def holds_credit_on(candidate_id, exam_id):
    return exam_id in candidate_credit_exam_ids(candidate_id)


# ---------------------------------------------------------------------------
# Scaled scores and the provisional projection (PRD §3.3)
# ---------------------------------------------------------------------------

def scaled_score_of(reg):
    raw = reg["raw_score"]
    if raw is None:
        return None
    return rhu(Decimal(raw) / Decimal(C.MAX_RAW_SCORE) * Decimal(10), 1)


def latest_live_setting(window_id):
    settings = [s for s in db.pass_mark_settings.values()
                if s["exam_window_id"] == window_id and s["status"] != "SUPERSEDED"]
    if not settings:
        return None
    settings.sort(key=lambda s: s["_seq"])
    return settings[-1]


def projected_result_of(reg):
    if reg["grading_status"] == "RELEASED":
        return None
    scaled = scaled_score_of(reg)
    if scaled is None:
        return None
    setting = latest_live_setting(reg["exam_window_id"])
    if setting is None:
        return None
    mark = setting["ratified_mark"] if setting["status"] == "RATIFIED" \
        else setting["proposed_mark"]
    if mark is None:
        return None
    return "PASS" if scaled >= Decimal(str(mark)) else "FAIL"


# ---------------------------------------------------------------------------
# Track enrollment bubble-up (PRD §3.5; pinned evaluation order: the capstone
# gate reads ONLY non-capstone passes, before any capstone/project contribution)
# ---------------------------------------------------------------------------

def track_modules(track_code):
    return [m for m in db.modules.values() if m["track_code"] == track_code]


def passed_module_ids(enrollment_id):
    return {a["module_id"] for a in db.module_attempts.values()
            if a["track_enrollment_id"] == enrollment_id and a["status"] == "PASSED"}


def enrollment_stats(enrollment):
    modules = track_modules(enrollment["track_code"])
    noncapstone = [m for m in modules if not m["is_capstone"]]
    capstones = [m for m in modules if m["is_capstone"]]
    passed = passed_module_ids(enrollment["id"])
    track_module_ids = {m["id"] for m in modules}
    ncp = sum(1 for m in noncapstone if m["id"] in passed)
    capstone_passed = 1 if any(m["id"] in passed for m in capstones) else 0
    project_passed = 1 if any(
        p["track_enrollment_id"] == enrollment["id"] and p["result"] == "PASS"
        for p in db.project_assessments.values()) else 0
    modules_passed = len(passed & track_module_ids)
    denominator = (C.NONCAPSTONE_WEIGHT * len(noncapstone)
                   + C.CAPSTONE_WEIGHT + C.PROJECT_WEIGHT)
    numerator = (C.NONCAPSTONE_WEIGHT * ncp
                 + C.CAPSTONE_WEIGHT * capstone_passed
                 + C.PROJECT_WEIGHT * project_passed)
    pct = float(rhu(Decimal(100) * Decimal(numerator) / Decimal(denominator), 2))
    return {
        "modules_passed_count": modules_passed,
        "completion_pct": pct,
        "noncapstone_all_passed": ncp == len(noncapstone),
        "capstone_passed": capstone_passed == 1,
    }


def sync_enrollment_after_pass(enrollment, module):
    """Bubble-up on a PASSED attempt: advance status, one version increment."""
    stats = enrollment_stats(enrollment)
    if enrollment["status"] == "ENROLLED" and stats["noncapstone_all_passed"]:
        enrollment["status"] = "CAPSTONE_ELIGIBLE"
    if enrollment["status"] == "CAPSTONE_ELIGIBLE" and module["is_capstone"]:
        enrollment["status"] = "COMPLETED"
    touch(enrollment)


def sync_enrollment_after_project(enrollment):
    """Bubble-up on a DECIDED-PASS project (completion_pct gains the weight)."""
    touch(enrollment)


# ---------------------------------------------------------------------------
# CPD requirement (PRD §3.8: proration in the admission year, carryover cap 10)
# ---------------------------------------------------------------------------

def cpd_required_hours(candidate, cycle_year, carryover_hours):
    admitted = candidate["associate_admitted_at"]
    if admitted is not None and admitted.year == cycle_year:
        months_remaining = 13 - admitted.month  # admission month counts in full
        base = -(-(C.CPD_BASE_HOURS * months_remaining) // 12)  # ceil
    else:
        base = C.CPD_BASE_HOURS
    return max(0, base - min(carryover_hours, C.CPD_CARRYOVER_CAP))


# ---------------------------------------------------------------------------
# Credential evaluation (PRD §3.9; synchronous, canonical deficiency order)
# ---------------------------------------------------------------------------

def evaluate_credential(candidate, credential):
    deficiencies = []
    if credential == "ASA":
        active = None
        for v in db.syllabus_versions.values():
            if v["status"] == "ACTIVE":
                active = v
                break
        if active is None:
            deficiencies.append("MISSING_PRELIM_CREDIT")
        else:
            prelim = [e for e in db.exams.values()
                      if e["syllabus_version_id"] == active["id"] and e["is_prelim"]]
            credits = candidate_credit_exam_ids(candidate["id"])
            if any(e["id"] not in credits for e in prelim):
                deficiencies.append("MISSING_PRELIM_CREDIT")
        approved_topics = {s["topic"] for s in db.vee_submissions.values()
                           if s["candidate_id"] == candidate["id"]
                           and s["status"] == "APPROVED"}
        if any(topic not in approved_topics for topic in C.VEE_TOPICS):
            deficiencies.append("MISSING_VEE_TOPIC")
        earned, transfer, _ = credit_totals(candidate["id"])
        if earned + min(transfer, C.ASA_TRANSFER_CREDIT_CAP) < C.ASA_MIN_TOTAL_CREDITS:
            deficiencies.append("INSUFFICIENT_TOTAL_CREDITS")
    else:  # FSA
        if candidate["membership_tier"] == "CANDIDATE":
            deficiencies.append("MISSING_ASA")
        if not any(t["candidate_id"] == candidate["id"] and t["status"] == "COMPLETED"
                   for t in db.track_enrollments.values()):
            deficiencies.append("TRACK_INCOMPLETE")
        if not any(p["candidate_id"] == candidate["id"] and p["result"] == "PASS"
                   for p in db.project_assessments.values()):
            deficiencies.append("MISSING_PROJECT_PASS")
        if not any(a["candidate_id"] == candidate["id"] and a["status"] == "ATTENDED"
                   for a in db.course_attendances.values()):
            deficiencies.append("MISSING_PROFESSIONALISM")
    order = {code: i for i, code in enumerate(C.DEFICIENCY_ORDER)}
    deficiencies.sort(key=lambda d: order[d])
    return deficiencies
