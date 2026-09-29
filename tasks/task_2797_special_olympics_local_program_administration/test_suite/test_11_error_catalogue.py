"""The error catalogue: collection-specific 404s and the guard errors of §3."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    CD,
    HSL,
    MR,
    OFFICER_1,
    OFFICER_2,
    OFFICER_3,
    OFFICER_4,
    PM,
)


def test_01_every_collection_answers_an_unknown_id_with_its_own_code():
    """Ten endpoints, ten distinct 404 codes, and nothing written anywhere.

    PRD §2.6: "The unresolved identifier decides the code:
    `ERR_PROGRAM_NOT_FOUND`, `ERR_ATHLETE_NOT_FOUND`,
    `ERR_MEDICAL_FORM_NOT_FOUND`, `ERR_VOLUNTEER_NOT_FOUND`,
    `ERR_CREDENTIAL_NOT_FOUND`, `ERR_SEASON_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`,
    `ERR_DIVISION_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`,
    `ERR_SCREENING_NOT_FOUND` or `ERR_CONTRIBUTION_NOT_FOUND`, each HTTP 404."

    Design: Corner/errors/not_found_ids_across_every_addressable_collection
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()

    probes = [
        (api_client.get_volunteer("11111111-1111-4111-8111-111111111111", PM),
         ApiErrorId.ERR_VOLUNTEER_NOT_FOUND),
        (api_client.get_credential("22222222-2222-4222-8222-222222222222",
                                   OFFICER_1),
         ApiErrorId.ERR_CREDENTIAL_NOT_FOUND),
        (api_client.get_season("33333333-3333-4333-8333-333333333333", CD),
         ApiErrorId.ERR_SEASON_NOT_FOUND),
        (api_client.get_practice_session(
            "44444444-4444-4444-8444-444444444444", PM),
         ApiErrorId.ERR_SESSION_NOT_FOUND),
        (api_client.get_division("55555555-5555-4555-8555-555555555555", CD),
         ApiErrorId.ERR_DIVISION_NOT_FOUND),
        (api_client.get_competition_entry(
            "66666666-6666-4666-8666-666666666666", CD),
         ApiErrorId.ERR_ENTRY_NOT_FOUND),
        (api_client.get_unified_team("77777777-7777-4777-8777-777777777777", CD),
         ApiErrorId.ERR_TEAM_NOT_FOUND),
        (api_client.review_medical_form(
            "88888888-8888-4888-8888-888888888888",
            f.review_medical_form_payload(), MR),
         ApiErrorId.ERR_MEDICAL_FORM_NOT_FOUND),
        (api_client.void_contribution(
            "99999999-9999-4999-8999-999999999999",
            f.void_contribution_payload(), PM),
         ApiErrorId.ERR_CONTRIBUTION_NOT_FOUND),
        (api_client.log_referral_followup(
            "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            f.referral_followup_payload(
                "LOGGED", note="Probe against a non-existent screening."), HSL),
         ApiErrorId.ERR_SCREENING_NOT_FOUND),
    ]
    for response, expected in probes:
        error = validate_error(response, expected.value, 404)
        assert response.json()["response_type"] == "error"
        assert isinstance(error["message"], str) and error["message"], (
            f"{expected.value} must carry a message string")

    after = fx.get_program(program["id"])
    assert after["version"] == 1
    assert after["credential_denominator_count"] == 0
    assert after["active_athlete_count"] == 0
    assert after["program_practice_minutes"] == 0
    assert after["sweep_epoch"] == 0


