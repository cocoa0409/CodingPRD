"""Difficulty queue — validation priority pairs: when one request violates
two rules, the earlier priority category produces the response (PRD §2.7)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    complaint_response_payload,
    conclude_review_deceptive_payload,
    create_application,
    create_bureau,
    create_business,
    create_consumer,
    decide_application_payload,
    file_and_forward_complaint,
    get_application,
    get_complaint,
    make_business_rep_headers,
    open_advertising_review,
    run_daily_close,
    set_clock,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def _setup_forwarded_pair():
    """Bureau, consumer, LARGE business and one complaint forwarded at the
    clock-start instant (response deadline 2026-09-15T00:00:00Z)."""
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer()
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    complaint = file_and_forward_complaint(consumer, business,
                                           category="SERVICE",
                                           description="window test")
    return bureau, consumer, business, complaint


class TestStateErrorBeatsWindowExpired:
    def test_post_sweep_response_gets_state_error_not_window_error(self, api):
        """PRD §2.7: "When a single request would violate several rules, the
        checks are evaluated in a fixed priority order and the earliest
        failing check produces the response — an authentication failure, for
        instance, is never masked by a later business rule."
        PRD §3.4: "A response of `kind` `BUSINESS_RESPONSE` with a free-text
        `body` moves the complaint from `FORWARDED` to `RESPONSE_RECEIVED`;
        after a rebuttal round, a further `BUSINESS_RESPONSE` moves it from
        `CONSUMER_REBUTTED` back to `RESPONSE_RECEIVED`."

        Design: Difficulty/priority_pair_validation_conflict/complaint_response_state_error_beats_window_expired
        """
        bureau, _consumer, business, complaint = _setup_forwarded_pair()
        # The sweep flips the complaint to UNANSWERED; the deadline is also
        # in the past, so the temporal rule is violated too.
        set_clock("2026-09-16T00:00:00Z")
        run_daily_close(bureau["id"])
        resp = api.add_complaint_response(
            complaint["id"],
            complaint_response_payload(kind="BUSINESS_RESPONSE",
                                       body="too late"),
            make_business_rep_headers(business["id"]))
        validate_error(resp, ApiErrorId.ERR_COMPLAINT_INVALID_STATE)
        assert resp.json()["data"]["error_id"] != \
            ApiErrorId.ERR_RESPONSE_WINDOW_EXPIRED
        current = get_complaint(complaint["id"])
        assert current["status"] == "UNANSWERED"
        assert current["responses"] == []

    def test_window_error_in_isolation_when_state_still_valid(self, api):
        """PRD §3.4: "The response window is enforced with an inclusive
        boundary: a response received exactly at `response_deadline_at` is on
        time, and only a response arriving after the deadline is rejected with
        `ERR_RESPONSE_WINDOW_EXPIRED`."

        Design: Difficulty/priority_pair_validation_conflict/complaint_response_state_error_beats_window_expired
        """
        # No daily close: the complaint stays FORWARDED past its deadline, so
        # only the temporal rule fails and its error must surface.
        _bureau, _consumer, business, complaint = _setup_forwarded_pair()
        set_clock("2026-09-16T00:00:00Z")
        resp = api.add_complaint_response(
            complaint["id"],
            complaint_response_payload(kind="BUSINESS_RESPONSE",
                                       body="too late"),
            make_business_rep_headers(business["id"]))
        validate_error(resp, ApiErrorId.ERR_RESPONSE_WINDOW_EXPIRED)
        current = get_complaint(complaint["id"])
        assert current["status"] == "FORWARDED"
        assert current["responses"] == []


def _setup_referred_with_void_invoice(api):
    """MICRO business: application 1 approved (invoice 40375) and never paid;
    the 2026-10-17 sweep voids the invoice and expires the application; a
    deceptive advertising conclusion leaves the business
    REFERRED_TO_REGULATOR; application 2 SUBMITTED."""
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    business = create_business(legal_name="Tiny Ad Co", home_state_code="IA",
                               employee_count=2,
                               founded_on="2020-01-01T00:00:00Z")
    app1 = create_application(business, billing_plan="ANNUAL_PREPAID",
                              license_number="LIC-T-1")
    app1 = submit_application(app1)
    validate_success(api.decide_application(
        app1["id"], decide_application_payload(), REVIEWER), 200)
    set_clock("2026-10-02T00:00:00Z")
    run_daily_close(bureau["id"])  # invoice OVERDUE
    set_clock("2026-10-17T00:00:00Z")
    run_daily_close(bureau["id"])  # invoice VOID, application EXPIRED
    review = open_advertising_review(
        business, claim_description="fake bureau rating claim",
        as_reviewer=True)
    validate_success(api.conclude_advertising_review(
        review["id"],
        conclude_review_deceptive_payload(regulator_name="State AG"),
        REVIEWER), 200)
    app2 = create_application(business, billing_plan="ANNUAL_PREPAID",
                              license_number="LIC-T-2")
    app2 = submit_application(app2)
    return bureau, business, app1, app2


class TestComplianceGateBeatsFiscalGate:
    def test_adverse_ad_review_reported_over_outstanding_dues(self, api):
        """PRD §2.7: "When a single request would violate several rules, the
        checks are evaluated in a fixed priority order and the earliest
        failing check produces the response — an authentication failure, for
        instance, is never masked by a later business rule."
        PRD §3.2: "The business must have no advertising review in
        `UNDER_REVIEW` or `REFERRED_TO_REGULATOR`, or the decision is rejected
        with `ERR_ADVERTISING_REVIEW_ADVERSE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/approve_adverse_ad_review_beats_outstanding_dues
        """
        _bureau, business, _app1, app2 = \
            _setup_referred_with_void_invoice(api)
        resp = api.decide_application(app2["id"],
                                      decide_application_payload(), REVIEWER)
        validate_error(resp, ApiErrorId.ERR_ADVERTISING_REVIEW_ADVERSE)
        assert resp.json()["data"]["error_id"] != \
            ApiErrorId.ERR_OUTSTANDING_DUES_BALANCE
        assert get_application(business["id"], app2["id"])["status"] == \
            "SUBMITTED"
        rows, meta = validate_paginated(api.list_dues_invoices(
            business["id"], make_business_rep_headers(business["id"])))
        assert len(rows) == 1 and meta["total_count"] == 1, \
            "no new invoice may be issued by a rejected approval"
