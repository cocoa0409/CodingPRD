"""Validation rules: severity gates, observation floors, hour floors and risk ceilings."""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    get_success_data,
    setup_failed_item_with_defect,
    setup_program_facility_department,
    setup_epoch_scoped_build_item,
    create_build_item_payload,
    create_credentialed_trainer_payload,
    create_staff_payload,
    create_training_assignment_payload,
    make_credentialed_trainer_headers,
    set_clock,
    BUILD_ANALYST,
    TEST_LEAD,
    TRAINING,
)


# ===========================================================================
# c_sev1_defect_cannot_be_deferred
# ===========================================================================

def test_deferring_a_blocking_severity_defect_is_refused(api, build_analyst_headers, test_lead_headers):
    """PRD §3.5: "a `TestLead` may defer a defect only when its severity is `SEV3`
    or `SEV4`, and a deferral attempt on a `SEV1` or `SEV2` defect is refused with
    `ERR_DEFECT_SEVERITY_NOT_DEFERRABLE` (HTTP 422)."
    PRD §3.5: "A `BuildAnalyst` begins remediation, moving the defect from `OPEN`
    to `IN_REMEDIATION`".

    Design: Corner/validations/c_sev1_defect_cannot_be_deferred
    """
    ctx = setup_failed_item_with_defect(severity="SEV1", defect_code="LBL-6001")
    remediating = validate_success(
        api.begin_remediation(ctx["defect"]["id"], build_analyst_headers), 200
    )
    assert remediating["status"] == "IN_REMEDIATION"

    refused = api_client.defer_defect(ctx["defect"]["id"], test_lead_headers)
    validate_error(refused, ApiErrorId.ERR_DEFECT_SEVERITY_NOT_DEFERRABLE, expected_status=422)


def test_the_refused_deferral_leaves_the_blocking_defect_in_remediation(api, build_analyst_headers, test_lead_headers):
    """PRD §3.5: "Severity also drives the `blocks_go_live` flag, which is true
    precisely while the severity is `SEV1` or `SEV2` and the defect has not
    reached `RESOLVED`".
    PRD §2.11: "the target must be in the exact from-state of the transition
    being triggered (otherwise `ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/validations/c_sev1_defect_cannot_be_deferred
    """
    ctx = setup_failed_item_with_defect(severity="SEV1", defect_code="LBL-6001")
    get_success_data(api.begin_remediation(ctx["defect"]["id"], build_analyst_headers))
    api_client.defer_defect(ctx["defect"]["id"], test_lead_headers)

    read = validate_success(api_client.get_test_defect(ctx["defect"]["id"], test_lead_headers), 200)
    assert read["status"] == "IN_REMEDIATION"
    assert read["blocks_go_live"] is True


# ===========================================================================
# c_deferring_sev4_defect_succeeds
# ===========================================================================

def test_the_same_defer_endpoint_accepts_a_non_blocking_severity(api, build_analyst_headers, test_lead_headers):
    """PRD §3.5: "a `TestLead` may defer a defect only when its severity is `SEV3`
    or `SEV4`".
    PRD §3.5: "Severity also drives the `blocks_go_live` flag, which is true
    precisely while the severity is `SEV1` or `SEV2` and the defect has not
    reached `RESOLVED`".

    Design: Corner/validations/c_deferring_sev4_defect_succeeds
    """
    ctx = setup_failed_item_with_defect(severity="SEV4", defect_code="LBL-6002")
    get_success_data(api.begin_remediation(ctx["defect"]["id"], build_analyst_headers))

    deferred = validate_success(api_client.defer_defect(ctx["defect"]["id"], test_lead_headers), 200)
    assert deferred["status"] == "DEFERRED"