def test_02_a_season_whose_milestones_run_backwards_is_refused():
    """The milestone chain must be strictly increasing, and nothing is created.

    PRD §3.5: the three milestones "must be **strictly increasing** in that
    order; a season whose dates are equal or out of order is refused with
    `ERR_SEASON_DATE_ORDER` (HTTP 400)."

    Design: Corner/errors/season_date_order_rejected_at_creation
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    payload = f.create_season_payload(
        season_name="Backwards Season", registration_deadline="2026-09-01",
        divisioning_date="2026-09-05", competition_date="2026-08-20")
    validate_error(api_client.create_season(program["id"], payload, CD),
                   ApiErrorId.ERR_SEASON_DATE_ORDER.value, 400)

    listing = api_client.list_program_seasons(program["id"], CD,
                                             params={"limit": 100})
    assert listing.json()["meta"]["total_count"] == 0


def test_03_the_four_credentialing_guards_answer_with_four_codes():
    """Four differently prepared credentials, four distinct refusals.

    PRD §3.3: "A branch already recorded in the current cycle may not be
    recorded a second time … refused with `ERR_CREDENTIAL_STEP_ALREADY_RECORDED`
    (HTTP 409)"; a `FLAGGED` credential may be certified "only with a present,
    non-empty `flag_override_reason` … omitting it is refused with
    `ERR_FLAG_OVERRIDE_REQUIRED` (422)"; "a volunteer whose age at file-opening
    time is under 18 may never be credentialed on the `COACH` track, and the
    attempt is refused with `ERR_MINOR_CANNOT_BE_COACH` (422)"; and the
    `role_class` "must equal the volunteer's declared `volunteer_class` … a
    mismatch is refused with `ERR_ROLE_CLASS_MISMATCH` (HTTP 422)."

    Design: Corner/errors/credentialing_guard_errors
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()

    volunteer_a = fx.add_volunteer(program["id"])
    credential_a = fx.open_credential(volunteer_a["id"], officer=OFFICER_1)
    fx.record_screening(credential_a["id"], officer=OFFICER_1,
                        completed_on="2026-07-01", result="CLEAR",
                        vendor_reference="BGS-1001")
    validate_error(api_client.record_credential_screening(
        credential_a["id"],
        f.record_screening_payload(completed_on="2026-07-20", result="CLEAR",
                                  vendor_reference="BGS-1002"), OFFICER_4),
        ApiErrorId.ERR_CREDENTIAL_STEP_ALREADY_RECORDED.value, 409)
    stored_a = validate_success(api_client.get_credential(credential_a["id"], PM))
    assert stored_a["screening_completed_on"] == "2026-07-01"
    assert stored_a["screening_vendor_reference"] == "BGS-1001"

    _volunteer_b, credential_b = fx.create_credential_ready_to_certify(
        program["id"],
        volunteer_overrides={"full_name": "Priya Shah",
                             "email": "priya@rb.example",
                             "date_of_birth": "1991-02-03"},
        screening_overrides={"completed_on": "2026-07-01", "result": "FLAGGED",
                             "vendor_reference": "BGS-1003"},
        training_overrides={"completed_on": "2026-07-05",
                            "curriculum_code": "PB-CORE-2026"})
    assert credential_b["status"] == "READY_TO_CERTIFY"
    validate_error(api_client.certify_credential(
        credential_b["id"], f.certify_credential_payload(), OFFICER_3),
        ApiErrorId.ERR_FLAG_OVERRIDE_REQUIRED.value, 422)
    stored_b = validate_success(api_client.get_credential(credential_b["id"], PM))
    assert stored_b["status"] == "READY_TO_CERTIFY"
    assert stored_b["expires_on"] is None

    volunteer_c = fx.add_volunteer(program["id"], full_name="Kai Nolan",
                                  email="kai@rb.example",
                                  date_of_birth="2010-06-01",
                                  volunteer_class="COACH")
    validate_error(api_client.create_credential(
        volunteer_c["id"], f.create_credential_payload(role_class="COACH"),
        OFFICER_1),
        ApiErrorId.ERR_MINOR_CANNOT_BE_COACH.value, 422)
    listing_c = api_client.list_volunteer_credentials(volunteer_c["id"], PM,
                                                     params={"limit": 100})
    assert listing_c.json()["meta"]["total_count"] == 0

    volunteer_d = fx.add_volunteer(program["id"], full_name="Tom Slater",
                                  email="tom@rb.example",
                                  date_of_birth="1992-04-04",
                                  volunteer_class="COACH")
    validate_error(api_client.create_credential(
        volunteer_d["id"],
        f.create_credential_payload(role_class="GENERAL_VOLUNTEER"), OFFICER_1),
        ApiErrorId.ERR_ROLE_CLASS_MISMATCH.value, 422)
    listing_d = api_client.list_volunteer_credentials(volunteer_d["id"], PM,
                                                     params={"limit": 100})
    assert listing_d.json()["meta"]["total_count"] == 0

    assert fx.get_program(program["id"])["credential_denominator_count"] == 2


