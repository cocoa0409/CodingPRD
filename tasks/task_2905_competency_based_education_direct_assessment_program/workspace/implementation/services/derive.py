"""Derived roll-ups: always full recomputations over the source rows (PRD 2.10)."""
from decimal import Decimal

import db as store
from db import db
from services import lookup
from services.nums import HUNDRED, ONE, ZERO, dec, rhu, trunc

LIVE_ATTEMPT_STATUSES = ("DRAFT", "UNDER_REVIEW", "ADJUDICATION",
                         "INTEGRITY_HOLD", "REVISION_REQUESTED")
LIVE_CASE_STATUSES = ("OPEN", "UNDER_INVESTIGATION")


# ------------------------------------------------------------------ program

def program_competency_count(program_row):
    return len([c for c in lookup.competencies_of(program_row["id"])
                if c["status"] == "ACTIVE"])


# --------------------------------------------------------------- competency

def effective_mastery_threshold(comp):
    if comp.get("mastery_threshold_pct") is not None:
        return rhu(comp["mastery_threshold_pct"], 2)
    program = lookup.program_of_competency(comp)
    if program is None:
        return None
    return rhu(program["mastery_threshold_pct"], 2)


def prerequisite_depth(comp):
    depth = 0
    seen = {comp["id"]}
    cursor = comp
    while cursor.get("prerequisite_competency_id"):
        nxt = db.competencies.get(cursor["prerequisite_competency_id"])
        if nxt is None or nxt["id"] in seen:
            break
        seen.add(nxt["id"])
        depth += 1
        cursor = nxt
    return depth


def effective_blueprint(comp):
    """The unique blueprint whose half-open window contains the clock."""
    now = db.now()
    best = None
    for bp in lookup.blueprints_of(comp["id"]):
        if bp["effective_from_utc"] > now:
            continue
        if bp["effective_to_utc"] is not None and now >= bp["effective_to_utc"]:
            continue
        if best is None or bp["effective_from_utc"] > best["effective_from_utc"]:
            best = bp
    return best


def current_published_blueprint(comp):
    for bp in lookup.blueprints_of(comp["id"]):
        if bp["status"] == "PUBLISHED" and bp["effective_to_utc"] is None:
            return bp
    return None


def blueprint_ordinal(bp):
    siblings = sorted(
        lookup.blueprints_of(bp["competency_id"]),
        key=lambda b: (b["effective_from_utc"], b["created_at"], b["_seq"]),
    )
    for index, row in enumerate(siblings):
        if row["id"] == bp["id"]:
            return index + 1
    return len(siblings) + 1


def mastered_by_student_count(comp):
    students = set()
    for att in db.attempts.values():
        if att["competency_id"] != comp["id"]:
            continue
        if att["status"] != "SCORED_MASTERED":
            continue
        if att.get("is_provisional_score"):
            continue
        students.add(att["student_id"])
    return len(students)


def blueprint_attempts_bound_count(bp):
    return len([a for a in db.attempts.values()
                if a.get("blueprint_id") == bp["id"]])


# ------------------------------------------------------------------ student

def mastered_attempts(student_id):
    return [a for a in lookup.attempts_of(student_id)
            if a["status"] == "SCORED_MASTERED"
            and not a.get("is_provisional_score")]


def mastered_competency_map(student_id):
    """competency_id -> the mastering attempt (earliest by mastery instant)."""
    result = {}
    for att in sorted(mastered_attempts(student_id),
                      key=lambda a: (a["mastered_at_utc"] or a["created_at"],
                                     a["created_at"], a["_seq"])):
        result.setdefault(att["competency_id"], att)
    return result


def mastered_unit_total(student_id):
    total = ZERO
    for comp_id in mastered_competency_map(student_id):
        comp = db.competencies.get(comp_id)
        if comp is not None:
            total = total + comp["unit_value"]
    return total


def mastered_competency_count(student_id):
    return len(mastered_competency_map(student_id))


def cumulative_credit_equivalency(student_row):
    program = lookup.program_of_student(student_row)
    total = mastered_unit_total(student_row["id"])
    if program is None or program["units_per_credit_hour"] <= 0:
        return rhu(ZERO, 1)
    return rhu(total / program["units_per_credit_hour"], 1)


def integrity_strike_count(student_id):
    return len([c for c in lookup.cases_of_student(student_id)
                if c["status"] == "SUBSTANTIATED"])


def open_case_count(student_id):
    return len([c for c in lookup.cases_of_student(student_id)
                if c["status"] in LIVE_CASE_STATUSES])


def student_has_live_case(student_id):
    return open_case_count(student_id) > 0


def attempt_has_live_case(attempt_id):
    return any(c["status"] in LIVE_CASE_STATUSES
               for c in lookup.cases_of_attempt(attempt_id))


def aid_scheduled_total_cents(student_id):
    return sum(d["scheduled_amount_cents"]
               for d in lookup.disbursements_of_student(student_id))


def aid_retained_total_cents(student_id):
    return sum(d["retained_amount_cents"]
               for d in lookup.disbursements_of_student(student_id))


def aid_returned_total_cents(student_id):
    return sum(d["returned_amount_cents"]
               for d in lookup.disbursements_of_student(student_id))


# --------------------------------------------------------------------- term

def term_days(term_row):
    return store.whole_days_between(term_row["term_start_utc"],
                                    term_row["term_end_utc"])


