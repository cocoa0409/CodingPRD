"""The engagement fee-allocation waterfall: tiering, rounding order and conservation."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    assert_engagement_letter,
    TEST_USERS,
    fixtures,
)

CO = TEST_USERS["compliance_officer_headers"]
EM = TEST_USERS["engagement_manager_headers"]


def test_single_request_share_uses_the_whole_share_tier_not_a_blended_tier(api):
    """PRD §3.2: "when the base share is at least 2,500,000 cents but below
    10,000,000 cents the multiplier is 0.95"
    PRD §3.2: "The raw allocated amount is the base share multiplied by the tier
    multiplier, and `allocated_fee_cents` is that raw amount rounded half-up to
    whole cents"

    Design: Difficulty/dual_variant_calc/fee_allocation_marginal_versus_blended_tier
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED"], fee_amount_cents=3_000_000
    )
    response = api_client.open_screening(requests[0]["id"], CO)
    screened = validate_success(response, 200)
    assert screened["allocated_fee_cents"] == 2_850_000
    assert screened["request_status"] == "SCREENING"


def test_single_request_share_reads_back_the_whole_share_multiplier(api):
    """PRD §3.2: "The base share is the engagement's `fee_amount_cents`
    multiplied by this request's `instrument_notional_cents` and divided by that
    denominator."
    PRD §3.2: "The raw allocated amount is the base share multiplied by the tier
    multiplier, and `allocated_fee_cents` is that raw amount rounded half-up to
    whole cents"

    Design: Difficulty/dual_variant_calc/fee_allocation_marginal_versus_blended_tier
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SHORT_TERM"], fee_amount_cents=3_000_000
    )
    get_success_data(api_client.open_screening(requests[0]["id"], CO))
    persisted = get_success_data(api_client.get_rating_request(requests[0]["id"], EM))
    assert persisted["allocated_fee_cents"] == 2_850_000
    assert persisted["allocated_fee_cents"] != 2_975_000


def test_share_just_below_and_at_the_tier_ceiling_select_different_multipliers(api):
    """PRD §3.2: "When the base share is below 2,500,000 cents the multiplier is
    the full 1.00"
    PRD §3.2: "when the base share is at least 2,500,000 cents but below
    10,000,000 cents the multiplier is 0.95"

    Design: Difficulty/combinatorial_formula/fee_share_tiered_selection_at_the_ceiling
    """
    entity_lo, engagement_lo, requests_lo = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED"], fee_amount_cents=2_499_999
    )
    entity_hi, engagement_hi, requests_hi = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED"], fee_amount_cents=2_500_000
    )
    get_success_data(api_client.open_screening(requests_lo[0]["id"], CO))
    get_success_data(api_client.open_screening(requests_hi[0]["id"], CO))

    low = get_success_data(api_client.get_rating_request(requests_lo[0]["id"], EM))
    high = get_success_data(api_client.get_rating_request(requests_hi[0]["id"], EM))
    assert low["allocated_fee_cents"] == 2_499_999
    assert high["allocated_fee_cents"] == 2_375_000
    credited = get_success_data(api_client.get_engagement_letter(engagement_hi["id"], EM))
    assert credited["fee_credited_cents"] == 2_375_000


def test_at_ceiling_share_is_credited_to_the_engagement(api):
    """PRD §3.2: "The engagement's `fee_credited_cents` is the sum of
    `allocated_fee_cents` across the letter's requests."

    Design: Difficulty/combinatorial_formula/fee_share_tiered_selection_at_the_ceiling
    """
    entity_lo, engagement_lo, requests_lo = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED"], fee_amount_cents=2_499_999
    )
    entity_hi, engagement_hi, requests_hi = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED"], fee_amount_cents=2_500_000
    )
    get_success_data(api_client.open_screening(requests_lo[0]["id"], CO))
    get_success_data(api_client.open_screening(requests_hi[0]["id"], CO))

    lo_letter = get_success_data(api_client.get_engagement_letter(engagement_lo["id"], EM))
    hi_letter = get_success_data(api_client.get_engagement_letter(engagement_hi["id"], EM))
    assert lo_letter["fee_credited_cents"] == 2_499_999
    assert hi_letter["fee_credited_cents"] == 2_375_000


def test_allocation_rounds_per_request_before_summing(api):
    """PRD §3.2: "The pinned order matters: round each request's own share first
    and sum afterward, never sum the raw unrounded shares and round once,
    because with two or more requests the two orders can differ by a cent"

    Design: Difficulty/combinatorial_formula/fee_allocation_rounding_order_per_request_then_sum
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED", "SHORT_TERM"], fee_amount_cents=10_000_000
    )
    for request in requests:
        get_success_data(api_client.open_screening(request["id"], CO))

    shares = [get_success_data(api_client.get_rating_request(r["id"], EM))["allocated_fee_cents"]
              for r in requests]
    assert shares == [3_166_667, 3_166_667, 3_166_667]
    letter = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert letter["fee_credited_cents"] == 9_500_001


