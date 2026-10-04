"""Trade reporting: dissemination banding, the 900-second timeliness
boundary, trade-time validation, cancellation state rules, ownership, and
public-tape scoping (PRD sections 2.7, 3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_trade,
    create_dealer_org,
    create_trade,
    create_trade_report_payload,
    make_dealer_rep_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PORTAL_OPERATOR = TEST_USERS["portal_operator_headers"]
PUBLIC = TEST_USERS["public_reader_headers"]

UNKNOWN_TRADE_ID = "11111111-2222-3333-4444-555555555555"


def _report(api, org_id, **overrides):
    """Raw trade-report call as the owning dealer, returning the response."""
    return api.create_trade_report(
        create_trade_report_payload(org_id, **overrides), make_dealer_rep_headers(org_id)
    )


def test_publication_actual_size_vs_capped_size(api):
    """PRD section 3.5: "the disseminated size `published_par` is the
    smaller of `par_amount` and 5,000,000 dollars, and `capped_flag` is
    true exactly when `par_amount` exceeds 5,000,000 — the public feed
    suppresses the true size of very large trades while reporting their
    existence."

    Design: Difficulty/dual_variant_calc/trade_publication_actual_vs_capped_size
    """
    org = create_dealer_org(api, org_code="BD-100", name="Dealer One")
    set_clock(api, "2026-09-01T12:00:00Z")

    small = validate_success(
        _report(api, org["id"], trade_type="CUSTOMER_BUY", par_amount=3000000,
                price=101.25, executed_at="2026-09-01T11:50:00Z"),
        201,
    )
    assert small["published_par"] == 3000000
    assert small["capped_flag"] is False

    big = validate_success(
        _report(api, org["id"], trade_type="CUSTOMER_BUY", par_amount=8000000,
                price=101.25, executed_at="2026-09-01T11:50:00Z"),
        201,
    )
    assert big["published_par"] == 5000000, (
        f"an 8,000,000-par trade must publish at the 5,000,000 cap, got {big['published_par']}"
    )
    assert big["capped_flag"] is True


def test_publication_cap_boundary_is_exclusive_for_the_flag(api):
    """PRD section 3.5: "`published_par` is the smaller of `par_amount` and
    5,000,000 dollars, and `capped_flag` is true exactly when `par_amount`
    exceeds 5,000,000" — so exactly 5,000,000 publishes in full without the
    cap flag, and 5,000,001 truncates to 5,000,000 with it.

    Design: Difficulty/dual_variant_calc/trade_publication_actual_vs_capped_size
    """
    org = create_dealer_org(api, org_code="BD-101", name="Dealer Cap Edge")
    set_clock(api, "2026-09-01T12:00:00Z")

    at_cap = validate_success(
        _report(api, org["id"], trade_type="CUSTOMER_BUY", par_amount=5000000,
                price=100.0, executed_at="2026-09-01T11:50:00Z"),
        201,
    )
    assert at_cap["published_par"] == 5000000
    assert at_cap["capped_flag"] is False, "par equal to the cap must not set capped_flag"

    over_cap = validate_success(
        _report(api, org["id"], trade_type="CUSTOMER_BUY", par_amount=5000001,
                price=100.0, executed_at="2026-09-01T11:50:00Z"),
        201,
    )
    assert over_cap["published_par"] == 5000000
    assert over_cap["capped_flag"] is True


def test_trade_report_is_born_disseminated(api):
    """PRD section 3.5: "Every trade report is born `DISSEMINATED`:
    publication is immediate, not a separate step."

    Design: Corner/state_machines/trade_report_created_directly_disseminated
    """
    org = create_dealer_org(api, org_code="BD-1002", name="Dealer Init")
    set_clock(api, "2026-09-01T12:00:00Z")
    trade = create_trade(
        api, org["id"], trade_type="CUSTOMER_BUY", par_amount=500000,
        price=100.0, executed_at="2026-09-01T11:55:00Z",
    )
    assert trade["status"] == "DISSEMINATED", (
        f"a validated trade must land in DISSEMINATED, got {trade['status']!r}"
    )


def test_nine_hundred_second_boundary_is_strictly_greater(api):
    """PRD section 3.5: "the report is late only when that gap strictly
    exceeds the fifteen-minute reporting limit — a gap of exactly 900
    seconds is timely. The boolean `late_flag` records the outcome, and
    `seconds_late` records the gap minus 900 seconds, never below zero."

    Design: Difficulty/boundary_precision_check/trade_report_nine_hundred_second_boundary
    """
    org = create_dealer_org(api, org_code="BD-601", name="Dealer Boundary")

    set_clock(api, "2026-09-01T10:15:00Z")
    exactly_900 = validate_success(
        _report(api, org["id"], trade_type="CUSTOMER_SELL", par_amount=100000,
                price=99.5, executed_at="2026-09-01T10:00:00Z"),
        201,
    )
    assert exactly_900["late_flag"] is False, "a gap of exactly 900 seconds is timely"
    assert exactly_900["seconds_late"] == 0

    set_clock(api, "2026-09-01T10:15:01Z")
    nine_o_one = validate_success(
        _report(api, org["id"], trade_type="CUSTOMER_SELL", par_amount=100000,
                price=99.5, executed_at="2026-09-01T10:00:00Z"),
        201,
    )
    assert nine_o_one["late_flag"] is True, "a gap of 901 seconds is late"
    assert nine_o_one["seconds_late"] == 1


def test_seconds_late_tracks_the_gap_minus_nine_hundred(api):
    """PRD section 3.5: "`seconds_late` records the gap minus 900 seconds,
    never below zero" and the report "is late only when that gap strictly
    exceeds the fifteen-minute reporting limit".

    Design: Difficulty/boundary_precision_check/trade_report_nine_hundred_second_boundary
    """
    org = create_dealer_org(api, org_code="BD-602", name="Dealer Seconds")

    set_clock(api, "2026-09-01T12:00:00Z")
    under = validate_success(
        _report(api, org["id"], trade_type="CUSTOMER_SELL", par_amount=100000,
                price=100.0, executed_at="2026-09-01T11:45:01Z"),  # 899-second gap
        201,
    )
    assert under["late_flag"] is False
    assert under["seconds_late"] == 0, "a sub-limit gap clamps seconds_late at zero"

    way_late = validate_success(
        _report(api, org["id"], trade_type="CUSTOMER_SELL", par_amount=100000,
                price=100.0, executed_at="2026-09-01T11:00:00Z"),  # 3600-second gap
        201,
    )
    assert way_late["late_flag"] is True
    assert way_late["seconds_late"] == 2700, (
        f"3600-second gap must yield seconds_late 2700, got {way_late['seconds_late']}"
    )


def test_trade_executed_in_the_future_rejected(api):
    """PRD section 3.5: "A report whose `executed_at` lies after the
    current logical time is rejected with `ERR_TRADE_TIME_INVALID`
    (HTTP 422)."

    Design: Corner/validations/trade_executed_in_future_returns_trade_time_invalid
    """
    org = create_dealer_org(api, org_code="BD-3003", name="Dealer Future")
    set_clock(api, "2026-09-01T12:00:00Z")
    resp = _report(api, org["id"], trade_type="INTER_DEALER", par_amount=100000,
                   price=100.0, executed_at="2026-09-01T12:00:01Z")
    validate_error(resp, ApiErrorId.ERR_TRADE_TIME_INVALID)


def test_cancelling_cancelled_trade_rejected_invalid_state(api):
    """PRD section 3.5: "Cancelling a trade that is already `CANCELLED` is
    rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/cancel_cancelled_trade_returns_invalid_state
    """
    org = create_dealer_org(api, org_code="BD-1003", name="Dealer Cancel")
    set_clock(api, "2026-09-01T12:00:00Z")
    trade = create_trade(
        api, org["id"], trade_type="INTER_DEALER", par_amount=100000,
        price=100.0, executed_at="2026-09-01T11:55:00Z",
    )
    cancel_trade(api, trade["id"], org["id"])

    resp = api.cancel_trade_report(trade["id"], make_dealer_rep_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_dealer_rep_cannot_report_trade_for_another_org(api):
    """PRD section 3.5: "the payload's `dealer_org_id` must equal the
    caller's `X-User-ID`, else `ERR_UNAUTHORIZED`".

    Design: Corner/endpoints/dealer_rep_cannot_report_trade_for_other_org
    """
    org_a = create_dealer_org(api, org_code="BD-4005A", name="Dealer A")
    org_b = create_dealer_org(api, org_code="BD-4005B", name="Dealer B")
    set_clock(api, "2026-09-01T12:00:00Z")

    # Headers identify org A while the payload names org B.
    resp = api.create_trade_report(
        create_trade_report_payload(
            org_b["id"], trade_type="INTER_DEALER", par_amount=100000,
            price=100.0, executed_at="2026-09-01T11:55:00Z",
        ),
        make_dealer_rep_headers(org_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


def test_cancel_unknown_trade_returns_trade_not_found(api):
    """PRD section 2.7: "Each resource family carries its own not-found
    error identifier:" — for trade reports that identifier is
    `ERR_TRADE_NOT_FOUND` (HTTP 404).

    Design: Corner/errors/cancel_unknown_trade_returns_trade_not_found
    """
    org = create_dealer_org(api, org_code="BD-5003", name="Dealer NotFound")
    resp = api.cancel_trade_report(UNKNOWN_TRADE_ID, make_dealer_rep_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_TRADE_NOT_FOUND)


def test_public_reader_sees_only_disseminated_trades(api):
    """PRD section 2.7: "a `PublicReader` sees only `PUBLISHED` disclosure
    submissions and `DISSEMINATED` trade reports, reflecting the portal's
    free public access mandate" and out-of-scope single reads report
    "`ERR_SUBMISSION_NOT_FOUND` or `ERR_TRADE_NOT_FOUND` — never as a
    permission error". "`PortalOperator` and `ComplianceOfficer` see all
    submissions and trades."

    Design: Corner/endpoints/public_reader_sees_only_disseminated_trades
    """
    org = create_dealer_org(api, org_code="BD-4003", name="Dealer Tape")
    set_clock(api, "2026-09-01T12:00:00Z")
    trade = create_trade(
        api, org["id"], trade_type="CUSTOMER_BUY", par_amount=100000,
        price=100.0, executed_at="2026-09-01T11:55:00Z",
    )
    cancel_trade(api, trade["id"], org["id"])

    public_list, public_meta = validate_paginated(api.list_trade_reports(PUBLIC))
    assert len(public_list) == 0, "a cancelled trade must vanish from the public tape"
    assert public_meta["total_count"] == 0

    hidden = api.get_trade_report(trade["id"], PUBLIC)
    validate_error(hidden, ApiErrorId.ERR_TRADE_NOT_FOUND)

    operator_view = validate_success(api.get_trade_report(trade["id"], PORTAL_OPERATOR), 200)
    assert operator_view["status"] == "CANCELLED"
