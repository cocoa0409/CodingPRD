"""Validation sequencing: when two checks both fail on one request, the first
failure in the declared order is the one reported."""
from test_helpers import (
    ApiErrorId,
    CLOCK_DELIVERY,
    CLOCK_ONBOARD,
    add_signed_note,
    api_client,
    attach_billable_clinician,
    complete_session,
    get_clinician,
    get_session,
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


def test_the_posture_gate_is_reported_ahead_of_the_referential_enrollment_check():
    """PRD §2.9: "The clinical safety gate is fifth: the session's clinician must
    read `billing_posture` of `BILLABLE` at the moment of completion, claim
    submission or claim resubmission, and a `GATED` or `FROZEN` posture blocks the
    operation with `ERR_CLINICIAN_NOT_BILLABLE`. Referential billing eligibility
    is sixth: the payer must be `ACTIVE` for the session's service date, the
    session's `cpt_code` must appear in the payer's `allowed_cpt_codes`, and an
    enrollment in `EFFECTIVE` status must cover the service date for that
    clinician-and-payer pair, failing which the request is rejected with
    `ERR_SERVICE_NOT_ENROLLED`."

    Design: Difficulty/priority_pair_validation_conflict/clinician_posture_gate_beats_payer_enrollment_check_on_claim_submission
    """
    scenario = make_completed_session_scenario()
    clinician_id = scenario["clinician"]["id"]
    enrollment_id = scenario["enrollment"]["id"]

    validate_success(api_client.terminate_payer_enrollment(enrollment_id, OPS))
    clinician = get_clinician(clinician_id)
    assert clinician["enrolled_payer_count"] == 0
    assert clinician["billing_posture"] == "FROZEN"

    rejected = api_client.create_claim({"session_id": scenario["session"]["id"]}, OPS)
    validate_error(rejected, ApiErrorId.ERR_CLINICIAN_NOT_BILLABLE)
    assert rejected.status_code == 422
    assert rejected.json()["data"]["error_id"] != ApiErrorId.ERR_SERVICE_NOT_ENROLLED.value


def test_both_gates_genuinely_fail_and_only_the_posture_one_is_reported():
    """PRD §2.9: "a caller who has both a stale credential and a bad payload must
    receive the credential error, and a test that exercises a valid payload
    against a stale credential must not be satisfied by a payload error."
    PRD §2.4: "A clinician with no `EFFECTIVE` enrollment therefore has an
    enrolled payer count of zero and is `FROZEN` regardless of licensure"

    Design: Difficulty/priority_pair_validation_conflict/clinician_posture_gate_beats_payer_enrollment_check_on_claim_submission
    """
    scenario = make_completed_session_scenario()
    session_id = scenario["session"]["id"]

    validate_success(api_client.terminate_payer_enrollment(scenario["enrollment"]["id"], OPS))

    payer = validate_success(api_client.get_payer(scenario["payer"]["id"], OPS))
    assert payer["status"] == "ACTIVE", (
        "the payer stays ACTIVE, so priority 6 fails only on enrollment coverage"
    )
    assert scenario["cpt_code"] in payer["allowed_cpt_codes"]

    rejected = api_client.create_claim({"session_id": session_id}, OPS)
    validate_error(rejected, ApiErrorId.ERR_CLINICIAN_NOT_BILLABLE)

    session = get_session(session_id)
    assert session["billing_state"] == "UNBILLED", (
        "the rejection left the billing axis unmoved"
    )
    assert session["claim_id"] is None
    assert api_client.list_claims(OPS, {"session_id": session_id}).json()["data"] == []


def make_completed_session_scenario() -> dict:
    """A BILLABLE clinician with one EFFECTIVE enrollment and one COMPLETED,
    signed, UNBILLED session."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    set_clock(CLOCK_DELIVERY)
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-16T14:00:00Z", "2026-06-16T15:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    session = complete_session(clinician["id"], session["id"])
    return {
        "payer": payer,
        "clinician": clinician,
        "patient": patient,
        "enrollment": attached["enrollment"],
        "session": session,
        "cpt_code": "90837",
    }


def test_the_declared_state_gate_is_reported_ahead_of_the_clinician_interval_conflict():
    """PRD §2.9: "Declared-state fourth: a resource that is not in a state from
    which the requested transition is declared is rejected with
    `ERR_INVALID_STATE`, and a resource already sitting in a terminal state that
    admits no further transition is rejected with `ERR_ALREADY_TERMINAL`."
    PRD §2.9: "Temporal conflicts are seventh, and within that group the
    clinician's availability is checked first, then the patient's own bookings,
    then the length of an enrollment window; the first conflict encountered
    produces its own identity"

    Design: Difficulty/priority_pair_validation_conflict/session_reopen_state_gate_beats_the_interval_conflict_on_the_same_request
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])

    make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-23T14:00:00Z", "2026-06-23T15:00:00Z"
    )
    s_move = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-30T15:00:00Z", "2026-06-30T16:00:00Z"
    )
    set_clock(CLOCK_DELIVERY)

    rejected = api_client.reschedule_session(
        s_move["id"],
        {"scheduled_start": "2026-06-23T14:30:00Z", "scheduled_end": "2026-06-23T15:30:00Z"},
        make_clinician_headers(clinician["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)
    assert rejected.status_code == 409
    assert rejected.json()["data"]["error_id"] != ApiErrorId.ERR_CLINICIAN_SLOT_CONFLICT.value

    moved = get_session(s_move["id"])
    assert moved["status"] == "SCHEDULED"
    assert moved["scheduled_start"] == "2026-06-30T15:00:00Z"


def test_the_same_overlapping_payload_is_refused_by_the_interval_rule_once_the_state_gate_is_satisfied():
    """PRD §3.4: "A cancelled session can be rescheduled to a new interval by
    supplying a fresh `scheduled_start` and `scheduled_end`, which must satisfy
    the same availability and overlap rules the original booking did"
    PRD §3.4: "neither the clinician nor the patient may hold an overlapping
    non-terminal session, where the clinician's own sessions additionally observe
    a 15-minute buffer"

    Design: Difficulty/priority_pair_validation_conflict/session_reopen_state_gate_beats_the_interval_conflict_on_the_same_request
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])

    s_hold = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-23T14:00:00Z", "2026-06-23T15:00:00Z"
    )
    s_move = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-30T15:00:00Z", "2026-06-30T16:00:00Z"
    )
    set_clock(CLOCK_DELIVERY)
    headers = make_clinician_headers(clinician["id"])

    validate_success(api_client.cancel_session(s_move["id"], headers))
    overlap = api_client.reschedule_session(
        s_move["id"],
        {"scheduled_start": "2026-06-23T14:30:00Z", "scheduled_end": "2026-06-23T15:30:00Z"},
        headers,
    )
    validate_error(overlap, ApiErrorId.ERR_CLINICIAN_SLOT_CONFLICT)
    assert overlap.status_code == 409

    hold = get_session(s_hold["id"])
    assert hold["status"] == "SCHEDULED"
    assert hold["slot_consumed"] is True, (
        "the rejected reschedules mutated nothing on the neighbouring session"
    )