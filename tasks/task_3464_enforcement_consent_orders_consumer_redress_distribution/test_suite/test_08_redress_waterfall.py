"""Redress waterfall: provisional vs final awards, pinned evaluation order,
floor-then-remainder rounding, loss cap, and the claims-close gate."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    approve_claim,
    close_claims_window,
    compute_waterfall,
    file_claim,
    get_claim,
    get_fund,
    make_claimant_specs,
    move_claim_under_review,
    redress_fund_transition_payload,
    setup_fund_with_approved_claims,
    setup_open_fund,
    start_disbursing,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["fund_administrator_headers"]  # fa-1

# Where the remainder-cent recipient depends on claim creation order, filings
# are separated by one logical day so created_at strictly orders them (PRD
# compares timestamps at second precision). Clock stays monotonic per test.
_DAY2 = "2026-10-02T00:00:00Z"
_DAY3 = "2026-10-03T00:00:00Z"


def _setup_two_approved_claims(judgment=3_000_000):
    """Fund OPEN_FOR_CLAIMS with claim A (loss 3,000,000, created on _DAY1)
    approved first and claim B (loss 1,000,000, created on _DAY2) approved
    second — strict created_at ordering pins the remainder cent to A."""
    bundle = setup_open_fund(
        judgment_amount_cents=judgment,
        monetary_relief_cents=judgment,
        claimant_specs=make_claimant_specs(2),
    )
    claim_a = file_claim(bundle["claimants"][0], 3_000_000)
    a_at_approval = approve_claim(claim_a["id"])
    advance_clock(_DAY2)
    claim_b = file_claim(bundle["claimants"][1], 1_000_000)
    approve_claim(claim_b["id"])
    bundle["claim_a"] = claim_a
    bundle["claim_b"] = claim_b
    bundle["a_provisional_at_approval"] = a_at_approval["provisional_award_cents"]
    bundle["fund"] = get_fund(bundle["fund"]["id"])
    return bundle


def test_claim_provisional_award_shrinks_at_final_waterfall():
    """PRD section 3.6: "Because provisional awards are recomputed on every
    approval against the current `APPROVED` set and the current collections,
    an early-approved claim's provisional award can shrink as later claims are
    approved against the same pool; nothing is final until disbursement."
    PRD section 3.7: "the final variant runs exactly once, against the frozen
    `APPROVED` set and the frozen collection figure, and writes
    `final_award_cents` onto every `APPROVED` claim, never to be recomputed."

    Design: Difficulty/dual_variant_calc/claim_provisional_award_shrinks_at_final_waterfall
    """
    bundle = _setup_two_approved_claims()
    assert bundle["a_provisional_at_approval"] == 2_500_000, (
        "sole approved claim: eligible 2,500,000, reserve 250,000, pool 2,750,000 covers it"
    )

    close_claims_window(bundle["fund"]["id"])
    start_disbursing(bundle["fund"]["id"])

    claim_a = get_claim(bundle["claim_a"]["id"])
    claim_b = get_claim(bundle["claim_b"]["id"])
    assert claim_a["final_award_cents"] == 1_892_858
    assert claim_b["final_award_cents"] == 757_142
    assert bundle["a_provisional_at_approval"] != claim_a["final_award_cents"], (
        "the provisional variant priced against the early approved set, the final "
        "variant against the frozen set"
    )


def test_waterfall_floor_per_claim_then_remainder_cent_by_created_at():
    """PRD section 2.7: "individual awards are floored to whole cents per claim
    *first*, and only then is the leftover remainder distributed one cent at a
    time to claims in `created_at` ascending order — earliest approved claim
    first, never ordered by `id`."

    Design: Difficulty/combinatorial_formula/waterfall_floor_per_claim_then_remainder_cent_by_created_at
    """
    bundle = _setup_two_approved_claims()
    fund_id = bundle["fund"]["id"]

    closed = close_claims_window(fund_id)
    assert closed["status"] == "CLAIMS_CLOSED"
    disbursing = start_disbursing(fund_id)
    assert disbursing["distributable_pool_cents"] == 2_650_000, (
        "3,000,000 collected - 350,000 reserve"
    )

    claim_a = get_claim(bundle["claim_a"]["id"])
    claim_b = get_claim(bundle["claim_b"]["id"])
    # floor(2650000*2500000/3500000) = 1892857; A is earliest-created, so the
    # 1-cent remainder lands on A: 1892858. B floors to 757142 exactly.
    expected = compute_waterfall(3_000_000, [2_500_000, 1_000_000])
    assert expected["awards_cents"] == [1_892_858, 757_142]
    assert claim_a["final_award_cents"] == 1_892_858
    assert claim_b["final_award_cents"] == 757_142
    total = claim_a["final_award_cents"] + claim_b["final_award_cents"]
    assert total == 2_650_000 == get_fund(fund_id)["distributable_pool_cents"], (
        "no cent may be created or destroyed by rounding"
    )


def test_distributable_pool_reserve_computed_from_eligible_not_pool():
    """PRD section 3.6: "The administration reserve is the smaller of two
    figures: ten percent of the total eligible loss, rounded up to a whole
    cent, and the fixed reserve cap of 500,000 cents." and "The distributable
    pool is the fund's `total_collected_cents` minus the administration
    reserve."

    Design: Difficulty/combinatorial_formula/distributable_pool_reserve_computed_from_eligible_not_pool
    """
    bundle = setup_fund_with_approved_claims(
        [3_000_000, 1_000_000],
        judgment_amount_cents=3_000_000,
        monetary_relief_cents=3_000_000,
    )
    closed = close_claims_window(bundle["fund"]["id"])
    assert closed["status"] == "CLAIMS_CLOSED"
    # Pinned order: reserve derives from total eligible (3,500,000) in step 2;
    # the pool only in step 3. The circular reading (10% of the pool) would
    # give reserve 272,728 and pool 2,727,272.
    assert closed["admin_reserve_cents"] == 350_000
    assert closed["distributable_pool_cents"] == 2_650_000
    assert closed["admin_reserve_cents"] != 272_728

    fund = get_fund(bundle["fund"]["id"])
    assert fund["admin_reserve_cents"] == 350_000
    assert fund["distributable_pool_cents"] == 2_650_000


def test_eligible_loss_capped_at_loss_cap_on_approval():
    """PRD section 3.6: "On each approval the system records
    `approved_by_user_id`, sets the claim's `eligible_loss_cents` to the
    smaller of its `documented_loss_cents` and the standing loss cap of
    2,500,000 cents".

    Design: Corner/calculations/eligible_loss_capped_at_loss_cap_on_approval
    """
    bundle = setup_open_fund(
        judgment_amount_cents=3_000_000,
        monetary_relief_cents=3_000_000,
        claimant_specs=make_claimant_specs(1),
    )
    claim = file_claim(bundle["claimants"][0], 3_000_000)
    approved = approve_claim(claim["id"])
    assert approved["eligible_loss_cents"] == 2_500_000, (
        "the loss cap clamps the 3,000,000 documented loss before any pro-rata arithmetic"
    )
    # Sole approved claim: reserve ceil(10% of 2,500,000) = 250,000; pool
    # 2,750,000 covers the eligibility in full.
    assert approved["provisional_award_cents"] == 2_500_000
    assert approved["approved_by_user_id"] == "fa-1"

    fetched = get_claim(claim["id"])
    assert fetched["eligible_loss_cents"] == 2_500_000
    assert fetched["provisional_award_cents"] == 2_500_000


def test_provisional_awards_recomputed_fund_wide_on_each_approval():
    """PRD section 3.6: "and then recomputes `provisional_award_cents` for
    *every* `APPROVED` claim of the fund against the currently collected
    money."

    Design: Corner/calculations/provisional_awards_recomputed_fund_wide_on_each_approval
    """
    bundle = setup_open_fund(
        judgment_amount_cents=3_000_000,
        monetary_relief_cents=3_000_000,
        claimant_specs=make_claimant_specs(2),
    )
    claim_a = file_claim(bundle["claimants"][0], 3_000_000)
    a_at_approval = approve_claim(claim_a["id"])
    assert a_at_approval["provisional_award_cents"] == 2_500_000

    advance_clock(_DAY2)  # strict created_at ordering for the remainder cent
    claim_b = file_claim(bundle["claimants"][1], 1_000_000)
    b_approval = approve_claim(claim_b["id"])  # FILED -> UNDER_REVIEW -> APPROVED
    assert b_approval["provisional_award_cents"] == 757_142

    claim_a_after = get_claim(claim_a["id"])
    assert claim_a_after["provisional_award_cents"] == 1_892_858, (
        "recomputed against the enlarged approved set while the fund is still OPEN_FOR_CLAIMS"
    )
    assert get_fund(bundle["fund"]["id"])["status"] == "OPEN_FOR_CLAIMS"


def test_claims_list_paginates_with_total_count_and_has_more():
    """PRD section 2.3: "`limit` sets the maximum number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets
    the number of items to skip and defaults to 0." and "Unless an endpoint
    states otherwise, list responses are sorted by `created_at` in ascending
    order".
    PRD section 4: "List claims, filterable by `claimant_id`,
    `redress_fund_id`, and `status`; ordered by `created_at` ascending".

    Design: Corner/entities/claims_list_paginates_with_total_count_and_has_more
    """
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        claimant_specs=make_claimant_specs(3),
    )
    fund_id = bundle["fund"]["id"]
    # Strict created_at ordering: file on three successive logical days.
    file_claim(bundle["claimants"][0], 100_000)
    advance_clock(_DAY2)
    claim_b = file_claim(bundle["claimants"][1], 200_000)
    advance_clock(_DAY3)
    file_claim(bundle["claimants"][2], 300_000)

    page1, meta1 = validate_paginated(
        api_client.list_claims(_ADMIN, params={"redress_fund_id": fund_id, "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert [c["documented_loss_cents"] for c in page1] == [100_000, 200_000], (
        "created_at ascending: the 100000 claim precedes the 200000 claim"
    )

    page2, meta2 = validate_paginated(
        api_client.list_claims(_ADMIN, params={"redress_fund_id": fund_id, "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False
    assert page2[0]["documented_loss_cents"] == 300_000

    filtered, meta3 = validate_paginated(
        api_client.list_claims(_ADMIN, params={"claimant_id": claim_b["claimant_id"]})
    )
    assert len(filtered) == 1
    assert meta3["total_count"] == 1
    assert filtered[0]["id"] == claim_b["id"]
    assert filtered[0]["documented_loss_cents"] == 200_000


def test_close_claims_with_unresolved_claim_rejected():
    """PRD section 3.6: "Closing is blocked while any claim of the fund
    remains `FILED` or `UNDER_REVIEW`, surfacing
    `ERR_UNRESOLVED_CLAIMS_EXIST`; denied and approved claims do not block."

    Design: Corner/validations/close_claims_with_unresolved_claim_rejected
    """
    bundle = setup_open_fund(
        judgment_amount_cents=1_500_000,
        monetary_relief_cents=1_500_000,
        claimant_specs=make_claimant_specs(2),
    )
    fund_id = bundle["fund"]["id"]
    claim_a = file_claim(bundle["claimants"][0], 100_000)
    approve_claim(claim_a["id"])
    claim_b = file_claim(bundle["claimants"][1], 200_000)
    move_claim_under_review(claim_b["id"])

    fund = get_fund(fund_id)
    resp = api_client.transition_redress_fund(
        fund_id,
        redress_fund_transition_payload("CLAIMS_CLOSED", fund["version"]),
        _ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_CLAIMS_EXIST)

    after = get_fund(fund_id)
    assert after["status"] == "OPEN_FOR_CLAIMS"
    assert after["version"] == fund["version"], "a rejected transition must not advance the version"
