"""Corner cases of the composite-score rounding order, the complaint-rate
denominator floor and the two complaint-deadline day bases."""
from test_helpers import (
    CO,
    PO,
    ApiErrorId,
    account_census_payload,
    api_client,
    assert_same_instant,
    create_diligence_review_payload,
    create_partner,
    file_complaint,
    get_success_data,
    pass_diligence,
    read_partner,
    seed_reserve_balance,
    set_clock,
    setup_contracted_partner,
    validate_error,
)


def _open_review(partner, **scores):
    partner = read_partner(partner["id"])
    return get_success_data(
        api_client.create_diligence_review(
            create_diligence_review_payload(partner["id"], partner["version"], **scores),
            PO,
        )
    )


def _report_census(partner_id, count, as_of_date="2026-08-01T00:00:00Z"):
    return get_success_data(
        api_client.report_account_census(
            partner_id,
            account_census_payload(end_user_account_count=count, as_of_date=as_of_date),
            PO,
        )
    )


class TestCompositeRoundingOrder:
    def test_each_weighted_component_rounds_to_two_places_before_the_sum_rounds_to_one(self):
        """Each of the four contributions is then formed **and rounded on its own** to two decimal
        places, half up: the business-model score weighted at 0.20, the funding score weighted at
        0.25, the compliance-capability score weighted at 0.35, and the effective complaint-history
        score weighted at 0.20. Those four already-rounded contributions are added together, and
        only that sum is rounded — half up, to one decimal place — to give `composite_score`.

        Design: Corner/calculations/diligence_composite_rounds_each_weighted_component_to_two_dp_then_the_sum_to_one_dp
        """
        partner = create_partner(
            legal_name="Northbeam Pay Inc",
            business_model="CARD_ISSUING",
            funding_stage="SERIES_B_PLUS",
            months_runway=24,
            disclosed_complaints_per_10k=12.50,
            end_user_account_count=100_000,
        )
        review = _open_review(
            partner,
            review_type="INITIAL",
            business_model_score=80,
            funding_score=80,
            compliance_capability_score=83,
            complaint_history_score=85,
        )
        assert review["composite_score"] == 0.0
        assert review["tier"] == "UNRATED"

        submitted = get_success_data(
            api_client.submit_diligence_review(
                review["id"], {"submission_note": "Rounding-sensitive scorecard."}, PO
            )
        )
        assert submitted["effective_complaint_history_score"] == 85, (
            "an INITIAL review takes the submitted complaint history verbatim"
        )
        assert submitted["composite_score"] == 82.1, (
            "components 16.00 + 20.00 + 29.05 + 17.00 sum to 82.05 and round half up to "
            f"82.1, got {submitted['composite_score']}"
        )
        assert submitted["composite_score"] != 82.0, (
            "truncating or rounding to even would both give 82.0"
        )
        assert submitted["tier"] == "TIER_2", "82.1 clears the 70.0 floor but not the 85.0 floor"


