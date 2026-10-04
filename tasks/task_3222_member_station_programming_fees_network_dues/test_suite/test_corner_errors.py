"""Uniqueness conflicts and the authentication gate. Queue B, section `errors`."""
from test_helpers import (
    ADMIN,
    ANONYMOUS_HEADERS,
    EDITOR,
    SCHEDULER,
    ApiErrorId,
    api_client,
    create_feed,
    create_program,
    create_station,
    set_clock,
    validate_error,
)

STATION_FIXTURE = dict(
    call_sign="WJCT", licensee_name="First Coast Licensee", state_code="FL",
    dma_market_rank=42, dma_households=660000, coverage_population=75000,
    full_time_staff_count=6, newsroom_staff_count=3,
    annual_local_revenue_cents=4800000, board_seat_region="REGION_SOUTH",
)


def test_a_call_sign_already_registered_is_refused():
    """PRD §2.9: "Uniqueness follows existence: a `call_sign` already taken fails
    with `ERR_CALL_SIGN_TAKEN` (409)".
    PRD §3.1: registration records "its `call_sign` — three or four uppercase
    letters, never repeated across the network".

    Design: Corner/errors/duplicate_call_sign_and_program_code_conflicts
    """
    set_clock("2026-09-01T00:00:00Z")
    create_station(**STATION_FIXTURE)
    resp = api_client.create_station(
        dict(STATION_FIXTURE, licensee_name="Duplicate Licensee",
             dma_market_rank=43), ADMIN)

    validate_error(resp, ApiErrorId.ERR_CALL_SIGN_TAKEN)


def test_a_program_code_already_in_use_is_refused():
    """PRD §3.6: "An editor creates one by naming a unique `program_code` matching
    the pattern `NP-` followed by four digits — reused codes fail with
    `ERR_PROGRAM_CODE_TAKEN`".

    Design: Corner/errors/duplicate_call_sign_and_program_code_conflicts
    """
    set_clock("2026-09-01T00:00:00Z")
    create_program(program_code="NP-1018", program_title="First Coast Journal")
    resp = api_client.create_program(
        {"program_code": "NP-1018", "program_title": "Duplicate Program",
         "strand_type": "NEWS", "national_premiere_at": "2026-10-01T00:00:00Z"},
        EDITOR)

    validate_error(resp, ApiErrorId.ERR_PROGRAM_CODE_TAKEN)


def test_a_feed_code_already_in_use_is_refused():
    """PRD §2.9: "a `feed_code` already in use fails with `ERR_FEED_CODE_TAKEN`
    (409)".
    PRD §3.4: the scheduler creates a feed "by naming a unique `feed_code` matching
    the pattern `FEED-` followed by four uppercase alphanumeric characters".

    Design: Corner/errors/duplicate_call_sign_and_program_code_conflicts
    """
    set_clock("2026-09-01T00:00:00Z")
    create_feed(feed_code="FEED-D004", feed_type="SATELLITE")
    resp = api_client.create_feed(
        {"feed_code": "FEED-D004", "feed_type": "DIGITAL",
         "total_capacity_units": 12, "max_reserved_capacity_ratio": 8000},
        SCHEDULER)

    validate_error(resp, ApiErrorId.ERR_FEED_CODE_TAKEN)


def test_a_request_without_any_role_header_is_refused_at_authentication():
    """PRD §2.1: "A request missing either header, or carrying an `X-User-Role` that
    does not name one of the seven roles below, is refused with
    `ERR_MISSING_AUTH` (HTTP 401)."

    Design: Corner/errors/auth_header_absent_rejected_first
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_schedule(
        {"schedule_code": "FY2027N", "fiscal_year": 2026, "base_fee_cents": 1200000,
         "revenue_rate_bps": 250, "market_size_multiplier_bps": 12500,
         "minimum_fee_cents": 100000, "maximum_fee_cents": 5000000,
         "annual_adjustment_bps": 0, "effective_from": "2026-06-01T00:00:00Z",
         "effective_to": "2027-06-01T00:00:00Z"},
        ANONYMOUS_HEADERS)

    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)


def test_authentication_outranks_the_path_existence_check():
    """PRD §2.9: "Authority is settled first. A request lacking either `X-User-ID` or
    `X-User-Role`, or naming a role outside the seven-role matrix, fails
    immediately with `ERR_MISSING_AUTH` (401) before any body or path is
    inspected."

    The path names a station identifier that was never registered, and the
    authority category still governs, so existence is never reached.

    Design: Corner/errors/auth_header_absent_rejected_first
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.submit_eligibility(
        "11111111-2222-4333-8444-555555555555", ANONYMOUS_HEADERS)
    error = validate_error(resp, ApiErrorId.ERR_MISSING_AUTH)

    assert error["error_id"] != ApiErrorId.ERR_RESOURCE_NOT_FOUND, (
        "the existence category must not be reached for an unauthenticated request"
    )