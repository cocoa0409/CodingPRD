"""Breadth tests over the error surface, part 2: assignment-phase,
settlement, milestone, transfer, and renewal guards."""
from test_helpers import (
    GRANT_DAY_ISO,
    TRANSITION_WINDOW_END_ISO,
    TRANSITION_WINDOW_START_ISO,
    UPFRONT_10M_UNITS,
    ApiErrorId,
    RenewalDecision,
    begin_quiet_period,
    close_round,
    complete_assignment,
    coverage_acceptable,
    create_assignment_bid_payload,
    create_incumbent_transition_payload,
    create_open_auction,
    create_qualified_applicant,
    create_transfer_application_payload,
    current_round,
    decide_renewal,
    expected_unjust_enrichment_cents,
    file_and_accept_milestone,
    file_assignment_bid,
    file_milestone_notice,
    file_renewal,
    file_transfer,
    get_auction,
    get_incumbent,
    get_license,
    get_supply_entry,
    get_transfer,
    incumbent_begin_relocation,
    incumbent_submit_plan,
    list_licenses,
    make_bidder_headers,
    make_incumbent_operator_headers,
    milestones_by_type,
    place_bid,
    register_applicant,
    register_incumbent,
    set_clock,
    settle_license_in_full,
    setup_active_license,
    setup_assignment_phase,
    setup_closed_auction_with_licenses,
    start_clock,
    transfer_begin_review,
    transfer_approve,
    validate_error,
    validate_paginated,
)


def _rural_license_with_transferee(settle: bool) -> dict:
    """Rural R wins CATEGORY_A @ PEA002 qty 1; transferee T is registered
    (never qualified) while the auction is still open. Runs the full clock
    and assignment chain. With `settle`, the license is then paid in full at
    the 2026-10-01 grant day (ACTIVE); otherwise it stays PENDING_PAYMENT."""
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction_id = ctx["auction"]["id"]
    r = create_qualified_applicant(
        auction_id,
        UPFRONT_10M_UNITS,
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    t = register_applicant(auction_id, legal_name="T Co")
    begin_quiet_period(auction_id, ctx["auction"]["application_deadline"])
    start_clock(auction_id)
    round_ = current_round(auction_id)
    place_bid(round_["id"], r["id"], "PEA002", "CATEGORY_A", 1)
    close_round(round_["id"])
    file_assignment_bid(auction_id, r["id"], "PEA002", "CATEGORY_A", 0)
    complete_assignment(auction_id)
    lic = list_licenses(auction_id=auction_id, holder_applicant_id=r["id"])[0]
    if settle:
        set_clock(GRANT_DAY_ISO)
        lic = settle_license_in_full(lic)
    return {"ctx": ctx, "r": r, "t": t, "license": lic}


def test_assignment_bid_by_non_winner_and_incomplete_bids(api, auction_admin_headers):
    """PRD §3.6: "the caller must be a recorded winner of that product in the
    final clock round, else `ERR_NOT_A_WINNER` (403)."
    PRD §3.6: "Completing the assignment (`action` `COMPLETE_ASSIGNMENT`,
    moving the auction `ASSIGNMENT_PHASE → CLOSED`) requires every winning
    tuple to have a `SUBMITTED` assignment bid from its applicant; there is
    no zero-amount default fallback, and a missing bid blocks completion with
    `ERR_ASSIGNMENT_BIDS_INCOMPLETE`."

    Design: Corner/errors/assignment_bid_by_non_winner_and_incomplete_bids
    """
    # R wins CATEGORY_A @ PEA002 qty 1; V is QUALIFIED but never bid.
    ctx = setup_assignment_phase(
        bids=[(0, "PEA002", "CATEGORY_A", 1)],
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {
                "legal_name": "Rural Wireless Co",
                "claims_rural_credit": True,
                "service_population": 200_000,
            },
            {"legal_name": "V Spectator"},
        ],
    )
    auction_id = ctx["auction"]["id"]
    v_id = ctx["applicants"][1]["id"]

    resp = api.create_assignment_bid(
        auction_id,
        create_assignment_bid_payload("PEA002", "CATEGORY_A", 1000),
        make_bidder_headers(v_id),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_A_WINNER)
    assert resp.status_code == 403

    resp2 = api.auction_phase(auction_id, "COMPLETE_ASSIGNMENT", auction_admin_headers)
    validate_error(resp2, ApiErrorId.ERR_ASSIGNMENT_BIDS_INCOMPLETE)
    assert resp2.status_code == 409

    # The failed completion leaves the phase in place; no licenses exist.
    assert get_auction(auction_id)["status"] == "ASSIGNMENT_PHASE"
    assert list_licenses(auction_id=auction_id) == []


