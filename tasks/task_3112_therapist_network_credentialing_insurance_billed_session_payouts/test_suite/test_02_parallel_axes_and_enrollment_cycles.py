"""The two parallel state dimensions on one Session row, and the enrollment
cycle that drives clinician posture."""
from test_helpers import (
    ApiErrorId,
    CLOCK_DELIVERY,
    add_signed_note,
    api_client,
    assert_clinician,
    assert_session,
    complete_session,
    get_clinician,
    get_note_rows,
    get_session,
    make_scheduled_session,
    make_verified_patient,
    set_clock,
    setup_completed_session,
    two_enrollment_clinician,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

OPS = TEST_USERS["ops_admin_headers"]


def test_reopening_a_completed_session_moves_only_the_transcription_axis():
    """PRD §3.4: "A completed session may be returned to `SCHEDULED` by an
    `OpsAdmin` so that its documentation can be corrected, but only while its
    `billing_state` is still `UNBILLED` and no claim exists for it; the reopen
    re-occupies the slot and re-derives both counters."
    PRD §3.4: "Notes are left in place by a reopen, and because the newest signed
    note still blocks a second delivery until it is superseded, re-opening a
    session is only useful in combination with recording a fresh note."

    Design: Difficulty/non_linear_state_machine/session_transcription_and_billing_axes_advance_independently_on_one_row
    """
    scenario = setup_completed_session()
    clinician_id = scenario["clinician"]["id"]
    session_id = scenario["session"]["id"]

    reopened = validate_success(api_client.reopen_session(session_id, OPS))
    assert_session(reopened)

    assert reopened["status"] == "SCHEDULED"
    assert reopened["billing_state"] == "UNBILLED", (
        "the billing axis does not move with the transcription axis"
    )
    assert reopened["slot_consumed"] is True
    assert reopened["claim_id"] is None
    assert get_clinician(clinician_id)["open_slot_count"] == 19, (
        "the reopen re-occupies exactly the one whole hour the session holds, "
        "from the twenty the two default blocks provide"
    )
    notes = get_note_rows(session_id)
    assert len(notes) == 1 and notes[0]["status"] == "SIGNED", (
        "the note survives the reopen"
    )


def test_claim_submission_is_refused_while_the_transcription_axis_is_scheduled():
    """PRD §3.5: "A claim is submitted against a session that has reached
    `COMPLETED`; the clinician's `billing_posture` must read `BILLABLE` at that
    instant, and the session must carry exactly one note reading `SIGNED` which
    is also the newest note for the session."
    PRD §2.9: "Declared-state fourth: a resource that is not in a state from
    which the requested transition is declared is rejected with
    `ERR_INVALID_STATE`".

    Design: Difficulty/non_linear_state_machine/session_transcription_and_billing_axes_advance_independently_on_one_row
    """
    scenario = setup_completed_session()
    session_id = scenario["session"]["id"]

    validate_success(api_client.reopen_session(session_id, OPS))
    rejected = api_client.create_claim({"session_id": session_id}, OPS)
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)
    assert rejected.status_code == 409

    session = get_session(session_id)
    assert session["status"] == "SCHEDULED"
    assert session["billing_state"] == "UNBILLED"
    assert session["claim_id"] is None
    assert api_client.list_claims(OPS, {"session_id": session_id}).json()["data"] == []


def test_suspending_and_reinstating_an_enrollment_re_derives_posture_without_moving_the_session_axis():
    """PRD §2.4: "A clinician reads `FROZEN` when `status` is `SUSPENDED` or
    `OFFBOARDED`, or when `enrolled_payer_count` is 0. Failing that, the clinician
    reads `GATED` when no `License` row for that clinician reads
    `verification_status` of `VERIFIED`, or when no `MalpracticePolicy` row for
    that clinician reads `policy_status` of `ACTIVE`. Otherwise the clinician
    reads `BILLABLE`."
    PRD §3.2: "A suspended enrollment may be reinstated back to `EFFECTIVE`,
    permitted only while the payer reads `ACTIVE`, `effective_from` is at or
    before the clock, and `effective_to` is either null or strictly after the
    clock; reinstating increments `enrolled_payer_count` and re-derives posture."

    Design: Difficulty/non_linear_state_machine/enrollment_cycles_between_effective_and_suspended_and_redrives_clinician_posture
    """
    scenario = two_enrollment_clinician()
    clinician_id = scenario["clinician"]["id"]
    enroll_pax = scenario["enroll_pax"]["id"]

    clinician = get_clinician(clinician_id)
    assert_clinician(clinician)
    assert clinician["enrolled_payer_count"] == 2
    assert clinician["billing_posture"] == "BILLABLE"

    suspended = validate_success(api_client.suspend_payer_enrollment(enroll_pax, OPS))
    assert suspended["status"] == "SUSPENDED"
    clinician = get_clinician(clinician_id)
    assert clinician["enrolled_payer_count"] == 1
    assert clinician["billing_posture"] == "BILLABLE", (
        "a verified license, an ACTIVE policy and at least one EFFECTIVE "
        "enrollment keep the clinician BILLABLE"
    )

    reinstated = validate_success(api_client.reinstate_payer_enrollment(enroll_pax, OPS))
    assert reinstated["status"] == "EFFECTIVE"
    clinician = get_clinician(clinician_id)
    assert clinician["enrolled_payer_count"] == 2
    assert clinician["billing_posture"] == "BILLABLE"


def test_reaching_zero_effective_enrollments_freezes_the_clinician_and_leaves_completed_sessions_untouched():
    """PRD §2.4: "Only `PayerEnrollment` rows in `EFFECTIVE` status count toward
    `enrolled_payer_count`; `PENDING`, `SUSPENDED` and `TERMINATED` rows do not."
    PRD §3.2: "When `enrolled_payer_count` drops to zero — whether because the
    last enrollment was terminated, suspended, or lost to a payer suspension —
    the clinician's posture becomes `FROZEN` under §2.4 even if every license and
    policy is in order, and the frozen-posture cascade cancels the clinician's
    open sessions."
    PRD §3.2: "which decrements the clinician's `enrolled_payer_count` and
    re-derives posture, while leaving sessions already `COMPLETED` untouched."

    Design: Difficulty/non_linear_state_machine/enrollment_cycles_between_effective_and_suspended_and_redrives_clinician_posture
    """
    scenario = two_enrollment_clinician()
    clinician_id = scenario["clinician"]["id"]
    enroll_pax = scenario["enroll_pax"]["id"]
    enroll_mcr = scenario["enroll_mcr"]["id"]

    patient = make_verified_patient(scenario["payer_pax"]["id"])
    session = make_scheduled_session(
        clinician_id, patient["id"], "2026-06-16T14:00:00Z", "2026-06-16T15:00:00Z"
    )
    add_signed_note(clinician_id, session["id"])
    set_clock(CLOCK_DELIVERY)
    session = complete_session(clinician_id, session["id"])
    assert session["status"] == "COMPLETED"

    validate_success(api_client.suspend_payer_enrollment(enroll_pax, OPS))
    validate_success(api_client.suspend_payer_enrollment(enroll_mcr, OPS))

    clinician = get_clinician(clinician_id)
    assert clinician["enrolled_payer_count"] == 0
    assert clinician["billing_posture"] == "FROZEN", (
        "zero effective enrollments freeze the clinician regardless of licensure"
    )
    final_session = get_session(session["id"])
    assert final_session["status"] == "COMPLETED", (
        "a session already COMPLETED is untouched by the posture regression"
    )
    assert final_session["billing_state"] == "UNBILLED"