"""Breadth tests over the error surface, part 1: registration and
qualification failures, plan-structure uniqueness, auction-phase temporal
guards, and clock-round bid errors."""
from test_helpers import (
    UPFRONT_10M_UNITS,
    ApiErrorId,
    add_area,
    add_block,
    assert_upfront_ledger_conserved,
    begin_quiet_period,
    close_round,
    create_applicant_payload,
    create_bid_payload,
    create_draft_plan,
    create_license_area_payload,
    create_license_block_payload,
    create_open_auction,
    create_qualified_applicant,
    get_applicant,
    get_auction,
    get_round,
    make_bidder_headers,
    open_next_round,
    place_bid,
    register_applicant,
    setup_clock_active_auction,
    start_clock,
    start_review,
    pay_upfront,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_ownership_sum_not_100_at_creation_returns_invalid(
    api, auction_admin_headers, bidder_headers
):
    """PRD §3.2: "Whenever the ownership array is supplied — at registration,
    in a later disclosure update, or when it is re-examined at qualification —
    its `stake_pct` values must sum to exactly 100, or the request fails with
    `ERR_OWNERSHIP_TOTAL_INVALID` (422)."

    Design: Corner/errors/ownership_sum_not_100_at_creation_returns_invalid
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction_id = ctx["auction"]["id"]

    payload = create_applicant_payload(
        auction_id,
        legal_name="Bad Cap Table",
        ownership_interests=[
            {"holder_name": "A", "stake_pct": 90, "holder_annual_revenue_cents": 0}
        ],
    )
    resp = api.create_applicant(payload, bidder_headers)
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_TOTAL_INVALID)
    assert resp.status_code == 422

    # Nothing persisted.
    rows, meta = validate_paginated(api.list_applicants(auction_id, auction_admin_headers))
    assert rows == []
    assert meta["total_count"] == 0


def test_dual_credit_claims_conflict_at_qualify(api, auction_admin_headers):
    """PRD §3.2: "Registration itself is permissive about the two credit
    claims: an applicant may register with both flags set, and the
    mutual-exclusion rule bites only at qualification."
    PRD §3.3: "Then the compliance gates: the `ownership_interests` stakes
    must sum to exactly 100, else `ERR_OWNERSHIP_TOTAL_INVALID`, and
    `claims_small_business` and `claims_rural_credit` must not both be true,
    else `ERR_CREDIT_CLAIM_CONFLICT` (422)."

    Design: Corner/errors/dual_credit_claims_conflict_at_qualify
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    g = register_applicant(
        ctx["auction"]["id"],
        legal_name="Greedy Credits",
        claims_small_business=True,
        claims_rural_credit=True,
        service_population=100_000,
    )
    pay_upfront(g["id"], UPFRONT_10M_UNITS)
    start_review(g["id"])

    resp = api.review_applicant(g["id"], "QUALIFY", auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_CREDIT_CLAIM_CONFLICT)
    assert resp.status_code == 422

    # The failed qualification leaves the state machine in place.
    assert get_applicant(g["id"])["status"] == "UNDER_REVIEW"


def test_qualify_without_upfront_returns_insufficient(api, auction_admin_headers):
    """PRD §3.3: "Last, the fiscal gate: the applicant must hold at least one
    eligibility unit, else `ERR_INSUFFICIENT_UPFRONT` (422)."

    Design: Corner/errors/qualify_without_upfront_returns_insufficient
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    r = register_applicant(
        ctx["auction"]["id"],
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    start_review(r["id"])

    resp = api.review_applicant(r["id"], "QUALIFY", auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_UPFRONT)
    assert resp.status_code == 422

    r_after = get_applicant(r["id"])
    assert r_after["eligibility_units"] == 0
    assert r_after["status"] == "UNDER_REVIEW"


def test_duplicate_area_code_and_category_rejected(api, auction_admin_headers):
    """PRD §3.1: "Two structural rules guard the plan's integrity: an
    `area_code` may appear only once within a band plan
    (`ERR_DUPLICATE_AREA_CODE`), and a `category` may appear only once within
    a band plan (`ERR_DUPLICATE_BLOCK_CATEGORY`)."

    Design: Corner/errors/duplicate_area_code_and_category_rejected
    """
    plan = create_draft_plan()
    add_area(plan["id"], area_code="PEA002", name="Rural Y", population=500_000)
    add_block(plan["id"], category="CATEGORY_A")

    # Reusing the same area_code inside the same plan is rejected.
    resp_area = api.create_license_area(
        create_license_area_payload(
            plan["id"], area_code="PEA002", name="Dup Area", population=1000
        ),
        auction_admin_headers,
    )
    validate_error(resp_area, ApiErrorId.ERR_DUPLICATE_AREA_CODE)
    assert resp_area.status_code == 409

    # Reusing the same category inside the same plan is rejected.
    resp_block = api.create_license_block(
        create_license_block_payload(
            plan["id"],
            category="CATEGORY_A",
            mhz_size=5,
            supply_per_area=1,
            price_per_mhz_pop_cents=1,
        ),
        auction_admin_headers,
    )
    validate_error(resp_block, ApiErrorId.ERR_DUPLICATE_BLOCK_CATEGORY)
    assert resp_block.status_code == 409


def test_quiet_period_before_deadline_rejected(api, auction_admin_headers):
    """PRD §3.4: "Once the logical clock has reached the auction's
    `application_deadline`, an `AuctionAdmin` may begin the quiet period
    (`action` `BEGIN_QUIET_PERIOD`, moving the auction `APPLICATION_OPEN →
    QUIET_PERIOD`); attempting it before the deadline has passed fails with
    `ERR_APPLICATION_DEADLINE_NOT_PASSED`."

    Design: Corner/errors/quiet_period_before_deadline_rejected
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction = ctx["auction"]

    # The logical clock still reads the 2026-09-01 epoch; the deadline is
    # 2026-09-15.
    resp = api.auction_phase(auction["id"], "BEGIN_QUIET_PERIOD", auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICATION_DEADLINE_NOT_PASSED)
    assert resp.status_code == 409

    # Once the clock has passed the deadline the same action succeeds.
    auction = begin_quiet_period(auction["id"], auction["application_deadline"])
    assert auction["status"] == "QUIET_PERIOD"


def test_start_clock_without_qualified_bidders_rejected(api, auction_admin_headers):
    """PRD §3.4: "Starting the clock (`action` `START_CLOCK`, moving
    `QUIET_PERIOD → CLOCK_ACTIVE`) requires at least one `QUALIFIED`
    applicant of the auction, failing which the attempt is rejected with
    `ERR_NO_QUALIFIED_BIDDERS` (422)."

    Design: Corner/errors/start_clock_without_qualified_bidders_rejected
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    # One applicant exists but was never reviewed, so none is QUALIFIED.
    register_applicant(
        ctx["auction"]["id"],
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    begin_quiet_period(ctx["auction"]["id"], ctx["auction"]["application_deadline"])

    resp = api.auction_phase(ctx["auction"]["id"], "START_CLOCK", auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NO_QUALIFIED_BIDDERS)
    assert resp.status_code == 422

    auction = get_auction(ctx["auction"]["id"])
    assert auction["status"] == "QUIET_PERIOD"
    assert auction["current_round_number"] == 0


def test_upfront_payment_after_clock_start_returns_window_closed(
    api, auction_admin_headers
):
    """PRD §3.2: "While the auction is `APPLICATION_OPEN` or `QUIET_PERIOD`,
    the bidder may add an `amount_cents` payment to the deposit; payments
    attempted after the auction has left those phases fail with
    `ERR_UPFRONT_WINDOW_CLOSED`."

    Design: Corner/errors/upfront_payment_after_clock_start_returns_window_closed
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction_id = ctx["auction"]["id"]
    create_qualified_applicant(
        auction_id,
        UPFRONT_10M_UNITS,
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    u = register_applicant(auction_id, legal_name="U Late")
    begin_quiet_period(auction_id, ctx["auction"]["application_deadline"])
    start_clock(auction_id)

    resp = api.add_upfront_payment(
        u["id"], UPFRONT_10M_UNITS, make_bidder_headers(u["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UPFRONT_WINDOW_CLOSED)
    assert resp.status_code == 409

    u_after = get_applicant(u["id"])
    assert u_after["upfront_paid_cents"] == 0
    assert u_after["eligibility_units"] == 0


def test_withdrawal_after_quiet_period_returns_window_closed(
    api, auction_admin_headers
):
    """PRD §3.3: "Withdrawal is the bidder's own exit and requires ownership
    of the applicant record; it is available from `SUBMITTED`,
    `UNDER_REVIEW`, `NEEDS_CORRECTION`, or `QUALIFIED` alike, but only while
    the auction is `APPLICATION_OPEN` — from the quiet period onward the
    window has closed and the attempt fails with
    `ERR_WITHDRAWAL_WINDOW_CLOSED`."

    Design: Corner/errors/withdrawal_after_quiet_period_returns_window_closed
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    s = register_applicant(ctx["auction"]["id"], legal_name="S Stuck")
    pay_upfront(s["id"], UPFRONT_10M_UNITS)
    begin_quiet_period(ctx["auction"]["id"], ctx["auction"]["application_deadline"])

    resp = api.withdraw_applicant(s["id"], make_bidder_headers(s["id"]))
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_WINDOW_CLOSED)
    assert resp.status_code == 409

    # No refund escaped; the ledger is untouched.
    s_after = get_applicant(s["id"])
    assert s_after["status"] == "SUBMITTED"
    assert s_after["upfront_held_cents"] == UPFRONT_10M_UNITS
    assert_upfront_ledger_conserved(s_after)


def test_bid_quantity_over_supply_and_duplicate_bid(api, auction_admin_headers):
    """PRD §3.5: "A `Bidder` places a clock bid against an open round by
    supplying `area_code`, `category`, and a whole-number `quantity` between
    1 and the block's `supply_per_area`; a non-positive or otherwise
    malformed quantity is rejected with `ERR_INVALID_REQUEST`, while one
    exceeding supply fails with `ERR_SUPPLY_EXCEEDED` (422)."
    PRD §3.5: "One bid per round, bidder, and product is allowed: a second
    `SUBMITTED` bid for the same triple is `ERR_DUPLICATE_BID`."

    Design: Corner/errors/bid_quantity_over_supply_and_duplicate_bid
    """
    # CATEGORY_A @ PEA002 has supply_per_area 2; the bidder holds
    # 100,000,000 eligibility units, so eligibility never shadows these.
    ctx = setup_clock_active_auction(
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[{"legal_name": "Big Pockets", "upfront_cents": 250_000_000_000}],
    )
    big_id = ctx["applicants"][0]["id"]
    round_id = ctx["round"]["id"]

    resp = api.place_bid(
        round_id,
        create_bid_payload("PEA002", "CATEGORY_A", 3),
        make_bidder_headers(big_id),
    )
    validate_error(resp, ApiErrorId.ERR_SUPPLY_EXCEEDED)
    assert resp.status_code == 422

    ok = validate_success(
        api.place_bid(
            round_id,
            create_bid_payload("PEA002", "CATEGORY_A", 2),
            make_bidder_headers(big_id),
        ),
        201,
    )
    assert ok["status"] == "SUBMITTED"

    resp2 = api.place_bid(
        round_id,
        create_bid_payload("PEA002", "CATEGORY_A", 1),
        make_bidder_headers(big_id),
    )
    validate_error(resp2, ApiErrorId.ERR_DUPLICATE_BID)
    assert resp2.status_code == 409


def test_bid_on_unknown_product_returns_product_not_found(api, auction_admin_headers):
    """PRD §2.7: "For bid and assignment-bid bodies, once every path
    identifier has resolved, the referenced product — the (`area_code`,
    `category`) pair — must exist in the auction's band plan, or the request
    fails with `ERR_PRODUCT_NOT_FOUND` (still 404)."

    Design: Corner/errors/bid_on_unknown_product_returns_product_not_found
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
    r_id = ctx["applicants"][0]["id"]

    resp = api.place_bid(
        ctx["round"]["id"],
        create_bid_payload("NOPE", "CATEGORY_A", 1),
        make_bidder_headers(r_id),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND)
    assert resp.status_code == 404


def test_bid_on_closed_product_in_later_round(api, auction_admin_headers):
    """PRD §3.5: "A product whose demand falls short of supply closes: it is
    excluded from the new round's `prices` array, is no longer biddable, and
    can never re-enter."
    PRD §3.5: "the product must both exist in the auction's band plan
    (`ERR_PRODUCT_NOT_FOUND`, checked only after every path identifier has
    resolved) and still be open in this round (`ERR_PRODUCT_CLOSED`)."

    Design: Corner/errors/bid_on_closed_product_in_later_round
    """
    # Round 1: CATEGORY_C demand 5 vs supply 4 (stays open); CATEGORY_D
    # demand 3 vs supply 4 (closes permanently).
    ctx = setup_clock_active_auction(
        area_codes=("PEA003",),
        block_categories=("CATEGORY_C", "CATEGORY_D"),
        bidder_specs=[
            {"legal_name": "G1 Wireless", "upfront_cents": 200_000_000_000},
            {"legal_name": "G2 Wireless", "upfront_cents": 25_000_000_000},
        ],
    )
    g1_id, g2_id = (a["id"] for a in ctx["applicants"])
    round1_id = ctx["round"]["id"]
    place_bid(round1_id, g1_id, "PEA003", "CATEGORY_C", 4)
    place_bid(round1_id, g1_id, "PEA003", "CATEGORY_D", 3)
    place_bid(round1_id, g2_id, "PEA003", "CATEGORY_C", 1)
    close_round(round1_id)

    round2 = get_round(open_next_round(ctx["auction"]["id"])["id"])
    assert [p["category"] for p in round2["prices"]] == ["CATEGORY_C"]

    resp = api.place_bid(
        round2["id"],
        create_bid_payload("PEA003", "CATEGORY_D", 1),
        make_bidder_headers(g1_id),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_CLOSED)
    assert resp.status_code == 409


def test_bid_over_eligibility_direct_trigger(api, auction_admin_headers):
    """PRD §3.5: "Per the global ordering of §2.7, the fiscal gate fires
    last: the bidder's cumulative activity in this round — the sum of
    `units_snapshot` over the bidder's bids in the round, the new bid
    included — must not exceed the bidder's current `eligibility_units`, or
    the bid is rejected with `ERR_BID_EXCEEDS_ELIGIBILITY` (422)."

    Design: Corner/errors/bid_over_eligibility_direct_trigger
    """
    # CATEGORY_A @ PEA001 carries 10 * 1,000,000 = 10,000,000 bidding units
    # per unit of quantity; the bidder holds exactly 5,000,000 units.
    ctx = setup_clock_active_auction(
        area_codes=("PEA001",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[{"legal_name": "Small Wallet", "upfront_cents": 12_500_000_000}],
    )
    sm_id = ctx["applicants"][0]["id"]
    assert get_applicant(sm_id)["eligibility_units"] == 5_000_000

    resp = api.place_bid(
        ctx["round"]["id"],
        create_bid_payload("PEA001", "CATEGORY_A", 1),
        make_bidder_headers(sm_id),
    )
    validate_error(resp, ApiErrorId.ERR_BID_EXCEEDS_ELIGIBILITY)
    assert resp.status_code == 422

    rows, meta = validate_paginated(api.list_applicant_bids(sm_id, auction_admin_headers))
    assert rows == []
    assert meta["total_count"] == 0
