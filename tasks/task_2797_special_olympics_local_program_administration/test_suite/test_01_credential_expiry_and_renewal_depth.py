"""Credential effective expiry, the fork/join, and the renewal cycle."""

from test_helpers import (
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    OFFICER_1,
    OFFICER_2,
    OFFICER_3,
    OFFICER_4,
    OFFICER_5,
    OFFICER_6,
    PM,
)
from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_credential, assert_instant_equals


def test_01_coach_credential_expiry_takes_the_earlier_training_branch():
    """A coach's 365-day training branch decides the effective expiry.

    PRD §3.3: "That expiry is the earliest of two dates in the ordinary case —
    the screening branch's expiry and the training branch's expiry"; "because a
    coach's training is valid for only 365 days, the training branch almost
    always decides a coach's expiry".

    Design: Difficulty/combinatorial_formula/credential_effective_expiry_role_min
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    _volunteer, credential = fx.create_certified_credential(
        program["id"],
        volunteer_overrides={"full_name": "Dana Ruiz", "email": "dana@rb.example",
                             "date_of_birth": "1988-04-12",
                             "volunteer_class": "COACH"},
        role_class="COACH",
        screening_overrides={"completed_on": "2026-07-01", "result": "CLEAR",
                             "vendor_reference": "BGS-1001"},
        training_overrides={"completed_on": "2026-07-05",
                            "curriculum_code": "PB-CORE-2026"},
    )
    assert_credential(credential)
    assert credential["status"] == "CERTIFIED"
    assert credential["screening_expires_on"] == "2029-06-30"
    assert credential["training_expires_on"] == "2027-07-05"
    assert credential["expires_on"] == "2027-07-05"


def test_02_unified_partner_expiry_uses_the_730_day_training_window():
    """The same completion dates expire a unified partner a year later.

    PRD §3.3: "a unified partner with identical completion dates expires a full
    365 days later than a coach would".

    Design: Difficulty/combinatorial_formula/credential_effective_expiry_role_min
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    _volunteer, credential = fx.create_certified_credential(
        program["id"],
        volunteer_overrides={"full_name": "Noah Byrd", "email": "noah@rb.example",
                             "date_of_birth": "1990-06-15",
                             "volunteer_class": "UNIFIED_PARTNER"},
        role_class="UNIFIED_PARTNER",
        screening_overrides={"completed_on": "2026-07-01", "result": "CLEAR",
                             "vendor_reference": "BGS-1002"},
        training_overrides={"completed_on": "2026-07-05",
                            "curriculum_code": "PB-CORE-2026"},
    )
    assert credential["status"] == "CERTIFIED"
    assert credential["training_expires_on"] == "2028-07-04"
    assert credential["expires_on"] == "2028-07-04"


