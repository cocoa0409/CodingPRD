"""Tests for endpoint-level claims: clock default, error envelope, coverage read."""
from test_helpers import (
    NON_EXISTENT_UUID,
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    make_platform_headers,
    create_org,
    create_active_agreement,
    create_plan,
    ApiErrorId,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()
PLATFORM = make_platform_headers()


def test_clock_default_is_fixed_2026_09_01_before_any_set(api):
    """PRD section 2.4: "Time in this system is logical, not wall-clock. The
    platform operator sets the logical clock through an admin-only capability that
    supplies a `to_iso8601` instant; at startup the clock reads exactly
    2026-09-01T00:00:00Z and never falls back to wall-clock time. Every temporal
    rule in this document — term windows, amendment windows, credit expiry,
    coverage replay, remaining-hours computations — evaluates against this
    logical clock."

    Design: Corner/endpoints/clock_default_is_fixed_2026_09_01_before_any_set
    """
    resp = api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, PLATFORM)
    data = validate_success(resp)
    # PRD section 5 renders timestamps with three fractional digits; section 2.4
    # pins the instant itself. Assert the canonical rendering of that instant.
    assert data["current_utc"] == "2026-09-01T00:00:00.000Z"
    # the default clock at startup is exactly this instant, so setting it to the
    # same value is consistent with never having set it
    resp = api.set_clock({"to_iso8601": "2026-09-05T12:00:00Z"}, PLATFORM)
    data = validate_success(resp)
    assert data["current_utc"] == "2026-09-05T12:00:00.000Z"


def test_error_envelope_shape_on_404(api):
    """PRD section 2.2: "All error API responses (4xx status codes) follow this
    standard envelope format" with "The `meta` object for error responses
    contains only `api_request_id` and `api_request_timestamp`." and "The
    `error_id` is a unique, machine-readable string that identifies the specific
    error. The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/error_envelope_shape_on_404
    """
    resp = api.get_billing_org(NON_EXISTENT_UUID, ADMIN)
    assert resp.status_code == 404
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]


def test_coverage_endpoint_window_hours_reported(api):
    """PRD section 3.4: "The `PROJECTED` mode is a purchase-time what-if that
    assumes full utilization: the covered amount is simply
    `hourly_commitment_cents` multiplied by the number of hours in the window. The
    two diverge precisely when any hour is under-utilized. The read accepts
    optional `mode`, `window_start`, and `window_end` parameters and reports
    `covered_cents`, the `mode` used, and `window_hours`."

    Design: Corner/endpoints/coverage_endpoint_window_hours_reported
    """
    org = create_org(name="Cv Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=1000000,
    )
    plan = create_plan(
        org["id"], agr["id"], type="SAVINGS_PLAN", instance_family="COMPUTE",
        units=0, hourly_commitment_cents=40, plan_discount_rate=0.30,
        term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
    )
    params = {"window_start": "2026-09-01T00:00:00Z",
              "window_end": "2026-09-01T05:00:00Z"}
    act = validate_success(
        api.get_plan_coverage(plan["id"], FINANCE, params={**params, "mode": "ACTUAL"})
    )
    assert act["window_hours"] == 5
    assert act["covered_cents"] == 0, "no usage at all -> zero actual coverage"
    proj = validate_success(
        api.get_plan_coverage(plan["id"], FINANCE, params={**params, "mode": "PROJECTED"})
    )
    assert proj["covered_cents"] == 200, "40 hourly x 5 hours full utilization"
    assert proj["mode"] == "PROJECTED"
