"""Error-catalog corner tests: header validation, state-gated creation, and
window shape checks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_all_permits,
    create_esa,
    create_project,
    create_project_payload,
    create_warranty_claim_payload,
    execute_esa,
    validate_error,
)

DEV = TEST_USERS["project_developer_headers"]
PERF = TEST_USERS["performance_engineer_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


def test_missing_user_context_header_returns_400(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
    `X-User-Role`. If either header is missing, or the role value is not one of
    the declared roles, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/errors/missing_user_context_header_returns_400
    """
    resp = api.create_project(
        create_project_payload(name="NoRole"),
        {"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_claim_on_draft_esa_rejected(api):
    """PRD §3.7: "Warranty claims themselves are filed by a `WarrantyAdmin`
    against an agreement in `EXECUTED` or `COMPLETED` status — filing against
    any other state is refused with `ERR_ESA_NOT_EXECUTABLE_STATE`"

    Design: Corner/errors/claim_on_draft_esa_rejected
    """
    project = create_project(api=api)
    esa = create_esa(project["id"], api=api)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(esa["id"], claimed_capacity_loss_mwh=1),
        WARRANTY,
    )
    validate_error(resp, ApiErrorId.ERR_ESA_NOT_EXECUTABLE_STATE)


def test_record_results_without_active_esa_rejected(api):
    """PRD §3.4: "A `PerformanceEngineer` schedules periodic guarantee tests
    against any project that has an agreement in `EXECUTED` or `COMPLETED`
    status — scheduling without one is refused with `ERR_NO_ACTIVE_ESA`."

    Design: Corner/errors/record_results_without_active_esa_rejected
    """
    project = create_project(api=api)
    resp = api.create_performance_test(
        {
            "project_id": project["id"],
            "test_type": "CAPACITY_TEST",
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-10T00:00:00Z",
        },
        PERF,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ESA)


def test_invalid_window_end_not_after_start_rejected(api):
    """PRD §3.4: "The create payload carries the `project_id`, a `test_type` of
    `CAPACITY_TEST` or `RTE_TEST`, and a window from `window_start` (inclusive)
    to `window_end` (exclusive); an end not strictly after the start is
    `ERR_INVALID_WINDOW`."

    Design: Corner/errors/invalid_window_end_not_after_start_rejected
    """
    project = create_project(api=api)
    esa = create_esa(project["id"], api=api)
    approve_all_permits(project["id"], api=api)
    execute_esa(esa["id"], project["id"], api=api)

    resp = api.create_performance_test(
        {
            "project_id": project["id"],
            "test_type": "CAPACITY_TEST",
            "window_start": "2026-09-10T00:00:00Z",
            "window_end": "2026-09-10T00:00:00Z",
        },
        PERF,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
