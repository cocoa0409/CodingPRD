"""Priority pairs: two rungs of the ladder could reject one request.

Each instance presents a single request that violates two rules at once and
pins which rung the error comes from.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    get_success_data,
    get_program,
    setup_program_and_facility,
    setup_program_facility_department,
    create_conversion_batch,
    create_credentialed_trainer_payload,
    create_proficiency_exam_payload,
    create_patient_order_payload,
    create_staff_payload,
    make_credentialed_trainer_headers,
    CONVERSION,
    RECONCILER,
    REVENUE,
    TRAINING,
    ANALYST,
    DIRECTOR,
)


# ===========================================================================
# r5a_state_precedes_safety_on_submit_claim
# ===========================================================================

def test_submitting_a_claim_on_an_unposted_order_reports_the_state_error(api, conversion_headers, revenue_headers):
    """PRD §2.11: "The ladder then moves through state: the target must be in the
    exact from-state of the transition being triggered (otherwise
    `ERR_INVALID_STATE`, HTTP 409)".
    PRD §3.8: "A charge may be submitted as a claim once the order is in billing
    state `CHARGE_POSTED` and its clinical state is `RECONCILED`; this is the
    point at which the clinical and billing dimensions must converge, and
    submitting a claim on an order that has not been clinically reconciled is
    refused with `ERR_ORDER_NOT_RECONCILED` (HTTP 422)."

    The order is neither charged nor reconciled, so both rungs fail; the state
    rung is earlier, so ERR_INVALID_STATE is reported.

    Design: Difficulty/priority_pair_validation_conflict/r5a_state_precedes_safety_on_submit_claim
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-6001", order_type="LAB",
            encounter_utc="2026-08-27T00:00:00Z", legacy_charge_cents=10000,
        ),
        conversion_headers,
    ))

    refused = api.submit_claim(order["id"], revenue_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert refused.json()["data"]["error_id"] != "ERR_ORDER_NOT_RECONCILED", (
        "the clinical-safety rung is later in the ladder and must not mask the state rung"
    )


def test_the_refused_claim_submission_leaves_both_dimensions_untouched(api, conversion_headers, revenue_headers, analyst_headers):
    """PRD §2.11: "The ladder then moves through state: the target must be in the
    exact from-state of the transition being triggered (otherwise
    `ERR_INVALID_STATE`, HTTP 409)".
    PRD §3.7: "The order starts in clinical state `CONVERTED` and billing state
    `UNPOSTED`".

    Design: Difficulty/priority_pair_validation_conflict/r5a_state_precedes_safety_on_submit_claim
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-6001", order_type="LAB",
            encounter_utc="2026-08-27T00:00:00Z", legacy_charge_cents=10000,
        ),
        conversion_headers,
    ))
    api.submit_claim(order["id"], revenue_headers)

    read = validate_success(api.get_patient_order(order["id"], analyst_headers), 200)
    assert read["billing_state"] == "UNPOSTED", "the failed request changed nothing"
    assert read["clinical_state"] == "CONVERTED"


# ===========================================================================
# r5b_state_precedes_fiscal_on_batch_load
# ===========================================================================

def test_loading_a_stale_epoch_batch_reports_the_epoch_error(api, conversion_headers):
    """PRD §2.11: "a conversion batch's `attempt_epoch` must equal the program's
    `current_epoch_index` (otherwise `ERR_EPOCH_MISMATCH`, HTTP 409)."
    PRD §3.2: "A batch whose penalty exceeds its ceiling is refused with
    `ERR_BALANCE_VARIANCE_EXCEEDED` (HTTP 422)".
    PRD §3.2: "Beginning validation requires the batch's `attempt_epoch` to equal
    the program's `current_epoch_index`".

    The batch is validated at epoch 0 with a 10 percent variance and the program
    then advances to epoch 1, so both the epoch rule and the fiscal cap fail on
    the load; the epoch rung is earlier, so ERR_EPOCH_MISMATCH is reported.

    Design: Difficulty/priority_pair_validation_conflict/r5b_state_precedes_fiscal_on_batch_load
    """
    prog, fac = setup_program_and_facility()
    batch = create_conversion_batch(
        fac["id"], payload_class="PATIENT_DEMOGRAPHICS", attempt_epoch=0,
        source_count=1000, reconciled_count=900,
        expected_facility_version=fac["version"],
    )
    validated = validate_success(api.begin_batch_validation(batch["id"], conversion_headers), 200)
    assert validated["variance_penalty_points"] == pytest.approx(10.00, abs=0.01), (
        "10 percent also breaches the PATIENT_DEMOGRAPHICS cap"
    )

    advanced = validate_success(api.advance_epoch(prog["id"], DIRECTOR), 200)
    assert advanced["current_epoch_index"] == 1

    refused = api.load_batch(batch["id"], conversion_headers)
    validate_error(refused, ApiErrorId.ERR_EPOCH_MISMATCH, expected_status=409)
    assert refused.json()["data"]["error_id"] != "ERR_BALANCE_VARIANCE_EXCEEDED"


def test_the_refused_stale_load_leaves_the_batch_in_validating(api, conversion_headers):
    """PRD §2.11: "a conversion batch's `attempt_epoch` must equal the program's
    `current_epoch_index` (otherwise `ERR_EPOCH_MISMATCH`, HTTP 409)."
    PRD §3.2: "A batch begins in `STAGED` and moves through `VALIDATING`,
    `LOADED` and `RECONCILED`, with `FAILED` and `ROLLED_BACK` as its other
    terminal outcomes."

    Design: Difficulty/priority_pair_validation_conflict/r5b_state_precedes_fiscal_on_batch_load
    """
    prog, fac = setup_program_and_facility()
    batch = create_conversion_batch(
        fac["id"], payload_class="PATIENT_DEMOGRAPHICS", attempt_epoch=0,
        source_count=1000, reconciled_count=900,
        expected_facility_version=fac["version"],
    )
    get_success_data(api.begin_batch_validation(batch["id"], conversion_headers))
    api.advance_epoch(prog["id"], DIRECTOR)
    api.load_batch(batch["id"], conversion_headers)

    read = validate_success(api.get_conversion_batch(batch["id"], conversion_headers), 200)
    assert read["status"] == "VALIDATING", "the refused load must not advance the batch"


# ===========================================================================
# r5c_constraint_precedes_temporal_on_unverified_proctor
# ===========================================================================

def _revoked_proctor_with_cooldown():
    """A staffer whose trainer proctor was revoked while a retake cooldown runs."""
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Nina Okafor"),
        TRAINING,
    ))
    trainer = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            staff["version"], application_code="CLN", certification_level="STANDARD",
            observation_hours=8,
        ),
        TRAINING,
    ))
    get_success_data(api_client.certify_trainer(trainer["id"], TRAINING))

    exam1 = get_success_data(api_client.schedule_exam(
        staff["id"], create_proficiency_exam_payload(trainer["id"], application_code="CLN"), TRAINING
    ))
    failed = get_success_data(api_client.record_exam_result(
        exam1["id"], {"exam_score": 60}, make_credentialed_trainer_headers(trainer["id"])
    ))
    get_success_data(api_client.revoke_trainer(trainer["id"], TRAINING))
    exam2 = get_success_data(api_client.schedule_exam(
        staff["id"], create_proficiency_exam_payload(trainer["id"], application_code="CLN"), TRAINING
    ))
    return {
        "prog": prog, "fac": fac, "dept": dept, "staff": staff, "trainer": trainer,
        "exam1": exam1, "exam2": exam2, "cooldown_until": failed["next_attempt_eligible_utc"],
    }


def test_a_revoked_proctors_recording_reports_the_credential_error(api, training_headers):
    """PRD §2.10: "The proctor of record must hold a `CredentialedTrainer` row
    whose `status` is `CERTIFIED` for the exam's `application_code`; otherwise
    the recording attempt is refused with `ERR_UNVERIFIED_TRAINER` (HTTP 403)."
    PRD §2.13: "A failed attempt sets the `next_attempt_eligible_utc` cooldown
    instant, and no retake may be recorded before the logical clock reaches it
    (`ERR_RETEST_COOLDOWN_ACTIVE`, HTTP 409)."

    Both the revoked credential and the running cooldown would refuse this
    retake; the credential rung is earlier, so ERR_UNVERIFIED_TRAINER is
    reported.

    Design: Difficulty/priority_pair_validation_conflict/r5c_constraint_precedes_temporal_on_unverified_proctor
    """
    ctx = _revoked_proctor_with_cooldown()

    refused = api.record_exam_result(
        ctx["exam2"]["id"], {"exam_score": 90},
        make_credentialed_trainer_headers(ctx["trainer"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_UNVERIFIED_TRAINER, expected_status=403)
    assert refused.json()["data"]["error_id"] != "ERR_RETEST_COOLDOWN_ACTIVE"


def test_the_refused_retake_leaves_the_second_exam_scheduled(api, training_headers):
    """PRD §2.13: "A failed attempt sets the `next_attempt_eligible_utc` cooldown
    instant, and no retake may be recorded before the logical clock reaches it
    (`ERR_RETEST_COOLDOWN_ACTIVE`, HTTP 409)."
    PRD §3.4: "Its status vocabulary is `SCHEDULED`, `COMPLETED_PASS`,
    `COMPLETED_FAIL` and `NO_SHOW`, and `passing_score` is fixed at 80."

    Design: Difficulty/priority_pair_validation_conflict/r5c_constraint_precedes_temporal_on_unverified_proctor
    """
    ctx = _revoked_proctor_with_cooldown()
    api.record_exam_result(
        ctx["exam2"]["id"], {"exam_score": 90},
        make_credentialed_trainer_headers(ctx["trainer"]["id"]),
    )

    read = validate_success(api.get_proficiency_exam(ctx["exam2"]["id"], training_headers), 200)
    assert read["status"] == "SCHEDULED", "the refused retake must not be recorded"
    assert ctx["cooldown_until"] is not None, "the failed first attempt set a cooldown instant"