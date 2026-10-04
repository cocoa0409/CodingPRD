"""Terminal-state lockdown, idempotency and transition preconditions."""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    get_success_data,
    get_build_item,
    setup_program_facility_department,
    setup_failed_item_with_defect,
    create_item_in_testing,
    create_test_scenario_payload,
    create_credentialed_trainer_payload,
    create_staff_payload,
    BUILD_ANALYST,
    TEST_LEAD,
    TRAINING,
)


# ===========================================================================
# c_revoked_trainer_is_terminal_and_cannot_be_recertified
# ===========================================================================

def _revoked_trainer_record():
    prog, fac, dept = setup_program_facility_department()
    staff = get_success_data(api_client.create_staff(
        prog["id"],
        create_staff_payload(fac["id"], dept["id"], full_name="Omar Haddad"),
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
    revoked = get_success_data(api_client.revoke_trainer(trainer["id"], TRAINING))
    assert revoked["status"] == "REVOKED"
    return {"prog": prog, "fac": fac, "dept": dept, "staff": staff, "trainer": trainer}


def test_recertifying_a_revoked_trainer_reports_invalid_state(api, training_headers):
    """PRD §3.4: "Its status vocabulary is `PENDING_OBSERVATION`, `CERTIFIED`,
    `EXPIRED` and `REVOKED`."
    PRD §3.4: "Once the clock reaches `expires_utc` the record becomes `EXPIRED`
    without any client request, and an expired record may be recertified under
    the same observation floor, which resets both instants afresh."
    PRD §3.4: "Revoking may be done from `CERTIFIED` and moves the record to the
    terminal `REVOKED`, refreshing the program's `net_trainer_count`."

    Design: Corner/state_machines/c_revoked_trainer_is_terminal_and_cannot_be_recertified
    """
    ctx = _revoked_trainer_record()

    refused = api_client.recertify_trainer(ctx["trainer"]["id"], training_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_the_revoked_trainer_record_stays_revoked_after_the_refused_recertification(api, training_headers):
    """PRD §2.11: "the target must be in the exact from-state of the transition
    being triggered (otherwise `ERR_INVALID_STATE`, HTTP 409)".
    PRD §3.4: "Revoking may be done from `CERTIFIED` and moves the record to the
    terminal `REVOKED`, refreshing the program's `net_trainer_count`."

    Design: Corner/state_machines/c_revoked_trainer_is_terminal_and_cannot_be_recertified
    """
    ctx = _revoked_trainer_record()
    api_client.recertify_trainer(ctx["trainer"]["id"], training_headers)

    read = validate_success(
        api_client.get_credentialed_trainer(ctx["trainer"]["id"], training_headers), 200
    )
    assert read["status"] == "REVOKED"


# ===========================================================================
# c_second_resolve_on_resolved_defect_returns_invalid_state
# ===========================================================================

def test_replaying_a_resolution_on_an_already_resolved_defect_reports_invalid_state(api, build_analyst_headers):
    """PRD §3.5: "A `BuildAnalyst` begins remediation, moving the defect from
    `OPEN` to `IN_REMEDIATION`".
    PRD §2.11: "the target must be in the exact from-state of the transition
    being triggered (otherwise `ERR_INVALID_STATE`, HTTP 409)".

    The resolve transition is declared from IN_REMEDIATION, so replaying it once
    the defect is already RESOLVED is refused.

    Design: Corner/state_machines/c_second_resolve_on_resolved_defect_returns_invalid_state
    """
    ctx = setup_failed_item_with_defect(severity="SEV3", defect_code="LBL-5001")
    get_success_data(api_client.begin_remediation(ctx["defect"]["id"], build_analyst_headers))
    get_success_data(api_client.resolve_defect(ctx["defect"]["id"], build_analyst_headers))

    refused = api_client.resolve_defect(ctx["defect"]["id"], build_analyst_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_the_replayed_resolution_leaves_the_defect_and_its_resolution_epoch_untouched(api, build_analyst_headers):
    """PRD §3.5: "Resolution also stamps `resolution_epoch` with the current epoch
    and clears `blocks_go_live`."
    PRD §2.11: "the target must be in the exact from-state of the transition
    being triggered (otherwise `ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/state_machines/c_second_resolve_on_resolved_defect_returns_invalid_state
    """
    ctx = setup_failed_item_with_defect(severity="SEV3", defect_code="LBL-5001")
    get_success_data(api_client.begin_remediation(ctx["defect"]["id"], build_analyst_headers))
    first = validate_success(api_client.resolve_defect(ctx["defect"]["id"], build_analyst_headers), 200)
    api_client.resolve_defect(ctx["defect"]["id"], build_analyst_headers)

    read = validate_success(api_client.get_test_defect(ctx["defect"]["id"], build_analyst_headers), 200)
    assert read["status"] == "RESOLVED"
    assert read["resolution_epoch"] == first["resolution_epoch"]


# ===========================================================================
# c_complete_validation_without_passed_scenario_returns_invalid_state
# ===========================================================================

def test_closing_validation_before_any_scenario_has_passed_reports_invalid_state(api, test_lead_headers):
    """PRD §3.3: "closing validation requires that at least one test scenario has
    passed in the current epoch (`test_cycles_passed` of at least 1) and that
    `open_defect_count` has returned to 0".
    PRD §2.11: "the target must be in the exact from-state of the transition
    being triggered (otherwise `ERR_INVALID_STATE`, HTTP 409)".

    The build item is in IN_TESTING but its only scenario is still DEFINED, so no
    cycle has passed and the call is refused.

    Design: Corner/state_machines/c_complete_validation_without_passed_scenario_returns_invalid_state
    """
    prog, fac, dept = setup_program_facility_department()
    item = create_item_in_testing(dept["id"])
    scenario = get_success_data(api_client.create_test_scenario(
        item["id"], create_test_scenario_payload(), test_lead_headers
    ))
    assert scenario["status"] == "DEFINED", "the scenario has never executed"
    assert item["test_cycles_passed"] == 0

    refused = api_client.complete_item_validation(item["id"], test_lead_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def test_a_passing_scenario_then_lets_the_same_build_item_close_validation(api, test_lead_headers):
    """PRD §3.3: "closing validation requires that at least one test scenario has
    passed in the current epoch (`test_cycles_passed` of at least 1) and that
    `open_defect_count` has returned to 0, at which point the item reaches the
    terminal `VALIDATION_COMPLETE`."
    PRD §3.5: "A passing outcome moves the scenario to `PASSED`, records the epoch
    and refreshes the build item's `test_cycles_passed`".

    Design: Corner/state_machines/c_complete_validation_without_passed_scenario_returns_invalid_state
    """
    prog, fac, dept = setup_program_facility_department()
    item = create_item_in_testing(dept["id"])
    scenario = get_success_data(api_client.create_test_scenario(
        item["id"], create_test_scenario_payload(), test_lead_headers
    ))
    api_client.complete_item_validation(item["id"], test_lead_headers)

    get_success_data(api_client.execute_scenario(
        scenario["id"], {"outcome": "PASS", "executed_epoch": 0}, test_lead_headers
    ))
    closed = validate_success(api_client.complete_item_validation(item["id"], test_lead_headers), 200)
    assert closed["status"] == "VALIDATION_COMPLETE"