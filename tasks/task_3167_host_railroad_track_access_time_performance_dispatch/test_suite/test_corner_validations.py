"""Validation corners: authentication, format-beats-auth, existence-beats-state."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId, fixtures, make_host_rep_headers


def test_request_without_auth_headers_is_unauthenticated(api):
    """A request with no auth headers is rejected 401 ERR_UNAUTHENTICATED.

    PRD: "Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, naming their operational capacity. The system recognizes exactly four roles: `SystemAdmin`, `PassengerOperator`, `HostRailroadRep`, and `StateSponsor`. A request missing either header, or presenting a role outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    Design: Corner/validations/missing_auth_headers_returns_unauthenticated
    """
    response = api.list_corridors(headers={})

    assert response.status_code == 401
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_format_failure_is_reported_before_auth(api):
    """A create with a missing required field and no auth headers reports ERR_VALIDATION.

    PRD: "The order is: first, request format — the body must be valid JSON with all required fields present, enum fields holding declared members, and numeric fields within range (a segment's `milepost_end` must be strictly greater than its `milepost_start`, a window's `window_end_at` must be strictly greater than its `window_start_at`, and coded `delay_minutes` must be at least zero), violations yielding `ERR_VALIDATION`; second, authentication (`ERR_UNAUTHENTICATED`)"
    Design: Corner/validations/format_failure_beats_auth_priority
    """
    response = api.create_host_railroad({"reporting_mark": "GPR"}, headers={})

    assert response.status_code == 400
    validate_error(response, ApiErrorId.ERR_VALIDATION)


def test_complete_on_nonexistent_run_returns_not_found(api):
    """Complete on a nonexistent run id returns 404 ERR_NOT_FOUND.

    PRD: "fourth, existence of every path identifier and every foreign-key identifier in the body (`ERR_NOT_FOUND`)"
    Design: Corner/validations/existence_beats_state_on_missing_run
    """
    host = fixtures.create_host(api)

    response = api.complete_train_run(
        "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        {"actual_arrival_at": "2026-09-02T09:17:00Z"},
        make_host_rep_headers(host["id"]),
    )

    assert response.status_code == 404
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)
