"""Cross-entity state dependencies: a parent's legal move depends on its children.

Covers facility validation gated on its departments, and shift activation gated
on the assigned staffer's credential.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    get_success_data,
    get_department,
    get_facility,
    get_staff,
    setup_department_with_cleared_staff,
    setup_credentialed_staff,
    create_credentialed_trainer_payload,
    create_proficiency_exam_payload,
    create_staff_payload,
    create_staffing_shift_payload,
    create_training_assignment_payload,
    make_credentialed_trainer_headers,
    setup_program_facility_department,
    set_clock,
    create_program,
    create_facility,
    create_department,
    TRAINING,
    BUILD_ANALYST,
    COMMAND_CENTER,
    DIRECTOR,
    ANALYST,
    TEST_LEAD,
)


# ===========================================================================
# r7a_facility_validation_requires_department_gate_and_defects_clear
# ===========================================================================

def test_facility_mark_validated_succeeds_when_every_department_gate_is_open(api, analyst_headers, director_headers):
    """PRD §3.2: "a facility may be marked validated only when every one of its
    departments has an open proficiency gate (`proficiency_gate_open` true), when
    every one of its departments has a `build_blocking_defect_count` of 0, and
    when the program's posture is `OPEN`."
    PRD §3.4: "an open blocking defect is refused with
    `ERR_DEFECT_BLOCKS_DEPARTMENT`."

    Design: Difficulty/cross_entity_state_dependency/r7a_facility_validation_requires_department_gate_and_defects_clear
    """
    ctx = setup_department_with_cleared_staff(
        application_code="CLN", required_staff_count=1, cleared_count=1,
        department_code="CLN", close_gate=True, configure_facility=True,
    )

    dept = get_department(ctx["dept"]["id"], analyst_headers)
    assert dept["status"] == "READY_FOR_GO_LIVE"
    assert dept["proficiency_gate_open"] is True
    assert dept["build_blocking_defect_count"] == 0

    validated = validate_success(api.mark_validated(ctx["fac"]["id"], director_headers), 200)
    assert validated["status"] == "VALIDATED"


def test_the_same_facility_call_is_refused_while_a_department_gate_stays_closed(api, analyst_headers, director_headers):
    """PRD §3.2: "a facility may be marked validated only when every one of its
    departments has an open proficiency gate (`proficiency_gate_open` true), when
    every one of its departments has a `build_blocking_defect_count` of 0, and
    when the program's posture is `OPEN`."
    PRD §3.2: "The facility status vocabulary is `SITE_REGISTERED`,
    `BUILD_CONFIGURED`, `REMEDIATION_REQUIRED`, `VALIDATED`, `CUTOVER_READY`,
    `LIVE`, `STABILIZED` and `STABILIZATION_AT_RISK`."

    A companion department with no cleared staffers keeps its gate closed, so the
    facility's transition past BUILD_CONFIGURED is inadmissible and the facility
    stays where it is.

    Design: Difficulty/cross_entity_state_dependency/r7a_facility_validation_requires_department_gate_and_defects_clear
    """
    ctx = setup_department_with_cleared_staff(
        application_code="CLN", required_staff_count=1, cleared_count=1,
        department_code="CLN", close_gate=True, configure_facility=True,
    )
    # A second department that has never been trained keeps the facility ineligible.
    create_department(
        ctx["fac"]["id"], department_code="UNCLEARED",
        application_scope=["CLN"], required_staff_count=4,
    )

    refused = api.mark_validated(ctx["fac"]["id"], director_headers)
    assert refused.status_code >= 400, (
        "a facility whose departments are not all gate-open cannot be marked validated"
    )

    facility = get_facility(ctx["fac"]["id"], analyst_headers)
    assert facility["status"] == "BUILD_CONFIGURED", "the refused call changed nothing"


# ===========================================================================
# r7b_shift_activation_requires_staff_credentialed
# ===========================================================================

def _staffer_verified_but_not_credentialed():
    """A program, facility, department and one proficiency-verified staffer."""
    set_clock()
    prog = create_program()
    fac = create_facility(prog["id"])
    dept = create_department(
        fac["id"], department_code="CLN", application_scope=["CLN"], required_staff_count=1
    )
    item = get_success_data(api_client.create_build_item(
        dept["id"],
        {"application_code": "CLN", "build_classification": "FOUNDATION_ADOPTED",
         "customization_depth": 1, "local_custom_fields": []},
        BUILD_ANALYST,
    ))
    # PRD §3.3: "Closing the department's build requires that at least one of its
    # build items has reached `BUILD_COMPLETE`, `IN_TESTING` or
    # `VALIDATION_COMPLETE`". The close is issued only once the item has reached
    # one of those states; an item still in DRAFT is not a satisfied precondition.
    get_success_data(api_client.start_build_item(item["id"], BUILD_ANALYST))
    get_success_data(api_client.complete_build_item(item["id"], BUILD_ANALYST))
    get_success_data(api_client.complete_department_build(dept["id"], BUILD_ANALYST))
    get_success_data(api_client.begin_training(dept["id"], TRAINING))

    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Ward Nurse",
                             staff_type="REGISTRATION"),
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
    assignment = get_success_data(api_client.create_training_assignment(
        staff["id"], create_training_assignment_payload(), TRAINING
    ))
    get_success_data(api_client.log_hours(assignment["id"], {"hours": 40}, TRAINING))
    get_success_data(api_client.complete_assignment(assignment["id"], TRAINING))
    exam = get_success_data(api_client.schedule_exam(
        staff["id"], create_proficiency_exam_payload(trainer["id"]), TRAINING
    ))
    get_success_data(api_client.record_exam_result(
        exam["id"], {"exam_score": 90}, make_credentialed_trainer_headers(trainer["id"])
    ))
    return {"prog": prog, "fac": fac, "dept": dept, "staff": get_staff(staff["id"]), "trainer": trainer}


def test_activating_a_shift_for_a_merely_verified_staffer_reports_invalid_state(api, command_center_headers):
    """PRD §3.10: "Activating a shift requires that the shift is `SCHEDULED`,
    that the logical clock has reached its `start_utc`, and that the assigned
    staff member holds `CREDENTIALED` status — an uncredentialed person cannot
    staff the command center."
    PRD §2.11: "the target must be in the exact from-state of the transition
    being triggered (otherwise `ERR_INVALID_STATE`, HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/r7b_shift_activation_requires_staff_credentialed
    """
    ctx = _staffer_verified_but_not_credentialed()
    assert ctx["staff"]["status"] == "PROFICIENCY_VERIFIED"

    set_clock("2026-09-02T00:00:00Z")
    shift = get_success_data(api_client.create_shift(
        create_staffing_shift_payload(
            ctx["staff"]["id"], ctx["fac"]["id"], support_role="AT_THE_ELBOW",
            start_utc="2026-09-02T06:00:00Z", end_utc="2026-09-02T14:00:00Z",
        ),
        command_center_headers,
    ))
    # PRD §3.10: "Activating a shift requires that the shift is SCHEDULED, that
    # the logical clock has reached its start_utc, and that the assigned staff
    # member holds CREDENTIALED status". The clock rung is satisfied first so the
    # credential rung is the one the attempt lands on.
    set_clock("2026-09-02T06:00:00Z")

    refused = api.activate_shift(shift["id"], command_center_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_issuing_the_credential_lets_the_same_shift_activate(api, command_center_headers, training_headers):
    """PRD §3.10: "Activating a shift requires that the shift is `SCHEDULED`,
    that the logical clock has reached its `start_utc`, and that the assigned
    staff member holds `CREDENTIALED` status — an uncredentialed person cannot
    staff the command center."
    PRD §3.4: "A person holding `PROFICIENCY_VERIFIED` status may be issued their
    go-live credential, which moves them to `CREDENTIALED`."

    Design: Difficulty/cross_entity_state_dependency/r7b_shift_activation_requires_staff_credentialed
    """
    ctx = _staffer_verified_but_not_credentialed()
    set_clock("2026-09-02T00:00:00Z")
    shift = get_success_data(api_client.create_shift(
        create_staffing_shift_payload(
            ctx["staff"]["id"], ctx["fac"]["id"], support_role="AT_THE_ELBOW",
            start_utc="2026-09-02T06:00:00Z", end_utc="2026-09-02T14:00:00Z",
        ),
        command_center_headers,
    ))

    credentialed = validate_success(api.issue_credential(ctx["staff"]["id"], training_headers), 200)
    assert credentialed["status"] == "CREDENTIALED"

    # PRD §3.10: activation also requires "that the logical clock has reached its
    # `start_utc`", so the clock is moved to the shift's start instant.
    set_clock("2026-09-02T06:00:00Z")
    activated = validate_success(api.activate_shift(shift["id"], command_center_headers), 200)
    assert activated["status"] == "ACTIVE"