def test_04_the_three_medical_submission_guards_separate_cleanly():
    """Future exam, stale exam and incomplete attestation each get their own code.

    PRD §3.2: "An `exam_date` after the logical clock date is refused with
    `ERR_EXAM_DATE_IN_FUTURE` (422). And an exam already past its shelf life at
    the moment of submission — meaning the exam date plus three years, 1095 days,
    falls before the clock date — is refused with `ERR_MEDICAL_EXAM_STALE`
    (422)"; "A form lacking affirmative cardiac clearance … is refused with
    `ERR_MEDICAL_ATTESTATION_INCOMPLETE` (HTTP 422)."

    Design: Corner/errors/medical_form_submission_guard_errors
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete = fx.register_athlete(program["id"])

    validate_error(api_client.create_medical_form(
        athlete["id"], f.create_medical_form_payload(exam_date="2026-09-01"), PM),
        ApiErrorId.ERR_EXAM_DATE_IN_FUTURE.value, 422)
    validate_error(api_client.create_medical_form(
        athlete["id"], f.create_medical_form_payload(exam_date="2023-08-01"), PM),
        ApiErrorId.ERR_MEDICAL_EXAM_STALE.value, 422)
    validate_error(api_client.create_medical_form(
        athlete["id"],
        f.create_medical_form_payload(exam_date="2026-06-15",
                                      attestation_cardiac_clearance=False), MR),
        ApiErrorId.ERR_MEDICAL_ATTESTATION_INCOMPLETE.value, 422)

    forms = api_client.list_athlete_medical_forms(athlete["id"], PM,
                                                 params={"limit": 100})
    assert forms.json()["meta"]["total_count"] == 0
    stored = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert stored["registration_status"] == "PENDING_MEDICAL"
    assert stored["medical_status"] == "NONE"
    assert stored["current_medical_form_id"] is None
    assert stored["version"] == 1


def test_05_a_fourth_revision_of_the_same_form_is_refused():
    """Three REJECTED → SUBMITTED cycles are allowed; the fourth is not.

    PRD §3.2: resubmission "is capped: a form may be revised at most three
    times, so a resubmission attempted when `revision_count` has already reached
    3 is refused with `ERR_RESUBMIT_LIMIT_REACHED` (409). The
    `REJECTED → SUBMITTED → REJECTED` cycle may therefore run at most three
    times before the family must start a fresh form."

    Design: Corner/errors/resubmit_limit_reached_after_three_revisions
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete = fx.register_athlete(program["id"])
    form = fx.file_medical_form(athlete["id"], exam_date="2026-06-15")
    assert form["status"] == "SUBMITTED"
    assert form["revision_count"] == 0

    for revision, exam_date in enumerate(
            ("2026-06-16", "2026-06-17", "2026-06-18"), start=1):
        rejected = fx.reject_medical_form(form["id"], reason_code="STALE_EXAM")
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason_code"] == "STALE_EXAM"
        resubmitted = validate_success(api_client.resubmit_medical_form(
            form["id"], f.resubmit_medical_form_payload(exam_date=exam_date), PM))
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == revision
        assert resubmitted["rejection_reason_code"] is None
        assert resubmitted["exam_date"] == exam_date

    fourth_rejection = fx.reject_medical_form(form["id"], reason_code="STALE_EXAM")
    assert fourth_rejection["revision_count"] == 3
    validate_error(api_client.resubmit_medical_form(
        form["id"], f.resubmit_medical_form_payload(exam_date="2026-06-19"), PM),
        ApiErrorId.ERR_RESUBMIT_LIMIT_REACHED.value, 409)

    rows = api_client.list_athlete_medical_forms(
        athlete["id"], PM, params={"limit": 100}).json()
    assert rows["meta"]["total_count"] == 1
    stored = rows["data"][0]
    assert stored["status"] == "REJECTED"
    assert stored["revision_count"] == 3
    assert stored["exam_date"] == "2026-06-18"
    assert stored["expires_on"] == "2029-06-17"

    stored_athlete = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert stored_athlete["medical_status"] == "NONE"
    assert stored_athlete["registration_status"] == "PENDING_MEDICAL"
    assert stored_athlete["current_medical_form_id"] is None


