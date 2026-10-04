"""Role scope, the optimistic-concurrency contract, and the saga compensations
that correct a previously committed line."""
from test_helpers import (
    ApiErrorId,
    CLOCK_EARLY,
    CLOCK_ONBOARD,
    add_signed_note,
    adjudicate,
    api_client,
    assert_payout_batch,
    assert_payout_line,
    attach_billable_clinician,
    complete_session,
    get_batch,
    get_batch_lines,
    get_clinician,
    get_patient,
    get_session,
    make_clinician,
    make_license,
    make_payer,
    make_rate,
    make_scheduled_session,
    make_verified_patient,
    open_and_lock_batch,
    set_clock,
    submit_claim,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import get_clinician_payout_lines
from test_helpers.test_users import (
    TEST_USERS,
    make_clinician_headers,
    make_patient_headers,
)

OPS = TEST_USERS["ops_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
PAYROLL = TEST_USERS["payroll_service_headers"]


def test_a_clinician_cannot_verify_a_license_because_the_reviewer_role_owns_it():
    """PRD §2.1: "A `Clinician` acts on their own schedule and documentation:
    creating and signing session notes and accepting or declining a continuity
    plan are theirs alone, while scheduling, completing, cancelling and
    rescheduling sessions are shared with `OpsAdmin`."

    Design: Corner/rbac/clinician_cannot_verify_a_license_because_compliance_officer_owns_it
    """
    set_clock(CLOCK_EARLY)
    clinician = make_clinician()
    license_row = make_license(clinician["id"])

    response = api_client.verify_license(
        clinician["id"], license_row["id"], make_clinician_headers(clinician["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403
    rows = api_client.list_licenses(clinician["id"], OPS).json()["data"]
    assert rows[0]["verification_status"] == "UNVERIFIED"
    assert rows[0]["verification_attempts"] == 0
    assert get_clinician(clinician["id"])["billing_posture"] == "FROZEN"

    # The identical call under the reviewer role succeeds.
    validate_success(api_client.verify_license(clinician["id"], license_row["id"], COMPLIANCE))


def test_a_patient_may_read_its_own_sessions_but_not_a_clinicians_payout_lines():
    """PRD §2.1: "`Patient` holds read-only access to their own sessions,
    cost-share quotes and clinician records."
    PRD §2.1: "Where a role is not listed as authorised for an endpoint, the
    attempt fails with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/patient_may_read_its_own_sessions_but_not_any_clinicians_payout_lines
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    headers = make_patient_headers(patient["id"])

    mine, meta = validate_paginated(
        api_client.list_sessions(headers, {"patient_id": patient["id"], "limit": 10, "offset": 0})
    )
    assert len(mine) == 1 and meta["total_count"] == 1
    assert validate_success(api_client.get_patient(patient["id"], headers))["id"] == patient["id"]

    refused = api_client.list_clinician_payout_lines(clinician["id"], headers, {"limit": 10, "offset": 0})
    error = validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED)
    assert refused.status_code == 403
    assert error["error_id"] != ApiErrorId.ERR_CLINICIAN_NOT_FOUND.value


def test_the_disbursement_integration_can_pay_a_locked_batch_but_cannot_open_one():
    """PRD §2.1: "`PayrollService` is the downstream disbursement integration: it
    may execute the disbursement run on a payout batch and read batches and
    lines, but it cannot open, lock, reconcile or supersede a batch."

    Design: Corner/rbac/payroll_service_can_pay_a_locked_batch_but_cannot_open_or_lock_one
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
    complete_session(clinician["id"], session["id"])
    set_clock("2026-06-09T00:00:00Z")
    batch = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")

    refused = api_client.create_payout_batch(
        {
            "period_start": "2026-06-15T00:00:00Z",
            "period_end": "2026-06-22T00:00:00Z",
            "schedule": "WEEKLY",
        },
        PAYROLL,
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED)
    assert refused.status_code == 403

    paid = validate_success(api_client.pay_payout_batch(batch["id"], PAYROLL))
    assert paid["status"] == "PAID"
    assert get_clinician(clinician["id"])["payout_balance_cents"] == 15_000
    batches, meta = validate_paginated(api_client.list_payout_batches(OPS, {"limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, "the refused open persisted nothing"


def test_onboarding_a_clinician_is_refused_for_an_authenticated_non_operator_role():
    """PRD §2.1: "`OpsAdmin` is the network operator: it onboards clinicians"
    PRD §2.1: "A request whose declared role is not permitted on the addressed
    endpoint is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/authenticated_caller_cannot_create_a_clinician_without_the_ops_admin_role
    """
    set_clock(CLOCK_EARLY)
    payload = {
        "full_name": "Avery Lin",
        "license_type": "LCSW",
        "primary_state": "CA",
        "specialty_tags": ["ANXIETY"],
        "weekly_caseload_target": 5,
        "availability_blocks": [{"weekday": 3, "start_minute": 480, "end_minute": 1080}],
    }
    response = api_client.create_clinician(payload, COMPLIANCE)
    error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED)
    assert response.status_code == 403
    assert error["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value
    assert api_client.list_clinicians(OPS).json()["data"] == []
    assert validate_success(api_client.create_clinician(payload, OPS), 201)["status"] == "ONBOARDING"


def test_superseding_a_batch_with_a_stale_observed_version_is_refused():
    """PRD §2.7: "Superseding an open payout batch requires
    `expected_open_batch_version`, carrying the client's last observed `version`
    of that `PayoutBatch`. If the batch's current `version` differs from the
    supplied value the request is rejected with `ERR_STALE_VERSION` and HTTP
    status 412."
    PRD §2.7: "omitting it is a malformed request (`ERR_INVALID_REQUEST`) rather
    than an unchecked write"

    Design: Corner/cross_cutting_complexity_layers/supersede_of_an_open_batch_rejects_a_stale_expected_version
    """
    set_clock("2026-06-09T00:00:00Z")
    batch = validate_success(
        api_client.create_payout_batch(
            {
                "period_start": "2026-06-01T00:00:00Z",
                "period_end": "2026-06-08T00:00:00Z",
                "schedule": "WEEKLY",
            },
            OPS,
        ),
        201,
    )
    stale = api_client.supersede_payout_batch(
        batch["id"], {"expected_open_batch_version": batch["version"] + 1}, OPS
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    assert stale.status_code == 412
    assert validate_success(api_client.get_payout_batch(batch["id"], OPS))["status"] == "OPEN"

    observed = validate_success(api_client.get_payout_batch(batch["id"], OPS))
    fresh = validate_success(
        api_client.supersede_payout_batch(
            batch["id"], {"expected_open_batch_version": observed["version"]}, OPS
        )
    )
    assert fresh["status"] == "SKIPPED"
    assert fresh["version"] > observed["version"]


def test_adding_a_note_against_a_superseded_session_version_is_refused():
    """PRD §2.7: "Adding a session note requires `expected_session_version`,
    carrying the client's last observed `version` of the `Session` the note is
    being attached to."
    PRD §3.4: "it locks any earlier signed note on the same session by moving it
    to `LOCKED`. The superseded note is not deleted and is not edited; it is
    simply no longer the note of record"

    Design: Corner/cross_cutting_complexity_layers/adding_a_note_against_a_stale_session_version_is_rejected
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
    stale_version = get_session(session["id"])["version"]
    first = validate_success(
        api_client.create_session_note(
            session["id"],
            {
                "diagnosis_code": "F41.1",
                "duration_minutes": 60,
                "cpt_code": "90837",
                "narrative": "First note, which advances the session version.",
                "expected_session_version": stale_version,
            },
            headers,
        ),
        201,
    )

    rejected = api_client.create_session_note(
        session["id"],
        {
            "diagnosis_code": "F41.1",
            "duration_minutes": 60,
            "cpt_code": "90837",
            "narrative": "Second note carrying the superseded session version.",
            "expected_session_version": stale_version,
        },
        headers,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION)
    assert rejected.status_code == 412
    notes = api_client.list_session_notes(session["id"], OPS).json()["data"]
    assert len(notes) == 1

    observed = get_session(session["id"])["version"]
    second = validate_success(
        api_client.create_session_note(
            session["id"],
            {
                "diagnosis_code": "F41.1",
                "duration_minutes": 60,
                "cpt_code": "90837",
                "narrative": "Second note replayed against the freshly observed version.",
                "expected_session_version": observed,
            },
            headers,
        ),
        201,
    )
    assert second["note_version"] == 2

    validate_success(api_client.sign_session_note(session["id"], second["id"], headers))
    notes = api_client.list_session_notes(session["id"], OPS).json()["data"]
    by_id = {row["id"]: row for row in notes}
    assert by_id[first["id"]]["status"] == "DRAFT", (
        "PRD §3.4 locks only an earlier *signed* note; this one was never signed, "
        "so it stays DRAFT and is simply no longer the note of record"
    )
    assert by_id[second["id"]]["status"] == "SIGNED", (
        "the two rows are distinct, so the second note is a real insert"
    )


def test_reassigning_a_continuity_successor_against_a_stale_plan_version_is_refused():
    """PRD §2.7: "Reassigning a continuity plan's successor clinician requires
    `expected_plan_version`, carrying the client's last observed `version` of that
    `ContinuityPlan`."
    PRD §3.7: "An `OpsAdmin` may assign or replace the successor on a plan, which
    returns a `DECLINED` or `ESCALATED` plan to `PENDING` and clears
    `swap_requested`"

    Design: Corner/cross_cutting_complexity_layers/reassigning_a_continuity_successor_against_a_stale_plan_version_is_rejected
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    successor = make_clinician()
    second_successor = make_clinician(
        full_name="Zara Whitfield", availability_blocks=[
            {"weekday": 5, "start_minute": 480, "end_minute": 1080}
        ],
    )
    departing = validate_success(
        api_client.create_clinician(
            {
                "full_name": "Nadia Okonkwo",
                "license_type": "LMFT",
                "primary_state": "CA",
                "specialty_tags": ["ANXIETY"],
                "weekly_caseload_target": 8,
                "availability_blocks": [{"weekday": 4, "start_minute": 480, "end_minute": 1080}],
            },
            OPS,
        ),
        201,
    )
    patient = make_verified_patient(payer["id"])
    plan = validate_success(
        api_client.create_continuity_plan(
            {"clinician_id": departing["id"], "patient_id": patient["id"],
             "reason": "OFFBOARDING", "successor_clinician_id": successor["id"]},
            OPS,
        ), 201
    )
    stale_version = plan["version"]

    first = validate_success(
        api_client.assign_continuity_successor(
            plan["id"],
            {"successor_clinician_id": second_successor["id"], "expected_plan_version": stale_version},
            OPS,
        )
    )
    assert first["successor_clinician_id"] == second_successor["id"]

    reused = api_client.assign_continuity_successor(
        plan["id"],
        {"successor_clinician_id": successor["id"], "expected_plan_version": stale_version},
        OPS,
    )
    validate_error(reused, ApiErrorId.ERR_STALE_VERSION)
    assert reused.status_code == 412
    row = validate_success(api_client.get_continuity_plan(plan["id"], OPS))
    assert row["successor_clinician_id"] == second_successor["id"], (
        "the first successor survives the rejected reassignment"
    )


def test_a_payer_status_patch_is_visible_in_its_own_response_and_on_the_next_read():
    """PRD §3.8: "Moving a payer to `SUSPENDED_AT_PAYER` cascades in three hops."
    PRD §3.2: "A suspended enrollment may be reinstated back to `EFFECTIVE`,
    permitted only while the payer reads `ACTIVE`, `effective_from` is at or
    before the clock, and `effective_to` is either null or strictly after the
    clock; reinstating increments `enrolled_payer_count` and re-derives
    posture."

    Design: Corner/cross_cutting_complexity_layers/patient_status_patch_is_visible_in_the_same_response
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])

    patched = validate_success(
        api_client.patch_payer(payer["id"], {"status": "SUSPENDED_AT_PAYER"}, OPS)
    )
    assert patched["status"] == "SUSPENDED_AT_PAYER", (
        "the patch response itself already reflects the new value"
    )
    assert validate_success(api_client.get_payer(payer["id"], OPS))["status"] == "SUSPENDED_AT_PAYER"
    assert validate_success(
        api_client.get_payer_enrollment(attached["enrollment"]["id"], OPS)
    )["status"] == "SUSPENDED"
    assert get_clinician(attached["clinician"]["id"])["billing_posture"] == "FROZEN"

    reinstate = api_client.reinstate_payer_enrollment(attached["enrollment"]["id"], OPS)
    validate_error(reinstate, ApiErrorId.ERR_PAYER_SUSPENDED)


def test_terminating_a_payer_denies_its_in_flight_claims_and_leaves_no_payable_line():
    """PRD §3.8: "Every enrollment with that payer in `PENDING`, `EFFECTIVE` or
    `SUSPENDED` status moves to `TERMINATED`. Every claim with that payer that is
    still `SUBMITTED` is denied with a `denial_code` of `NOT_COVERED`."

    Design: Corner/cross_cutting_complexity_layers/payer_termination_is_a_saga_that_denies_claims_and_adjusts_the_payout_line
    """
    set_clock(CLOCK_ONBOARD)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    attached = attach_billable_clinician(payer["id"])
    clinician = attached["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    session = complete_session(clinician["id"], session["id"])
    claim = submit_claim(session["id"])

    set_clock("2026-06-09T00:00:00Z")
    batch = validate_success(
        api_client.create_payout_batch(
            {
                "period_start": "2026-06-01T00:00:00Z",
                "period_end": "2026-06-08T00:00:00Z",
                "schedule": "WEEKLY",
            },
            OPS,
        ),
        201,
    )
    validate_success(api_client.patch_payer(payer["id"], {"status": "TERMINATED"}, OPS))

    assert validate_success(api_client.get_payer(payer["id"], OPS))["status"] == "TERMINATED"
    assert validate_success(
        api_client.get_payer_enrollment(attached["enrollment"]["id"], OPS)
    )["status"] == "TERMINATED"
    denied = validate_success(api_client.get_claim(claim["id"], OPS))
    assert denied["claim_status"] == "DENIED"
    assert denied["denial_code"] == "NOT_COVERED"
    assert get_session(session["id"])["billing_state"] == "DENIED"

    # PRD §3.6's scheduled basis earns on every COMPLETED session in the window
    # "regardless of whether the payer has paid anything", so the batch still has
    # its one line — but the denial §3.8 appended leaves the clinician nothing
    # payable: the clawback sits on a zero-gross PENDING line of its own and a
    # PENDING line "contributes zero" to the balance.
    locked = validate_success(api_client.lock_payout_batch(batch["id"], OPS))
    assert locked["line_count"] == 1
    assert locked["total_gross_cents"] == 15_000
    assert get_batch(batch["id"])["line_count"] == 1
    clawback_lines = [
        line
        for line in get_clinician_payout_lines(clinician["id"])
        if line["gross_cents"] == 0
    ]
    assert len(clawback_lines) == 1, "§3.8 gives the clawback a line of its own"
    assert clawback_lines[0]["adjustment_cents"] == -15_000
    assert clawback_lines[0]["line_status"] == "PENDING"
    assert clawback_lines[0]["net_cents"] == 0
    assert get_clinician(clinician["id"])["payout_balance_cents"] == 0


def test_reopening_a_completed_session_reproduces_the_pre_completion_slot_counter():
    """PRD §3.4: "the reopen re-occupies the slot and re-derives both counters."
    PRD §2.6: "A derived field is a mutation: re-deriving `open_slot_count`,
    `billing_posture`, `benefit_status` or a provider's aggregate counters
    refreshes `updated_at` and increments `version`."

    Design: Corner/cross_cutting_complexity_layers/session_reopen_restores_the_recomputed_slot_counter
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(
        payer["id"],
        availability_blocks=[{"weekday": 3, "start_minute": 960, "end_minute": 1020}],
    )["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    assert get_clinician(clinician["id"])["open_slot_count"] == 0, (
        "the 60-minute booking exactly consumes the single 60-minute block"
    )

    set_clock("2026-06-03T18:00:00Z")
    complete_session(clinician["id"], session["id"])
    assert get_clinician(clinician["id"])["open_slot_count"] == 1
    assert get_patient(patient["id"])["visit_count_year"] == 1

    validate_success(api_client.reopen_session(session["id"], OPS))
    assert get_clinician(clinician["id"])["open_slot_count"] == 0, (
        "the reopen reproduces the pre-completion value exactly"
    )
    assert get_session(session["id"])["slot_consumed"] is True
    assert get_patient(patient["id"])["visit_count_year"] == 0


def test_submitting_the_same_session_twice_does_not_duplicate_the_claim():
    """PRD §3.5: "A successful submission creates the claim, stamps `submitted_on`
    from the logical clock, inherits the patient's payer and the session's
    clinician onto the claim, moves the claim through its initial `DRAFT` state to
    `SUBMITTED`, and at the same time advances the session's parallel billing axis
    to `CLAIM_SUBMITTED` and records the claim's identifier as the session's
    `claim_id`."

    Design: Corner/cross_cutting_complexity_layers/submitting_the_same_session_twice_returns_invalid_state_rather_than_duplicating_a_claim
    """
    set_clock(CLOCK_EARLY)
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

    first = validate_success(api_client.create_claim({"session_id": session["id"]}, OPS), 201)
    assert first["claim_status"] == "SUBMITTED"

    second = api_client.create_claim({"session_id": session["id"]}, OPS)
    error = validate_error(second, ApiErrorId.ERR_INVALID_STATE)
    assert second.status_code == 409
    assert error["error_id"] != ApiErrorId.ERR_INVALID_REQUEST.value

    claims, meta = validate_paginated(
        api_client.list_claims(OPS, {"session_id": session["id"], "limit": 10, "offset": 0})
    )
    assert len(claims) == 1 and meta["total_count"] == 1
    row = get_session(session["id"])
    assert row["claim_id"] == first["id"]
    assert row["billing_state"] == "CLAIM_SUBMITTED"


def test_a_denial_against_a_locked_line_deflates_it_without_un_paying_it():
    """PRD §3.6: "a line that was already paid keeps its `gross_cents` and shows
    the reversal in `adjustment_cents` rather than having its gross rewritten."
    PRD §3.6: "A line whose adjustment falls below zero becomes `CLAWED_BACK`
    only if it was already `PAID`; a line that is still `PENDING` keeps its
    `PENDING` status and simply has its net floored at zero."

    Design: Corner/consistency_model/a_regression_recomputed_denial_corrects_the_previously_committed_line
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
    claim = submit_claim(session["id"])
    adjudicate(claim["id"], "PAID")

    set_clock("2026-06-09T00:00:00Z")
    batch = open_and_lock_batch("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z", "WEEKLY")
    lines = get_batch_lines(batch["id"])
    assert lines[0]["line_status"] == "PENDING"
    assert lines[0]["net_cents"] == 15_000
    assert lines[0]["gross_cents"] == 15_000

    validate_success(
        api_client.adjudicate_claim(
            claim["id"], {"outcome": "DENIED", "denial_code": "DUPLICATE"}, OPS
        )
    )
    after = get_batch_lines(batch["id"])
    assert after[0]["line_status"] == "PENDING", (
        "the floor keeps the status unchanged, because the line was never paid"
    )
    assert after[0]["net_cents"] == 0
    assert after[0]["adjustment_cents"] == -15_000
    assert after[0]["gross_cents"] == 15_000, (
        "the compensation deflates the line rather than un-paying it"
    )
    assert_payout_line(after[0])
    assert get_session(session["id"])["billing_state"] == "DENIED"

    frozen = get_batch(batch["id"])
    assert frozen["total_net_cents"] == 15_000, (
        "totals were frozen as a snapshot at lock time"
    )
    assert frozen["status"] == "LOCKED"
    assert_payout_batch(frozen)


def test_a_failed_lock_leaves_no_partial_line_set_and_a_later_attempt_materializes_all_of_it():
    """PRD §3.6: "At lock time the system materialises one line per clinician who
    has at least one eligible session in the window"
    PRD §3.6: "locking before the period closes, from a status other than `OPEN`,
    or with no non-voided lines is refused with `ERR_BATCH_NOT_LOCKABLE`."

    Design: Corner/consistency_model/a_rejected_slice_leaves_the_period_open_with_no_partial_lines
    """
    set_clock(CLOCK_EARLY)
    payer = make_payer()
    make_rate(payer["id"], rate_cents=15_000)
    clinician = attach_billable_clinician(payer["id"])["clinician"]
    patient = make_verified_patient(payer["id"])
    session = make_scheduled_session(
        clinician["id"], patient["id"], "2026-06-03T16:00:00Z", "2026-06-03T17:00:00Z"
    )
    add_signed_note(clinician["id"], session["id"])
    set_clock("2026-06-03T18:00:00Z")
    complete_session(clinician["id"], session["id"])

    set_clock("2026-06-05T00:00:00Z")
    batch = validate_success(
        api_client.create_payout_batch(
            {
                "period_start": "2026-06-01T00:00:00Z",
                "period_end": "2026-06-08T00:00:00Z",
                "schedule": "WEEKLY",
            },
            OPS,
        ),
        201,
    )
    early = api_client.lock_payout_batch(batch["id"], OPS)
    validate_error(early, ApiErrorId.ERR_BATCH_NOT_LOCKABLE)

    lines, meta = validate_paginated(
        api_client.list_payout_batch_lines(batch["id"], OPS, {"limit": 10, "offset": 0})
    )
    assert lines == [] and meta["total_count"] == 0, (
        "no partial materialization occurred"
    )
    row = get_batch(batch["id"])
    assert row["status"] == "OPEN"
    assert row["total_net_cents"] == 0

    set_clock("2026-06-08T00:00:00Z")
    locked = validate_success(api_client.lock_payout_batch(batch["id"], OPS))
    assert locked["line_count"] == 1
    assert locked["total_net_cents"] == 15_000
    assert len(get_batch_lines(batch["id"])) == 1, (
        "the single attempt produced the complete line set, with no stranded line"
    )