def test_a_deferred_non_blocking_defect_carries_no_go_live_flag(api, build_analyst_headers, test_lead_headers):
    """PRD §3.5: "Severity also drives the `blocks_go_live` flag, which is true
    precisely while the severity is `SEV1` or `SEV2` and the defect has not
    reached `RESOLVED`".
    PRD §3.5: "The defect's status vocabulary is `OPEN`, `IN_REMEDIATION`,
    `RESOLVED`, `DEFERRED` and `REOPENED`."

    Design: Corner/validations/c_deferring_sev4_defect_succeeds
    """
    ctx = setup_failed_item_with_defect(severity="SEV4", defect_code="LBL-6002")
    get_success_data(api.begin_remediation(ctx["defect"]["id"], build_analyst_headers))
    api_client.defer_defect(ctx["defect"]["id"], test_lead_headers)

    read = validate_success(api_client.get_test_defect(ctx["defect"]["id"], test_lead_headers), 200)
    assert read["blocks_go_live"] is False


# ===========================================================================
# c_retest_before_cooldown_returns_retest_cooldown_active
# ===========================================================================

def _proctor_with_running_cooldown():
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Bianca Reyes"),
        TRAINING,
    ))
    trainer = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            staff["version"], application_code="CLN", observation_hours=8
        ),
        TRAINING,
    ))
    get_success_data(api_client.certify_trainer(trainer["id"], TRAINING))
    exam1 = get_success_data(api_client.schedule_exam(
        staff["id"], {"application_code": "CLN", "proctored_by_trainer_id": trainer["id"]}, TRAINING
    ))
    failed = get_success_data(api_client.record_exam_result(
        exam1["id"], {"exam_score": 55},
        make_credentialed_trainer_headers(trainer["id"]),
    ))
    exam2 = get_success_data(api_client.schedule_exam(
        staff["id"], {"application_code": "CLN", "proctored_by_trainer_id": trainer["id"]}, TRAINING
    ))
    return {"prog": prog, "fac": fac, "dept": dept, "staff": staff,
            "trainer": trainer, "exam1": exam1, "exam2": exam2,
            "cooldown_until": failed["next_attempt_eligible_utc"]}