def test_06_late_entry_and_a_second_result_on_the_same_entry_both_fail():
    """The temporal gate and the entry-state gate, each with its own code.

    PRD §3.5: "The clock date must fall on or before the season's
    `registration_deadline`, or the entry is refused with
    `ERR_REGISTRATION_DEADLINE_PASSED` (409)"; PRD §3.7: "The entry must be in
    `LOCKED` and not already `RESULTED`, `ADVANCED`, `DISQUALIFIED` or `VOIDED`;
    anything else is refused with `ERR_ENTRY_STATE_INVALID` (409)."

    Design: Corner/errors/entry_deadline_and_entry_state_errors
    """
    late_world = fx.setup_entry_ready_world(
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}}])
    assert late_world["season"]["registration_deadline"] == "2026-09-01"
    fx.set_clock("2026-09-02T00:00:00Z")
    validate_error(api_client.create_competition_entry(
        f.create_entry_payload(late_world["season"]["id"],
                               late_world["athletes"][0]["id"]), CD),
        ApiErrorId.ERR_REGISTRATION_DEADLINE_PASSED.value, 409)
    late_season = validate_success(
        api_client.get_season(late_world["season"]["id"], CD))
    assert late_season["entry_count"] == 0
    assert late_season["status"] == "PRACTICE_OPEN"

    locked = _locked_athletics_world()
    fx.set_clock("2026-09-20T09:00:00Z")
    entry = locked["entries"][0]
    resulted = validate_success(api_client.post_entry_result(
        entry["id"], f.post_result_payload(13.5), CD))
    assert resulted["status"] in ("RESULTED", "ADVANCED")
    assert resulted["result_value"] == 13.5

    validate_error(api_client.post_entry_result(
        entry["id"], f.post_result_payload(12.9), CD),
        ApiErrorId.ERR_ENTRY_STATE_INVALID.value, 409)
    stored = validate_success(api_client.get_competition_entry(entry["id"], CD))
    assert stored["status"] != "LOCKED"
    assert stored["result_value"] == 13.5


