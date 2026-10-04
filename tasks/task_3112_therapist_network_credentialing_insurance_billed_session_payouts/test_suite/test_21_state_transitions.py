"""Individual state transitions: the license verification branches, the reset
path, the invalid cancel, and the session's starting state."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EARLY,
    CLOCK_ONBOARD,
    add_signed_note,
    api_client,
    assert_license,
    assert_session,
    attach_billable_clinician,
    complete_session,
    get_clinician,
    get_session,
    make_clinician,
    make_license,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    open_and_lock_batch,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_clinician_headers

OPS = TEST_USERS["ops_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_verifying_a_live_license_stamps_the_verifier_and_the_clock():
    """PRD §3.1: "If the license's `expires_on` is strictly after the logical
    clock, the license becomes `VERIFIED` and the call records `verified_at` from
    the clock and `verified_by_user_id` from the acting header."
    PRD §2.1: "The server may record it — for example as `created_by_user_id` on
    `PayoutBatch`, as `verified_by_user_id` on `License`"

    Design: Corner/state_machines/license_verify_stamps_the_verifier_and_returns_the_license_to_verified
    """
    set_clock(CLOCK_EARLY)
    clinician = make_clinician()
    license_row = make_license(clinician["id"])

    verified = validate_success(
        api_client.verify_license(clinician["id"], license_row["id"], COMPLIANCE)
    )
    assert_license(verified)
    assert verified["verification_status"] == "VERIFIED"
    assert verified["verified_at"] == "2026-01-05T00:00:00Z", (
        "the verification instant comes from the logical clock"
    )
    assert verified["verified_by_user_id"] == COMPLIANCE["X-User-ID"]
    assert verified["verification_attempts"] == 1
    assert get_clinician(clinician["id"])["billing_posture"] == "FROZEN", (
        "PRD §2.4: FROZEN when `enrolled_payer_count` is 0, and the enrollment "
        "is still missing"
    )


def test_verifying_an_already_expired_license_records_a_failure_rather_than_raising_an_error():
    """PRD §3.1: "If `expires_on` is at or before the logical clock, the attempt
    fails and the license becomes `FAILED` instead. Either way
    `verification_attempts` grows by 1."

    Design: Corner/state_machines/license_verify_with_an_already_expired_license_records_failed
    """
    set_clock(CLOCK_EARLY)
    clinician = make_clinician()
    license_row = make_license(
        clinician["id"], license_number="LCSW-CA-55409", expires_on="2025-12-31T00:00:00Z"
    )

    result = validate_success(
        api_client.verify_license(clinician["id"], license_row["id"], COMPLIANCE)
    )
    assert result["verification_status"] == "FAILED"
    assert result["verification_status"] != "VERIFIED", (
        "the expiry is at or before the clock, so the ascending branch is unreachable"
    )
    assert result["verification_attempts"] == 1
    assert result["verified_at"] is None
    assert get_clinician(clinician["id"])["billing_posture"] == "FROZEN", (
        "PRD §2.4: FROZEN when `enrolled_payer_count` is 0"
    )


def test_resetting_a_failed_license_leaves_the_attempt_count_untouched():
    """PRD §3.1: "A `FAILED` license can be returned to `UNVERIFIED` by a reset,
    which leaves `verification_attempts` untouched and clears `verified_at` to
    null, so the same license can be attempted again after the underlying data is
    corrected."

    Design: Corner/state_machines/license_reset_verification_returns_failed_to_unverified_without_touching_the_attempt_count
    """
    set_clock(CLOCK_EARLY)
    clinician = make_clinician()
    license_row = make_license(
        clinician["id"], license_number="LCSW-CA-55409", expires_on="2025-12-31T00:00:00Z"
    )
    validate_success(api_client.verify_license(clinician["id"], license_row["id"], COMPLIANCE))

    reset = validate_success(
        api_client.reset_license_verification(clinician["id"], license_row["id"], COMPLIANCE)
    )
    assert reset["verification_status"] == "EXPIRED", (
        "PRD §3.1 checks EXPIRED before UNVERIFIED, and a reset does not move "
        "`expires_on` — the clock is already past it"
    )
    assert reset["verification_attempts"] == 1, "the retry budget survives the reset"
    assert reset["verified_at"] is None
    assert reset["verified_by_user_id"] is None

    second = validate_success(
        api_client.verify_license(clinician["id"], license_row["id"], COMPLIANCE)
    )
    assert second["verification_status"] == "FAILED", (
        "the license is still expired, so the second attempt fails too"
    )
    assert second["verification_attempts"] == 2
    assert get_clinician(clinician["id"])["billing_posture"] == "FROZEN", (
        "PRD §2.4: FROZEN when `enrolled_payer_count` is 0"
    )


def test_cancelling_a_completed_session_is_refused_and_leaves_both_axes_alone():
    """PRD §3.4: "A requested or scheduled session may be cancelled by the
    treating `Clinician` or an `OpsAdmin`"
    PRD §2.9: "a resource that is not in a state from which the requested
    transition is declared is rejected with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/session_cancel_from_a_completed_session_returns_invalid_state
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    slots_after_completion = get_clinician(clinician["id"])["open_slot_count"]

    rejected = api_client.cancel_session(session["id"], make_clinician_headers(clinician["id"]))
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)
    assert rejected.status_code == 409

    row = get_session(session["id"])
    assert row["status"] == "COMPLETED"
    assert row["slot_consumed"] is False
    assert row["billing_state"] == "UNBILLED", (
        "the billing axis was not reset by the rejection"
    )
    assert get_clinician(clinician["id"])["open_slot_count"] == slots_after_completion


