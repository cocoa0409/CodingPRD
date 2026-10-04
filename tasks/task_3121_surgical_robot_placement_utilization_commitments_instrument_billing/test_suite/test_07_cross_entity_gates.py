"""Cross-entity state dependencies: case booking gated on the system's service status."""

from test_helpers import (
    TEST_USERS,
    api_client,
    get_success_data,
    setup_commissioned_system,
    validate_error,
    validate_success,
)


def test_booking_on_a_service_action_system_is_refused(api):
    """PRD §3.4: "The account's ownership of the system is enforced too, and a mismatch is
    `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
    PRD §3.2: "A `PlatformAdmin` may decommission a system from either `IN_SERVICE` or
    `INSTALLED`; any other status fails with `ERR_SYSTEM_STATUS_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/case_creation_or_surgery_blocked_when_status_in_service_action
    """
    ctx = setup_commissioned_system()
    in_action = get_success_data(api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["service_engineer_headers"]), 200)
    assert in_action["service_status"] == "SERVICE_ACTION_REQUIRED"

    res = api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-20T08:00:00Z", "duration_minutes": 60,
         "instrument_load": 1, "is_emergency": False},
        ctx.account_headers)

    validate_error(res, "ERR_SYSTEM_STATUS_INVALID", expected_status=409)


def test_an_emergency_case_on_a_service_action_system_is_never_billable(api):
    """PRD §3.4: "Two overrides then apply, and they override everything above. A case whose
    `case_status` is not `COMPLETED` is never billable, so a `SCHEDULED` or `CANCELLED` case
    reports zero. And a case on a system whose `service_status` is `SERVICE_ACTION_REQUIRED`
    is never billable, so it reports zero as well."

    Design: Difficulty/cross_entity_state_dependency/case_creation_or_surgery_blocked_when_status_in_service_action
    """
    ctx = setup_commissioned_system()
    api_client.open_service_action(
        ctx.system["id"], {"expected_robot_system_version": ctx.system["version"]},
        TEST_USERS["service_engineer_headers"])

    booked = validate_success(api_client.create_procedure_case(
        ctx.system["id"],
        {"training_record_id": ctx.surgeon["id"], "procedure_family": "UROLOGY",
         "case_started_at": "2026-09-21T08:00:00Z", "duration_minutes": 60,
         "instrument_load": 1, "is_emergency": True},
        ctx.account_headers), 201)

    assert booked["instrument_billing_cents"] == 0, (
        "a non-completed case is never billable"
    )