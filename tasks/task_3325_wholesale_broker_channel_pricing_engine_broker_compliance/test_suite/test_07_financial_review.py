"""Financial review scoring, the tier ladder and volume-expectation banding."""
from test_helpers import (
    ANY,
    ApiErrorId,
    financial_strength_score,
    get_broker,
    record_and_pass_financial_review,
    record_financial_review,
    request_and_approve_eligibility,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    approve_broker,
    create_submitted_broker,
    record_license,
    set_clock,
)
from test_helpers.test_users import TEST_USERS, make_channel_manager_headers


def test_pending_review_shows_its_score_but_leaves_the_broker_untouched(api):
    """PRD §3.2: "The review is created in `PENDING` status, and its
    `computed_financial_strength_score` is calculated and stored immediately — but the broker's
    own `financial_strength_score` is untouched at this point."
    PRD §3.2: "A pending review leaves the broker exactly where it was, even though the review
    row itself displays a score."

    Design: Difficulty/dual_variant_calc/broker_score_review_basis_vs_declared_basis
    """
    broker = create_submitted_broker(home_state="TX")
    b = broker["id"]
    record_license(b, state_code="TX")
    assert get_broker(b)["financial_strength_score"] == 0.00

    review = record_financial_review(b)
    assert review["status"] == "PENDING"
    expected = financial_strength_score(100_000_000, 40_000_000, 0, 5)
    assert expected == 100.00
    assert review["computed_financial_strength_score"] == expected

    refreshed = get_broker(b)
    assert float(refreshed["financial_strength_score"]) == 0.00, (
        "the declared-basis interpretation would have installed the score at creation"
    )
    assert refreshed["tier"] == "UNRATED"

    passed, meta = validate_paginated(
        api_client.list_financial_reviews(b, TEST_USERS["any_headers"], {"status": "PASSED"})
    )
    assert passed == [] and meta["total_count"] == 0


def test_passing_the_review_installs_the_score_and_recomputes_the_tier(api):
    """PRD §3.2: "When those hold, the review becomes `PASSED`, the broker's
    `financial_strength_score` is overwritten with the review's `computed_financial_strength_score`,
    the broker's `tier` is recomputed from the new score"
    PRD §3.2: "A score of at least 85.00 yields `TIER_1`"

    Design: Difficulty/dual_variant_calc/broker_score_review_basis_vs_declared_basis
    """
    broker = create_submitted_broker(home_state="TX")
    b = broker["id"]
    record_license(b, state_code="TX")
    review = record_financial_review(b)

    decided = validate_success(
        api_client.decide_financial_review(review["id"], {"outcome": "PASSED"},
                                           make_channel_manager_headers())
    )
    assert decided["status"] == "PASSED"
    assert decided["is_current"] is True

    after = get_broker(b)
    assert after["financial_strength_score"] == 100.00
    assert after["tier"] == "TIER_1"


def test_unattested_review_defaults_to_false_and_cannot_pass(api):
    """PRD §3.2: "a boolean `audit_attested` that defaults to false."
    PRD §3.2: "the review must have `audit_attested` true — an unattested review can never pass,
    and the attempt is refused with `ERR_FINANCIAL_REVIEW_PENDING`"

    Design: Corner/entities/financial_review_audit_attested_defaults_to_false
    """
    broker = create_submitted_broker(home_state="TX")
    b = broker["id"]
    record_license(b, state_code="TX")

    review = validate_success(
        api_client.create_financial_review(
            b,
            {
                "net_worth_cents": 100_000_000, "liquidity_cents": 40_000_000,
                "total_liabilities_cents": 0, "years_in_business": 5,
                "prior_year_funded_volume_cents": 100_000_000,
            },
            make_channel_manager_headers(),
        ),
        expected_status=201,
    )
    assert review["audit_attested"] is False, "not null"
    assert review["computed_financial_strength_score"] == 100.00

    response = api_client.decide_financial_review(
        review["id"], {"outcome": "PASSED"}, make_channel_manager_headers()
    )
    validate_error(response, ApiErrorId.ERR_FINANCIAL_REVIEW_PENDING, expected_status=409)

    unchanged = validate_success(api_client.get_broker(b, ANY))
    assert unchanged["financial_strength_score"] == 0.00


def test_a_below_expectation_band_caps_a_tier_one_result_down(api):
    """PRD §3.2: "A score of at least 85.00 yields `TIER_1`"
    PRD §3.2: "when the broker's current `PASSED` review (the row whose `is_current` is true)
    has a band other than `MEETS_EXPECTATION`, a computed `TIER_1` is capped down to `TIER_2`."

    Design: Corner/calculations/broker_tier_banded_score_with_volume_cap
    """
    broker = create_submitted_broker(home_state="TX")
    b = broker["id"]
    record_license(b, state_code="TX")

    # net worth 300M saturates the net-worth term; 0 liabilities, 5 years -> a 100.00 score.
    review = record_financial_review(
        b, net_worth_cents=300_000_000, liquidity_cents=40_000_000,
        total_liabilities_cents=0, years_in_business=5,
        prior_year_funded_volume_cents=50_000_000,
    )
    assert review["computed_financial_strength_score"] == 100.00
    validate_success(
        api_client.decide_financial_review(review["id"], {"outcome": "PASSED"},
                                           make_channel_manager_headers())
    )
    approved = approve_broker(b)

    assert approved["financial_strength_score"] == 100.00
    assert approved["tier"] == "TIER_2", "BELOW_EXPECTATION volume caps TIER_1 down to TIER_2"

    fetched = validate_success(api_client.get_broker(b, ANY))
    assert fetched["tier"] == "TIER_2"

    current, meta = validate_paginated(
        api_client.list_financial_reviews(b, TEST_USERS["any_headers"], {"status": "PASSED"})
    )
    assert meta["total_count"] == 1
    assert current[0]["is_current"] is True


def test_a_passed_review_cannot_be_decided_again(api):
    """PRD §3.2: "A review that is not `PENDING` can no longer be decided and yields
    `ERR_REVIEW_ALREADY_DECIDED`."

    Design: Corner/state_machines/expired_license_cannot_be_revoked_and_financial_review_terminal_lockdown
    """
    broker = create_submitted_broker(home_state="TX")
    b = broker["id"]
    record_license(b, state_code="TX", expires_on="2026-10-01T00:00:00Z")
    review = record_and_pass_financial_review(b)
    set_clock("2026-10-05T00:00:00Z")

    response = api_client.decide_financial_review(
        review["id"], {"outcome": "FAILED"}, make_channel_manager_headers()
    )
    validate_error(response, ApiErrorId.ERR_REVIEW_ALREADY_DECIDED, expected_status=409)
    assert get_broker(b)["financial_strength_score"] == 100.00


def test_a_failed_review_leaves_the_broker_score_alone(api):
    """PRD §3.2: "the review becomes `FAILED`, its `is_current` stays false, and the broker's
    `financial_strength_score` is not updated at all by a failed review."

    Design: Corner/state_machines/expired_license_cannot_be_revoked_and_financial_review_terminal_lockdown
    """
    broker = create_submitted_broker(home_state="TX")
    b = broker["id"]
    record_license(b, state_code="TX")
    review = record_financial_review(b)

    decided = validate_success(
        api_client.decide_financial_review(review["id"], {"outcome": "FAILED"},
                                           make_channel_manager_headers())
    )
    assert decided["status"] == "FAILED"
    assert decided["is_current"] is False
    assert get_broker(b)["financial_strength_score"] == 0.00