def term_attempts_used(term_row):
    return len([a for a in lookup.attempts_on_term(term_row["id"])
                if a["status"] != "VOIDED"])


def units_mastered_in_term(term_row):
    seen = {}
    for att in lookup.attempts_on_term(term_row["id"]):
        if att["status"] != "SCORED_MASTERED" or att.get("is_provisional_score"):
            continue
        seen.setdefault(att["competency_id"], True)
    total = ZERO
    for comp_id in seen:
        comp = db.competencies.get(comp_id)
        if comp is not None:
            total = total + comp["unit_value"]
    return total


def credit_equivalency_earned(term_row):
    student_row = db.students.get(term_row["student_id"])
    program = lookup.program_of_student(student_row) if student_row else None
    units = units_mastered_in_term(term_row)
    if program is None or program["units_per_credit_hour"] <= 0:
        return 0
    return trunc(units / program["units_per_credit_hour"])


def active_term_covering_clock(student_id):
    now = db.now()
    for term_row in lookup.terms_of(student_id):
        if term_row["status"] != "ACTIVE":
            continue
        if term_row["term_start_utc"] <= now < term_row["term_end_utc"]:
            return term_row
    return None


def active_terms(student_id):
    return [t for t in lookup.terms_of(student_id) if t["status"] == "ACTIVE"]


# ------------------------------------------------------------------- mentor

def mentor_caseload(mentor_row):
    return len([a for a in lookup.assignments_for_mentor(mentor_row["id"])
                if a["status"] == "ACTIVE"])


def active_assignment(student_id):
    for asg in store.by_created(lookup.assignments_of(student_id),
                                descending=True):
        if asg["status"] == "ACTIVE":
            return asg
    return None


def next_contact_due(asg):
    anchor = asg.get("last_contact_utc") or asg["assigned_at_utc"]
    return store.add_days(anchor, asg["cadence_days"])


def cadence_state(asg):
    due = next_contact_due(asg)
    now = db.now()
    if now <= due:
        return "COMPLIANT", 0, due
    return "OVERDUE", store.whole_days_between(due, now), due


def unconsumed_endorsements(asg):
    rows = [e for e in asg.get("endorsements", []) if not e["consumed"]]
    rows.sort(key=lambda e: (e["created_at"], e["seq"]))
    return rows


def endorsement_count(asg):
    return len(asg.get("endorsements", []))


# ---------------------------------------------------------------- evaluator

def submitted_score_count(evaluator_row):
    return len([s for s in db.scores.values()
                if s["evaluator_id"] == evaluator_row["id"]
                and s["status"] == "SUBMITTED"])


def _completed_pairs():
    """Yield (attempt, score_slot_1, score_slot_2) for every completed pair."""
    pairs = []
    for att in db.attempts.values():
        if att["status"] == "VOIDED":
            continue
        slot1 = None
        slot2 = None
        for sc in lookup.scores_of(att["id"]):
            if sc["status"] != "SUBMITTED":
                continue
            if sc["reader_ordinal"] == 1:
                slot1 = sc
            elif sc["reader_ordinal"] == 2:
                slot2 = sc
        if slot1 is not None and slot2 is not None:
            pairs.append((att, slot1, slot2))
    return pairs


def _pair_agrees(att, slot1, slot2):
    program = lookup.program_of_attempt(att)
    tolerance = program["irr_tolerance_pct"] if program else ZERO
    gap = abs(slot1["weighted_score_pct"] - slot2["weighted_score_pct"])
    return gap <= tolerance


def evaluator_reliability(evaluator_row):
    paired = 0
    agreeing = 0
    for att, slot1, slot2 in _completed_pairs():
        if evaluator_row["id"] not in (slot1["evaluator_id"],
                                       slot2["evaluator_id"]):
            continue
        paired += 1
        if _pair_agrees(att, slot1, slot2):
            agreeing += 1
    if paired == 0:
        rate = rhu(HUNDRED, 2)
    else:
        rate = rhu((Decimal(agreeing) / Decimal(paired)) * HUNDRED, 2)
    return paired, agreeing, rate


# ------------------------------------------------------------------ attempt

def attempt_integrity_hold(att):
    if att["status"] == "VOIDED":
        return False
    return attempt_has_live_case(att["id"])


def attempt_scores_received_count(att):
    return len([s for s in lookup.scores_of(att["id"])
                if s["status"] == "SUBMITTED"])


def attempt_cooloff_until(att):
    if att["status"] != "SCORED_NOT_MASTERED":
        return None
    if att.get("scored_at_utc") is None:
        return None
    program = lookup.program_of_attempt(att)
    if program is None:
        return None
    return store.add_seconds(att["scored_at_utc"],
                             int(program["attempt_cooloff_hours"])
                             * store.SECONDS_PER_HOUR)


def attempt_number(att):
    if att["status"] == "VOIDED":
        return att.get("_frozen_attempt_number", att.get("attempt_number", 1))
    siblings = [a for a in db.attempts.values()
                if a["student_id"] == att["student_id"]
                and a["competency_id"] == att["competency_id"]
                and a["status"] != "VOIDED"]
    siblings = store.by_created(siblings)
    for index, row in enumerate(siblings):
        if row["id"] == att["id"]:
            return index + 1
    return len(siblings) + 1
