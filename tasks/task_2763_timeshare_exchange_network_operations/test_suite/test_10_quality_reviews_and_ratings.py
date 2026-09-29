"""Post-stay reviews: the completion gate, the two-stage score and uniqueness."""

from test_helpers import (
    ANALYST_HEADERS,
    ApiErrorId,
    assert_decimal_equals,
    assert_quality_review,
    bank_deposit,
    confirm_request,
    factories,
    file_exchange_request,
    file_quality_review,
    list_page,
    list_quality_reviews,
    make_member_headers,
    read_confirmation,
    read_member,
    read_resort,
    run_matching,
    set_clock,
    setup_confirmed_exchange,
    setup_market,
    validate_error,
    validate_success,
)

CANONICAL_WINDOW = {
    "window_start_date": "2027-06-01",
    "window_end_date": "2027-06-30",
    "member_count": 2,
}
BRONZE_WINTER = {
    "band_code": "BRONZE",
    "start_month_day": "11-01",
    "end_month_day": "12-31",
}


def _completed_stay():
    """The canonical exchange carried past the seven stay nights by a second run."""
    scenario = setup_confirmed_exchange(**CANONICAL_WINDOW)
    assert scenario["confirmation"]["status"] == "CONFIRMED"
    assert scenario["confirmation"]["awarded_check_in_date"] == "2027-06-15"
    set_clock("2027-06-22T00:00:00Z")
    scenario["completion_run"] = run_matching("complete the stay")
    return scenario


def _two_completed_bronze_stays():
    """Two STUDIO stays at one resort, both completed, ready to be reviewed."""
    market = setup_market(
        member_count=2,
        extra_bands=(BRONZE_WINTER,),
    )
    m1, m2 = market["members"][0], market["members"][1]
    resort_id = market["resort"]["id"]

    early = bank_deposit(
        m1["id"], resort_id, unit_size="STUDIO", check_in_date="2026-12-05"
    )
    late = bank_deposit(
        m1["id"], resort_id, unit_size="STUDIO", check_in_date="2026-12-20"
    )
    for week in (early, late):
        assert week["season_band_code"] == "BRONZE"
        assert week["awarded_power"] == 29, (
            "30 * 0.70 * 1.10 = 23.1 -> 23, plus 6 is 29, lead factor 1.00"
        )

    funding = bank_deposit(
        m2["id"], resort_id, unit_size="TWO_BR", check_in_date="2027-05-10"
    )
    assert funding["awarded_power"] == 107

    requests = []
    for start, end in (("2026-12-01", "2026-12-10"), ("2026-12-15", "2026-12-25")):
        request = file_exchange_request(
            m2["id"], resort_id, requested_unit_size="STUDIO",
            window_start_date=start, window_end_date=end,
            deposit_id=funding["id"],
        )
        assert request["required_power_estimate"] == 29
        assert request["power_budget"] == 117
        assert request["quoted_charge_cents"] == 23060
        requests.append(request)

    run_matching("pair each winter request with its week")
    confirmations = [confirm_request(m2["id"], request["id"]) for request in requests]

    set_clock("2026-12-27T00:00:00Z")
    completion_run = run_matching("complete both winter stays")

    return {
        "resort_id": resort_id,
        "m1": m1,
        "m2": m2,
        "weeks": (early, late),
        "confirmations": confirmations,
        "completion_run": completion_run,
    }