def test_recording_a_retake_before_the_cooldown_elapses_is_refused(api, training_headers):
    """PRD §2.13: "A failed attempt sets the `next_attempt_eligible_utc` cooldown
    instant, and no retake may be recorded before the logical clock reaches it
    (`ERR_RETEST_COOLDOWN_ACTIVE`, HTTP 409)."
    PRD §3.4: "A score below 80 moves the exam to `COMPLETED_FAIL`, sets
    `next_attempt_eligible_utc` to the logical clock plus the retest cooldown,
    and likewise refreshes the department ratio."

    Design: Corner/validations/c_retest_before_cooldown_returns_retest_cooldown_active
    """
    ctx = _proctor_with_running_cooldown()
    assert ctx["cooldown_until"] is not None

    refused = api.record_exam_result(
        ctx["exam2"]["id"], {"exam_score": 90},
        make_credentialed_trainer_headers(ctx["trainer"]["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_RETEST_COOLDOWN_ACTIVE, expected_status=409)


def test_advancing_the_clock_past_the_cooldown_lets_the_retake_post(api, training_headers, director_headers):
    """PRD §2.13: "no retake may be recorded before the logical clock reaches it
    (`ERR_RETEST_COOLDOWN_ACTIVE`, HTTP 409)."
    PRD §2.13: "An exam is passed at a `passing_score` of 80: a recorded
    `exam_score` of exactly 80 passes, and any score below 80 fails."

    Design: Corner/validations/c_retest_before_cooldown_returns_retest_cooldown_active
    """

    ctx = _proctor_with_running_cooldown()
    api.record_exam_result(
        ctx["exam2"]["id"], {"exam_score": 90},
        make_credentialed_trainer_headers(ctx["trainer"]["id"]),
    )

    still_scheduled = validate_success(
        api.get_proficiency_exam(ctx["exam2"]["id"], training_headers), 200
    )
    assert still_scheduled["status"] == "SCHEDULED"

    set_clock(ctx["cooldown_until"])
    passed = validate_success(
        api.record_exam_result(
            ctx["exam2"]["id"], {"exam_score": 90},
            make_credentialed_trainer_headers(ctx["trainer"]["id"]),
        ),
        200,
    )
    assert passed["status"] == "COMPLETED_PASS"


# ===========================================================================
# c_trainer_observation_below_floor_returns_422
# ===========================================================================

def test_certifying_on_too_few_observation_hours_is_refused(api, training_headers):
    """PRD §2.13: "A `CredentialedTrainer` may only be certified, or recertified
    after expiry, when the recorded `observation_hours` meets the minimum
    observation requirement of the requested `certification_level`; a shortfall is
    refused with `ERR_TRAINER_OBSERVATION_INSUFFICIENT` (HTTP 422)."
    PRD §2.13: "The `certification_level` is exactly one of `STANDARD` or
    `ADVANCED`."

    Design: Corner/validations/c_trainer_observation_below_floor_returns_422
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Dana Whitfield"),
        TRAINING,
    ))
    trainer = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            staff["version"], application_code="CLN", certification_level="STANDARD",
            observation_hours=3,
        ),
        TRAINING,
    ))

    refused = api_client.certify_trainer(trainer["id"], training_headers)
    validate_error(refused, ApiErrorId.ERR_TRAINER_OBSERVATION_INSUFFICIENT, expected_status=422)


def test_the_under_observed_trainer_record_stays_pending(api, training_headers):
    """PRD §3.4: "The record begins in `PENDING_OBSERVATION`. Its status
    vocabulary is `PENDING_OBSERVATION`, `CERTIFIED`, `EXPIRED` and `REVOKED`."
    PRD §2.13: "a shortfall is refused with
    `ERR_TRAINER_OBSERVATION_INSUFFICIENT` (HTTP 422)."

    Design: Corner/validations/c_trainer_observation_below_floor_returns_422
    """
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Dana Whitfield"),
        TRAINING,
    ))
    trainer = get_success_data(api_client.create_credentialed_trainer(
        staff["id"],
        create_credentialed_trainer_payload(
            staff["version"], observation_hours=3
        ),
        TRAINING,
    ))
    api_client.certify_trainer(trainer["id"], training_headers)

    read = validate_success(api_client.get_credentialed_trainer(trainer["id"], training_headers), 200)
    assert read["status"] == "PENDING_OBSERVATION"


# ===========================================================================
# c_local_custom_build_over_risk_limit_blocks_validation
# ===========================================================================

def test_a_locally_customised_item_over_the_risk_limit_cannot_close_validation(api, build_analyst_headers, test_lead_headers):
    """PRD §2.12: "a `LOCAL_CUSTOM` build item whose `customization_risk_points`
    exceeds 40.00 is not admissible to advance either out of build or out of
    validation without a remediation record, and the attempt is refused with
    `ERR_CUSTOMIZATION_LIMIT_EXCEEDED` (HTTP 422)."
    PRD §3.3: "closing validation requires that at least one test scenario has
    passed in the current epoch".

    The item scores 92.00 with its scenario already passed, so the ceiling is the
    only thing standing between it and VALIDATION_COMPLETE.

    Design: Corner/validations/c_local_custom_build_over_risk_limit_blocks_validation
    """
    ctx = setup_epoch_scoped_build_item(application_code="LAB")
    # Rebuild the item with the over-limit customization profile.
    item = get_success_data(api_client.create_build_item(
        ctx["dept"]["id"],
        create_build_item_payload(
            application_code="LAB", build_classification="LOCAL_CUSTOM",
            customization_depth=2,
            local_custom_fields=[f"CF{n:02d}" for n in range(1, 13)],
        ),
        build_analyst_headers,
    ))
    scenario = get_success_data(api_client.create_test_scenario(
        item["id"], {"scenario_class": "UNIT", "step_count": 6}, test_lead_headers
    ))
    # PRD §2.12: "a LOCAL_CUSTOM build item whose customization_risk_points
    # exceeds 40.00 is not admissible to advance either out of build or out of
    # validation". The ceiling is published as soon as the item exists, so
    # starting build work is the first rung it guards.
    assert item["customization_risk_points"] == pytest.approx(92.00, abs=0.01)

    refused = api_client.start_build_item(item["id"], build_analyst_headers)
    validate_error(refused, ApiErrorId.ERR_CUSTOMIZATION_LIMIT_EXCEEDED, expected_status=422)
    assert scenario is not None


def test_the_over_limit_item_stays_in_testing_after_the_refused_validation(api, build_analyst_headers, test_lead_headers):
    """PRD §2.12: "Completing a build item's build work scores that customization
    into `customization_risk_points`, and the score is a signal the organization
    treats as a control: a `LOCAL_CUSTOM` build item whose
    `customization_risk_points` exceeds 40.00 is not admissible to advance either
    out of build or out of validation without a remediation record".
    PRD §3.3: "The item's status vocabulary is `DRAFT`, `IN_BUILD`,
    `BUILD_COMPLETE`, `IN_TESTING`, `VALIDATION_COMPLETE` and the rejection state
    `BUILD_REJECTED`."

    Design: Corner/validations/c_local_custom_build_over_risk_limit_blocks_validation
    """
    ctx = setup_epoch_scoped_build_item(application_code="LAB")
    item = get_success_data(api_client.create_build_item(
        ctx["dept"]["id"],
        create_build_item_payload(
            application_code="LAB", build_classification="LOCAL_CUSTOM",
            customization_depth=2,
            local_custom_fields=[f"CF{n:02d}" for n in range(1, 13)],
        ),
        build_analyst_headers,
    ))
    api_client.start_build_item(item["id"], build_analyst_headers)

    read = validate_success(api_client.get_build_item(item["id"], test_lead_headers), 200)
    assert read["status"] == "DRAFT", "the refused advance left the item where it was"
    assert read["customization_risk_points"] == pytest.approx(92.00, abs=0.01)


# ===========================================================================
# c_completing_assignment_below_required_hours_returns_422
# ===========================================================================

def _assignment_with_half_the_hours():
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Elias Moreau"),
        TRAINING,
    ))
    assignment = get_success_data(api_client.create_training_assignment(
        staff["id"], create_training_assignment_payload(required_hours=40), TRAINING
    ))
    logged = get_success_data(api_client.log_hours(assignment["id"], {"hours": 20}, TRAINING))
    return {"prog": prog, "fac": fac, "dept": dept, "staff": staff,
            "assignment": assignment, "logged": logged}


def test_completing_an_assignment_short_of_its_hours_is_refused(api, training_headers):
    """PRD §3.4: "Completing an assignment requires that `completed_hours` have
    reached `required_hours` — a shortfall is refused with
    `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422) — and completes the assignment".
    PRD §3.4: "The same call recomputes `completion_pct` as 100 multiplied by
    `completed_hours` divided by `required_hours`, capped at 100, and moves the
    assignment to `IN_PROGRESS`."

    Design: Corner/validations/c_completing_assignment_below_required_hours_returns_422
    """
    ctx = _assignment_with_half_the_hours()
    assert ctx["logged"]["status"] == "IN_PROGRESS"
    assert ctx["logged"]["completion_pct"] == pytest.approx(50.00, abs=0.01)

    refused = api_client.complete_assignment(ctx["assignment"]["id"], training_headers)
    validate_error(refused, ApiErrorId.ERR_TRAINING_HOURS_INSUFFICIENT, expected_status=422)


def test_topping_up_the_hours_lets_the_same_assignment_complete(api, training_headers):
    """PRD §3.4: "Logging is admissible from either `ASSIGNED` or `IN_PROGRESS`,
    so an assignment may be topped up over several calls."
    PRD §3.4: "Completing an assignment requires that `completed_hours` have
    reached `required_hours` — a shortfall is refused with
    `ERR_TRAINING_HOURS_INSUFFICIENT` (HTTP 422) — and completes the assignment,
    which in turn recomputes the staff member's `accumulated_training_hours`."

    Design: Corner/validations/c_completing_assignment_below_required_hours_returns_422
    """
    ctx = _assignment_with_half_the_hours()
    api_client.complete_assignment(ctx["assignment"]["id"], training_headers)

    still_open = validate_success(
        api_client.get_training_assignment(ctx["assignment"]["id"], training_headers), 200
    )
    assert still_open["status"] == "IN_PROGRESS"

    get_success_data(api_client.log_hours(ctx["assignment"]["id"], {"hours": 20}, TRAINING))
    completed = validate_success(api_client.complete_assignment(ctx["assignment"]["id"], training_headers), 200)
    assert completed["status"] == "COMPLETED"