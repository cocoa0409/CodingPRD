"""A claim's eligibility depends on the session's transcription axis, and an
enrollment's transitions depend on the payer's status rather than its own."""
from test_helpers import (
    ApiErrorId,
    CLOCK_DELIVERY,
    CLOCK_ONBOARD,
    add_signed_note,
    api_client,
    attach_billable_clinician,
    credential_clinician,
    get_enrollment,
    get_session,
    make_clinician,
    make_enrollment,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_clinician_headers

OPS = TEST_USERS["ops_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _scheduled_signed_session_before_start() -> dict:
    """A SCHEDULED session carrying a SIGNED note, with the clock still short of
    its scheduled start."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-23T14:00:00Z", "2026-06-23T15:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock(CLOCK_DELIVERY)
    return {"payer": payer, "clinician": clinician, "patient": patient, "session": session}


def test_claim_creation_is_refused_while_the_session_is_still_scheduled():
    """PRD §3.5: "A claim is submitted against a session that has reached
    `COMPLETED`"
    PRD §2.9: "Declared-state fourth: a resource that is not in a state from
    which the requested transition is declared is rejected with
    `ERR_INVALID_STATE`"

    Design: Difficulty/cross_entity_state_dependency/claim_submission_requires_the_session_transcription_axis_to_be_completed
    """
    scenario = _scheduled_signed_session_before_start()
    rejected = api_client.create_claim({"session_id": scenario["session"]["id"]}, OPS)
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)
    assert rejected.status_code == 409

    session = get_session(scenario["session"]["id"])
    assert session["status"] == "SCHEDULED"
    assert session["billing_state"] == "UNBILLED"
    assert session["claim_id"] is None


def test_completion_before_the_scheduled_start_is_refused_and_succeeds_once_the_clock_reaches_it():
    """PRD §3.4: "Delivery is recorded by the treating `Clinician` or an
    `OpsAdmin` marking a scheduled session delivered, which is permitted only
    when the patient is attached, at least one note on the session is `SIGNED`,
    the scheduled start is not later than the logical clock, and the owning
    clinician is not `OFFBOARDED`."

    Design: Difficulty/cross_entity_state_dependency/claim_submission_requires_the_session_transcription_axis_to_be_completed
    """
    scenario = _scheduled_signed_session_before_start()
    clinician_id = scenario["clinician"]["id"]
    session_id = scenario["session"]["id"]
    headers = make_clinician_headers(clinician_id)

    early = api_client.complete_session(session_id, headers)
    validate_error(early, ApiErrorId.ERR_INVALID_STATE)
    assert get_session(session_id)["status"] == "SCHEDULED", (
        "the same SIGNED note was never the blocking factor — the status was"
    )

    set_clock("2026-06-23T15:00:00Z")
    completed = validate_success(api_client.complete_session(session_id, headers))
    assert completed["status"] == "COMPLETED"

    claim = validate_success(api_client.create_claim({"session_id": session_id}, OPS), 201)
    assert claim["claim_status"] == "SUBMITTED"
    assert get_session(session_id)["billing_state"] == "CLAIM_SUBMITTED"


def test_enrollment_activation_follows_the_payer_status_not_the_enrollment_own_fields():
    """PRD §3.2: "An `OpsAdmin` may move an enrollment from `PENDING` to
    `EFFECTIVE` only when its `effective_from` is at or before the logical clock,
    the owning clinician holds at least one license reading `VERIFIED` whose
    `issuing_state` equals the clinician's `primary_state`, the payer's `status`
    is `ACTIVE`, and the clinician holds at least one malpractice policy whose
    `coverage_cents` is at least the payer's
    `min_malpractice_coverage_cents` and whose `policy_status` reads `ACTIVE`."
    PRD §3.2: "A payer whose status is `SUSPENDED_AT_PAYER` or `TERMINATED` blocks
    activation with `ERR_PAYER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_and_suspension_follow_the_payer_status_not_their_own
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    attached = _credential_only(payer["id"])
    clinician = attached["clinician"]
    enrollment = make_enrollment(
        clinician["id"], payer["id"], effective_from="2026-02-01T00:00:00Z"
    )
    assert enrollment["status"] == "PENDING"

    validate_success(api_client.patch_payer(payer["id"], {"status": "SUSPENDED_AT_PAYER"}, OPS))
    blocked = api_client.activate_payer_enrollment(enrollment["id"], OPS)
    validate_error(blocked, ApiErrorId.ERR_PAYER_SUSPENDED)
    assert blocked.status_code == 409
    assert get_enrollment(enrollment["id"])["status"] == "PENDING", (
        "nothing was written by the rejected activation"
    )


def test_the_identical_activation_succeeds_once_the_payer_returns_to_active():
    """PRD §3.2: "On activation the system pins `rate_set_version_pinned` to the
    highest `rate_set_version` among the payer's rate rows for the clinician's
    license type and primary state whose window covers `effective_from`, or
    leaves it null when no such row is effective at that instant, derives
    `effective_window_days`, and recomputes the clinician's
    `enrolled_payer_count` and posture."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activation_and_suspension_follow_the_payer_status_not_their_own
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    attached = _credential_only(payer["id"])
    clinician = attached["clinician"]
    enrollment = make_enrollment(
        clinician["id"], payer["id"], effective_from="2026-02-01T00:00:00Z"
    )

    validate_success(api_client.patch_payer(payer["id"], {"status": "SUSPENDED_AT_PAYER"}, OPS))
    validate_error(
        api_client.activate_payer_enrollment(enrollment["id"], OPS),
        ApiErrorId.ERR_PAYER_SUSPENDED,
    )
    validate_success(api_client.patch_payer(payer["id"], {"status": "ACTIVE"}, OPS))

    activated = validate_success(api_client.activate_payer_enrollment(enrollment["id"], OPS))
    assert activated["status"] == "EFFECTIVE"
    assert activated["rate_set_version_pinned"] is None, (
        "no rate row is on file, so the pin resolves to null"
    )
    clinician = validate_success(api_client.get_clinician(clinician["id"], OPS))
    assert clinician["billing_posture"] == "BILLABLE", (
        "a VERIFIED license, an ACTIVE policy and one EFFECTIVE enrollment"
    )


def _credential_only(payer_id: str) -> dict:
    """A clinician with a VERIFIED CA license and an ACTIVE malpractice policy
    above the payer's floor, but no enrollment yet."""
    clinician = make_clinician()
    credentialing = credential_clinician(clinician)
    return {
        "clinician": validate_success(api_client.get_clinician(clinician["id"], OPS)),
        "license": credentialing["license"],
        "policy": credentialing["policy"],
    }