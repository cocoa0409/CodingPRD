"""Corner queue — endpoints and error catalogue probes: the daily-close
operations counter (PRD §2.4), the authentication floor (PRD §2.1), and
entity-specific 404s (PRD §2.6)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_bureau,
    create_bureau,
    set_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def test_run_daily_close_increments_ops_day_index_and_returns_bureau(api):
    """PRD §2.4: "Each run increments the bureau's `ops_day_index` by exactly
    1 and then performs four sweeps across the bureau's territory: complaints
    whose response window has lapsed are closed as unanswered (§3.4);
    mediation offers past their acceptance deadline expire (§3.5); invoices
    past their due date are marked overdue, and invoices more than 15 days
    past due are voided, which expires the linked accreditation application
    (§3.3); and the suspension scan evaluates every accredited or suspended
    business in the territory against its latest published rating (§3.7)."

    Design: Corner/endpoints/run_daily_close_increments_ops_day_index_and_returns_bureau
    """
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    first = validate_success(api.run_daily_close(bureau["id"], ADMIN), 200)
    assert_bureau(first)
    assert first["id"] == bureau["id"]
    assert first["ops_day_index"] == 1
    assert first["dues_collected_cents"] == 0
    second = validate_success(api.run_daily_close(bureau["id"], ADMIN), 200)
    assert second["ops_day_index"] == 2


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting party, and `X-User-Role`, declaring the capacity in
    which they act. The system recognizes exactly four roles, spelled exactly
    as follows: `BureauAdmin`, `StandardsReviewer`, `BusinessRep`, and
    `Consumer`. A request missing either header, or carrying a role value
    outside this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_auth_headers_returns_401
    """
    resp = api.list_businesses({})  # no X-User-Role / X-User-ID at all
    error = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert error["message"], "the error envelope carries a message"
    body = resp.json()
    assert body["response_type"] == "error"
    assert set(body["meta"]) == {"api_request_id", "api_request_timestamp"}


def test_business_get_unknown_id_returns_business_not_found(api):
    """PRD §2.6: "Each missing resource yields its own not-found error:
    `ERR_BUREAU_NOT_FOUND`, `ERR_BUSINESS_NOT_FOUND`,
    `ERR_CONSUMER_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`,
    `ERR_APPLICATION_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
    `ERR_MEDIATION_NOT_FOUND`, `ERR_ARBITRATION_NOT_FOUND`,
    `ERR_SNAPSHOT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`,
    `ERR_AD_REVIEW_NOT_FOUND`, or `ERR_SCAM_REPORT_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/business_get_unknown_id_returns_business_not_found
    """
    resp = api.get_business(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BUSINESS_NOT_FOUND)


def test_run_daily_close_on_unknown_bureau_returns_bureau_not_found(api):
    """PRD §2.6: "For every such path, identifiers are validated strictly
    left to right: the request is rejected at the first path identifier that
    names no existing resource, and a nested resource must belong to the
    parent named in its path."

    Design: Corner/errors/run_daily_close_on_unknown_bureau_returns_bureau_not_found
    """
    resp = api.run_daily_close(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_BUREAU_NOT_FOUND)