def _locked_athletics_world():
    """Three entries in one VALID division, season taken to ENTRIES_LOCKED."""
    athlete_specs = [
        {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
        {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01"}},
        {"athlete": {"legal_name": "Grace Lin", "birth_date": "2004-05-20"}},
    ]
    entry_specs = [
        {"athlete_index": 0, "skill_score": 14.0},
        {"athlete_index": 1, "skill_score": 13.6},
        {"athlete_index": 2, "skill_score": 13.2},
    ]
    return fx.setup_entries_locked_season(athlete_specs, entry_specs)


def test_07_a_locked_season_refuses_entries_early_results_and_a_second_lock():
    """Three different endpoints, three different codes, one locked season.

    PRD §3.5: entry creation requires the season to be "in `PRACTICE_OPEN`
    (`ERR_SEASON_NOT_PRACTICE_OPEN`, 409)"; PRD §3.7: "the clock date must have
    reached the season's `competition_date`, a result filed early being refused
    with `ERR_COMPETITION_DATE_NOT_REACHED` (409)"; PRD §3.6: locking "requires
    the season to be in `DIVISIONED` (`ERR_SEASON_STATE_INVALID`, 409)".

    Design: Corner/errors/locked_season_rejects_entries_results_and_relock
    """
    world = _locked_athletics_world()
    season_id = world["season"]["id"]
    assert world["season"]["status"] == "ENTRIES_LOCKED"
    locked_version = world["season"]["version"]

    validate_error(api_client.create_competition_entry(
        f.create_entry_payload(season_id, world["athletes"][0]["id"],
                               event_code="200M_DASH"), CD),
        ApiErrorId.ERR_SEASON_NOT_PRACTICE_OPEN.value, 409)

    validate_error(api_client.post_entry_result(
        world["entries"][0]["id"], f.post_result_payload(13.5), CD),
        ApiErrorId.ERR_COMPETITION_DATE_NOT_REACHED.value, 409)

    validate_error(api_client.lock_season_entries(season_id, {}, CD),
                   ApiErrorId.ERR_SEASON_STATE_INVALID.value, 409)

    after = validate_success(api_client.get_season(season_id, CD))
    assert after["status"] == "ENTRIES_LOCKED"
    assert after["version"] == locked_version
    assert after["entry_count"] == 3
    for entry in world["entries"]:
        stored = validate_success(
            api_client.get_competition_entry(entry["id"], CD))
        assert stored["status"] == "LOCKED"
        assert stored["result_value"] is None


def test_08_attendance_filed_before_the_session_starts_is_refused():
    """The clock has not reached scheduled_start, so no row may exist yet.

    PRD §3.4: "Attendance may not be filed before the session has begun: the
    logical clock must have reached the session's `scheduled_start`, or the
    request is refused with `ERR_ATTENDANCE_BEFORE_SESSION_START` (422)."

    Design: Corner/errors/attendance_before_session_start_rejected
    """
    world = fx.setup_session_ready_world(
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}}])
    session = world["session"]
    assert session["status"] == "SCHEDULED"

    payload = f.create_attendance_payload(world["athletes"][0]["id"],
                                          session["version"], minutes_present=60)
    validate_error(
        api_client.create_attendance_record(session["id"], payload, PM),
        ApiErrorId.ERR_ATTENDANCE_BEFORE_SESSION_START.value, 422)

    stored = validate_success(api_client.get_practice_session(session["id"], PM))
    assert stored["recorded_attendance_count"] == 0
    assert stored["version"] == session["version"]
    rows = api_client.list_session_attendance_records(session["id"], PM,
                                                      params={"limit": 100})
    assert rows.json()["meta"]["total_count"] == 0
    athlete = validate_success(
        api_client.get_athlete(world["athletes"][0]["id"], PM))
    assert athlete["cumulative_practice_minutes"] == 0
    assert athlete["counted_session_count"] == 0


def test_09_a_session_scheduled_into_the_past_is_refused():
    """On-or-after the clock is the rule, so the clock instant itself is legal.

    PRD §3.4: "The `scheduled_start` must fall on or after the logical clock; a
    session scheduled into the past is refused with `ERR_SESSION_START_IN_PAST`
    (422)."

    Design: Corner/errors/session_start_in_past_rejected
    """
    world = fx.setup_practice_ready_program()
    past = f.create_practice_session_payload(
        world["season"]["id"], world["credential"]["id"],
        scheduled_start="2026-07-31T10:00:00Z", duration_minutes=60)
    validate_error(api_client.create_practice_session(past, PM),
                   ApiErrorId.ERR_SESSION_START_IN_PAST.value, 422)
    listing = api_client.list_practice_sessions(
        PM, params={"season_id": world["season"]["id"], "limit": 100})
    assert listing.json()["meta"]["total_count"] == 0

    at_the_clock = f.create_practice_session_payload(
        world["season"]["id"], world["credential"]["id"],
        scheduled_start="2026-08-01T00:00:00Z", duration_minutes=60)
    created = validate_success(api_client.create_practice_session(at_the_clock, PM),
                              201)
    assert created["status"] == "SCHEDULED"
    assert created["recorded_attendance_count"] == 0


