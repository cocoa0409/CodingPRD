"""Declared transitions, illegal from-states and the transitions only a sweep makes."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import CD, MR, MR2, OFFICER_1, OFFICER_2, OFFICER_3, PM


def test_01_open_practice_moves_the_season_from_planning_to_practice_open():
    """The declared trigger returns the season with only its version moved.

    PRD §3.4: "Opening the practice window moves the season `PLANNING →
    PRACTICE_OPEN`… It also requires the program to hold at least one live
    certified coach credential and a posture that is not `FROZEN`."

    Design: Corner/state_machines/season_open_practice_moves_planning_to_practice_open
    """
    world = fx.setup_program_with_certified_coach()
    season = fx.create_season(world["program"]["id"])
    assert season["status"] == "PLANNING"

    response = api_client.open_season_practice(season["id"], {}, CD)
    assert response.status_code == 200
    opened = validate_success(response)
    assert opened["status"] == "PRACTICE_OPEN"
    assert opened["divisioning_run_count"] == 0
    assert opened["entry_count"] == 0
    assert opened["divisioned_entry_count"] == 0
    assert opened["version"] == season["version"] + 1

    program = fx.get_program(world["program"]["id"])
    assert program["compliance_posture"] == "OPEN"
    assert program["certified_coach_count"] == 1
    volunteer = validate_success(
        api_client.get_volunteer(world["volunteer"]["id"], PM))
    assert volunteer["status"] == "CREDENTIALED"
    assert validate_success(api_client.get_credential(
        world["credential"]["id"], PM))["status"] == "CERTIFIED"


def test_02_certifying_before_the_fork_joins_is_refused():
    """SCREENING_CLEARED is not a certifiable state.

    PRD §3.3: "The credential must be in `READY_TO_CERTIFY`, or in
    `RENEWAL_IN_PROGRESS` with both branches refreshed; any other state… is
    refused with `ERR_CREDENTIAL_NOT_READY_TO_CERTIFY` (HTTP 409)"; and
    "Recording screening on a credential in `INITIATED` advances it `INITIATED →
    SCREENING_CLEARED`".

    Design: Corner/state_machines/certify_before_both_branches_returns_not_ready
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    volunteer = fx.add_volunteer(program["id"])
    credential = fx.open_credential(volunteer["id"], officer=OFFICER_1)
    after_screening = fx.record_screening(credential["id"], officer=OFFICER_1)
    assert after_screening["status"] == "SCREENING_CLEARED"

    validate_error(
        api_client.certify_credential(credential["id"], {}, OFFICER_3),
        ApiErrorId.ERR_CREDENTIAL_NOT_READY_TO_CERTIFY.value, 409)

    stored = validate_success(api_client.get_credential(credential["id"], PM))
    assert stored["status"] == "SCREENING_CLEARED"
    assert stored["certified_at"] is None
    assert stored["certified_by_user_id"] is None
    assert stored["expires_on"] is None
    assert stored["screening_expires_on"] == "2029-06-30"
    assert stored["training_completed_on"] is None

    after = fx.get_program(program["id"])
    assert after["certified_coach_count"] == 0
    assert after["compliance_posture"] == "FROZEN"


def test_03_open_practice_on_a_frozen_program_is_refused():
    """A zero-coach program is FROZEN by construction and cannot open practice.

    PRD §3.4: "because a program with a zero certified-coach count is `FROZEN` by
    construction, both of those surface as `ERR_PROGRAM_POSTURE_FROZEN` (409)."

    Design: Corner/state_machines/open_practice_on_frozen_program_rejected
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    season = fx.create_season(program["id"])
    validate_error(api_client.open_season_practice(season["id"], {}, CD),
                   ApiErrorId.ERR_PROGRAM_POSTURE_FROZEN.value, 409)

    stored = validate_success(api_client.get_season(season["id"], CD))
    assert stored["status"] == "PLANNING"
    after = fx.get_program(program["id"])
    assert after["compliance_posture"] == "FROZEN"
    assert after["certified_coach_count"] == 0
    assert after["credential_denominator_count"] == 0
    assert after["expired_credential_ratio"] == 0.0


def test_04_one_approval_fires_every_declared_side_effect():
    """The form, both athlete dimensions and the program counter all move.

    PRD §3.2: "An approval moves the form `SUBMITTED → APPROVED`, stamps
    `approved_at` with the logical clock instant and `reviewed_by_user_id` with
    the reviewing user's `X-User-ID`, and then drives both athlete dimensions at
    once… The approval also sets `current_medical_form_id` to the newly approved
    form's id, increments the program's `active_athlete_count` by one, and
    recomputes the program's posture."

    Design: Corner/state_machines/medical_form_approval_side_effects_activate_athlete
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete = fx.register_athlete(program["id"])
    form = fx.file_medical_form(athlete["id"], exam_date="2026-06-15")

    response = api_client.review_medical_form(
        form["id"], f.review_medical_form_payload(decision="APPROVE"), MR)
    assert response.status_code == 200
    approved = validate_success(response)
    assert approved["status"] == "APPROVED"
    assert approved["expires_on"] == "2029-06-14"
    assert_instant_equals(approved["approved_at"], "2026-08-01T00:00:00.000Z",
                          "approved_at")
    assert approved["reviewed_by_user_id"] == "reviewer-1"
    assert approved["rejection_reason_code"] is None

    after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert after["registration_status"] == "ACTIVE"
    assert after["medical_status"] == "CLEARED"
    assert after["registration_expires_on"] == "2027-08-01"
    assert after["current_medical_form_id"] == form["id"]

    program_after = fx.get_program(program["id"])
    assert program_after["active_athlete_count"] == 1
    assert program_after["compliance_posture"] == "FROZEN"


def test_05_reviewing_an_already_approved_form_is_refused():
    """APPROVED is not a legal from-state, and no side effect runs twice.

    PRD §3.2: "The form must be in `SUBMITTED`, or the review is refused with
    `ERR_MEDICAL_FORM_STATE_INVALID` (409)."

    Design: Corner/state_machines/review_already_approved_form_returns_state_invalid
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete, form = fx.create_active_athlete(program["id"])
    forms = api_client.list_athlete_medical_forms(athlete["id"], PM).json()["data"]
    approved_version = next(row for row in forms
                            if row["id"] == form["id"])["version"]

    validate_error(
        api_client.review_medical_form(
            form["id"],
            f.review_medical_form_payload(decision="REJECT",
                                          rejection_reason_code="ILLEGIBLE"),
            MR2),
        ApiErrorId.ERR_MEDICAL_FORM_STATE_INVALID.value, 409)

    rows = api_client.list_athlete_medical_forms(athlete["id"], PM).json()["data"]
    stored = next(row for row in rows if row["id"] == form["id"])
    assert stored["status"] == "APPROVED"
    assert stored["version"] == approved_version
    assert stored["reviewed_by_user_id"] == "reviewer-1"
    assert stored["rejection_reason_code"] is None

    after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert after["registration_status"] == "ACTIVE"
    assert after["medical_status"] == "CLEARED"
    assert fx.get_program(program["id"])["active_athlete_count"] == 1


def test_06_a_new_credential_starts_in_initiated_with_both_branches_empty():
    """It counts in the denominator while certifying nobody.

    PRD §3.3: "A credential that passes both starts in `INITIATED` with both
    branches outstanding: `screening_result`, `screening_completed_on`,
    `screening_expires_on`… `certified_at`, `flag_override_reason`, `expires_on`
    and `denial_reason_code` are all null. Opening the file recomputes the
    program's `credential_denominator_count`"; and the volunteer status "reads
    `PROSPECT` before any credential has ever reached `CERTIFIED`".

    Design: Corner/state_machines/credential_starts_in_initiated
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    volunteer = fx.add_volunteer(program["id"])
    response = api_client.create_credential(
        volunteer["id"], f.create_credential_payload(role_class="COACH"),
        OFFICER_1)
    credential = validate_success(response, 201)
    assert credential["status"] == "INITIATED"
    assert credential["version"] == 1
    for field in ("screening_result", "screening_completed_on",
                  "screening_expires_on", "training_completed_on",
                  "training_expires_on", "expires_on", "certified_at",
                  "certified_by_user_id", "flag_override_reason",
                  "denial_reason_code"):
        assert credential[field] is None, f"{field} must start null"
    assert credential["volunteer_id"] == volunteer["id"]
    assert credential["role_class"] == "COACH"

    assert validate_success(
        api_client.get_volunteer(volunteer["id"], PM))["status"] == "PROSPECT"
    after = fx.get_program(program["id"])
    assert after["credential_denominator_count"] == 1
    assert after["expired_credential_count"] == 0
    assert after["expired_credential_ratio"] == 0.0
    assert after["certified_coach_count"] == 0


def test_07_a_withdrawn_athlete_cannot_be_withdrawn_again():
    """WITHDRAWN is terminal, and the first reason code stands.

    PRD §3.1: withdrawal "is accepted from any of the three non-terminal
    registration states and refused with `ERR_ATHLETE_ALREADY_WITHDRAWN` (HTTP
    409) when the athlete is already `WITHDRAWN`."

    Design: Corner/state_machines/withdrawn_athlete_cannot_be_withdrawn_again
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    athlete, _form = fx.create_active_athlete(program["id"])
    withdrawn = validate_success(api_client.withdraw_athlete(
        athlete["id"], f.withdraw_athlete_payload(
            withdrawal_reason_code="MOVED_AWAY"), PM))
    assert withdrawn["registration_status"] == "WITHDRAWN"

    validate_error(
        api_client.withdraw_athlete(
            athlete["id"],
            f.withdraw_athlete_payload(withdrawal_reason_code="AGED_OUT"), PM),
        ApiErrorId.ERR_ATHLETE_ALREADY_WITHDRAWN.value, 409)

    after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert after["registration_status"] == "WITHDRAWN"
    assert after["withdrawal_reason_code"] == "MOVED_AWAY"
    assert after["version"] == withdrawn["version"]
    assert fx.get_program(program["id"])["active_athlete_count"] == 0


def test_08_fulfilling_an_already_received_pledge_is_refused():
    """The gift is never counted twice, and the stored date is not overwritten.

    PRD §3.9: fulfilment "requires the contribution to be in `PLEDGED` — anything
    else is refused with `ERR_CONTRIBUTION_STATE_INVALID` (409) — and moves it
    `PLEDGED → RECEIVED` with the date stored."

    Design: Corner/state_machines/contribution_fulfill_twice_rejected
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    contribution = fx.log_contribution(
        program["id"], donor_name="Cedar Valley Rotary",
        contribution_type="CASH_PLEDGE", designation="GENERAL",
        stated_value_cents=250_000)
    fulfilled = validate_success(api_client.fulfill_contribution(
        contribution["id"], f.fulfill_contribution_payload(
            received_on="2026-08-01"), PM))
    assert fulfilled["status"] == "RECEIVED"

    # PRD §3.9 requires `received_on` to "fall on or before the clock date", so
    # the retry reuses the clock date and isolates the PLEDGED state rule.
    validate_error(
        api_client.fulfill_contribution(
            contribution["id"],
            f.fulfill_contribution_payload(received_on="2026-08-01"), PM),
        ApiErrorId.ERR_CONTRIBUTION_STATE_INVALID.value, 409)

    rows = api_client.list_program_contributions(
        program["id"], PM).json()["data"]
    stored = next(row for row in rows if row["id"] == contribution["id"])
    assert stored["status"] == "RECEIVED"
    assert stored["received_on"] == "2026-08-01"
    assert stored["version"] == fulfilled["version"]

    after = fx.get_program(program["id"])
    assert after["recognized_support_cents"] == 250_000
    assert after["pledged_support_cents"] == 0


def test_09_withdrawing_an_athlete_voids_her_live_entry():
    """One call on the athlete endpoint reaches down into the entry.

    PRD §3.1: withdrawing from `ACTIVE` "records the reason code, then voids every
    competition entry whose participant is this athlete and whose status is
    `SUBMITTED`, `DIVISIONED` or `LOCKED`, stamping `void_reason_code` as
    `ATHLETE_WITHDRAWN` on each… and finally the program decrements
    `active_athlete_count` by one and recomputes its posture."

    Design: Corner/state_machines/athlete_withdraw_cascades_to_live_entries
    """
    world = fx.setup_entry_ready_world(athlete_specs=[
        {"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}}])
    athlete = world["athletes"][0]
    entry = fx.submit_entry(world["season"]["id"], athlete["id"],
                            event_code="100M_DASH", skill_score=40.0)
    assert entry["status"] == "SUBMITTED"

    response = api_client.withdraw_athlete(
        athlete["id"],
        f.withdraw_athlete_payload(withdrawal_reason_code="MOVED_AWAY"), PM)
    assert response.status_code == 200
    withdrawn = validate_success(response)
    assert withdrawn["registration_status"] == "WITHDRAWN"
    assert withdrawn["withdrawal_reason_code"] == "MOVED_AWAY"
    assert withdrawn["medical_status"] == "CLEARED"

    voided = validate_success(api_client.get_competition_entry(entry["id"], CD))
    assert voided["status"] == "VOIDED"
    assert voided["void_reason_code"] == "ATHLETE_WITHDRAWN"

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["entry_count"] == 0
    assert season["status"] == "PRACTICE_OPEN"
    program = fx.get_program(world["program"]["id"])
    assert program["active_athlete_count"] == 0
    assert program["compliance_posture"] == "OPEN"


def test_10_the_sweep_voids_the_future_session_and_spares_the_held_one():
    """The cascade is conditional on the child session's own state.

    PRD §3.9 step one: "every credential in `CERTIFIED` whose `expires_on` falls
    before the clock date moves to `EXPIRED`, dragging behind it… the voiding of
    its still-future `SCHEDULED` sessions with `void_reason_code`
    `CREDENTIAL_EXPIRED`"; PRD §3.4: "if this was the very first row on the
    session, the session moves `SCHEDULED → HELD`".

    Design: Corner/state_machines/sweep_voids_future_session_but_spares_held_session
    """
    world = fx.setup_practice_ready_program()
    athlete, _form = fx.create_active_athlete(world["program"]["id"])
    session_a = fx.schedule_session(world["season"]["id"],
                                    world["credential"]["id"],
                                    scheduled_start="2026-09-10T10:00:00Z",
                                    duration_minutes=60)
    fx.set_clock("2026-09-10T10:00:00Z")
    record = fx.record_attendance(session_a["id"], athlete["id"],
                                  session_a["version"], minutes_present=60)
    session_b = fx.schedule_session(world["season"]["id"],
                                    world["credential"]["id"],
                                    scheduled_start="2027-07-10T10:00:00Z",
                                    duration_minutes=60)

    fx.set_clock("2027-07-06T00:00:00Z")
    fx.run_sweep(world["program"]["id"])

    credential = validate_success(
        api_client.get_credential(world["credential"]["id"], PM))
    assert credential["status"] == "EXPIRED"
    assert credential["expires_on"] == "2027-07-05"

    voided = validate_success(api_client.get_practice_session(session_b["id"], PM))
    assert voided["status"] == "VOIDED"
    assert voided["void_reason_code"] == "CREDENTIAL_EXPIRED"

    spared = validate_success(api_client.get_practice_session(session_a["id"], PM))
    assert spared["status"] == "HELD"
    assert spared["void_reason_code"] is None
    assert spared["recorded_attendance_count"] == 1

    rows = api_client.list_session_attendance_records(
        session_a["id"], PM).json()["data"]
    stored = next(row for row in rows if row["id"] == record["id"])
    assert stored["status"] == "COUNTED"
    assert stored["counted_minutes"] == 60

    athlete_after = validate_success(api_client.get_athlete(athlete["id"], PM))
    assert athlete_after["cumulative_practice_minutes"] == 60
    assert athlete_after["counted_session_count"] == 1
    assert athlete_after["registration_status"] == "ACTIVE"

    program = fx.get_program(world["program"]["id"])
    assert program["program_practice_minutes"] == 60
    assert program["certified_coach_count"] == 0
    assert program["expired_credential_ratio"] == 1.0
    assert program["compliance_posture"] == "FROZEN"
    assert program["sweep_epoch"] == 1
    assert_instant_equals(program["last_sweep_at"], "2027-07-06T00:00:00.000Z",
                          "last_sweep_at")


def test_11_only_a_sweep_can_complete_a_locked_season():
    """Step five bubbles the parent to COMPLETED once every entry has reported.

    PRD §3.9 step five: "every season in `ENTRIES_LOCKED` where the clock date has
    passed the season's `competition_date` and every entry of the season not in
    `VOIDED` is in `RESULTED`, `ADVANCED` or `DISQUALIFIED` moves `ENTRIES_LOCKED
    → COMPLETED`, incrementing that season's `version` — this is an automatic
    transition with no operator equivalent, so a season reaches its terminal state
    only through a checkpoint."

    Design: Corner/state_machines/entries_locked_season_completes_on_sweep
    """
    world = fx.setup_entries_locked_season(
        [{"athlete": {"legal_name": "Maya Foster", "birth_date": "2004-03-09"}},
         {"athlete": {"legal_name": "Ivan Petrov", "birth_date": "2003-10-01"}},
         {"athlete": {"legal_name": "Grace Lin", "birth_date": "1998-05-20"}}],
        [{"athlete_index": 0, "skill_score": 40.0},
         {"athlete_index": 1, "skill_score": 39.0},
         {"athlete_index": 2, "skill_score": 38.0}],
        divisioning_clock="2026-09-02T00:00:00Z")
    entries = world["entries"]

    fx.set_clock("2026-09-20T00:00:00Z")
    for entry, result_value in zip(entries, (38.0, 39.0, 40.0)):
        validate_success(api_client.post_entry_result(
            entry["id"], f.post_result_payload(result_value,
                                               disqualified=False), CD))

    fx.set_clock("2026-09-21T00:00:00Z")
    fx.run_sweep(world["program"]["id"])

    season = validate_success(api_client.get_season(world["season"]["id"], CD))
    assert season["status"] == "COMPLETED"

    expected = [(1.0526, 1, "ADVANCED_STATE", "ADVANCED"),
                (1.0, 2, "ADVANCED_STATE", "ADVANCED"),
                (0.95, 3, "NOT_ADVANCED", "RESULTED")]
    for entry, (ratio, placement, advancement, status) in zip(entries, expected):
        stored = validate_success(
            api_client.get_competition_entry(entry["id"], CD))
        assert stored["performance_ratio"] == ratio
        assert stored["placement"] == placement
        assert stored["advancement_status"] == advancement
        assert stored["status"] == status

    division = validate_success(
        api_client.get_division(entries[0]["division_id"], CD))
    assert division["status"] == "VALID"
    assert division["entry_count"] == 3
    assert division["ability_band_high"] == 40.0
    assert division["ability_band_low"] == 38.0
    assert division["ability_spread_ratio"] == 1.0526

    program = fx.get_program(world["program"]["id"])
    assert program["sweep_epoch"] == 1
    assert_instant_equals(program["last_sweep_at"], "2026-09-21T00:00:00.000Z",
                          "last_sweep_at")
    assert program["compliance_posture"] == "OPEN"
