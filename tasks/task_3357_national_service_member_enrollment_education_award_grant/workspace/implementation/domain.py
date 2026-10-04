"""Cross-entity business operations: cascades, bubble-ups, selectors, expiry."""
from decimal import Decimal

import clock
import constants as C
import db
import util


def touch(entity):
    """PRD 2.5: every mutation refreshes updated_at and increments version."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] += 1


# ------------------------------------------------------------------ selectors
def latest_check(member_id):
    """The member's latest check = highest check_seq (strictly monotonic)."""
    checks = [c for c in db.store.checks.values() if c["member_id"] == member_id]
    if not checks:
        return None
    return max(checks, key=lambda c: c["check_seq"])


# ------------------------------------------------------------------ calculations
def match_line_allowable(line):
    """Per-line rounding (pinned order): round each line to integer cents first."""
    rate = C.MATCH_RATE_CASH if line["category"] == "CASH" else C.MATCH_RATE_IN_KIND
    return util.round_half_up_int(Decimal(line["amount_cents"]) * rate)


def match_lines_total(lines):
    return sum(match_line_allowable(line) for line in lines)


def cost_per_msy(numerator_cents, total_term_minutes):
    """round_half_up(numerator * 102000 / total_term_minutes, 2) as a number."""
    return util.round_half_up_2dp(
        Decimal(numerator_cents) * Decimal(C.MSY_MINUTES) / Decimal(total_term_minutes)
    )


# ------------------------------------------------------------------ bubble-ups
def competition_bubble(competition):
    """CLOSED -> AWARDS_FINALIZED the moment no application is non-terminal."""
    if competition["status"] != "CLOSED":
        return
    open_states = ("DRAFT", "UNDER_REVIEW", "CLARIFICATION_REQUESTED")
    for app in db.store.applications.values():
        if app["competition_id"] == competition["id"] and app["status"] in open_states:
            return
    competition["status"] = "AWARDS_FINALIZED"
    touch(competition)


def visit_bubble(visit):
    """CONDUCTED -> CLOSED once >=1 finding exists and all findings are RESOLVED."""
    if visit["status"] != "CONDUCTED":
        return
    findings = [f for f in db.store.findings.values() if f["visit_id"] == visit["id"]]
    if findings and all(f["status"] == "RESOLVED" for f in findings):
        visit["status"] = "CLOSED"
        touch(visit)


# ------------------------------------------------------------------ slots
def refill_vacated_slot(slot):
    """Immediate refill evaluation of a VACATED slot (PRD 3.3)."""
    award = db.store.awards.get(slot["award_id"])
    if (
        award is not None
        and award["status"] == "ACTIVE"
        and slot["fill_count"] < C.SLOT_MAX_FILL_COUNT
    ):
        slot["status"] = "OPEN"
    else:
        slot["status"] = "RETIRED"
    touch(slot)


# ------------------------------------------------------------------ award cascades
def suspend_award(award, reason):
    """ACTIVE -> SUSPENDED; cascades to every ACTIVE enrollment (AWARD_CASCADE)."""
    award["status"] = "SUSPENDED"
    award["suspension_reason"] = reason
    touch(award)
    suspended_enrollment_ids = []
    for e in db.store.enrollments.values():
        if e["award_id"] == award["id"] and e["status"] == "ACTIVE":
            e["status"] = "SUSPENDED"
            e["suspension_origin"] = "AWARD_CASCADE"
            touch(e)
            suspended_enrollment_ids.append(e["id"])
    return suspended_enrollment_ids


def reinstate_award(award):
    """SUSPENDED -> ACTIVE; returns only AWARD_CASCADE-suspended enrollments."""
    award["status"] = "ACTIVE"
    award["suspension_reason"] = None
    touch(award)
    for e in db.store.enrollments.values():
        if (
            e["award_id"] == award["id"]
            and e["status"] == "SUSPENDED"
            and e["suspension_origin"] == "AWARD_CASCADE"
        ):
            e["status"] = "ACTIVE"
            e["suspension_origin"] = "NONE"
            touch(e)


# ------------------------------------------------------------------ education awards
def maybe_expire_education_award(ea):
    """Lazy expiry (PRD 2.9): past-deadline ISSUED/PARTIALLY_USED -> EXPIRED."""
    if ea["status"] in ("ISSUED", "PARTIALLY_USED"):
        deadline = clock.parse_datetime(ea["use_deadline_at"])
        if deadline is not None and clock.now() > deadline:
            ea["status"] = "EXPIRED"


def recompute_award_status_after_balance_change(ea):
    if ea["remaining_balance_cents"] == 0:
        ea["status"] = "EXHAUSTED"
    elif ea["remaining_balance_cents"] == ea["issued_amount_cents"]:
        ea["status"] = "ISSUED"
    else:
        ea["status"] = "PARTIALLY_USED"


# ------------------------------------------------------------------ check adjudication
def adjudication_cascade(check):
    """Ripple of a check leaving PENDING (PRD 3.4)."""
    member_id = check["member_id"]
    if check["adjudication"] == "CLEARED":
        for e in db.store.enrollments.values():
            if e["member_id"] == member_id and e["status"] == "PENDING_CHECKS":
                e["status"] = "ACTIVE"
                touch(e)
                slot = db.store.slots.get(e["slot_id"])
                if slot is not None and slot["status"] == "RESERVED":
                    slot["status"] = "FILLED"
                    slot["fill_count"] += 1
                    touch(slot)
    elif check["adjudication"] == "FLAGGED":
        for e in db.store.enrollments.values():
            if e["member_id"] == member_id and e["status"] == "PENDING_CHECKS":
                e["status"] = "CANCELLED"
                touch(e)
                slot = db.store.slots.get(e["slot_id"])
                if slot is not None and slot["status"] == "RESERVED":
                    slot["status"] = "OPEN"
                    touch(slot)
