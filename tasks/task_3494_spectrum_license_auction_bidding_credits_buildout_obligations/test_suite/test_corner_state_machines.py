"""Breadth tests over the state-machine surface: invalid transitions,
terminal lockdowns, idempotency, precondition enforcement, valid cyclic
edges, and transition side effects."""
from test_helpers import (
    GRANT_DAY_ISO,
    UPFRONT_10M_UNITS,
    ApiErrorId,
    MilestoneDecision,
    RenewalDecision,
    add_area,
    add_block,
    assert_clock_round,
    assert_upfront_ledger_conserved,
    begin_quiet_period,
    close_round,
    complete_assignment,
    create_draft_plan,
    create_open_auction,
    create_published_plan,
    create_qualified_applicant,
    decide_renewal,
    expected_term_end,
    file_and_accept_milestone,
    file_assignment_bid,
    file_milestone_notice,
    file_renewal,
    file_transfer,
    get_applicant,
    get_auction,
    get_demand_entry,
    get_license,
    get_price_entry,
    get_round,
    get_supply_entry,
    get_transfer,
    list_licenses,
    list_rounds,
    patch_disclosure,
    pay_upfront,
    place_bid,
    postpone,
    register_applicant,
    review_milestone,
    set_clock,
    settle_license_in_full,
    setup_assignment_phase,
    setup_clock_active_auction,
    setup_closed_auction_with_licenses,
    start_clock,
    transfer_withdraw,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_qualify_from_submitted_rejected_invalid_state(api, auction_admin_headers):
    """PRD §3.3: "Qualification (`QUALIFY`, moving the applicant
    `UNDER_REVIEW → QUALIFIED`) applies four checks in a fixed order. First
    the state gate: the applicant must be `UNDER_REVIEW`, else
    `ERR_APPLICANT_INVALID_STATE`."

    Design: Corner/state_machines/qualify_from_submitted_rejected_invalid_state
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    r = register_applicant(
        ctx["auction"]["id"],
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    r = pay_upfront(r["id"], UPFRONT_10M_UNITS)

    # QUALIFY is only legal from UNDER_REVIEW; SUBMITTED is rejected and the
    # record is not mutated.
    resp = api.review_applicant(r["id"], "QUALIFY", auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_INVALID_STATE)
    assert resp.status_code == 409

    r_after = get_applicant(r["id"])
    assert r_after["status"] == "SUBMITTED"
    assert r_after["credit_pct"] == 0


def test_rejected_applicant_terminal_lockdown(api, auction_admin_headers):
    """PRD §3.3: "Rejection (`REJECT`) moves an applicant `UNDER_REVIEW →
    REJECTED` and refunds the deposit in full: the entire
    `upfront_held_cents` moves into `upfront_refunded_cents`, leaving the
    held balance at 0 and preserving the conservation invariant."
    PRD §3.3: "Both `REJECTED` and `WITHDRAWN` are terminal."

    Design: Corner/state_machines/rejected_applicant_terminal_lockdown
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    r = register_applicant(
        ctx["auction"]["id"],
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    r = pay_upfront(r["id"], UPFRONT_10M_UNITS)
    review = api.review_applicant
    validate_success(review(r["id"], "START_REVIEW", auction_admin_headers), 200)
    validate_success(review(r["id"], "REJECT", auction_admin_headers), 200)

    # Terminal lockdown: no review edge leaves REJECTED.
    resp = review(r["id"], "START_REVIEW", auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_APPLICANT_INVALID_STATE)

    r_after = get_applicant(r["id"])
    assert r_after["status"] == "REJECTED"
    # The refund side effect of REJECT is the final ledger state.
    assert r_after["upfront_refunded_cents"] == UPFRONT_10M_UNITS
    assert r_after["upfront_held_cents"] == 0
    assert_upfront_ledger_conserved(r_after)


def test_double_publish_band_plan_rejected(api, auction_admin_headers):
    """PRD §3.1: "Publishing moves the plan `DRAFT → PUBLISHED`" and
    "attempting to publish a plan that is no longer `DRAFT` fails with
    `ERR_BAND_PLAN_NOT_DRAFT`. `PUBLISHED` is terminal".
    PRD §2.5: "The `version` field is an integer that starts at 1 and
    increments by exactly one on every mutation of the resource".

    Design: Corner/state_machines/double_publish_band_plan_rejected
    """
    ctx = create_published_plan(("PEA002",), ("CATEGORY_A",))
    plan_id = ctx["plan"]["id"]
    assert ctx["plan"]["status"] == "PUBLISHED"

    resp = api.publish_band_plan(plan_id, auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_BAND_PLAN_NOT_DRAFT)
    assert resp.status_code == 409

    # The failed second publish is not a mutation: version stays at 2
    # (creation v1 + the one successful publish).
    plan_after = validate_success(api.get_band_plan(plan_id, auction_admin_headers), 200)
    assert plan_after["status"] == "PUBLISHED"
    assert plan_after["version"] == 2


def test_band_plan_publish_requires_area_and_block(api, auction_admin_headers):
    """PRD §3.1: "Publishing moves the plan `DRAFT → PUBLISHED` and requires
    at least one license area and at least one license block; publishing an
    empty plan fails with `ERR_BAND_PLAN_INCOMPLETE` (422)".

    Design: Corner/state_machines/band_plan_publish_requires_area_and_block
    """
    plan = create_draft_plan()
    add_block(plan["id"], "CATEGORY_A")

    # Zero areas: the publish precondition fails.
    resp = api.publish_band_plan(plan["id"], auction_admin_headers)
    validate_error(resp, ApiErrorId.ERR_BAND_PLAN_INCOMPLETE)
    assert resp.status_code == 422

    # After adding an area the same publish succeeds.
    add_area(plan["id"], "PEA002")
    published = validate_success(api.publish_band_plan(plan["id"], auction_admin_headers), 200)
    assert published["status"] == "PUBLISHED"


def test_auction_postpone_reverts_quiet_period(api):
    """PRD §3.4: "If conditions change, the administrator may postpone
    (`action` `POSTPONE`, moving `QUIET_PERIOD → APPLICATION_OPEN`), which
    lifts the freeze; the auction may later re-enter the quiet period,
    subject again to the deadline check."

    Design: Corner/state_machines/auction_postpone_reverts_quiet_period
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
    assert get_auction(auction["id"])["status"] == "QUIET_PERIOD"

    # The revert edge lifts the anti-collusion freeze: a disclosure edit that
    # would be rejected during QUIET_PERIOD now succeeds.
    postpone(auction["id"])
    assert get_auction(auction["id"])["status"] == "APPLICATION_OPEN"
    s2 = patch_disclosure(s["id"], s_v, legal_name="Sigma LLC (amended)")
    assert s2["legal_name"] == "Sigma LLC (amended)"
    assert s2["version"] == s_v + 1


def test_milestone_refile_after_rejection_cycle(api, auction_admin_headers):
    """PRD §3.8: "Filing is allowed from `PENDING` or `REJECTED` — filing
    against an `ACCEPTED` or `MISSED` milestone fails with
    `ERR_MILESTONE_INVALID_STATE`" and "Rejection moves the milestone to
    `REJECTED`, from which the licensee may re-file under the same rules as
    an initial filing."
    PRD §3.8: "the certified `covered_population` multiplied by 100 must be
    at least the milestone's `required_coverage_pct` multiplied by the
    license area's `population` — an exact integer comparison with an
    inclusive boundary, so coverage of exactly 40.000 percent passes an
    `INTERIM` milestone".
    PRD §2.5: "The `version` field is an integer that starts at 1 and
    increments by exactly one on every mutation of the resource".

    Design: Corner/state_machines/milestone_refile_after_rejection_cycle
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA001",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[{"legal_name": "Winner One LLC"}],
    )
    w1 = ctx["applicants"][0]
    auction_id = ctx["auction"]["id"]
    r1 = ctx["round"]
    place_bid(r1["id"], w1["id"], "PEA001", "CATEGORY_A", 1)
    close_round(r1["id"])
    file_assignment_bid(auction_id, w1["id"], "PEA001", "CATEGORY_A", 0)
    complete_assignment(auction_id)
    lic = list_licenses(holder_applicant_id=w1["id"])[0]
    set_clock(GRANT_DAY_ISO)
    lic = settle_license_in_full(lic)
    assert lic["status"] == "ACTIVE"

    # INTERIM milestone of the 1,000,000-pop area: required_coverage_pct 40.
    ms_rows, _ = validate_paginated(
        api.list_buildout_milestones(lic["id"], auction_admin_headers)
    )
    interim = [m for m in ms_rows if m["milestone_type"] == "INTERIM"][0]
    v0 = interim["version"]
    assert v0 == 1

    # First filing below the bar; REJECT is not coverage-gated.
    filed1 = file_milestone_notice(interim["id"], w1["id"], 399_999, v0)
    assert filed1["status"] == "FILED"
    assert filed1["covered_population"] == 399_999
    assert filed1["version"] == v0 + 1
    rejected = review_milestone(interim["id"], MilestoneDecision.REJECT)
    assert rejected["status"] == "REJECTED"
    assert rejected["version"] == v0 + 2

    # The REJECTED -> FILED loop edge: re-filing with the fresh OCC version.
    filed2 = file_milestone_notice(interim["id"], w1["id"], 400_000, v0 + 2)
    assert filed2["status"] == "FILED"
    assert filed2["version"] == v0 + 3

    # 400,000 * 100 >= 40 * 1,000,000 exactly (inclusive boundary).
    accepted = review_milestone(interim["id"], MilestoneDecision.ACCEPT)
    assert accepted["status"] == "ACCEPTED"


def test_transfer_withdraw_from_filed_keeps_license_untouched(api):
    """PRD §3.9: "The transferor may withdraw from `FILED` or
    `INFO_REQUESTED`, moving the application to `WITHDRAWN`."
    PRD §3.6: "the lease fields `active_lease_start`, `active_lease_end`, and
    `leased_to_applicant_id` are null while no lease is active".
    PRD §3.9: "An approved `FULL_ASSIGNMENT` rewrites the license's
    `holder_applicant_id` to the transferee." — only approval rewrites the
    license; withdrawal carries no compensation.

    Design: Corner/state_machines/transfer_withdraw_from_filed_keeps_license_untouched
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction = ctx["auction"]
    r = create_qualified_applicant(
        auction["id"],
        UPFRONT_10M_UNITS,
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    t = register_applicant(auction["id"], legal_name="T Co")
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])
    rounds = list_rounds(auction["id"])
    place_bid(rounds[0]["id"], r["id"], "PEA002", "CATEGORY_A", 1)
    close_round(rounds[0]["id"])
    file_assignment_bid(auction["id"], r["id"], "PEA002", "CATEGORY_A", 0)
    complete_assignment(auction["id"])
    lic = list_licenses(holder_applicant_id=r["id"])[0]
    set_clock(GRANT_DAY_ISO)
    lic = settle_license_in_full(lic)

    ta = file_transfer(lic, t["id"])
    assert ta["status"] == "FILED"

    transfer_withdraw(ta["id"], r["id"])
    assert get_transfer(ta["id"])["status"] == "WITHDRAWN"

    # The license is exactly as before: holder unchanged, still ACTIVE, no
    # lease fields set.
    lic_after = get_license(lic["id"])
    assert lic_after["holder_applicant_id"] == r["id"]
    assert lic_after["status"] == "ACTIVE"
    assert lic_after["active_lease_start"] is None
    assert lic_after["active_lease_end"] is None
    assert lic_after["leased_to_applicant_id"] is None


def test_payment_deadline_lapse_cancels_license(api):
    """PRD §3.6: "Each license's `payment_deadline` is set to the logical
    instant of its creation plus 30 days".
    PRD §3.7: "If the logical clock advances past a license's
    `payment_deadline` while it is still `PENDING_PAYMENT`, the deadline
    sweep cancels it, and the cancellation cascades in two hops: first, the
    holder's remaining held deposit is forfeit — the holder applicant's
    `upfront_held_cents` moves into its `upfront_forfeited_cents`; second,
    that forfeiture itself adds the forfeited amount to the auction's
    `forfeited_deposits_cents`."

    Design: Corner/state_machines/payment_deadline_lapse_cancels_license
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
    # Created while the clock read 2026-09-16 -> deadline +30 days.
    assert lic["payment_deadline"] == "2026-10-16T00:00:00Z"
    assert lic["status"] == "PENDING_PAYMENT"

    set_clock("2026-10-17T00:00:00Z")

    lic_after = get_license(lic["id"])
    assert lic_after["status"] == "CANCELLED"
    assert lic_after["payment_deadline"] == "2026-10-16T00:00:00Z"
    r_after = get_applicant(r["id"])
    assert r_after["upfront_held_cents"] == 0
    assert r_after["upfront_forfeited_cents"] == UPFRONT_10M_UNITS
    assert_upfront_ledger_conserved(r_after)
    assert get_auction(ctx["auction"]["id"])["forfeited_deposits_cents"] == UPFRONT_10M_UNITS


def test_start_clock_creates_round_one_with_opening_prices(api):
    """PRD §3.4: "The transition performs four side effects atomically. It
    creates clock round 1 in `OPEN` status with opening prices: for every
    product — every (area, block) pair of the auction's band plan — the
    posted `price_cents` is the block's `mhz_size` multiplied by the area's
    `population`, multiplied by the block's `price_per_mhz_pop_cents`, an
    exact integer with no rounding step. It initializes the auction's
    `available_supply`, an array of (`area_code`, `category`, `available`)
    entries in which every product's `available` starts at the block's
    `supply_per_area`. It snapshots every `QUALIFIED` applicant's
    `initial_eligibility_units` from that applicant's current
    `eligibility_units`. And it sets the auction's `current_round_number` to
    1."

    Design: Corner/state_machines/start_clock_creates_round_one_with_opening_prices
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction = ctx["auction"]
    r = create_qualified_applicant(
        auction["id"],
        UPFRONT_10M_UNITS,
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    begin_quiet_period(auction["id"], auction["application_deadline"])

    start_clock(auction["id"])

    rounds = list_rounds(auction["id"])
    assert len(rounds) == 1
    r1 = rounds[0]
    assert_clock_round(r1)
    assert r1["round_number"] == 1
    assert r1["stage"] == 1
    assert r1["status"] == "OPEN"
    # 10 MHz * 500,000 pop * 50 cents/MHz-pop = 250,000,000.
    assert len(r1["prices"]) == 1
    price = get_price_entry(r1, "PEA002", "CATEGORY_A")
    assert price["price_cents"] == 250_000_000

    auction_after = get_auction(auction["id"])
    assert auction_after["status"] == "CLOCK_ACTIVE"
    assert auction_after["current_round_number"] == 1
    assert get_supply_entry(auction_after, "PEA002", "CATEGORY_A")["available"] == 2

    r_after = get_applicant(r["id"])
    assert r_after["initial_eligibility_units"] == 10_000_000


def test_complete_assignment_marks_bids_applied_and_licenses_created(
    api, auction_admin_headers
):
    """PRD §3.6: "Completion mints one license per won unit, in
    `PENDING_PAYMENT` status." and "The `credit_pct` is copied from the
    winning applicant at creation and never changes thereafter".
    PRD §3.6: "Completion also marks every winner's assignment bid `SUBMITTED
    → APPLIED` — `APPLIED` is terminal for the assignment bid — decrements
    each product's `available_supply` entry by the number of licenses created
    in it, and moves the auction to `CLOSED`, its terminal state."
    PRD §3.6: "the auction's `total_proceeds_cents` is then the sum of those
    per-license figures".

    Design: Corner/state_machines/complete_assignment_marks_bids_applied_and_licenses_created
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
    r = ctx["applicants"][0]
    auction_id = ctx["auction"]["id"]
    ab = file_assignment_bid(auction_id, r["id"], "PEA002", "CATEGORY_A", 0)
    assert ab["status"] == "SUBMITTED"

    complete_assignment(auction_id)

    # The winner's assignment bid flipped to APPLIED in the same aftermath.
    abs_rows, _ = validate_paginated(
        api.list_applicant_assignment_bids(r["id"], auction_admin_headers)
    )
    assert len(abs_rows) == 1
    assert abs_rows[0]["status"] == "APPLIED"

    lic = list_licenses(holder_applicant_id=r["id"])[0]
    assert lic["status"] == "PENDING_PAYMENT"
    assert lic["holder_applicant_id"] == r["id"]
    assert lic["credit_pct"] == 15

    auction_after = get_auction(auction_id)
    assert auction_after["status"] == "CLOSED"
    # Single license: 250,000,000 * 85/100 = 212,500,000.
    assert auction_after["total_proceeds_cents"] == 212_500_000


def test_bid_creation_live_updates_round_demand(api):
    """PRD §3.5: "While a round is `OPEN`, demand is maintained live: each
    new bid adds its quantity into the round's `aggregate_demand`, and each
    voided bid's quantity is removed, so the open round always reflects
    current `SUBMITTED` bids."

    Design: Corner/state_machines/bid_creation_live_updates_round_demand
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA002",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {
                "legal_name": "Rural Wireless Co",
                "claims_rural_credit": True,
                "service_population": 200_000,
            },
            {"legal_name": "Winner One LLC"},
        ],
    )
    r, w1 = ctx["applicants"]
    r1 = ctx["round"]

    place_bid(r1["id"], r["id"], "PEA002", "CATEGORY_A", 1)
    place_bid(r1["id"], w1["id"], "PEA002", "CATEGORY_A", 2)

    # The round is still OPEN and the demand ledger already reads 1 + 2.
    live = get_round(r1["id"])
    assert live["status"] == "OPEN"
    assert get_demand_entry(live, "PEA002", "CATEGORY_A")["demand_quantity"] == 3


def test_renewal_grant_extends_term_and_cycles_license(api, auction_admin_headers):
    """PRD §3.9: "A license is renewable inside a window at the end of its
    term: from 365 days before `term_end` through `term_end` itself,
    inclusive at both ends."
    PRD §3.9: "Filing moves the license `ACTIVE → RENEWAL_REVIEW` and creates
    the renewal application, which passes through `FILED` and into
    `UNDER_REVIEW` within the same request — filing and review-open are one
    operation."
    PRD §3.9: "A grant moves the application to `GRANTED`, returns the
    license to `ACTIVE`, and extends `term_end` by 3650 days, so the renewal
    cycle may repeat when the new window arrives."

    Design: Corner/state_machines/renewal_grant_extends_term_and_cycles_license
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction = ctx["auction"]
    r = create_qualified_applicant(
        auction["id"],
        UPFRONT_10M_UNITS,
        legal_name="Rural Wireless Co",
        claims_rural_credit=True,
        service_population=200_000,
    )
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])
    rounds = list_rounds(auction["id"])
    place_bid(rounds[0]["id"], r["id"], "PEA002", "CATEGORY_A", 1)
    close_round(rounds[0]["id"])
    file_assignment_bid(auction["id"], r["id"], "PEA002", "CATEGORY_A", 0)
    complete_assignment(auction["id"])
    lic = list_licenses(holder_applicant_id=r["id"])[0]
    set_clock(GRANT_DAY_ISO)  # 2026-10-01
    lic = settle_license_in_full(lic)
    assert lic["status"] == "ACTIVE"
    assert lic["grant_date"] == GRANT_DAY_ISO
    # term_end = grant + 3650 days = 2036-09-28 (calendar-naive day math).
    assert lic["term_end"] == expected_term_end(GRANT_DAY_ISO) == "2036-09-28T00:00:00Z"

    # Accept both milestones (40% and 70% of the 500,000-pop area) so the
    # deep-future clock jump cannot miss them and terminate the license.
    ms_rows, _ = validate_paginated(
        api.list_buildout_milestones(lic["id"], auction_admin_headers)
    )
    interim = [m for m in ms_rows if m["milestone_type"] == "INTERIM"][0]
    final = [m for m in ms_rows if m["milestone_type"] == "FINAL"][0]
    file_and_accept_milestone(interim, r["id"], 500_000)
    file_and_accept_milestone(final, r["id"], 400_000)

    # The renewal window is [2035-09-29, 2036-09-28]; 2035-10-01 is inside.
    set_clock("2035-10-01T00:00:00Z")
    ren = file_renewal(lic)
    assert ren["status"] == "UNDER_REVIEW"  # filing and review-open are one request
    assert get_license(lic["id"])["status"] == "RENEWAL_REVIEW"

    decide_renewal(ren["id"], RenewalDecision.GRANT)

    lic_after = get_license(lic["id"])
    assert lic_after["status"] == "ACTIVE"  # the cycle completed
    # 2036-09-28 + 3650 days = 2046-09-26.
    assert (
        lic_after["term_end"]
        == expected_term_end(GRANT_DAY_ISO, renewals_granted=1)
        == "2046-09-26T00:00:00Z"
    )
    ren_rows, _ = validate_paginated(
        api.list_renewal_applications(lic["id"], auction_admin_headers)
    )
    assert len(ren_rows) == 1
    assert ren_rows[0]["status"] == "GRANTED"