def test_a_requested_session_starts_on_both_axes_without_consuming_a_slot():
    """PRD §3.4: "It starts at `status` of `REQUESTED` with `billing_state` of
    `UNBILLED`, `slot_consumed` false and `quoted_cost_share_cents` null.
    Requesting does not commit resources; scheduling does."

    Design: Corner/state_machines/session_create_starts_requested_with_an_unbilled_billing_axis
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    clinician = make_clinician()
    patient = make_verified_patient(payer["id"])

    session = validate_success(
        api_client.create_session(
            {
                "clinician_id": clinician["id"],
                "patient_id": patient["id"],
                "scheduled_start": "2026-06-03T16:00:00Z",
                "scheduled_end": "2026-06-03T17:00:00Z",
                "cpt_code": "90837",
                "modality": "VIDEO",
            },
            OPS,
        ),
        201,
    )
    assert_session(session)
    assert session["status"] == "REQUESTED"
    assert session["billing_state"] == "UNBILLED"
    assert session["slot_consumed"] is False
    assert session["quoted_cost_share_cents"] is None
    assert session["claim_id"] is None
    assert session["version"] == 1
    assert get_clinician(clinician["id"])["open_slot_count"] == 20, (
        "the two 600-minute default blocks are twenty whole hours, and the "
        "requested session has not yet consumed a slot"
    )


def test_reconciling_an_already_reconciled_batch_is_refused_as_terminal():
    """PRD §3.6: "Reconciling is permitted only when every non-voided line on a
    paid batch is `PAID` or `CLAWED_BACK`, and it closes the batch: any denial
    adjustment that landed after payment is applied as an additional clawback and
    the batch lands terminally in `RECONCILED`."
    PRD §2.9: "a resource already sitting in a terminal state that admits no
    further transition is rejected with `ERR_ALREADY_TERMINAL`"

    Design: Corner/state_machines/reconcile_on_an_already_reconciled_batch_returns_already_terminal
    """
    scenario = _paid_batch_scenario()
    batch_id = scenario["batch"]["id"]

    reconciled = validate_success(api_client.reconcile_payout_batch(batch_id, OPS))
    assert reconciled["status"] == "RECONCILED"
    frozen_total = reconciled["total_net_cents"]
    assert frozen_total == 15_000

    rejected = api_client.reconcile_payout_batch(batch_id, OPS)
    error = validate_error(rejected, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert rejected.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_BATCH_NOT_PAYABLE.value, (
        "the terminal state is isolated from the payable precondition"
    )
    batch = validate_success(api_client.get_payout_batch(batch_id, OPS))
    assert batch["total_net_cents"] == frozen_total
    assert batch["line_count"] == 1
    assert get_clinician(scenario["clinician"]["id"])["payout_balance_cents"] == 15_000


def test_signing_the_same_note_twice_is_refused_and_moves_nothing():
    """PRD §3.4: "Signing is permitted only for the clinician the session belongs to
    — the acting header must equal the session's `clinician_id` — and only when
    the `diagnosis_code` is present, the `narrative` is non-empty, and
    `duration_minutes` falls between 45 and 120 minutes inclusive."
    PRD §2.9: "a resource that is not in a state from which the requested
    transition is declared is rejected with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/signing_the_same_note_twice_returns_invalid_state
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    headers = make_clinician_headers(clinician["id"])
    note = validate_success(
        api_client.create_session_note(
            session["id"],
            {
                "diagnosis_code": "F41.1",
                "duration_minutes": 60,
                "cpt_code": "90837",
                "narrative": "Note for the repeated-sign corner.",
                "expected_session_version": get_session(session["id"])["version"],
            },
            headers,
        ),
        201,
    )
    first = validate_success(api_client.sign_session_note(session["id"], note["id"], headers))
    assert first["status"] == "SIGNED"

    retry = api_client.sign_session_note(session["id"], note["id"], headers)
    validate_error(retry, ApiErrorId.ERR_INVALID_STATE)
    assert retry.status_code == 409

    row = api_client.list_session_notes(session["id"], OPS).json()["data"]
    assert len(row) == 1
    assert row[0]["status"] == "SIGNED", "the retry did not lock the note"
    assert row[0]["signed_at"] == first["signed_at"]
    assert row[0]["note_version"] == 1


def _paid_batch_scenario() -> dict:
    """A completed, billed, paid session on a locked-then-paid batch."""
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = validate_success(api_client.create_claim({"session_id": session["id"]}, OPS), 201)
    validate_success(api_client.adjudicate_claim(claim["id"], {"outcome": "PAID"}, OPS))

    set_clock("2026-06-09T00:00:00Z")
    batch = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")
    batch = validate_success(api_client.pay_payout_batch(batch["id"], OPS))
    return {"payer": payer, "clinician": clinician, "patient": patient,
            "session": session, "claim": claim, "batch": batch}