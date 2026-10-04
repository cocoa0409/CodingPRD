"""Depth tests for cross-entity state dependencies: a license's completing
settlement payment is gated on the INCUMBENT machine of its area, and bid
placement is gated on the BIDDER's APPLICANT machine."""
from test_helpers import (
    QUIET_PERIOD_DAY_ISO,
    TRANSITION_WINDOW_END_ISO,
    TRANSITION_WINDOW_START_ISO,
    UPFRONT_12_5M_UNITS,
    ApiErrorId,
    assert_bid,
    begin_quiet_period,
    create_open_auction,
    create_qualified_applicant,
    get_incumbent,
    get_license,
    incumbent_begin_relocation,
    incumbent_submit_plan,
    list_milestones,
    make_bidder_headers,
    pay_upfront,
    place_bid,
    register_applicant,
    register_incumbent,
    setup_closed_auction_with_licenses,
    settle_license_in_full,
    start_clock,
    validate_error,
    validate_paginated,
)


def test_settlement_blocked_until_incumbents_cleared(api):
    """PRD §3.7: "The payment that would complete settlement — the one
    bringing `paid_cents` up to `net_price_cents` — carries one extra
    precondition: every incumbent registered in the license's area must be
    `RELOCATING` or `CLEARED`. An incumbent still `NOTIFIED`,
    `PLAN_SUBMITTED`, or `DISPUTED` in that area blocks the completing payment
    with `ERR_INCUMBENTS_NOT_CLEARED` (409)."
    PRD §3.7: "On completion the license becomes `ACTIVE`: `grant_date` is
    stamped with the current logical instant, `term_end` is computed as the
    grant date plus 3650 days, and two buildout milestones are created in
    `PENDING` status".

    Design: Difficulty/cross_entity_state_dependency/settlement_blocked_until_incumbents_cleared
    """
    ctx = setup_closed_auction_with_licenses(
        bids=[(0, "PEA002", "CATEGORY_A", 1)],
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
    lic = ctx["licenses"][0]
    assert lic["status"] == "PENDING_PAYMENT"

    # The incumbent of the license's area sits in NOTIFIED: a state of a
    # DIFFERENT entity gates this license's settlement.
    incumbent = register_incumbent(
        ctx["plan"]["id"],
        ctx["areas"]["PEA002"]["id"],
        callsign="KOLD940",
        relocation_cost_cents=5_000_000,
    )
    resp = api.add_settlement_payment(
        lic["id"], 212_500_000, make_bidder_headers(r["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INCUMBENTS_NOT_CLEARED)

    # NOTIFIED -> PLAN_SUBMITTED -> RELOCATING; RELOCATING does not block.
    incumbent_submit_plan(incumbent["id"])
    incumbent_after = incumbent_begin_relocation(
        incumbent["id"], TRANSITION_WINDOW_START_ISO, TRANSITION_WINDOW_END_ISO
    )
    assert incumbent_after["status"] == "RELOCATING"

    settled = settle_license_in_full(lic)
    assert settled["status"] == "ACTIVE"
    assert settled["paid_cents"] == 212_500_000
    # The clock read 2026-09-16 when the completing payment landed: grant
    # time is the clock at payment, not at license creation.
    assert settled["grant_date"] == QUIET_PERIOD_DAY_ISO

    milestones = list_milestones(lic["id"])
    assert len(milestones) == 2
    assert [m["milestone_type"] for m in milestones] == ["INTERIM", "FINAL"]
    assert all(m["status"] == "PENDING" for m in milestones)


def test_bid_gated_on_applicant_qualified(api, auction_admin_headers):
    """PRD §3.5: "the bidder must be `QUALIFIED` (bids by applicants in any
    other status land on `ERR_APPLICANT_INVALID_STATE`)".
    PRD §3.2: "Each payment increases `upfront_paid_cents` and
    `upfront_held_cents` by the amount paid and immediately recomputes
    `eligibility_units` as the held balance divided by 2500, rounded down to a
    whole unit" — money buys eligibility, not qualification.

    Design: Difficulty/cross_entity_state_dependency/bid_gated_on_applicant_qualified
    """
    ctx = create_open_auction(area_codes=("PEA001",), block_categories=("CATEGORY_A",))
    auction = ctx["auction"]
    # U is SUBMITTED with a fully paid deposit — eligible but never reviewed.
    u = register_applicant(auction["id"], legal_name="U Unreviewed")
    u = pay_upfront(u["id"], UPFRONT_12_5M_UNITS)
    assert u["status"] == "SUBMITTED"
    assert u["eligibility_units"] == 12_500_000
    # V is QUALIFIED, which also makes START_CLOCK legal.
    v = create_qualified_applicant(
        auction["id"], UPFRONT_12_5M_UNITS, legal_name="V Verified"
    )
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])
    r1_rounds = api.list_rounds(auction["id"], auction_admin_headers)
    rounds, _ = validate_paginated(r1_rounds)
    r1 = rounds[0]

    resp = api.place_bid(
        r1["id"],
        {"area_code": "PEA001", "category": "CATEGORY_A", "quantity": 1},
        make_bidder_headers(u["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_APPLICANT_INVALID_STATE)

    # The qualified bidder succeeds in the same round.
    bid = place_bid(r1["id"], v["id"], "PEA001", "CATEGORY_A", 1)
    assert_bid(bid)
    assert bid["status"] == "SUBMITTED"

    u_bids, _ = validate_paginated(
        api.list_applicant_bids(u["id"], auction_admin_headers)
    )
    assert u_bids == []
