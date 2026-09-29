"""Lookups, gates, derived fields and cascades.

PRD 2.10: "cascades run to completion within the triggering request: there is
no deferred settlement, no background sweep and no eventual consistency. When
the request returns, every derived value reachable from the write is already
correct." And: "whenever a cascade acts on a set of sibling rows ... those rows
are processed in `created_at` ascending order."
"""

from decimal import Decimal

import errors
from db import db, now, order_rows, touch
from errors import fail
from services import calc

# --- collection scans ------------------------------------------------------


def rows_of(collection, **filters):
    out = []
    for row in collection.values():
        match = True
        for key, value in filters.items():
            if row.get(key) != value:
                match = False
                break
        if match:
            out.append(row)
    return order_rows(out)


# --- lookups (step 4 of PRD 2.9: existence, HTTP 404) ---------------------


def get_program(program_id):
    row = db.season_programs.get(program_id)
    if row is None:
        fail(errors.ERR_SEASON_PROGRAM_NOT_FOUND,
             "Season program '%s' was not found." % program_id)
    return row


def get_official(official_id):
    row = db.officials.get(official_id)
    if row is None:
        fail(errors.ERR_OFFICIAL_NOT_FOUND,
             "Official '%s' was not found." % official_id)
    return row


def get_application(application_id):
    row = db.applications.get(application_id)
    if row is None:
        fail(errors.ERR_APPLICATION_NOT_FOUND,
             "Advancement application '%s' was not found." % application_id)
    return row


def get_game(game_id):
    row = db.games.get(game_id)
    if row is None:
        fail(errors.ERR_GAME_NOT_FOUND, "Game '%s' was not found." % game_id)
    return row


def get_assignment(assignment_id):
    row = db.assignments.get(assignment_id)
    if row is None:
        fail(errors.ERR_ASSIGNMENT_NOT_FOUND,
             "Crew assignment '%s' was not found." % assignment_id)
    return row


def get_play_grade(grade_id):
    row = db.play_grades.get(grade_id)
    if row is None:
        fail(errors.ERR_PLAY_GRADE_NOT_FOUND,
             "Play grade '%s' was not found." % grade_id)
    return row


def get_appeal(appeal_id):
    row = db.appeals.get(appeal_id)
    if row is None:
        fail(errors.ERR_APPEAL_NOT_FOUND, "Grade appeal '%s' was not found." % appeal_id)
    return row


def get_station(station_id):
    row = db.replay_stations.get(station_id)
    if row is None:
        fail(errors.ERR_REPLAY_STATION_NOT_FOUND,
             "Replay station '%s' was not found." % station_id)
    return row


def get_review(review_id):
    row = db.replay_reviews.get(review_id)
    if row is None:
        fail(errors.ERR_REPLAY_REVIEW_NOT_FOUND,
             "Replay review '%s' was not found." % review_id)
    return row


def get_pool_report(report_id):
    row = db.pool_reports.get(report_id)
    if row is None:
        fail(errors.ERR_POOL_REPORT_NOT_FOUND,
             "Pool report '%s' was not found." % report_id)
    return row


def get_discipline_action(action_id):
    row = db.discipline_actions.get(action_id)
    if row is None:
        fail(errors.ERR_DISCIPLINE_ACTION_NOT_FOUND,
             "Discipline action '%s' was not found." % action_id)
    return row


def get_season_record(record_id):
    row = db.season_records.get(record_id)
    if row is None:
        # Season records are only ever read; they share the official's 404 space
        # is not declared, so the closest declared identifier error is used.
        fail(errors.ERR_OFFICIAL_NOT_FOUND,
             "Season record '%s' was not found." % record_id)
    return row


# --- program resolution and the write gate (step 7 of PRD 2.9) ------------


def program_of_official(official):
    return db.season_programs.get(official["season_program_id"])


def program_of_game(game):
    return db.season_programs.get(game["season_program_id"])


def program_of_application(application):
    official = db.officials.get(application["official_id"])
    return program_of_official(official) if official else None


def program_of_grade(grade):
    game = db.games.get(grade["game_id"])
    return program_of_game(game) if game else None


def require_program_open(program):
    """PRD 2.5: "A business write attempted while the owning program is still
    CONFIGURING, or after it has reached POSTSEASON_LOCKED, is rejected with
    ERR_SEASON_NOT_OPEN (HTTP 409).\""""
    if program is None or program["status"] != "OPEN":
        fail(errors.ERR_SEASON_NOT_OPEN,
             "The owning season program is not OPEN.")
    return program


# --- crew posture and crew strength (PRD 3.4) ----------------------------


def assignments_of_game(game_id):
    return rows_of(db.assignments, game_id=game_id)


def assignments_of_official(official_id):
    return rows_of(db.assignments, official_id=official_id)