def test_03_flagged_screening_caps_expiry_one_year_after_certification():
    """A FLAGGED screening admits a third term into the min().

    PRD §3.3: the expiry is "the earliest of three dates when the screening was
    `FLAGGED`, the third being the certification date plus one year, 365 days",
    since "a flagged screening shortens the credential to at most a year from
    certification regardless of how much life the branch dates had left".

    Design: Difficulty/combinatorial_formula/credential_effective_expiry_role_min
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    _volunteer, credential = fx.create_certified_credential(
        program["id"],
        volunteer_overrides={"full_name": "Priya Shah", "email": "priya@rb.example",
                             "date_of_birth": "1991-02-03",
                             "volunteer_class": "UNIFIED_PARTNER"},
        role_class="UNIFIED_PARTNER",
        screening_overrides={"completed_on": "2026-07-01", "result": "FLAGGED",
                             "vendor_reference": "BGS-1003"},
        training_overrides={"completed_on": "2026-07-05",
                            "curriculum_code": "PB-CORE-2026"},
        certify_overrides={
            "flag_override_reason":
                "Non-disqualifying municipal citation reviewed by the safety committee"},
    )
    assert credential["status"] == "CERTIFIED"
    assert credential["training_expires_on"] == "2028-07-04"
    assert credential["expires_on"] == "2027-08-01"
    assert_instant_equals(credential["certified_at"], "2026-08-01T00:00:00.000Z",
                          "certified_at")


def test_04_training_branch_may_be_recorded_before_the_screening_branch():
    """Either fork branch may go first; only the join reaches READY_TO_CERTIFY.

    PRD §3.3: "The fork joins on `READY_TO_CERTIFY`… recording training on a
    credential in `INITIATED` advances it `INITIATED → TRAINING_COMPLETE`" and
    "recording screening on a credential already in `TRAINING_COMPLETE` advances
    it `TRAINING_COMPLETE → READY_TO_CERTIFY`".

    Design: Difficulty/non_linear_state_machine/credential_fork_join_and_renewal_cycle
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    volunteer = fx.add_volunteer(program["id"])
    credential = fx.open_credential(volunteer["id"], role_class="COACH",
                                    officer=OFFICER_1)
    assert credential["status"] == "INITIATED"

    after_training = fx.record_training(
        credential["id"], officer=OFFICER_2,
        completed_on="2026-07-05", curriculum_code="PB-CORE-2026")
    assert after_training["status"] == "TRAINING_COMPLETE"
    assert after_training["screening_result"] is None

    after_screening = fx.record_screening(
        credential["id"], officer=OFFICER_1, completed_on="2026-07-01",
        result="CLEAR", vendor_reference="BGS-1001")
    assert after_screening["status"] == "READY_TO_CERTIFY"

    certified = fx.certify_credential(credential["id"], officer=OFFICER_3)
    assert certified["status"] == "CERTIFIED"
    assert certified["expires_on"] == "2027-07-05"