class TestRenewalVariantDiscardsTheSubmittedHistory:
    def test_the_renewal_substitution_drops_the_composite_under_the_pass_floor(self):
        """For a `RENEWAL` review, the submitted `complaint_history_score` is still stored on the
        row but is **not used**: `effective_complaint_history_score` becomes 100 less one point for
        every 5 basis points of the partner's persisted `complaint_rate_bps`, with the basis-point
        quotient taken as a whole number by discarding any fraction, and the result floored at 0 so
        it never goes negative.

        Design: Corner/calculations/renewal_diligence_discards_the_submitted_complaint_history_score_and_fails_the_composite_floor
        """
        partner = create_partner(legal_name="Bluecrest Ledger Inc", end_user_account_count=20)
        initial, partner = pass_diligence(
            partner,
            business_model_score=60,
            funding_score=60,
            compliance_capability_score=60,
            complaint_history_score=100,
            review_type="INITIAL",
        )
        assert initial["effective_complaint_history_score"] == 100
        assert initial["composite_score"] == 68.0, (
            f"12.00 + 15.00 + 21.00 + 20.00, got {initial['composite_score']}"
        )
        assert initial["tier"] == "TIER_3"
        assert partner["status"] == "DILIGENCE_PASSED"
        assert partner["capability_tier"] == "TIER_3"

        _report_census(partner["id"], 20)
        file_complaint(partner["id"], received_at="2026-07-10T00:00:00Z")
        rated = read_partner(partner["id"])
        assert rated["complaint_rate_bps"] == 500, (
            f"one complaint over 20 accounts, got {rated['complaint_rate_bps']}"
        )

        renewal = _open_review(
            partner,
            review_type="RENEWAL",
            business_model_score=60,
            funding_score=60,
            compliance_capability_score=60,
            complaint_history_score=100,
        )
        submitted = get_success_data(api_client.submit_diligence_review(renewal["id"], {}, PO))
        assert submitted["complaint_history_score"] == 100, (
            "the submitted value is still stored, merely unused"
        )
        assert submitted["effective_complaint_history_score"] == 0, (
            "100 less floor(500/5) is 0, floored at 0"
        )
        assert submitted["composite_score"] == 48.0, (
            f"12.00 + 15.00 + 21.00 + 0.00, got {submitted['composite_score']}"
        )
        assert submitted["tier"] == "UNRATED"

        refused = api_client.decide_diligence_review(
            renewal["id"], {"outcome": "PASSED"}, CO
        )
        validate_error(refused, ApiErrorId.ERR_DILIGENCE_SCORE_BELOW_FLOOR, 422)

        after = read_partner(partner["id"])
        assert after["status"] == "IN_DILIGENCE"
        assert after["capability_tier"] == "TIER_3", "the earlier pass is untouched"
        assert after["latest_composite_score"] == 68.0


class TestComplaintRateDenominator:
    def test_a_never_filed_census_floors_the_denominator_at_one_account(self):
        """The denominator is `end_user_account_count`, or 1 if that value is smaller than 1. The
        rate is the numerator multiplied by 10000, divided by the denominator, rounded half up to a
        whole number of basis points. A partner that has never filed a census therefore has a
        denominator floor of 1, so a single complaint alone drives the rate to 10000 basis points.

        Design: Corner/calculations/complaint_rate_uses_a_denominator_floor_of_one_when_no_census_was_ever_filed
        """
        partner = create_partner(legal_name="Driftwood Pay Inc", end_user_account_count=0)
        assert read_partner(partner["id"])["complaint_rate_bps"] == 0, (
            "no complaints leaves the numerator at 0 whatever the floor does"
        )

        complaint = file_complaint(partner["id"], received_at="2026-07-10T00:00:00Z")
        assert complaint["handling_owner"] == "BANK", (
            "the computed default applies because no executed agreement exists"
        )
        floored = read_partner(partner["id"])
        assert floored["complaint_rate_bps"] == 10_000, (
            f"one complaint over max(1, 0) accounts, got {floored['complaint_rate_bps']}"
        )

        censused = _report_census(partner["id"], 100_000)
        assert censused["end_user_account_count"] == 100_000
        assert censused["complaint_rate_bps"] == 0, (
            f"the same complaint over 100000 accounts rounds to 0, got "
            f"{censused['complaint_rate_bps']}"
        )
        still = get_success_data(api_client.get_complaint(complaint["id"], PO))
        assert still["status"] == "RECEIVED", "the census rescaled the rate without touching the row"

    def test_the_restrict_rung_is_inclusive_at_two_hundred_and_fifty_basis_points(self):
        """Otherwise the posture becomes `RESTRICTED` if `complaint_rate_bps` has reached 250, or
        `unreconciled_variance_cents` has reached 5,000,000 cents (fifty thousand dollars of
        unexplained settlement variance), or `growth_breach_count` has reached 2. Every one of those
        thresholds is inclusive. A complaint rate of exactly 250 basis points yields `RESTRICTED`;
        249 basis points yields `HEIGHTENED`.

        Design: Corner/calculations/the_complaint_rate_restrict_threshold_is_inclusive_at_exactly_two_hundred_fifty_bps
        """
        ctx = setup_contracted_partner(
            partner_overrides={"legal_name": "Alderway Pay Inc", "end_user_account_count": 40}
        )
        partner_id = ctx["partner"]["id"]
        seed_reserve_balance(partner_id, ctx["reserve"], 312_500)
        assert read_partner(partner_id)["reserve_shortfall_cents"] == 0

        _report_census(partner_id, 40)
        set_clock("2026-08-03T12:00:00Z")
        complaint = file_complaint(
            partner_id,
            channel="STATE_AG",
            category="DISCLOSURE",
            severity="HIGH",
            received_at="2026-08-03T09:30:00Z",
            narrative="a state attorney general inquiry about the fee schedule",
        )
        assert_same_instant(
            complaint["response_due_at"], "2026-08-17T23:59:59.999Z", "response_due_at"
        )

        at_250 = read_partner(partner_id)
        assert at_250["complaint_rate_bps"] == 250, at_250["complaint_rate_bps"]
        assert at_250["oversight_posture"] == "RESTRICTED", "the 250 bps rung is inclusive"
        assert at_250["reserve_shortfall_cents"] == 0

        at_244 = _report_census(partner_id, 41)
        assert at_244["complaint_rate_bps"] == 244, (
            f"one complaint over 41 accounts is 243.902... which rounds half up to 244, got "
            f"{at_244['complaint_rate_bps']}"
        )
        assert at_244["oversight_posture"] == "HEIGHTENED", (
            "244 is under the restrict rung but at or above the 120 bps heighten rung"
        )
        assert at_244["reserve_shortfall_cents"] == 0, (
            "the HEIGHTENED reading comes from the complaint rate, not from the reserve"
        )


