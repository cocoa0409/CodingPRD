"""The one optimistic-concurrency guard in the system, exercised end to end."""
from test_helpers import (
    COMPLIANCE,
    api_client,
    create_report_payload,
    log_activity,
    registration_version,
    setup_registration_with_adopted_position,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_stale_registration_version_is_refused_then_the_current_one_is_accepted():
    """Logging an activity moves the registration underneath an unsent report body.

    PRD 2.9: "If that value does not equal the registration's current `version` at the
    moment of the write, the request is rejected with `ERR_STALE_REGISTRATION_VERSION` and
    HTTP 412."
    PRD 2.9: "Because the registration's `version` is incremented by every activity log,
    every activity void, every registration transition, and every report creation, a stale
    expectation is exactly the signal that some other writer has changed the picture."

    Design: Corner/Cross-Cutting Complexity Layers/report_create_rejects_a_stale_registration_version_then_accepts_the_current_one
    """
    state = setup_registration_with_adopted_position()
    registration_id = state["registration"]["id"]
    stale_version = registration_version(registration_id)

    log_activity(
        registration_id,
        state["position"]["id"],
        activity_date="2026-02-15",
        hours=2.000,
        expenditure_cents=300_000,
    )
    current_version = registration_version(registration_id)
    assert current_version == stale_version + 1

    validate_error(
        api_client.create_expenditure_report(
            create_report_payload(registration_id, stale_version, period_code="2026Q1"),
            COMPLIANCE,
        ),
        "ERR_STALE_REGISTRATION_VERSION",
        412,
    )
    assert registration_version(registration_id) == current_version

    report = validate_success(
        api_client.create_expenditure_report(
            create_report_payload(registration_id, current_version, period_code="2026Q1"),
            COMPLIANCE,
        ),
        201,
    )
    assert report["status"] == "OPEN"
    assert report["included_activity_count"] == 1
    assert report["method_a_total_cents"] == 300_000
    assert report["filed_total_cents"] == 300_000

    rows, meta = validate_paginated(
        api_client.list_registration_expenditure_reports(registration_id, COMPLIANCE)
    )
    assert [row["id"] for row in rows] == [report["id"]]
    assert meta["total_count"] == 1
