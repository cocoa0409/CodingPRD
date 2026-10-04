"""Breadth: malformed and inverted inputs are refused by the shape check."""

import pytest

from test_helpers import (
    TEST_USERS,
    add_project,
    api_client,
    assert_same_instant,
    create_capital_call_payload,
    create_exit_event_payload,
    form_fund,
    list_project_capital_calls,
    list_project_exit_events,
    onboard_developer,
    plan_exit_event,
    read_project,
    setup_canonical_scenario,
    setup_exit_eligible_project,
    validate_error,
)


def test_an_out_of_enum_milestone_is_refused_by_the_shape_check():
    """PRD §3.5: "The `milestone` must be one of `CONSTRUCTION_START`,
    `CONSTRUCTION_50PCT`, `LEASE_UP_50PCT`, `LEASE_UP_STABILIZED`, or
    `PLACED_IN_SERVICE`."
    PRD §2.9: "Request shape. Every required input must be present, every enum
    input must be a declared member, every numeric input must be non-negative".
    PRD §2.9: "Failure is `ERR_INVALID_REQUEST`, HTTP 400."

    Design: Corner/validations/malformed_enum_input_returns_invalid_request_from_the_shape_check
    """
    from test_helpers import ApiErrorId

    developer = onboard_developer()
    fund = form_fund()
    project = add_project(developer["id"], fund["id"])

    response = api_client.create_capital_call(
        project["id"],
        create_capital_call_payload(
            milestone="ROOF_DRIED_IN",
            expected_project_version=project["version"],
        ),
        TEST_USERS["asset_manager_headers"],
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert response.status_code == 400
    assert list_project_capital_calls(project["id"]) == []


def test_an_exercise_deadline_inside_the_rofr_window_is_refused_at_issue():
    """PRD §3.9: "Issuing the option notice, available to an `Underwriter` or an
    `AssetManager`, moves the event from `PENDING` to `OPTION_NOTICE_ISSUED` and
    requires that the owning project be in `COMPLIANCE_PERIOD` or `EXIT_ELIGIBLE`,
    that the `exercise_deadline` be at or after the `rofr_notice_date` — otherwise
    the request is rejected with `ERR_EXIT_WINDOW_INVERTED` — and that the computed
    `rofr_expires_at` fall at or before the `exercise_deadline`, otherwise the
    request is rejected with `ERR_EXIT_WINDOW_INVERTED` as well."

    A 180-day window from 2031-01-01 expires 2031-06-30, well past the
    2031-02-01 deadline.

    Design: Corner/validations/coverage_window_inversion_returns_exit_window_inverted
    """
    from test_helpers import ApiErrorId

    scenario = setup_exit_eligible_project()
    exit_event = plan_exit_event(
        scenario.project["id"],
        rofr_notice_date="2031-01-01T00:00:00Z",
        rofr_window_days=180,
        exercise_deadline="2031-02-01T00:00:00Z",
    )

    response = api_client.exercise_exit_event(
        exit_event["id"], "ISSUE_NOTICE", TEST_USERS["underwriter_headers"]
    )

    validate_error(response, ApiErrorId.ERR_EXIT_WINDOW_INVERTED)
    assert response.status_code == 400


def test_a_refused_notice_leaves_the_exit_event_pending():
    """PRD §3.9: "The exit event begins at `PENDING`, and its `rofr_expires_at` is
    computed as the `rofr_notice_date` plus the `rofr_window_days`."

    Design: Corner/validations/coverage_window_inversion_returns_exit_window_inverted
    """
    from test_helpers import ApiErrorId

    scenario = setup_exit_eligible_project()
    exit_event = plan_exit_event(
        scenario.project["id"],
        rofr_notice_date="2031-01-01T00:00:00Z",
        rofr_window_days=180,
        exercise_deadline="2031-02-01T00:00:00Z",
    )
    assert exit_event["status"] == "PENDING"
    assert_same_instant(exit_event["rofr_expires_at"], "2031-06-30T00:00:00Z")

    response = api_client.exercise_exit_event(
        exit_event["id"], "ISSUE_NOTICE", TEST_USERS["underwriter_headers"]
    )
    validate_error(response, ApiErrorId.ERR_EXIT_WINDOW_INVERTED)

    stored = list_project_exit_events(scenario.project["id"])[0]
    assert stored["status"] == "PENDING"
    assert read_project(scenario.project["id"])["status"] == "EXIT_ELIGIBLE"