def derive_crew_posture(game):
    """"While the game's `status` is `SCHEDULED`, posture is `STAFFED` when
    `confirmed_crew_count` is greater than or equal to the program's
    `crew_size_required` and `UNDERSTAFFED` otherwise ... Once the game's
    `status` is anything other than `SCHEDULED`, posture is frozen at
    `LOCKED`.\""""
    if game["status"] != "SCHEDULED":
        return "LOCKED"
    program = program_of_game(game)
    required = program["crew_size_required"] if program else 0
    if game["confirmed_crew_count"] >= required:
        return "STAFFED"
    return "UNDERSTAFFED"


PROJECTED_STATUSES = ("PROPOSED", "CONFIRMED")
REALIZED_STATUSES = ("COMPLETED",)


def compute_crew_strength(game, variant):
    program = program_of_game(game)
    if program is None:
        return Decimal("0.00")
    statuses = PROJECTED_STATUSES if variant == "PROJECTED" else REALIZED_STATUSES
    contributions = []
    for assignment in assignments_of_game(game["id"]):
        if assignment["status"] not in statuses:
            continue
        official = db.officials.get(assignment["official_id"])
        if official is None:
            continue
        contributions.append(calc.assignment_contribution(
            official["seasons_experience"], official["tier"], assignment["position"]))
    return calc.crew_strength_index(contributions, program["crew_size_required"])


def refresh_game_derived(game, variant):
    """Re-derives the game's posture and its crew strength index for `variant`."""
    game["confirmed_crew_count"] = len([
        a for a in assignments_of_game(game["id"]) if a["status"] == "CONFIRMED"])
    game["crew_posture"] = derive_crew_posture(game)
    game["crew_strength_index"] = compute_crew_strength(game, variant)
    game["crew_strength_variant"] = variant


# --- training, clearance and deficiency (PRD 3.2) ------------------------


def training_records_of(official_id):
    return rows_of(db.training_records, official_id=official_id)


def derive_preseason_cleared(official):
    """"`preseason_cleared` becomes true only when the official holds both a
    passed `PHYSICAL_TEST` record and a passed `RULES_EXAM` record.\""""
    has_physical = False
    has_exam = False
    for record in training_records_of(official["id"]):
        if not record["passed"]:
            continue
        if record["record_type"] == "PHYSICAL_TEST":
            has_physical = True
        elif record["record_type"] == "RULES_EXAM":
            has_exam = True
    return has_physical and has_exam


def has_passed_rules_exam(official):
    for record in training_records_of(official["id"]):
        if record["record_type"] == "RULES_EXAM" and record["passed"]:
            return True
    return False


def training_deficiency_count(official, program):
    """"The clinic shortfall is the program's `clinic_attendance_required` minus
    the number of that official's `RULES_CLINIC` records, with any negative
    result treated as zero ... The physical shortfall is zero when the official
    has at least one `PHYSICAL_TEST` record whose `passed` is true, and one
    otherwise.\""""
    clinics = 0
    physical_passed = False
    for record in training_records_of(official["id"]):
        if record["record_type"] == "RULES_CLINIC":
            clinics += 1
        elif record["record_type"] == "PHYSICAL_TEST" and record["passed"]:
            physical_passed = True
    required = program["clinic_attendance_required"] if program else 0
    clinic_shortfall = max(0, required - clinics)
    physical_shortfall = 0 if physical_passed else 1
    return clinic_shortfall + physical_shortfall


# --- discipline posture (PRD 3.6, 3.8) ------------------------------------

DISCIPLINE_NON_TERMINAL = ("OPENED", "REMEDIATION_ASSIGNED", "REASSESSED",
                           "ESCALATED")
DISCIPLINE_SUPERSEDABLE = ("OPENED", "REMEDIATION_ASSIGNED", "REASSESSED")


def discipline_actions_of(official_id):
    return rows_of(db.discipline_actions, official_id=official_id)


def has_blocking_discipline(official_id, ignore_action_id=None):
    """"the official has no discipline action whose status is `OPENED`,
    `REMEDIATION_ASSIGNED`, `REASSESSED` or `ESCALATED`.\""""
    for action in discipline_actions_of(official_id):
        if ignore_action_id is not None and action["id"] == ignore_action_id:
            continue
        if action["status"] in DISCIPLINE_NON_TERMINAL:
            return True
    return False


# --- season record and the accuracy variants (PRD 3.6) --------------------


def season_record_of(official_id):
    records = rows_of(db.season_records, official_id=official_id)
    return records[0] if records else None


def appeals_of_grade(grade_id):
    return rows_of(db.appeals, play_grade_id=grade_id)


def grade_was_overturned(grade_id):
    for appeal in appeals_of_grade(grade_id):
        if appeal["status"] == "OVERTURNED":
            return True
    return False


