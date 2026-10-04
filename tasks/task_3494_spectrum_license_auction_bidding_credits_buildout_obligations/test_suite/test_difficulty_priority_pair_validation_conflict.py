"""Depth tests for validation-priority conflicts: when one request violates
checks in two different PRD tiers, the earlier tier's error is reported and
the later check is never consulted."""
from test_helpers import (
    UPFRONT_12_5M_UNITS,
    UPFRONT_20M_UNITS,
    ApiErrorId,
    begin_quiet_period,
    close_round,
    create_open_auction,
    create_qualified_applicant,
    get_applicant,
    get_auction,
    make_bidder_headers,
    place_bid,
    register_applicant,
    setup_clock_active_auction,
    start_clock,
    validate_error,
    validate_paginated,
)


def test_closed_round_state_beats_eligibility_fiscal(api, auction_admin_headers):
    """PRD §2.7: "When a request could fail several checks, the server
    evaluates them in a fixed priority order and reports only the first
    failure; later checks are never consulted once an earlier one has fired."
    PRD §2.7 (state-gate tier): "the target entity must be in a from-state of
    the requested transition, surfaced through the machine-specific error id"
    — naming `ERR_ROUND_NOT_OPEN` among the 409 state errors.
    PRD §2.7 (fiscal tier, last): "money and quota checks:
    `ERR_BID_EXCEEDS_ELIGIBILITY`, `ERR_OVERPAYMENT`,
    `ERR_INSUFFICIENT_UPFRONT`, `ERR_UNJUST_ENRICHMENT_CONFIRMATION_REQUIRED`,
    and `ERR_COVERAGE_BELOW_REQUIREMENT` (all 422)."
    PRD §3.5: "The round must be `OPEN` (`ERR_ROUND_NOT_OPEN`)" and "the
    bidder's cumulative activity in this round — the sum of `units_snapshot`
    over the bidder's bids in the round, the new bid included — must not
    exceed the bidder's current `eligibility_units`, or the bid is rejected
    with `ERR_BID_EXCEEDS_ELIGIBILITY` (422)."

    The setup keeps the auction CLOCK_ACTIVE (demand 3 > supply 2) so the
    ONLY state violation is the closed round itself; the fiscal arm (20M
    units demanded vs 12.5M eligible) would fire if the state gate did not
    pre-empt it.

    Design: Difficulty/priority_pair_validation_conflict/closed_round_state_beats_eligibility_fiscal
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA001",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {"legal_name": "P Bidder", "upfront_cents": UPFRONT_12_5M_UNITS},
            {"legal_name": "Q Bidder", "upfront_cents": UPFRONT_20M_UNITS},
        ],
    )
    p, q = ctx["applicants"]
    auction_id = ctx["auction"]["id"]
    r1 = ctx["round"]

    # Demand 1 + 2 = 3 > supply 2, so closing round 1 keeps the auction
    # CLOCK_ACTIVE; the product stays open and P stays QUALIFIED.
    place_bid(r1["id"], p["id"], "PEA001", "CATEGORY_A", 1)
    place_bid(r1["id"], q["id"], "PEA001", "CATEGORY_A", 2)
    close_round(r1["id"])
    assert get_auction(auction_id)["status"] == "CLOCK_ACTIVE"

    # P's attempted qty 2 = 20,000,000 units > 12,500,000 eligibility: the
    # fiscal violation exists, but the round-state violation reports first.
    resp = api.place_bid(
        r1["id"],
        {"area_code": "PEA001", "category": "CATEGORY_A", "quantity": 2},
        make_bidder_headers(p["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_ROUND_NOT_OPEN)
    assert resp.status_code == 409
    assert err["error_id"] != ApiErrorId.ERR_BID_EXCEEDS_ELIGIBILITY

    # No new bid was created: P still has exactly the one PROCESSED original.
    p_bids, _ = validate_paginated(
        api.list_applicant_bids(p["id"], auction_admin_headers, params={"round_id": r1["id"]})
    )
    assert len(p_bids) == 1
    assert p_bids[0]["status"] == "PROCESSED"


def test_quiet_period_safety_beats_ownership_constraint(api):
    """PRD §3.4: "The quiet period starts the anti-collusion freeze: from
    that moment until the auction reaches `CLOSED`, disclosure updates and
    correction resubmissions are rejected with `ERR_QUIET_PERIOD_VIOLATION`."
    PRD §3.2: "Whenever the ownership array is supplied — at registration, in
    a later disclosure update, or when it is re-examined at qualification —
    its `stake_pct` values must sum to exactly 100, or the request fails with
    `ERR_OWNERSHIP_TOTAL_INVALID` (422)."
    PRD §2.7: "the quiet-period freeze (`ERR_QUIET_PERIOD_VIOLATION`, 409)
    and, at qualification, the ownership-total and credit-claim gates
    (`ERR_OWNERSHIP_TOTAL_INVALID` and `ERR_CREDIT_CLAIM_CONFLICT`, both 422,
    the ownership total checked first)."

    Design: Difficulty/priority_pair_validation_conflict/quiet_period_safety_beats_ownership_constraint
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction = ctx["auction"]
    s = register_applicant(
        auction["id"],
        legal_name="Sigma LLC",
        ownership_interests=[
            {"holder_name": "A", "stake_pct": 60, "holder_annual_revenue_cents": 0},
            {"holder_name": "B", "stake_pct": 40, "holder_annual_revenue_cents": 0},
        ],
    )
    s_v = s["version"]
    begin_quiet_period(auction["id"], auction["application_deadline"])

    # The replacement stakes sum to 90 — but the anti-collusion freeze
    # rejects the disclosure update before the ownership total is consulted.
    resp = api.patch_disclosure(
        s["id"],
        {
            "expected_applicant_version": s_v,
            "ownership_interests": [
                {"holder_name": "A", "stake_pct": 90, "holder_annual_revenue_cents": 0},
                {"holder_name": "B", "stake_pct": 0, "holder_annual_revenue_cents": 0},
            ],
        },
        make_bidder_headers(s["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_QUIET_PERIOD_VIOLATION)
    assert resp.status_code == 409
    assert err["error_id"] != ApiErrorId.ERR_OWNERSHIP_TOTAL_INVALID

    # The failed PATCH leaves the record untouched.
    s_after = get_applicant(s["id"])
    assert s_after["version"] == s_v
    assert sum(oi["stake_pct"] for oi in s_after["ownership_interests"]) == 100
