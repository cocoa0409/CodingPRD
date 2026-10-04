"""Difficulty queue — boundary precision: the inclusive response-window
boundary at the exact deadline instant (PRD §3.4) and the inclusive grade
floor at score 90 (PRD §3.6)."""

from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    complaint_response_payload,
    create_bureau,
    create_business,
    create_consumer,
    create_rating_snapshot_payload,
    file_and_forward_complaint,
    get_complaint,
    make_business_rep_headers,
    open_advertising_review,
    parse_iso,
    set_clock,
    setup_business_with_resolved_complaints,
    setup_published_scam_reports,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def _setup_world():
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    return bureau, consumer


class TestResponseDeadlineInclusiveBoundary:
    def _setup_two_forwarded(self):
        bureau, consumer = _setup_world()
        business = create_business(legal_name="BigBox Services Inc",
                                   home_state_code="IA", employee_count=250,
                                   founded_on="2018-01-01T00:00:00Z")
        c1 = file_and_forward_complaint(consumer, business,
                                        category="SERVICE",
                                        description="exactly on deadline")
        c2 = file_and_forward_complaint(consumer, business,
                                        category="BILLING",
                                        description="one second late")
        return business, c1, c2

    def test_response_at_exact_deadline_is_on_time(self, api):
        """PRD §3.4: "The response window is enforced with an inclusive
        boundary: a response received exactly at `response_deadline_at` is on
        time, and only a response arriving after the deadline is rejected with
        `ERR_RESPONSE_WINDOW_EXPIRED`."
        PRD §3.4: "the status moves from `RECEIVED` to `FORWARDED`,
        `forwarded_at` is stamped, and `response_deadline_at` is set exactly
        14 days later — precisely 1209600 seconds after `forwarded_at`."

        Design: Difficulty/boundary_precision_check/response_deadline_inclusive_at_exact_instant
        """
        business, c1, _c2 = self._setup_two_forwarded()
        assert parse_iso(c1["response_deadline_at"]) == parse_iso(
            c1["forwarded_at"]) + timedelta(days=14)
        assert parse_iso(c1["response_deadline_at"]) == parse_iso(
            "2026-09-15T00:00:00Z")
        set_clock("2026-09-15T00:00:00Z")  # exactly the deadline
        resp = api.add_complaint_response(
            c1["id"],
            complaint_response_payload(kind="BUSINESS_RESPONSE",
                                       body="exactly on the deadline"),
            make_business_rep_headers(business["id"]))
        answered = validate_success(resp, 201)
        assert answered["status"] == "RESPONSE_RECEIVED"
        assert answered["responses"][0]["on_time"] is True
        assert parse_iso(answered["responses"][0]["received_at"]) == \
            parse_iso("2026-09-15T00:00:00Z")

    def test_response_one_second_late_is_rejected(self, api):
        """PRD §3.4: "The response window is enforced with an inclusive
        boundary: a response received exactly at `response_deadline_at` is on
        time, and only a response arriving after the deadline is rejected with
        `ERR_RESPONSE_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/response_deadline_inclusive_at_exact_instant
        """
        business, _c1, c2 = self._setup_two_forwarded()
        set_clock("2026-09-15T00:00:01Z")  # one second past the deadline
        resp = api.add_complaint_response(
            c2["id"],
            complaint_response_payload(kind="BUSINESS_RESPONSE",
                                       body="one second late"),
            make_business_rep_headers(business["id"]))
        validate_error(resp, ApiErrorId.ERR_RESPONSE_WINDOW_EXPIRED)
        current = get_complaint(c2["id"])
        assert current["status"] == "FORWARDED"
        assert current["responses"] == []


class TestGradeBoundary:
    def _setup_scam_business(self, consumer):
        """MICRO business with exactly three published scam reports (scam
        deduction 10, everything else zero)."""
        business = create_business(legal_name="Scam Target LLC",
                                   home_state_code="IA", employee_count=4,
                                   founded_on="2020-01-01T00:00:00Z")
        setup_published_scam_reports(consumer, business, 3)
        return business

    def _setup_reviewed_business(self, consumer):
        """MICRO business with four RESOLVED complaints (volume deduction 6)
        and one open advertising review (advertising deduction 5)."""
        business = create_business(legal_name="Reviewed Tools Co",
                                   home_state_code="IA", employee_count=4,
                                   founded_on="2020-01-01T00:00:00Z")
        setup_business_with_resolved_complaints(consumer, business, 4)
        open_advertising_review(business, claim_description="eco-friendly")
        return business

    def test_score_90_is_a_minus(self, api):
        """PRD §3.6: "Because every boundary is inclusive on its lower end, a
        score of exactly 90 earns `A_MINUS` while 89 earns `B_PLUS`."
        PRD §3.6: "`scam_deduction` is 10 points when
        `published_scam_count_12m` is 3 or more, and 0 points otherwise."

        Design: Difficulty/boundary_precision_check/grade_boundary_score_90_is_a_minus_89_is_b_plus
        """
        _bureau, consumer = _setup_world()
        business = self._setup_scam_business(consumer)
        resp = api.create_rating_snapshot(
            business["id"], create_rating_snapshot_payload("PUBLISHED"),
            ADMIN)
        snap = validate_success(resp, 201)
        assert snap["scam_deduction"] == 10
        for component in ("volume_deduction", "unanswered_deduction",
                          "unresolved_deduction", "arbitration_deduction",
                          "age_deduction", "advertising_deduction",
                          "pending_deduction"):
            assert snap[component] == 0, component
        assert snap["score"] == 90
        assert snap["grade"] == "A_MINUS"

    def test_score_89_is_b_plus(self, api):
        """PRD §3.6: "Because every boundary is inclusive on its lower end, a
        score of exactly 90 earns `A_MINUS` while 89 earns `B_PLUS`."
        PRD §3.6: "The deduction is 6 points for every complaint above the
        threshold, capped at 30 points; a business at or below its threshold
        loses nothing to volume."

        Design: Difficulty/boundary_precision_check/grade_boundary_score_90_is_a_minus_89_is_b_plus
        """
        _bureau, consumer = _setup_world()
        business = self._setup_reviewed_business(consumer)
        resp = api.create_rating_snapshot(
            business["id"], create_rating_snapshot_payload("PUBLISHED"),
            ADMIN)
        snap = validate_success(resp, 201)
        # 4 outcomes over the MICRO threshold of 3: 6 * (4 - 3) = 6.
        assert snap["volume_deduction"] == 6
        assert snap["advertising_deduction"] == 5
        assert snap["score"] == 89
        assert snap["grade"] == "B_PLUS"
