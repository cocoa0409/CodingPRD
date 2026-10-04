"""Outcome publication, public display, and annual reporting (PRD §3.8, §3.10)."""
from test_helpers import (
    ApiErrorId,
    get_app,
    get_success_data,
    make_accreditation_officer_headers,
    make_plan_coordinator_headers,
    make_public_viewer_headers,
    publish_outcome,
    set_clock,
    setup_closed_application,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import api_client


def _instant(iso: str) -> str:
    """Normalize an ISO 8601 UTC timestamp to second precision for comparison."""
    from datetime import datetime, timezone
    s = iso[:-1] + "+00:00" if iso.endswith("Z") else iso
    return datetime.fromisoformat(s).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _officer():
    return make_accreditation_officer_headers()


def _public():
    return make_public_viewer_headers()


def test_public_accreditation_status_display(api):
    """PRD §3.8: "Publishing sets `published` to true, computes
    `public_display_until` as the `decided_at` timestamp plus 36 months (same
    day-of-month, with month-end dates clamping to the last day of the resulting
    month)".

    Design: Corner/endpoints/public_accreditation_status_display
    """
    ctx = setup_closed_application()
    outcome = ctx["outcome"]

    published = publish_outcome(outcome["id"])
    assert published["published"] is True
    assert published["is_publicly_displayed"] is True
    assert published["public_display_until"] is not None
    # decided at the logical clock 2026-09-01 + 36 months = 2029-09-01
    assert published["public_display_until"].startswith("2029-09-01"), (
        f"decided_at + 36 months, got {published['public_display_until']}"
    )


def test_outcome_revise_after_resurvey_rejected_when_not_scoring(api):
    """PRD §3.8: "Revising requires the application to be back in `SCORING`
    (which the resurvey-completion cascade has just arranged)". PRD §2.5 item 7
    covers wrong-state transitions with `ERR_APPLICATION_INVALID_STATE`.

    Design: Corner/endpoints/outcome_revise_after_resurvey
    """
    ctx = setup_closed_application()
    r = api_client.revise_outcome(ctx["outcome"]["id"], _officer())
    validate_error(r, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
    assert r.status_code == 409
    after = get_success_data(api_client.get_outcome(ctx["outcome"]["id"], _officer()))
    assert after["decision_sequence"] == 1, "failed revise leaves the sequence unchanged"


def test_second_outcome_create_rejected(api):
    """PRD §3.8: "Exactly one `AccreditationOutcome` exists per application: a
    second decision call on the same application is rejected with
    `ERR_OUTCOME_ALREADY_EXISTS`, and re-decision after a resurvey uses the
    revise operation instead."

    Design: Corner/endpoints/second_outcome_create_rejected
    """
    ctx = setup_closed_application()
    r = api_client.create_outcome(ctx["app"]["id"], _officer())
    validate_error(r, ApiErrorId.ERR_OUTCOME_ALREADY_EXISTS)
    assert r.status_code == 409


def test_quality_measure_duplicate_rejected(api):
    """PRD §3.11: "at most one result may exist per (scope, `measure_code`,
    `measurement_year`) triple, and duplicates are rejected with
    `ERR_MEASURE_RESULT_DUPLICATE`."

    Design: Corner/endpoints/quality_measure_duplicate_rejected
    """
    from test_helpers import add_measure, create_plan, create_scope
    plan = create_plan()
    scope = create_scope(plan["id"])
    add_measure(scope["id"], plan["id"], measure_code="HEDIS-CBP",
                measurement_year=2025, percentile=70)

    r = api_client.create_quality_measure_result(
        scope["id"],
        {"measure_code": "HEDIS-CBP", "measurement_year": 2025,
         "percentile": 71, "is_reportable": True},
        make_plan_coordinator_headers(plan["id"]))
    validate_error(r, ApiErrorId.ERR_MEASURE_RESULT_DUPLICATE)
    assert r.status_code == 409

    # The same code for a different measurement year is fine.
    ok = api_client.create_quality_measure_result(
        scope["id"],
        {"measure_code": "HEDIS-CBP", "measurement_year": 2024,
         "percentile": 65, "is_reportable": True},
        make_plan_coordinator_headers(plan["id"]))
    validate_success(ok, expected_status=201)


def test_annual_report_due_date_computed_at_creation(api):
    """PRD §3.10: "The report's `due_date` is computed at creation as March 31
    of the year after the `reporting_year`, at 23:59:59 UTC. New reports begin
    in `DRAFT` with `is_late` false."

    Design: Corner/entities/annual_report_due_date_computed_at_creation
    """
    ctx = setup_closed_application()
    r = api_client.create_annual_report(
        ctx["app"]["id"],
        {"reporting_year": 2027,
         "attestation": "We attest the data submitted is complete and accurate."},
        make_plan_coordinator_headers(ctx["plan"]["id"]))
    report = validate_success(r, expected_status=201)
    # PRD pins the instant (March 31 of the next year at 23:59:59 UTC), not the
    # string rendering of the field.
    assert _instant(report["due_date"]) == "2028-03-31T23:59:59"
    assert report["status"] == "DRAFT"
    assert report["is_late"] is False


def test_annual_report_returned_reopen_resubmit_cycle(api):
    """PRD §3.10: "A returned report can be reopened by the plan's coordinator:
    reopening requires the report to be `RETURNED` (otherwise
    `ERR_REPORT_INVALID_STATE`), moves it back to `DRAFT`, and resets `is_late`
    to false. A reopened report re-enters the submission cycle, and its lateness
    is re-evaluated at each submission against the same fixed `due_date` — a
    report reopened after its due date will be `LATE` again on its next
    submission."

    Design: Corner/state_machines/annual_report_returned_reopen_resubmit_cycle
    """
    ctx = setup_closed_application()
    plan_id = ctx["plan"]["id"]
    coord = make_plan_coordinator_headers(plan_id)

    report = validate_success(api_client.create_annual_report(
        ctx["app"]["id"],
        {"reporting_year": 2025,
         "attestation": "We attest the data submitted is complete and accurate."},
        coord), expected_status=201)
    assert _instant(report["due_date"]) == "2026-03-31T23:59:59"

    # Pin the logical clock before the due date so the first submission is on
    # time (PRD §3.10: "when the logical clock at submission time is at or
    # before the `due_date`, the report becomes `SUBMITTED` with `is_late` false").
    set_clock("2026-03-01T00:00:00Z")
    submitted = get_success_data(api_client.submit_annual_report(report["id"], coord))
    assert submitted["status"] == "SUBMITTED"
    assert submitted["is_late"] is False

    returned = get_success_data(api_client.review_annual_report(
        report["id"], {"accepted": False}, _officer()))
    assert returned["status"] == "RETURNED"

    reopened = get_success_data(api_client.reopen_annual_report(report["id"], coord))
    assert reopened["status"] == "DRAFT"
    assert reopened["is_late"] is False
    assert _instant(reopened["due_date"]) == "2026-03-31T23:59:59", "due_date stays fixed"

    set_clock("2026-04-15T00:00:00Z")
    resubmitted = get_success_data(api_client.submit_annual_report(report["id"], coord))
    assert resubmitted["status"] == "LATE"
    assert resubmitted["is_late"] is True
    assert _instant(resubmitted["due_date"]) == "2026-03-31T23:59:59"


def test_outcome_publish_idempotent_display_window(api):
    """PRD §3.8: "Publishing sets `published` to true, computes
    `public_display_until` as the `decided_at` timestamp plus 36 months" — the
    window derives from `decided_at`, so re-publishing the same outcome leaves
    `public_display_until` unchanged.

    Design: Corner/errors_stubs/outcome_publish_idempotent_display_window
    """
    ctx = setup_closed_application()
    first = publish_outcome(ctx["outcome"]["id"])
    assert first["published"] is True
    assert first["is_publicly_displayed"] is True

    second = publish_outcome(ctx["outcome"]["id"])
    assert second["public_display_until"] == first["public_display_until"], (
        "decided_at + 36 months computed once; re-publish must not move the window"
    )
    assert second["published"] is True
    assert second["is_publicly_displayed"] is True
    assert get_app(ctx["app"]["id"])["status"] == "CLOSED"
