"""The athlete's two independent dimensions and the urgent-finding cascade."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import CD, HSL, MR, PM


def test_01_urgent_finding_holds_the_medical_dimension_only():
    """medical_status CLEARED → HOLD leaves registration_status ACTIVE.

    PRD §3.8: an URGENT finding means "The athlete's medical dimension drops to
    `HOLD` — from `CLEARED → HOLD` or from `RESTRICTED → HOLD`".

    Design: Difficulty/non_linear_state_machine/athlete_parallel_registration_and_medical_dimensions
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete, _form = fx.create_active_athlete(program["id"])
    assert athlete["registration_status"] == "ACTIVE"
    assert athlete["medical_status"] == "CLEARED"

    fx.record_screening_finding(
        athlete["id"], discipline="HEALTHY_HEARING", screened_on="2026-08-01",
        finding_severity="URGENT",
        finding_note="Bilateral conductive loss, immediate referral")

    after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert after["medical_status"] == "HOLD"
    assert after["registration_status"] == "ACTIVE"


def test_02_registration_expiry_is_the_earlier_of_shelf_life_and_one_year():
    """The form outlives the registration it created.

    PRD §3.2: "the athlete's `registration_expires_on` is set to **whichever
    comes first** of two dates: the approved form's own expiry, that is the exam
    date plus 1095 days, and one year — 365 days — after the clock date on which
    the approval was recorded."

    Design: Difficulty/non_linear_state_machine/athlete_parallel_registration_and_medical_dimensions
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete, form = fx.create_active_athlete(
        program["id"], form_overrides={"exam_date": "2026-06-15"})
    assert form["status"] == "APPROVED"
    assert form["expires_on"] == "2029-06-14"
    assert athlete["registration_expires_on"] == "2027-08-01"


def test_03_sweep_lapses_registration_while_the_medical_hold_persists():
    """Neither dimension's transition is a precondition of the other.

    PRD §3.9 step three: "every athlete in `ACTIVE` whose
    `registration_expires_on` falls before the clock date … moves `ACTIVE →
    LAPSED`"; PRD §3.8: escalation "changes nothing about the athlete's hold".

    Design: Difficulty/non_linear_state_machine/athlete_parallel_registration_and_medical_dimensions
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete, form = fx.create_active_athlete(program["id"])
    screening = fx.record_screening_finding(
        athlete["id"], discipline="HEALTHY_HEARING", screened_on="2026-08-01",
        finding_severity="URGENT",
        finding_note="Bilateral conductive loss, immediate referral")

    fx.set_clock("2027-08-02T00:00:00Z")
    fx.run_sweep(program["id"])

    after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert after["registration_expires_on"] == "2027-08-01"
    assert after["registration_status"] == "LAPSED"
    assert after["medical_status"] == "HOLD"

    forms = api_client.list_athlete_medical_forms(athlete["id"], PM).json()["data"]
    stored_form = next(row for row in forms if row["id"] == form["id"])
    assert stored_form["status"] == "APPROVED"
    assert stored_form["expires_on"] == "2029-06-14"

    screenings = api_client.list_athlete_health_screenings(
        athlete["id"], PM).json()["data"]
    stored_screening = next(row for row in screenings
                            if row["id"] == screening["id"])
    assert stored_screening["referral_status"] == "ESCALATED"
    assert stored_screening["referral_due_on"] == "2026-08-15"

    program_after = fx.get_program(program["id"])
    assert program_after["unresolved_urgent_referral_count"] == 1
    assert program_after["compliance_posture"] == "FROZEN"
    assert program_after["sweep_epoch"] == 1
    assert_instant_equals(program_after["last_sweep_at"],
                          "2027-08-02T00:00:00.000Z", "last_sweep_at")


def _lapsed_registration_world():
    """Athlete whose registration lapses while everything else stays healthy."""
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete, _form = fx.create_active_athlete(program["id"])
    fx.set_clock("2027-06-01T00:00:00Z")
    _volunteer, credential = fx.create_certified_credential(
        program["id"],
        screening_overrides={"completed_on": "2027-06-01"},
        training_overrides={"completed_on": "2027-06-01",
                            "curriculum_code": "PB-CORE-2027"})
    season = fx.create_practice_open_season(
        program["id"], season_name="Summer 2027 Athletics",
        registration_deadline="2027-08-20", divisioning_date="2027-08-25",
        competition_date="2027-09-10")
    session = fx.schedule_session(season["id"], credential["id"],
                                  scheduled_start="2027-08-10T10:00:00Z")
    fx.set_clock("2027-08-10T10:00:00Z")
    fx.run_sweep(program["id"])
    return {"program": program, "athlete": athlete, "credential": credential,
            "season": season, "session": session,
            "session_version": session["version"]}


def test_04_attendance_refused_while_the_registration_dimension_is_lapsed():
    """The athlete's registration dimension alone blocks the attendance record.

    PRD §3.4: "The athlete must belong to the same program and be in
    `registration_status` `ACTIVE`, else 422 `ERR_ATHLETE_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/attendance_requires_active_athlete_registration
    """
    world = _lapsed_registration_world()
    payload = f.create_attendance_payload(world["athlete"]["id"],
                                          world["session_version"],
                                          minutes_present=60)
    validate_error(
        api_client.create_attendance_record(world["session"]["id"], payload, PM),
        ApiErrorId.ERR_ATHLETE_NOT_ACTIVE.value, 422)

    athlete = validate_success(api_client.get_athlete(world["athlete"]["id"], PM))
    assert athlete["registration_status"] == "LAPSED"
    assert athlete["medical_status"] == "CLEARED"
    credential = validate_success(
        api_client.get_credential(world["credential"]["id"], PM))
    assert credential["status"] == "CERTIFIED"
    assert fx.get_program(world["program"]["id"])["compliance_posture"] == "OPEN"
    assert fx.session_version(world["session"]["id"]) == world["session_version"]