def test_10_duplicate_and_over_capacity_attendance_get_different_codes():
    """One filled slot, one 409 for the repeat and one 409 for the newcomer.

    PRD §3.4: "A second row for the same athlete on the same session is refused
    with `ERR_DUPLICATE_ATTENDANCE` (409). And when the session's
    `recorded_attendance_count` has already reached its `capacity_slots`, the
    request is refused with `ERR_SESSION_CAPACITY_EXCEEDED` (409)."

    Design: Corner/errors/duplicate_attendance_and_capacity_errors
    """
    world = fx.setup_session_ready_world(
        session_overrides={"capacity_slots": 1},
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
            {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01"}},
        ],
        attendance_clock="2026-09-10T10:00:00Z")
    session = world["session"]
    first = fx.record_attendance(session["id"], world["athletes"][0]["id"],
                                session["version"], minutes_present=60)
    assert first["status"] == "COUNTED"
    filled_version = fx.session_version(session["id"])

    validate_error(api_client.create_attendance_record(
        session["id"],
        f.create_attendance_payload(world["athletes"][0]["id"], filled_version,
                                    minutes_present=50), PM),
        ApiErrorId.ERR_DUPLICATE_ATTENDANCE.value, 409)
    validate_error(api_client.create_attendance_record(
        session["id"],
        f.create_attendance_payload(world["athletes"][1]["id"], filled_version,
                                    minutes_present=60), PM),
        ApiErrorId.ERR_SESSION_CAPACITY_EXCEEDED.value, 409)

    stored = validate_success(api_client.get_practice_session(session["id"], PM))
    assert stored["recorded_attendance_count"] == 1
    assert stored["capacity_slots"] == 1
    assert stored["version"] == filled_version
    rows = api_client.list_session_attendance_records(session["id"], PM,
                                                      params={"limit": 100}).json()
    assert rows["meta"]["total_count"] == 1
    assert rows["data"][0]["athlete_id"] == world["athletes"][0]["id"]
    second_athlete = validate_success(
        api_client.get_athlete(world["athletes"][1]["id"], PM))
    assert second_athlete["cumulative_practice_minutes"] == 0


def test_11_duplicate_member_and_a_noncompliant_roster_entry_are_refused():
    """A two-member roster is NON_COMPLIANT, and nobody may be listed twice.

    PRD §3.5: "Nobody may be listed twice, so re-adding an athlete or a
    volunteer already on the roster is refused with `ERR_DUPLICATE_TEAM_MEMBER`
    (409)"; a roster is `COMPLIANT` only "when the two counts are equal, **at
    least two athletes** are on the roster …", and a `UNIFIED_TEAM`
    participant's "`roster_status` must be exactly `COMPLIANT`, or the entry is
    refused with `ERR_ROSTER_NOT_COMPLIANT` (422)."

    Design: Corner/errors/unified_roster_duplicate_and_noncompliant_entry
    """
    world = fx.setup_compliant_unified_team(
        athlete_specs=[
            {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}}],
        partner_specs=[{"full_name": "Noah Byrd", "email": "noah@rb.example",
                        "date_of_birth": "1999-04-12"}])
    team = world["team"]
    assert team["athlete_count"] == 1
    assert team["partner_count"] == 1
    assert team["age_span_years"] == 5
    assert team["roster_status"] == "NON_COMPLIANT"
    version = team["version"]

    validate_error(api_client.add_unified_team_member(
        team["id"],
        f.add_team_member_payload("ATHLETE", world["athletes"][0]["id"], version),
        CD),
        ApiErrorId.ERR_DUPLICATE_TEAM_MEMBER.value, 409)
    validate_error(api_client.add_unified_team_member(
        team["id"],
        f.add_team_member_payload("PARTNER", world["partners"][0]["id"], version),
        CD),
        ApiErrorId.ERR_DUPLICATE_TEAM_MEMBER.value, 409)

    validate_error(api_client.create_competition_entry(
        f.create_entry_payload(world["season"]["id"], team["id"],
                               participant_type="UNIFIED_TEAM",
                               event_code="4X100_RELAY"), CD),
        ApiErrorId.ERR_ROSTER_NOT_COMPLIANT.value, 422)

    stored = validate_success(api_client.get_unified_team(team["id"], CD))
    assert stored["version"] == version
    assert stored["athlete_ids"] == [world["athletes"][0]["id"]]
    assert stored["partner_volunteer_ids"] == [world["partners"][0]["id"]]
    assert stored["roster_status"] == "NON_COMPLIANT"
    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 0