def included_grades(official_id, variant):
    """PROVISIONAL: "includes every grade whose `grade_status` is `POSTED` or
    `FINAL`, using each grade's current `grade_code`". FINAL: "includes grades
    whose `grade_status` is `FINAL` and nothing else ... a grade whose appeal
    ended in `OVERTURNED` is excluded from both numerator and denominator."""
    out = []
    for grade in rows_of(db.play_grades, official_id=official_id):
        if variant == "FINAL":
            if grade["grade_status"] != "FINAL":
                continue
            if grade_was_overturned(grade["id"]):
                continue
        else:
            if grade["grade_status"] not in ("POSTED", "FINAL"):
                continue
        out.append(grade)
    return out


def derive_postseason_eligible(record, official):
    """"It is true when the official is `accuracy_eligible`, and the official's
    `status` is `ACTIVE`, and the official's `preseason_cleared` is true, and the
    official has no discipline action whose status is `OPENED`,
    `REMEDIATION_ASSIGNED`, `REASSESSED` or `ESCALATED`.\""""
    return bool(record["accuracy_eligible"]
                and official["status"] == "ACTIVE"
                and official["preseason_cleared"]
                and not has_blocking_discipline(official["id"]))


def recompute_season_record(official, variant, bump=True):
    """Refreshes `graded_play_count`, `weighted_error_points`, `accuracy_index`,
    `accuracy_variant`, `accuracy_eligible` and `postseason_eligible`."""
    record = season_record_of(official["id"])
    if record is None:
        return None
    program = program_of_official(official)
    grades = included_grades(official["id"], variant)
    record["graded_play_count"] = len(grades)
    record["weighted_error_points"] = calc.weighted_error_points(grades)
    record["accuracy_index"] = calc.accuracy_index(
        record["weighted_error_points"], record["graded_play_count"])
    record["accuracy_variant"] = variant
    if program is not None:
        record["accuracy_eligible"] = bool(
            record["accuracy_index"] >= program["accuracy_eligibility_threshold"]
            and record["graded_play_count"] >= program["min_graded_plays_for_eligibility"])
    else:
        record["accuracy_eligible"] = False
    record["postseason_eligible"] = derive_postseason_eligible(record, official)
    if bump:
        touch(record)
    return record


def refresh_postseason_eligible(official, bump=True):
    """Used by the discipline surface, which moves only the non-accuracy
    conjuncts of the eligibility derivation."""
    record = season_record_of(official["id"])
    if record is None:
        return None
    before = record["postseason_eligible"]
    record["postseason_eligible"] = derive_postseason_eligible(record, official)
    if bump and record["postseason_eligible"] != before:
        touch(record)
    return record


# --- availability and retention (PRD 3.9) ---------------------------------

OBLIGATION_STATUSES = ("COMPLETED", "VOIDED", "WITHDRAWN")


def availability_for(official_id):
    completed = 0
    obligated = 0
    for assignment in assignments_of_official(official_id):
        if assignment["status"] == "COMPLETED":
            completed += 1
        if assignment["status"] in OBLIGATION_STATUSES:
            obligated += 1
    return calc.availability_component(completed, obligated)


# --- the shared void cascade (PRD 3.8, 3.9) -------------------------------

VOIDABLE_STATUSES = ("PROPOSED", "CONFIRMED")
OPEN_GAME_STATUSES = ("SCHEDULED", "IN_PROGRESS")


def void_assignments(official, game_statuses=OPEN_GAME_STATUSES):
    """"Every assignment of the suspended official whose status is `PROPOSED` or
    `CONFIRMED`, and whose game is still `SCHEDULED` or `IN_PROGRESS`, is
    transitioned to `VOIDED` in `created_at` ascending order with `released_at`
    stamped from the logical clock. Each void decrements that official's
    `open_assignment_count` by 1. Each void of a previously `CONFIRMED`
    assignment additionally decrements its game's `confirmed_crew_count` by 1 and
    recomputes that game's `crew_strength_index` with the `PROJECTED` variant --
    and `crew_posture` is re-derived only while the game is still `SCHEDULED`."""
    voided = 0
    for assignment in assignments_of_official(official["id"]):
        if assignment["status"] not in VOIDABLE_STATUSES:
            continue
        game = db.games.get(assignment["game_id"])
        if game is None:
            continue
        if game_statuses is not None and game["status"] not in game_statuses:
            continue
        was_confirmed = assignment["status"] == "CONFIRMED"
        assignment["status"] = "VOIDED"
        assignment["released_at"] = now()
        touch(assignment)
        official["open_assignment_count"] = max(
            0, official["open_assignment_count"] - 1)
        voided += 1
        if was_confirmed and game["status"] in OPEN_GAME_STATUSES:
            refresh_game_derived(game, "PROJECTED")
            touch(game)
    return voided