def test_05_reapproving_a_newer_form_lets_the_identical_call_through():
    """Restoring the registration dimension is the only change needed.

    PRD §3.2: "When an athlete has fallen to `LAPSED` and a newer form is
    approved, registration moves `LAPSED → ACTIVE`, `registration_expires_on` is
    recomputed from the new form by the identical whichever-comes-first rule".

    Design: Difficulty/cross_entity_state_dependency/attendance_requires_active_athlete_registration
    """
    world = _lapsed_registration_world()
    payload = f.create_attendance_payload(world["athlete"]["id"],
                                          world["session_version"],
                                          minutes_present=60)
    validate_error(
        api_client.create_attendance_record(world["session"]["id"], payload, PM),
        ApiErrorId.ERR_ATHLETE_NOT_ACTIVE.value, 422)

    newer = fx.file_medical_form(world["athlete"]["id"], exam_date="2027-07-01")
    fx.approve_medical_form(newer["id"], reviewer=MR)
    athlete = validate_success(api_client.get_athlete(world["athlete"]["id"], PM))
    assert athlete["registration_status"] == "ACTIVE"
    assert athlete["registration_expires_on"] == "2028-08-09"

    record = validate_success(
        api_client.create_attendance_record(world["session"]["id"], payload, PM),
        201)
    assert record["athlete_id"] == world["athlete"]["id"]
    assert record["minutes_present"] == 60


def _divisioned_cascade_world():
    """One VALID division of three entries, ready for an urgent finding."""
    athlete_specs = [
        {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
        {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01"}},
        {"athlete": {"legal_name": "Grace Lin", "birth_date": "1998-05-20"}},
    ]
    entry_specs = [
        {"athlete_index": 0, "skill_score": 40.0},
        {"athlete_index": 1, "skill_score": 39.0},
        {"athlete_index": 2, "skill_score": 38.0},
    ]
    return fx.setup_divisioned_season(
        athlete_specs, entry_specs,
        divisioning_clock="2026-09-02T00:00:00Z")


def test_06_urgent_finding_voids_only_the_screened_athletes_entry():
    """Hop one and hop two of the cascade, with the peers left untouched.

    PRD §3.8: "Every competition entry whose participant is this athlete and
    whose status is `SUBMITTED`, `DIVISIONED` or `LOCKED` becomes `VOIDED` with
    `void_reason_code` set to `ATHLETE_MEDICAL_HOLD`."

    Design: Difficulty/transitive_cascade/urgent_referral_hold_cascade
    """
    world = _divisioned_cascade_world()
    entries = world["entries"]
    assert [entry["status"] for entry in entries] == ["DIVISIONED"] * 3

    screening = fx.record_screening_finding(
        world["athletes"][0]["id"], discipline="FUNFITNESS",
        screened_on="2026-09-02", finding_severity="URGENT",
        finding_note="Uncontrolled hypertension, immediate referral")

    rows = api_client.list_athlete_health_screenings(
        world["athletes"][0]["id"], PM).json()["data"]
    stored = next(row for row in rows if row["id"] == screening["id"])
    assert stored["referral_status"] == "REFERRED"
    assert stored["referral_due_on"] == "2026-09-16"

    athlete = validate_success(
        api_client.get_athlete(world["athletes"][0]["id"], PM))
    assert athlete["medical_status"] == "HOLD"
    assert athlete["registration_status"] == "ACTIVE"

    voided = validate_success(api_client.get_competition_entry(entries[0]["id"], CD))
    assert voided["status"] == "VOIDED"
    assert voided["void_reason_code"] == "ATHLETE_MEDICAL_HOLD"
    for entry in entries[1:]:
        peer = validate_success(api_client.get_competition_entry(entry["id"], CD))
        assert peer["status"] == "DIVISIONED"


def test_07_the_void_shrinks_the_division_and_restricts_the_program():
    """Hops three and four: the division re-derives and the posture follows.

    PRD §3.8: "Every division that lost an entry recomputes its `entry_count` …
    dropping `VALID → UNDERSIZED` if it fell below three live entries. And the
    program's `unresolved_urgent_referral_count` increments by one, after which
    the posture is recomputed".

    Design: Difficulty/transitive_cascade/urgent_referral_hold_cascade
    """
    world = _divisioned_cascade_world()
    division_id = world["entries"][1]["division_id"]
    before = validate_success(api_client.get_division(division_id, CD))
    assert before["status"] == "VALID"
    assert before["entry_count"] == 3

    fx.record_screening_finding(
        world["athletes"][0]["id"], discipline="FUNFITNESS",
        screened_on="2026-09-02", finding_severity="URGENT",
        finding_note="Uncontrolled hypertension, immediate referral")

    after = validate_success(api_client.get_division(division_id, CD))
    assert after["entry_count"] == 2
    assert after["status"] == "UNDERSIZED"

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["divisioned_entry_count"] == 2

    program = fx.get_program(world["program"]["id"])
    assert program["unresolved_urgent_referral_count"] == 1
    assert program["compliance_posture"] == "RESTRICTED"
