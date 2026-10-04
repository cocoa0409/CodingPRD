"""Depth tests for non-linear (cyclic) state machines: the auction
pause/resume cycle gating bid placement, and the applicant
correction/resubmission loop with its OCC version threading."""
from test_helpers import (
    UPFRONT_10M_UNITS,
    ApiErrorId,
    ApplicantReviewAction,
    assert_applicant,
    assert_bid,
    assert_eligibility_from_held,
    create_open_auction,
    get_auction,
    make_bidder_headers,
    patch_disclosure,
    pause_clock,
    pay_upfront,
    place_bid,
    register_applicant,
    resubmit_applicant,
    resume_clock,
    review_applicant,
    setup_clock_active_auction,
    validate_error,
)


def test_auction_pause_resume_cycle(api, auction_admin_headers):
    """PRD §3.4: "The administrator may pause the clock (`action`
    `PAUSE_CLOCK`, moving `CLOCK_ACTIVE → CLOCK_PAUSED`) and later resume it
    (`action` `RESUME_CLOCK`, moving `CLOCK_PAUSED → CLOCK_ACTIVE`). While the
    auction is paused, bid placement is rejected with
    `ERR_AUCTION_INVALID_STATE`, and rounds can neither be opened nor closed,
    since both require `CLOCK_ACTIVE`."
    PRD §3.5: "A created bid is `SUBMITTED`, with its `units_snapshot` frozen
    at bid time as the `quantity` multiplied by the product's bidding units,
    so later changes elsewhere can never rewrite a bid's contribution."

    Design: Difficulty/non_linear_state_machine/auction_pause_resume_cycle
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {
                "legal_name": "Rural Wireless Co",
                "claims_rural_credit": True,
                "service_population": 200_000,
            }
        ],
    )
    r = ctx["applicants"][0]
    auction_id = ctx["auction"]["id"]
    r1 = ctx["round"]

    pause_clock(auction_id)
    assert get_auction(auction_id)["status"] == "CLOCK_PAUSED"

    # The round is still OPEN; the AUCTION state gate rejects the bid.
    resp = api.place_bid(
        r1["id"],
        {"area_code": "PEA002", "category": "CATEGORY_A", "quantity": 1},
        make_bidder_headers(r["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AUCTION_INVALID_STATE)

    resume_clock(auction_id)
    assert get_auction(auction_id)["status"] == "CLOCK_ACTIVE"

    # The identical bid succeeds after the resume edge — the cycle is real.
    bid = place_bid(r1["id"], r["id"], "PEA002", "CATEGORY_A", 1)
    assert_bid(bid)
    assert bid["status"] == "SUBMITTED"
    # units_snapshot = 1 * (10 MHz * 500,000 pop).
    assert bid["units_snapshot"] == 5_000_000


def test_applicant_correction_loop(api):
    """PRD §2.5: "The `version` field is an integer that starts at 1 and
    increments by exactly one on every mutation of the resource, including
    mutations performed as cascaded side effects of an operation on another
    resource."
    PRD §3.3: "Requesting a correction (`REQUEST_CORRECTION`) moves it
    `UNDER_REVIEW → NEEDS_CORRECTION`, from which the owning bidder resubmits:
    the resubmission carries `expected_applicant_version` (§2.8), requires the
    auction to still be `APPLICATION_OPEN` — once the quiet period has begun,
    the freeze rejects resubmission with `ERR_QUIET_PERIOD_VIOLATION` — and
    returns the applicant to `UNDER_REVIEW` with its `version` incremented by
    1."
    PRD §3.2: "the ownership array, when supplied, replaces the previous array
    wholesale and must again sum to exactly 100."

    Design: Difficulty/non_linear_state_machine/applicant_correction_loop
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction_id = ctx["auction"]["id"]

    k = register_applicant(
        auction_id,
        legal_name="Kappa Radio",
        claims_small_business=True,
        ownership_interests=[
            {"holder_name": "A", "stake_pct": 60, "holder_annual_revenue_cents": 0},
            {"holder_name": "B", "stake_pct": 40, "holder_annual_revenue_cents": 0},
        ],
    )
    assert k["version"] == 1
    assert k["status"] == "SUBMITTED"

    # Every mutation of the Applicant increments its version by exactly one:
    # the upfront payment rewrites the ledger fields, so it bumps too.
    k = pay_upfront(k["id"], UPFRONT_10M_UNITS)
    assert k["version"] == 2

    k = review_applicant(k["id"], ApplicantReviewAction.START_REVIEW)
    assert k["version"] == 3
    assert k["status"] == "UNDER_REVIEW"

    k = review_applicant(k["id"], ApplicantReviewAction.REQUEST_CORRECTION)
    assert k["version"] == 4
    assert k["status"] == "NEEDS_CORRECTION"

    # OCC-guarded disclosure edit inside the loop consumes the fresh version.
    k = patch_disclosure(
        k["id"],
        k["version"],
        ownership_interests=[
            {"holder_name": "A", "stake_pct": 70, "holder_annual_revenue_cents": 0},
            {"holder_name": "B", "stake_pct": 30, "holder_annual_revenue_cents": 0},
        ],
    )
    assert k["version"] == 5
    assert {oi["holder_name"]: oi["stake_pct"] for oi in k["ownership_interests"]} == {
        "A": 70,
        "B": 30,
    }

    k = resubmit_applicant(k["id"], k["version"])
    assert k["version"] == 6
    assert k["status"] == "UNDER_REVIEW"

    # The loop terminates in QUALIFIED; the credit is computed from the
    # amended disclosure (small-business, zero attributable revenue -> 35%).
    k = review_applicant(k["id"], ApplicantReviewAction.QUALIFY)
    assert_applicant(k)
    assert k["status"] == "QUALIFIED"
    assert k["credit_pct"] == 35
    assert k["attributable_revenue_cents"] == 0
    assert k["eligibility_units"] == 10_000_000
    assert_eligibility_from_held(k)