def test_12_a_no_contact_restriction_bars_a_basketball_entry():
    """The restriction is read off the approved form and matched to the sport.

    PRD §3.5: "The athlete's approved medical restrictions must be compatible
    with the season's sport: a `restrictions` array containing `NO_SWIMMING`
    bars entry into a `SWIMMING` season, and one containing `NO_CONTACT` bars
    entry into a `BASKETBALL` season, both refused with
    `ERR_MEDICAL_RESTRICTION_INCOMPATIBLE` (422)."

    Design: Corner/errors/medical_restriction_incompatible_with_contact_sport
    """
    world = fx.setup_entry_ready_world(
        athlete_specs=[{"athlete": {"legal_name": "Maya Foster",
                                    "birth_date": "2004-03-09",
                                    "sport": "BASKETBALL"},
                        "form": {"restrictions": ["NO_CONTACT"]}}],
        season_overrides={"sport": "BASKETBALL",
                          "season_name": "Fall 2026 Basketball"})
    athlete = validate_success(
        api_client.get_athlete(world["athletes"][0]["id"], PM))
    assert athlete["registration_status"] == "ACTIVE"
    assert athlete["medical_status"] == "RESTRICTED"
    assert world["forms"][0]["restrictions"] == ["NO_CONTACT"]

    validate_error(api_client.create_competition_entry(
        f.create_entry_payload(world["season"]["id"], athlete["id"],
                               event_code="3ON3_BASKETBALL"), CD),
        ApiErrorId.ERR_MEDICAL_RESTRICTION_INCOMPATIBLE.value, 422)

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 0
    assert season["status"] == "PRACTICE_OPEN"
    entries = api_client.list_competition_entries(
        CD, params={"season_id": world["season"]["id"], "limit": 100})
    assert entries.json()["meta"]["total_count"] == 0


def test_13_follow_up_on_a_routine_screening_is_refused():
    """NOT_REQUIRED is terminal, so there is no referral to follow up.

    PRD §3.8: "A `ROUTINE` finding needs no follow-up: `referral_status` is set
    to `NOT_REQUIRED`, which is terminal, and `referral_due_on` stays null"; and
    "a follow-up attempted against a screening in `NOT_REQUIRED` or `RESOLVED`
    is refused with `ERR_SCREENING_STATE_INVALID` (409)."

    Design: Corner/errors/referral_followup_on_routine_screening_rejected
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete, _form = fx.create_active_athlete(program["id"])
    screening = fx.record_screening_finding(
        athlete["id"], discipline="SPECIAL_SMILES", screened_on="2026-08-01",
        finding_severity="ROUTINE",
        finding_note="Routine dental check, no action needed")
    assert screening["referral_status"] == "NOT_REQUIRED"
    assert screening["referral_due_on"] is None
    assert screening["followup_count"] == 0

    validate_error(api_client.log_referral_followup(
        screening["id"],
        f.referral_followup_payload("LOGGED",
                                    note="Attempted contact with the family."),
        HSL),
        ApiErrorId.ERR_SCREENING_STATE_INVALID.value, 409)
    validate_error(api_client.log_referral_followup(
        screening["id"],
        f.referral_followup_payload("RESOLVED", note="Closing the record."), MR),
        ApiErrorId.ERR_SCREENING_STATE_INVALID.value, 409)

    rows = api_client.list_athlete_health_screenings(
        athlete["id"], PM, params={"limit": 100}).json()
    assert rows["meta"]["total_count"] == 1
    stored = rows["data"][0]
    assert stored["referral_status"] == "NOT_REQUIRED"
    assert stored["followup_count"] == 0
    assert stored["last_followup_note"] is None
    assert stored["referral_due_on"] is None

    after = fx.get_program(program["id"])
    assert after["unresolved_urgent_referral_count"] == 0
    stored_athlete = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert stored_athlete["medical_status"] == "CLEARED"
    assert stored_athlete["registration_status"] == "ACTIVE"