def test_05_expired_credential_returns_to_certified_through_renewal():
    """The CERTIFIED → EXPIRED → RENEWAL_IN_PROGRESS → CERTIFIED loop closes.

    PRD §3.3: "Recording either branch afresh on an expired credential moves it
    `EXPIRED → RENEWAL_IN_PROGRESS`", and re-certifying "applies the identical
    certification side effects, and additionally decrements
    `expired_credential_count` before recomputing the posture, closing the
    `CERTIFIED → EXPIRED → RENEWAL_IN_PROGRESS → CERTIFIED` loop".

    Design: Difficulty/non_linear_state_machine/credential_fork_join_and_renewal_cycle
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    volunteer = fx.add_volunteer(program["id"])
    credential = fx.open_credential(volunteer["id"], role_class="COACH",
                                    officer=OFFICER_1)
    fx.record_training(credential["id"], officer=OFFICER_2,
                       completed_on="2026-07-05",
                       curriculum_code="PB-CORE-2026")
    fx.record_screening(credential["id"], officer=OFFICER_1,
                        completed_on="2026-07-01", result="CLEAR",
                        vendor_reference="BGS-1001")
    fx.certify_credential(credential["id"], officer=OFFICER_3)

    fx.set_clock("2027-07-06T00:00:00Z")
    fx.run_sweep(program["id"])
    expired = validate_success(api_client.get_credential(credential["id"], PM))
    assert expired["status"] == "EXPIRED"

    renewing = fx.record_screening(credential["id"], officer=OFFICER_4,
                                   completed_on="2027-07-06", result="CLEAR",
                                   vendor_reference="BGS-2001")
    assert renewing["status"] == "RENEWAL_IN_PROGRESS"
    fx.record_training(credential["id"], officer=OFFICER_5,
                       completed_on="2027-07-06",
                       curriculum_code="PB-CORE-2027")

    recertified = fx.certify_credential(credential["id"], officer=OFFICER_6)
    assert recertified["status"] == "CERTIFIED"
    assert recertified["screening_expires_on"] == "2030-07-05"
    assert recertified["training_expires_on"] == "2028-07-05"
    assert recertified["expires_on"] == "2028-07-05"
    assert_instant_equals(recertified["certified_at"], "2027-07-06T00:00:00.000Z",
                          "certified_at")
    assert recertified["certified_by_user_id"] == "officer-6"
    assert recertified["screening_recorded_by_user_id"] == "officer-4"
    assert recertified["training_recorded_by_user_id"] == "officer-5"

    program_after = fx.get_program(program["id"])
    assert program_after["certified_coach_count"] == 1
    assert program_after["expired_credential_count"] == 0
    assert program_after["expired_credential_ratio"] == 0.0
    assert program_after["compliance_posture"] == "OPEN"


def test_06_session_rejected_while_the_named_credential_is_not_certified():
    """Session creation depends on the *credential's* state, not the request.

    PRD §3.4: "The named credential must be a genuinely live coaching credential
    — `role_class` of `COACH`, status `CERTIFIED`, and `expires_on` falling on or
    after the clock date — or the request is refused with
    `ERR_COACH_CREDENTIAL_INVALID` (422)."

    Design: Difficulty/cross_entity_state_dependency/practice_session_requires_certified_coach_credential
    """
    world = fx.setup_practice_ready_program()
    second = fx.setup_program_with_second_coach(
        world, certify=False,
        screening_overrides={"vendor_reference": "BGS-1004"})
    credential_b = second["credential"]
    assert credential_b["status"] == "READY_TO_CERTIFY"

    payload = f.create_practice_session_payload(
        world["season"]["id"], credential_b["id"],
        scheduled_start="2026-09-10T10:00:00Z", duration_minutes=60,
        capacity_slots=10)
    validate_error(api_client.create_practice_session(payload, PM),
                   ApiErrorId.ERR_COACH_CREDENTIAL_INVALID.value, 422)

    listing = api_client.list_practice_sessions(
        PM, params={"coach_credential_id": credential_b["id"]})
    body = listing.json()
    assert listing.status_code == 200
    assert body["meta"]["total_count"] == 0
    assert body["data"] == []


def test_07_identical_session_request_succeeds_once_the_credential_certifies():
    """Only the credential's state changes between the two attempts.

    PRD §3.4: "The server derives `scheduled_end` as the start instant advanced
    by the duration, and derives `counts_toward_minimum`, which is true when the
    duration is at least 45 minutes and the session has not been voided… The
    session is created in `SCHEDULED`".

    Design: Difficulty/cross_entity_state_dependency/practice_session_requires_certified_coach_credential
    """
    world = fx.setup_practice_ready_program()
    second = fx.setup_program_with_second_coach(
        world, certify=False,
        screening_overrides={"vendor_reference": "BGS-1004"})
    credential_b = second["credential"]
    payload = f.create_practice_session_payload(
        world["season"]["id"], credential_b["id"],
        scheduled_start="2026-09-10T10:00:00Z", duration_minutes=60,
        capacity_slots=10)
    validate_error(api_client.create_practice_session(payload, PM),
                   ApiErrorId.ERR_COACH_CREDENTIAL_INVALID.value, 422)

    certified = fx.certify_credential(credential_b["id"], officer=OFFICER_6)
    assert certified["status"] == "CERTIFIED"
    assert certified["expires_on"] == "2027-07-05"

    session = validate_success(api_client.create_practice_session(payload, PM), 201)
    assert session["status"] == "SCHEDULED"
    assert session["coach_credential_id"] == credential_b["id"]
    assert_instant_equals(session["scheduled_end"], "2026-09-10T11:00:00.000Z",
                          "scheduled_end")
    assert session["counts_toward_minimum"] is True


def test_08_sweep_expiry_voids_only_the_expired_coachs_future_session():
    """The credential expiry — not the sweep — voids the dependent session.

    PRD §3.3: when a credential moves `CERTIFIED → EXPIRED`, "every practice
    session naming this credential that is still `SCHEDULED` with a
    `scheduled_start` later than the clock becomes `VOIDED` with
    `void_reason_code` set to `CREDENTIAL_EXPIRED`".

    Design: Difficulty/transitive_cascade/sweep_credential_expiry_voids_scheduled_sessions
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    _vol1, credential_1 = fx.create_certified_credential(program["id"])
    _vol2, credential_2 = fx.create_certified_credential(
        program["id"],
        volunteer_overrides={"full_name": "Leo Marsh", "email": "leo@rb.example",
                             "date_of_birth": "1985-09-09",
                             "volunteer_class": "COACH"},
        screening_overrides={"vendor_reference": "BGS-1004"},
        training_overrides={"completed_on": "2026-07-20"})
    season = fx.create_practice_open_season(
        program["id"], season_name="Summer 2027 Athletics",
        practice_minimum_sessions=2, practice_minimum_minutes=90,
        registration_deadline="2027-08-01", divisioning_date="2027-08-05",
        competition_date="2027-08-20")
    session_1 = fx.schedule_session(season["id"], credential_1["id"],
                                    scheduled_start="2027-07-10T10:00:00Z")
    session_2 = fx.schedule_session(season["id"], credential_2["id"],
                                    scheduled_start="2027-07-10T14:00:00Z")

    fx.set_clock("2027-07-06T00:00:00Z")
    fx.run_sweep(program["id"])

    expired = validate_success(api_client.get_credential(credential_1["id"], PM))
    assert expired["status"] == "EXPIRED"
    assert expired["expires_on"] == "2027-07-05"
    still_certified = validate_success(
        api_client.get_credential(credential_2["id"], PM))
    assert still_certified["status"] == "CERTIFIED"
    assert still_certified["expires_on"] == "2027-07-20"

    voided = validate_success(
        api_client.get_practice_session(session_1["id"], PM))
    assert voided["status"] == "VOIDED"
    assert voided["void_reason_code"] == "CREDENTIAL_EXPIRED"
    survivor = validate_success(
        api_client.get_practice_session(session_2["id"], PM))
    assert survivor["status"] == "SCHEDULED"
    assert survivor["void_reason_code"] is None