class TestBusinessAndCalendarDayBases:
    def test_a_saturday_and_the_following_monday_share_one_business_day_deadline(self):
        """A visible consequence of the midnight anchor is that a Saturday intake and the following
        Monday intake on the same channel produce **the same** due date. For these,
        `response_due_at` is simply `received_at` advanced by that many days as straight instant
        arithmetic — weekends are consumed like any other day, and the time of day of `received_at`
        is preserved exactly.

        Design: Corner/calculations/a_saturday_and_the_following_monday_intake_share_one_business_basis_due_date
        """
        partner = create_partner(legal_name="Quillon Wallet Inc", end_user_account_count=50_000)
        set_clock("2026-08-16T12:00:00Z")

        saturday = file_complaint(
            partner["id"],
            channel="SOCIAL",
            category="FEES",
            severity="MEDIUM",
            received_at="2026-08-01T09:30:00Z",
            narrative="a weekend post complaining about a surprise fee",
        )
        monday = file_complaint(
            partner["id"],
            channel="SOCIAL",
            category="FEES",
            severity="MEDIUM",
            received_at="2026-08-03T09:30:00Z",
            narrative="the same grievance posted again on the Monday",
        )
        calendar = file_complaint(
            partner["id"],
            channel="CFPB_PORTAL",
            category="FEES",
            severity="MEDIUM",
            received_at="2026-08-01T09:30:00Z",
            narrative="the same grievance routed through the regulator portal",
        )

        assert_same_instant(
            saturday["response_due_at"], "2026-08-10T23:59:59.999Z", "saturday due"
        )
        assert_same_instant(monday["response_due_at"], "2026-08-10T23:59:59.999Z", "monday due")
        assert_same_instant(
            calendar["response_due_at"], "2026-08-16T09:30:00.000Z", "calendar due"
        )
        assert saturday["response_due_at"] != calendar["response_due_at"], (
            "the two day bases diverge from the very same intake instant"
        )