def test_overpayment_and_zero_payment_rejected(api, auction_admin_headers):
    """PRD §3.7: "The license must be `PENDING_PAYMENT`, else
    `ERR_LICENSE_INVALID_STATE`, and each payment must be positive and must
    not exceed the remaining balance — `net_price_cents` minus `paid_cents` —
    with either violation rejected as `ERR_OVERPAYMENT` (422)."

    Design: Corner/errors/overpayment_and_zero_payment_rejected
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
    lic = ctx["licenses"][0]
    r_id = lic["holder_applicant_id"]
    assert lic["status"] == "PENDING_PAYMENT"
    # 250,000,000 clock price at the 15% rural credit.
    assert lic["net_price_cents"] == 212_500_000

    # One cent over the remaining balance, and a zero payment, both fail.
    over = api.add_settlement_payment(lic["id"], 212_500_001, make_bidder_headers(r_id))
    validate_error(over, ApiErrorId.ERR_OVERPAYMENT)
    assert over.status_code == 422
    zero = api.add_settlement_payment(lic["id"], 0, make_bidder_headers(r_id))
    validate_error(zero, ApiErrorId.ERR_OVERPAYMENT)
    assert zero.status_code == 422

    # The exact payment then succeeds and grants the license.
    granted = settle_license_in_full(get_license(lic["id"]))
    assert granted["status"] == "ACTIVE"
    assert granted["paid_cents"] == 212_500_000


def test_accept_with_coverage_below_requirement_rejected(api, auction_admin_headers):
    """PRD §3.8: "Acceptance requires the coverage cross-multiplication to
    hold: the certified `covered_population` multiplied by 100 must be at
    least the milestone's `required_coverage_pct` multiplied by the license
    area's `population` — an exact integer comparison with an inclusive
    boundary, so coverage of exactly 40.000 percent passes an `INTERIM`
    milestone — and any shortfall fails with
    `ERR_COVERAGE_BELOW_REQUIREMENT` (422)."

    Design: Corner/errors/accept_with_coverage_below_requirement_rejected
    """
    ctx = setup_active_license(
        bids=[(0, "PEA001", "CATEGORY_A", 1)],
        area_codes=("PEA001",),
        block_categories=("CATEGORY_A",),
        grant_day_iso=GRANT_DAY_ISO,
    )
    lic = ctx["license"]
    w1_id = lic["holder_applicant_id"]
    interim = ctx["milestones"]["INTERIM"]

    # PEA001 population 1,000,000, INTERIM requires 40%: 399,999 * 100
    # < 40 * 1,000,000 — one resident short.
    filed = file_milestone_notice(interim["id"], w1_id, 399_999, interim["version"])
    assert filed["status"] == "FILED"
    assert not coverage_acceptable(399_999, 40, 1_000_000)

    resp = api.review_milestone(interim["id"], "ACCEPT", auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_COVERAGE_BELOW_REQUIREMENT)
    assert resp.status_code == 422

    # The failed ACCEPT leaves the milestone reviewable.
    assert milestones_by_type(lic["id"])["INTERIM"]["status"] == "FILED"


def test_lease_with_end_before_start_rejected(api, auction_admin_headers):
    """PRD §3.9: "A lease additionally requires `lease_start` and `lease_end`
    with the end strictly after the start (`ERR_LEASE_DATES_INVALID`, 422)"

    Design: Corner/errors/lease_with_end_before_start_rejected
    """
    env = _rural_license_with_transferee(settle=True)
    lic, r, t = env["license"], env["r"], env["t"]
    assert lic["status"] == "ACTIVE"

    resp = api.create_transfer_application(
        lic["id"],
        create_transfer_application_payload(
            t["id"],
            "LEASE",
            lease_start="2027-06-01T00:00:00Z",
            lease_end="2027-01-01T00:00:00Z",
        ),
        make_bidder_headers(r["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEASE_DATES_INVALID)
    assert resp.status_code == 422

    # No TransferApplication persists.
    rows, meta = validate_paginated(api.list_license_transfers(lic["id"], auction_admin_headers))
    assert rows == []
    assert meta["total_count"] == 0


def test_unjust_enrichment_approval_requires_confirmation(
    api, auction_admin_headers, transfer_reviewer_headers
):
    """PRD §3.9: "If the transferee's `credit_pct` is lower than the
    license's `credit_pct`, the schedule percentage is 100 — a less
    credit-eligible buyer repays the credit in full regardless of holding
    period."
    PRD §3.9: "The repayment is the license's `credit_amount_cents`
    multiplied by the schedule percentage, divided by 100, and rounded half
    up to a whole cent."
    PRD §3.9: "Approval requires the license to be `ACTIVE` or
    `RENEWAL_REVIEW` (`ERR_LICENSE_INVALID_STATE` otherwise) and, when the
    application's `unjust_enrichment_cents` exceeds 0, requires the request
    to carry `confirm_unjust_enrichment_repayment` set to true, else
    `ERR_UNJUST_ENRICHMENT_CONFIRMATION_REQUIRED` (422)."

    Design: Corner/errors/unjust_enrichment_approval_requires_confirmation
    """
    env = _rural_license_with_transferee(settle=True)
    lic, r, t = env["license"], env["r"], env["t"]
    assert lic["credit_pct"] == 15
    # credit basis: 250,000,000 gross less the 212,500,000 net.
    assert lic["credit_amount_cents"] == 37_500_000
    assert env["ctx"]["auction"]["id"] == lic["auction_id"]

    set_clock("2027-01-01T00:00:00Z")  # year 0 of the holding period
    ta = file_transfer(lic, t["id"])
    # Transferee credit_pct 0 < 15 forces the 100% schedule.
    assert ta["unjust_enrichment_cents"] == 37_500_000
    assert ta["unjust_enrichment_cents"] == expected_unjust_enrichment_cents(
        37_500_000, GRANT_DAY_ISO, "2027-01-01T00:00:00Z", 0, 15
    )
    transfer_begin_review(ta["id"])

    # APPROVE without the confirmation flag fails; with it, the transfer
    # lands and the holder is rewritten.
    resp = api.review_transfer_application(
        ta["id"], {"action": "APPROVE"}, transfer_reviewer_headers
    )
    validate_error(resp, ApiErrorId.ERR_UNJUST_ENRICHMENT_CONFIRMATION_REQUIRED)
    assert resp.status_code == 422

    approved = transfer_approve(ta["id"], confirm_unjust_enrichment_repayment=True)
    assert approved["status"] == "APPROVED"
    assert get_license(lic["id"])["holder_applicant_id"] == t["id"]


def test_renewal_outside_window_and_double_review_guards(
    api, auction_admin_headers, transfer_reviewer_headers
):
    """PRD §3.9: "A license is renewable inside a window at the end of its
    term: from 365 days before `term_end` through `term_end` itself,
    inclusive at both ends. The holder files for renewal inside that window —
    outside it the filing fails with `ERR_RENEWAL_WINDOW_CLOSED`"
    PRD §3.9: "Any of these attempted from a state without that edge fails
    with `ERR_TRANSFER_INVALID_STATE`"

    Design: Corner/errors/renewal_outside_window_and_double_review_guards
    """
    env = _rural_license_with_transferee(settle=True)
    lic, r, t = env["license"], env["r"], env["t"]
    ta = file_transfer(lic, t["id"])
    transfer_begin_review(ta["id"])  # FILED -> UNDER_REVIEW

    set_clock("2026-10-02T00:00:00Z")  # day after grant: ~10 years early
    ren = api.create_renewal_application(lic["id"], make_bidder_headers(r["id"]))
    validate_error(ren, ApiErrorId.ERR_RENEWAL_WINDOW_CLOSED)
    assert ren.status_code == 409

    # BEGIN_REVIEW has no edge from UNDER_REVIEW.
    again = api.review_transfer_application(
        ta["id"], {"action": "BEGIN_REVIEW"}, transfer_reviewer_headers
    )
    validate_error(again, ApiErrorId.ERR_TRANSFER_INVALID_STATE)
    assert again.status_code == 409

    assert get_license(lic["id"])["status"] == "ACTIVE"
    assert get_transfer(ta["id"])["status"] == "UNDER_REVIEW"


def test_milestone_review_of_pending_and_incumbent_early_clear(
    api, auction_admin_headers
):
    """PRD §3.8: "An `AuctionAdmin` reviews a `FILED` milestone with a
    `decision` of `ACCEPT` or `REJECT`; reviewing a milestone that is not
    `FILED` fails with `ERR_MILESTONE_INVALID_STATE`."
    PRD §3.7: "Finally the owner confirms clearing (`CONFIRM_CLEARED`, moving
    `RELOCATING → CLEARED`), which is allowed only once the logical clock has
    reached `transition_window_end`; an earlier attempt fails with
    `ERR_INCUMBENT_INVALID_STATE`."

    Design: Corner/errors/milestone_review_of_pending_and_incumbent_early_clear
    """
    ctx = setup_closed_auction_with_licenses(
        bids=[(0, "PEA001", "CATEGORY_A", 1)],
        area_codes=("PEA001",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[{"legal_name": "Winner One LLC"}],
    )
    lic = ctx["licenses"][0]

    # The incumbent must be RELOCATING before the completing payment; its
    # window ends 2026-11-05.
    inc = register_incumbent(
        ctx["plan"]["id"],
        ctx["areas"]["PEA001"]["id"],
        callsign="KX500",
        relocation_cost_cents=9_000_000,
    )
    incumbent_submit_plan(inc["id"])
    incumbent_begin_relocation(
        inc["id"], TRANSITION_WINDOW_START_ISO, TRANSITION_WINDOW_END_ISO
    )
    set_clock(GRANT_DAY_ISO)
    lic = settle_license_in_full(lic)
    interim = milestones_by_type(lic["id"])["INTERIM"]
    assert interim["status"] == "PENDING"

    # 2026-10-20 is inside the relocation window but before its end.
    set_clock("2026-10-20T00:00:00Z")
    resp = api.review_milestone(interim["id"], "ACCEPT", auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_MILESTONE_INVALID_STATE)
    assert resp.status_code == 409

    resp2 = api.transition_incumbent(
        inc["id"],
        create_incumbent_transition_payload("CONFIRM_CLEARED"),
        make_incumbent_operator_headers(inc["id"]),
    )
    validate_error(resp2, ApiErrorId.ERR_INCUMBENT_INVALID_STATE)
    assert resp2.status_code == 409

    # Neither guard touched state.
    assert milestones_by_type(lic["id"])["INTERIM"]["status"] == "PENDING"
    assert get_incumbent(inc["id"])["status"] == "RELOCATING"


def test_duplicate_assignment_bid_rejected(api, auction_admin_headers):
    """PRD §3.6: "Only one assignment bid may exist per bidder and product
    (`ERR_DUPLICATE_ASSIGNMENT_BID`)."

    Design: Corner/errors/duplicate_assignment_bid_rejected
    """
    ctx = setup_assignment_phase(
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
    auction_id = ctx["auction"]["id"]
    r_id = ctx["applicants"][0]["id"]

    first = file_assignment_bid(auction_id, r_id, "PEA002", "CATEGORY_A", 0)
    assert first["status"] == "SUBMITTED"

    resp = api.create_assignment_bid(
        auction_id,
        create_assignment_bid_payload("PEA002", "CATEGORY_A", 999),
        make_bidder_headers(r_id),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT_BID)
    assert resp.status_code == 409

    # The first bid stands; no supersede happened.
    rows, meta = validate_paginated(
        api.list_applicant_assignment_bids(r_id, auction_admin_headers)
    )
    assert len(rows) == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["amount_cents"] == 0


def test_transfer_filed_before_license_active_rejected(api, auction_admin_headers):
    """PRD §3.9: "Filing against a license in any other status, including
    `RENEWAL_REVIEW`, fails with `ERR_LICENSE_INVALID_STATE`, and the filer
    must be the license holder (`ERR_FORBIDDEN_OWNERSHIP`)."

    Design: Corner/errors/transfer_filed_before_license_active_rejected
    """
    env = _rural_license_with_transferee(settle=False)
    lic, r, t = env["license"], env["r"], env["t"]
    assert lic["status"] == "PENDING_PAYMENT"

    resp = api.create_transfer_application(
        lic["id"],
        create_transfer_application_payload(t["id"], "FULL_ASSIGNMENT"),
        make_bidder_headers(r["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LICENSE_INVALID_STATE)
    assert resp.status_code == 409

    rows, meta = validate_paginated(api.list_license_transfers(lic["id"], auction_admin_headers))
    assert rows == []
    assert meta["total_count"] == 0
    assert get_license(lic["id"])["status"] == "PENDING_PAYMENT"


def test_renewal_decide_twice_rejected_and_deny_terminates(
    api, auction_admin_headers, transfer_reviewer_headers
):
    """PRD §3.9: "Filing moves the license `ACTIVE → RENEWAL_REVIEW` and
    creates the renewal application, which passes through `FILED` and into
    `UNDER_REVIEW` within the same request — filing and review-open are one
    operation."
    PRD §3.9: "A `TransferReviewer` then decides with a `decision` of `GRANT`
    or `DENY`; deciding an application that is not `UNDER_REVIEW` fails with
    `ERR_RENEWAL_INVALID_STATE`."
    PRD §3.9: "A denial moves the application to `DENIED` and the license
    `RENEWAL_REVIEW → TERMINATED`, and cascades: every transfer application
    of the license still `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED` is
    denied, and the product's `available_supply` entry increases by 1."

    Design: Corner/errors/renewal_decide_twice_rejected_and_deny_terminates
    """
    ctx = setup_active_license(
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
        grant_day_iso=GRANT_DAY_ISO,
    )
    lic = ctx["license"]
    r_id = lic["holder_applicant_id"]

    # Accept both milestones (PEA002 population 500,000; the 40% and 70%
    # bars are 200,000 and 350,000) so the deep-future clock jump cannot
    # sweep them to MISSED.
    file_and_accept_milestone(ctx["milestones"]["INTERIM"], r_id, 500_000)
    file_and_accept_milestone(ctx["milestones"]["FINAL"], r_id, 400_000)

    # term_end is grant 2026-10-01 plus 3650 days; 2035-10-01 is inside the
    # final-365-days renewal window.
    set_clock("2035-10-01T00:00:00Z")
    ren = file_renewal(lic)
    assert ren["status"] == "UNDER_REVIEW"
    assert get_license(lic["id"])["status"] == "RENEWAL_REVIEW"

    decide_renewal(ren["id"], RenewalDecision.DENY)
    assert get_license(lic["id"])["status"] == "TERMINATED"
    rows, _meta = validate_paginated(
        api.list_renewal_applications(lic["id"], auction_admin_headers)
    )
    assert len(rows) == 1
    assert rows[0]["id"] == ren["id"]
    assert rows[0]["status"] == "DENIED"
    # The denial returned the won unit to the product's inventory.
    auction = get_auction(ctx["auction"]["id"])
    assert get_supply_entry(auction, "PEA002", "CATEGORY_A")["available"] == 2

    # Terminal-state lockdown: a second decide on the DENIED application.
    resp = api.decide_renewal(ren["id"], "GRANT", transfer_reviewer_headers)
    validate_error(resp, ApiErrorId.ERR_RENEWAL_INVALID_STATE)
    assert resp.status_code == 409