def test_per_request_rounding_leaves_no_reversal_at_open_screening(api):
    """PRD §3.2: "the credited and reversed totals begin at zero and move only as
    requests against the engagement are opened, returned, or terminated."
    PRD §3.2: "The denominator of that waterfall is the sum of the
    `instrument_notional_cents` over all `RatingRequest` rows that share the same
    `engagement_letter_id`"

    Design: Difficulty/combinatorial_formula/fee_allocation_rounding_order_per_request_then_sum
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED", "SHORT_TERM"], fee_amount_cents=10_000_000
    )
    for request in requests:
        get_success_data(api_client.open_screening(request["id"], CO))

    letter = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert_engagement_letter(letter)
    assert letter["fee_reversed_cents"] == 0


def test_reversing_one_allocation_conserves_the_credited_plus_reversed_pool(api):
    """PRD §2.6: "an engagement's credited and reversed fee allocations reconcile
    against the contracted `fee_amount_cents`"
    PRD §3.2: "it reverses the request's `allocated_fee_cents` into the
    engagement's `fee_reversed_cents`"

    Design: Difficulty/compensating_invariant/fee_reversal_conserves_credited_plus_reversed
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED", "SHORT_TERM"], fee_amount_cents=10_000_000
    )
    for request in requests:
        get_success_data(api_client.open_screening(request["id"], CO))
    pre = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    conserved_total = pre["fee_credited_cents"] + pre["fee_reversed_cents"]
    assert conserved_total == 9_500_001

    get_success_data(api_client.return_request_to_submitted(requests[0]["id"], CO))

    post = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert post["fee_credited_cents"] + post["fee_reversed_cents"] == conserved_total
    assert post["fee_reversed_cents"] == 3_166_667


def test_conserved_pool_is_untouched_and_request_returns_to_intake(api):
    """PRD §2.6: "Several quantities are conservative in the accounting sense and
    must balance exactly at every state change"
    PRD §3.2: "it reverses the request's `allocated_fee_cents` into the
    engagement's `fee_reversed_cents` while resetting `allocated_fee_cents` to
    zero."

    Design: Difficulty/compensating_invariant/fee_reversal_conserves_credited_plus_reversed
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED", "SHORT_TERM"], fee_amount_cents=10_000_000
    )
    for request in requests:
        get_success_data(api_client.open_screening(request["id"], CO))
    get_success_data(api_client.return_request_to_submitted(requests[0]["id"], CO))

    reverted_request = get_success_data(api_client.get_rating_request(requests[0]["id"], EM))
    assert reverted_request["allocated_fee_cents"] == 0
    assert reverted_request["request_status"] == "SUBMITTED"
    letter = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert letter["fee_credited_cents"] == 6_333_334


def test_re_screening_restores_the_same_credit_rather_than_doubling_it(api):
    """PRD §3.2: "Because this route exists, a request can be bounced between
    `SUBMITTED` and `SCREENING` as often as intake needs without being
    abandoned."
    PRD §3.2: "The engagement's `fee_credited_cents` is the sum of
    `allocated_fee_cents` across the letter's requests."

    Design: Corner/endpoints/open_screening_recomputes_engagement_fee_credit_idempotently
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED"], fee_amount_cents=10_000_000
    )
    request = requests[0]
    for row in requests:
        get_success_data(api_client.open_screening(row["id"], CO))
    first = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert first["fee_credited_cents"] == 9_500_000

    get_success_data(api_client.return_request_to_submitted(request["id"], CO))
    get_success_data(api_client.open_screening(request["id"], CO))

    final_request = get_success_data(api_client.get_rating_request(request["id"], EM))
    final_letter = get_success_data(api_client.get_engagement_letter(engagement["id"], EM))
    assert final_request["request_status"] == "SCREENING"
    assert final_request["allocated_fee_cents"] == 4_750_000
    assert final_letter["fee_credited_cents"] == 9_500_000, "re-screening restores, not doubles"