class TestReviewGatedOnCompletion:
    def test_a_review_before_the_completion_sweep_is_refused(self, api):
        """A CONFIRMED confirmation is not yet a stay that can be rated.

        PRD §3.8: "That confirmation must be owned by the reviewing member and
        must be `COMPLETED`, an incomplete stay being refused with
        `ERR_STAY_NOT_COMPLETED`"

        Design: Difficulty/cross_entity_state_dependency/quality_review_blocked_until_confirmation_completed
        """
        scenario = setup_confirmed_exchange(**CANONICAL_WINDOW)
        resort = read_resort(scenario["resort"]["id"])

        response = api.create_quality_review(
            resort["id"],
            factories.quality_review_payload(
                scenario["confirmation"]["id"], resort["version"]
            ),
            make_member_headers(scenario["m2"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_STAY_NOT_COMPLETED.value, 409)

        _, meta = list_quality_reviews(resort_id=resort["id"])
        assert meta["total_count"] == 0

    def test_the_same_review_is_accepted_once_the_run_completes_the_stay(self, api):
        """Step 4 flips the third entity and the identical call then succeeds.

        PRD §3.5: "Every confirmation whose `status` is `CONFIRMED` and whose
        `awarded_check_in_date` plus seven stay nights is not later than the
        calendar date of `as_of_utc` moves `CONFIRMED` → `COMPLETED` ... Completion
        is what unlocks the post-stay quality review of §3.8"

        Design: Difficulty/cross_entity_state_dependency/quality_review_blocked_until_confirmation_completed
        """
        scenario = _completed_stay()
        assert scenario["completion_run"]["completed_confirmation_count"] == 1
        completed = read_confirmation(scenario["confirmation"]["id"])
        assert completed["status"] == "COMPLETED"

        resort = read_resort(scenario["resort"]["id"])
        review = validate_success(
            api.create_quality_review(
                resort["id"],
                factories.quality_review_payload(completed["id"], resort["version"]),
                make_member_headers(scenario["m2"]["id"]),
            ),
            201,
        )
        assert_quality_review(review)
        assert_decimal_equals(review["composite_score"], "8.15", "composite_score")

        after = read_resort(resort["id"])
        assert after["review_count"] == 1
        assert after["quality_score"] is None, "fewer than the two reviews required"
        assert after["quality_rating"] == "GOLD_CROWN", (
            "still the operator's initial rating"
        )

        _, meta = list_quality_reviews(confirmation_id=completed["id"])
        assert meta["total_count"] == 1


class TestQualityScoreIsAMeanOfComposites:
    def test_the_second_review_publishes_the_mean_of_the_rounded_composites(self, api):
        """6.95 is the mean of 8.15 and 5.75, and it drops the resort two rungs.

        PRD §3.8: "From the second review onward, `quality_score` is the mean of
        the window's `composite_score` values — their sum divided by the number of
        reviews in the window — rounded half up to two decimal places. Note
        carefully that the mean is taken over the *already-rounded* per-review
        composites, never over their raw weighted sums."

        Design: Corner/calculations/resort_quality_score_mean_of_composites_sets_standard_rating
        """
        market = _two_completed_bronze_stays()
        assert market["completion_run"]["completed_confirmation_count"] == 2
        for confirmation in market["confirmations"]:
            assert read_confirmation(confirmation["id"])["status"] == "COMPLETED"

        first = file_quality_review(
            market["resort_id"],
            market["m2"]["id"],
            market["confirmations"][0]["id"],
            read_resort(market["resort_id"])["version"],
            cleanliness_score=9,
            service_score=8,
            amenities_score=7,
        )
        assert_decimal_equals(first["composite_score"], "8.15", "composite_score")

        after_first = read_resort(market["resort_id"])
        assert after_first["review_count"] == 1
        assert after_first["quality_score"] is None, "one review is below the minimum"
        assert after_first["quality_rating"] == "GOLD_CROWN"

        second = file_quality_review(
            market["resort_id"],
            market["m2"]["id"],
            market["confirmations"][1]["id"],
            after_first["version"],
            cleanliness_score=6,
            service_score=6,
            amenities_score=5,
        )
        assert_decimal_equals(
            second["composite_score"], "5.75", "composite_score"
        )

        after_second = read_resort(market["resort_id"])
        assert after_second["review_count"] == 2
        assert_decimal_equals(
            after_second["quality_score"], "6.95", "quality_score"
        )
        assert after_second["quality_rating"] == "STANDARD", (
            "6.95 selects the 5.00 band, two rungs below GOLD_CROWN, in one call"
        )
        assert after_second["downgrade_notches"] == 0
        assert after_second["complaint_strikes"] == 0, (
            "the drop came from the score bands alone, not from a dispute penalty"
        )

    def test_the_two_stays_cost_the_exchanging_member_what_the_quotes_said(self, api):
        """The scoring scenario's cash and power arithmetic is the ordinary one.

        PRD §3.6: "Two ledger entries may be written. The first is unconditional:
        an `EXCHANGE_DEBIT` taking `settlement_power` from the confirming member."

        Design: Corner/calculations/resort_quality_score_mean_of_composites_sets_standard_rating
        """
        market = _two_completed_bronze_stays()

        seeker = read_member(market["m2"]["id"])
        assert seeker["trading_power_balance"] == 49, "107 credited, 29 and 29 debited"
        assert seeker["wallet_credit_cents"] == 33980, "80100 less two 23060 charges"


class TestDuplicateReviewRejected:
    def test_a_second_review_of_the_same_confirmation_is_refused(self, api):
        """Uniqueness is on confirmation_id, and a fresh OCC token cannot buy a pass.

        PRD §3.8: "at most one review may exist per `confirmation_id`, a second
        attempt being refused with `ERR_DUPLICATE_QUALITY_REVIEW`"

        Design: Corner/validations/duplicate_quality_review_for_the_same_confirmation_is_rejected
        """
        scenario = _completed_stay()
        assert scenario["completion_run"]["completed_confirmation_count"] == 1
        confirmation = read_confirmation(scenario["confirmation"]["id"])
        assert confirmation["status"] == "COMPLETED"

        first = file_quality_review(
            scenario["resort"]["id"],
            scenario["m2"]["id"],
            confirmation["id"],
            read_resort(scenario["resort"]["id"])["version"],
        )
        assert_decimal_equals(first["composite_score"], "8.15", "composite_score")

        current = read_resort(scenario["resort"]["id"])
        response = api.create_quality_review(
            current["id"],
            factories.quality_review_payload(confirmation["id"], current["version"]),
            make_member_headers(scenario["m2"]["id"]),
        )
        validate_error(
            response, ApiErrorId.ERR_DUPLICATE_QUALITY_REVIEW.value, 409
        )

    def test_the_duplicate_never_double_counts_the_rating_state(self, api):
        """review_count stays at 1, so the score and the band are untouched.

        PRD §3.8: "The resort's own figures are recomputed after every review.
        `review_count` is the number of that resort's reviews."

        Design: Corner/validations/duplicate_quality_review_for_the_same_confirmation_is_rejected
        """
        scenario = _completed_stay()
        confirmation = read_confirmation(scenario["confirmation"]["id"])
        file_quality_review(
            scenario["resort"]["id"],
            scenario["m2"]["id"],
            confirmation["id"],
            read_resort(scenario["resort"]["id"])["version"],
        )
        current = read_resort(scenario["resort"]["id"])
        validate_error(
            api.create_quality_review(
                current["id"],
                factories.quality_review_payload(
                    confirmation["id"], current["version"]
                ),
                make_member_headers(scenario["m2"]["id"]),
            ),
            ApiErrorId.ERR_DUPLICATE_QUALITY_REVIEW.value,
            409,
        )

        _, meta = list_quality_reviews(confirmation_id=confirmation["id"])
        assert meta["total_count"] == 1

        after = read_resort(scenario["resort"]["id"])
        assert after["review_count"] == 1
        assert after["quality_score"] is None
        assert after["quality_rating"] == "GOLD_CROWN"

        _, all_reviews = list_page(api.list_quality_reviews(ANALYST_HEADERS))
        assert all_reviews["total_count"] == 1