def test_09_sweep_expiry_drives_the_posture_to_frozen_and_stamps_the_epoch():
    """One expiry of two credentials is a 0.5000 ratio, which freezes the program.

    PRD §2.7: "If the certified coach count is zero, or the ratio is greater than
    or equal to 0.50, the posture is `FROZEN`"; PRD §3.9 step six: "`sweep_epoch`
    is incremented by exactly one, and `last_sweep_at` is stamped with the
    logical clock instant".

    Design: Difficulty/transitive_cascade/sweep_credential_expiry_voids_scheduled_sessions
    """
    fx.set_clock("2026-08-01T00:00:00Z")
    program = fx.create_program()
    fx.create_certified_credential(program["id"])
    fx.create_certified_credential(
        program["id"],
        volunteer_overrides={"full_name": "Leo Marsh", "email": "leo@rb.example",
                             "date_of_birth": "1985-09-09",
                             "volunteer_class": "COACH"},
        screening_overrides={"vendor_reference": "BGS-1004"},
        training_overrides={"completed_on": "2026-07-20"})

    fx.set_clock("2027-07-06T00:00:00Z")
    fx.run_sweep(program["id"])

    after = fx.get_program(program["id"])
    assert after["certified_coach_count"] == 1
    assert after["credential_denominator_count"] == 2
    assert after["expired_credential_count"] == 1
    assert after["expired_credential_ratio"] == 0.5
    assert after["compliance_posture"] == "FROZEN"
    assert after["sweep_epoch"] == 1
    assert_instant_equals(after["last_sweep_at"], "2027-07-06T00:00:00.000Z",
                          "last_sweep_at")
