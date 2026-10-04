"""Safety recommendations: the respond/classify reclassification loop,
unacceptable-streak closure gating, dual-variant aging (calendar vs business
days), the strict 90-day overdue boundary, and addressee identity (PRD §3.7).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_safety_recommendation,
    classify_pending_response,
    close_recommendation,
    close_recommendation_payload,
    create_org,
    get_recommendation,
    make_addressee_contact_headers,
    recommendation_response_payload,
    respond_and_classify,
    set_clock,
    setup_analysis_with_recommendation,
    submit_response,
    validate_error,
)

MD_PROPOSER = TEST_USERS["md_proposer_headers"]


class TestReclassificationLoop:
    def test_recommendation_reclassification_loop_and_streak_tracking(self, api):
        """PRD §3.7: "A response carrying `response_text` is accepted from
        `OPEN_AWAITING_RESPONSE`, `OPEN_ACCEPTABLE`, or `OPEN_UNACCEPTABLE`; it
        appends an entry to `response_log` holding a server-minted
        `response_id`, the text, a `responded_at` stamp from the logical clock,
        `classification_pending` set true, and `classification` and
        `classified_at` left null, and it moves the recommendation to
        `OPEN_UNCLASSIFIED`." PRD §3.7:
        "Classifying it `ACCEPTABLE` marks the pending entry with that
        classification, stamps its `classified_at`, moves the recommendation to
        `OPEN_ACCEPTABLE`, and resets `unacceptable_streak` to zero.
        Classifying it `UNACCEPTABLE` moves the recommendation to
        `OPEN_UNACCEPTABLE` and recomputes the streak as the number of
        consecutive `UNACCEPTABLE` classifications at the tail of the log."

        Design: Corner/state_machines/recommendation_reclassification_loop_and_streak_tracking
        """
        ctx = setup_analysis_with_recommendation()
        rec_id = ctx["recommendation"]["id"]
        org_id = ctx["org"]["id"]

        rec = submit_response(rec_id, org_id, response_text="We will implement quarterly inspections starting Q4.")
        assert rec["status"] == "OPEN_UNCLASSIFIED"

        rec = classify_pending_response(rec_id, "ACCEPTABLE")
        assert rec["status"] == "OPEN_ACCEPTABLE"
        assert rec["unacceptable_streak"] == 0

        # The reclassification loop out of OPEN_ACCEPTABLE.
        rec = submit_response(rec_id, org_id, response_text="Correction: implementation slips to next year.")
        assert rec["status"] == "OPEN_UNCLASSIFIED"

        rec = classify_pending_response(rec_id, "UNACCEPTABLE")
        assert rec["status"] == "OPEN_UNACCEPTABLE"
        assert rec["unacceptable_streak"] == 1

        assert_safety_recommendation(rec)
        log = rec["response_log"]
        assert len(log) == 2
        assert [entry["classification"] for entry in log] == ["ACCEPTABLE", "UNACCEPTABLE"]
        assert all(entry["classification_pending"] is False for entry in log)

    def test_close_unacceptable_requires_streak_of_two(self, api):
        """PRD §3.7: "From `OPEN_UNACCEPTABLE`, closure as `CLOSED_UNACCEPTABLE`
        additionally demands an `unacceptable_streak` of at least two — a
        single unacceptable response never suffices to close a recommendation
        unfavorably, and the attempt is rejected with
        `ERR_UNACCEPTABLE_STREAK_INSUFFICIENT`." PRD §3.7: "any closed status
        rejects responses with the same error" (`ERR_RECOMMENDATION_STATE_INVALID`).

        Design: Corner/validations/close_unacceptable_requires_streak_of_two
        """
        ctx = setup_analysis_with_recommendation()
        rec_id = ctx["recommendation"]["id"]
        org_id = ctx["org"]["id"]

        rec = respond_and_classify(rec_id, org_id, "UNACCEPTABLE",
                                   response_text="We disagree with the finding.")
        assert rec["unacceptable_streak"] == 1

        resp = api.close_recommendation(
            rec_id, close_recommendation_payload("CLOSED_UNACCEPTABLE"), MD_PROPOSER
        )
        validate_error(resp, ApiErrorId.ERR_UNACCEPTABLE_STREAK_INSUFFICIENT)

        rec = respond_and_classify(rec_id, org_id, "UNACCEPTABLE",
                                   response_text="We still decline to act.")
        assert rec["unacceptable_streak"] == 2

        rec = close_recommendation(rec_id, "CLOSED_UNACCEPTABLE")
        assert rec["status"] == "CLOSED_UNACCEPTABLE"

        # A closed recommendation rejects further responses.
        resp = api.submit_response(
            rec_id,
            recommendation_response_payload("Late change of heart."),
            make_addressee_contact_headers(org_id),
        )
        validate_error(resp, ApiErrorId.ERR_RECOMMENDATION_STATE_INVALID)


class TestAgingDualVariant:
    def test_aging_variants_at_eighty_three_calendar_days(self, api):
        """PRD §3.7: "`calendar_elapsed_days` counts whole days elapsed since
        issuance. `business_elapsed_days` counts, at date granularity, the days
        after the issuance date up to and including the current day whose
        weekday is Monday through Friday, with no holiday calendar consulted."
        PRD §3.7: "`aging_bucket` triages the open workload: `GREEN` below
        sixty business days, `AMBER` from sixty through eighty-nine inclusive,
        and `RED` at ninety business days or beyond."

        Design: Difficulty/dual_variant_calc/dual_variant_recommendation_aging_calendar_vs_business
        """
        ctx = setup_analysis_with_recommendation()
        rec_id = ctx["recommendation"]["id"]
        # Issued at the initial logical clock (2026-09-01, a Tuesday).
        assert ctx["recommendation"]["issued_at"].startswith("2026-09-01T00:00:00")

        set_clock("2026-11-23T00:00:00Z")
        rec = get_recommendation(rec_id)
        # 83 calendar days but only 59 business days (Mon-Fri) since issuance.
        assert rec["calendar_elapsed_days"] == 83
        assert rec["business_elapsed_days"] == 59
        assert rec["aging_bucket"] == "GREEN", "59 business days is below the AMBER floor"
        assert rec["overdue"] is False

    def test_aging_variants_diverge_and_bucket_follows_business_days(self, api):
        """PRD §3.7: "`aging_bucket` triages the open workload: `GREEN` below
        sixty business days, `AMBER` from sixty through eighty-nine inclusive,
        and `RED` at ninety business days or beyond" — the bucket follows the
        business-day variant, which disagrees with the calendar count at the
        same clock (84 calendar vs 60 business days here).

        Design: Difficulty/dual_variant_calc/dual_variant_recommendation_aging_calendar_vs_business
        """
        ctx = setup_analysis_with_recommendation()
        rec_id = ctx["recommendation"]["id"]

        set_clock("2026-11-24T00:00:00Z")
        rec = get_recommendation(rec_id)
        assert rec["calendar_elapsed_days"] == 84
        assert rec["business_elapsed_days"] == 60
        # 60 >= 60 hits the inclusive AMBER lower bound even though the
        # calendar variant reads 84.
        assert rec["aging_bucket"] == "AMBER"
        assert rec["overdue"] is False


class TestOverdueBoundary:
    def test_exactly_ninety_days_is_not_overdue(self, api):
        """PRD §3.7: "`overdue` is true exactly when more than ninety calendar
        days have elapsed — precisely ninety days is not overdue — and the
        recommendation is not in one of the three closed states."

        Design: Difficulty/boundary_precision_check/boundary_overdue_strictly_greater_than_ninety_days
        """
        ctx = setup_analysis_with_recommendation()
        rec_id = ctx["recommendation"]["id"]

        set_clock("2026-11-30T00:00:00Z")
        rec = get_recommendation(rec_id)
        assert rec["calendar_elapsed_days"] == 90
        assert rec["overdue"] is False, "the strict > comparison spares exactly 90"
        # Aging never mutates lifecycle state.
        assert rec["status"] == "OPEN_AWAITING_RESPONSE"

    def test_ninety_one_days_is_overdue(self, api):
        """PRD §3.7: "`overdue` is true exactly when more than ninety calendar
        days have elapsed — precisely ninety days is not overdue — and the
        recommendation is not in one of the three closed states."

        Design: Difficulty/boundary_precision_check/boundary_overdue_strictly_greater_than_ninety_days
        """
        ctx = setup_analysis_with_recommendation()
        rec_id = ctx["recommendation"]["id"]

        set_clock("2026-12-01T00:00:00Z")
        rec = get_recommendation(rec_id)
        assert rec["calendar_elapsed_days"] == 91
        assert rec["overdue"] is True
        assert rec["status"] == "OPEN_AWAITING_RESPONSE"


class TestAddresseeIdentity:
    def test_addressee_contact_of_wrong_org_cannot_respond(self, api):
        """PRD §2.1: "An `AddresseeContact` response requires `X-User-ID` to
        equal the recommendation's `addressee_org_id`, else
        `ERR_NOT_ADDRESSEE`."

        Design: Corner/rbac/addressee_contact_of_wrong_org_cannot_respond
        """
        ctx = setup_analysis_with_recommendation()
        rec_id = ctx["recommendation"]["id"]
        other_org = create_org(legal_name="Piedmont Airframe Works", org_type="MANUFACTURER")

        resp = api.submit_response(
            rec_id,
            recommendation_response_payload("We are not the addressee but will answer anyway."),
            make_addressee_contact_headers(other_org["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_ADDRESSEE)

        rec = get_recommendation(rec_id)
        assert rec["response_log"] == []
        assert rec["status"] == "OPEN_AWAITING_RESPONSE"
