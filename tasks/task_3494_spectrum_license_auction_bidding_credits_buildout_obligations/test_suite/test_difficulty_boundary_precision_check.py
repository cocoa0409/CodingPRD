"""Depth tests for boundary precision: the inclusive 80-percent activity
boundary at round close, and the day-1824/day-1825 flip of the
unjust-enrichment repayment schedule."""
from test_helpers import (
    GRANT_DAY_ISO,
    UPFRONT_10M_UNITS,
    UPFRONT_12_5M_UNITS,
    UPFRONT_ONE_UNIT,
    add_area,
    add_block,
    begin_quiet_period,
    close_round,
    complete_assignment,
    create_auction,
    create_draft_plan,
    create_open_auction,
    create_qualified_applicant,
    current_round,
    days_between,
    file_and_accept_milestone,
    file_assignment_bid,
    file_transfer,
    get_applicant,
    get_auction,
    get_license,
    get_transfer,
    list_licenses,
    list_milestones,
    open_applications,
    place_bid,
    publish_plan,
    set_clock,
    settle_license_in_full,
    start_clock,
    transfer_withdraw,
)


def test_activity_requirement_exact_boundary(api):
    """PRD §3.5: "The requirement is set by the round's `stage`: 800
    milli-units (80 percent) in stage 1 and 950 milli-units (95 percent) in
    stage 2. If the applicant's activity multiplied by 1000 is at least the
    stage requirement multiplied by the applicant's current
    `eligibility_units`, eligibility is unchanged — the boundary is inclusive.
    Otherwise `eligibility_units` is reduced to the applicant's activity
    multiplied by 1000 and divided by the stage requirement, rounded down to a
    whole unit."
    PRD §3.5: "When the round being closed shows demand at or below supply
    for every product still open for bidding, closing it also advances the
    auction `CLOCK_ACTIVE → ASSIGNMENT_PHASE`".

    Design: Difficulty/boundary_precision_check/activity_requirement_exact_boundary
    """
    # CATEGORY_A: 10 MHz, supply 2 (10M units); CATEGORY_B here is 5 MHz,
    # supply 1, 10 cents/MHz-pop (5M units) over the 1,000,000-pop area.
    plan = create_draft_plan()
    add_area(plan["id"], "PEA001")
    add_block(plan["id"], "CATEGORY_A")
    add_block(
        plan["id"], "CATEGORY_B", mhz_size=5, supply_per_area=1, price_per_mhz_pop_cents=10
    )
    publish_plan(plan["id"])
    auction = create_auction(plan["id"])
    open_applications(auction["id"])
    p = create_qualified_applicant(auction["id"], UPFRONT_12_5M_UNITS, legal_name="P Bidder")
    q = create_qualified_applicant(auction["id"], UPFRONT_12_5M_UNITS, legal_name="Q Bidder")
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])

    # P lands exactly ON the 800/1000 requirement (10M activity vs 12.5M
    # eligibility); Q lands below it (5M activity). The two differ ONLY in
    # which product they bid.
    r1 = current_round(auction["id"])
    place_bid(r1["id"], p["id"], "PEA001", "CATEGORY_A", 1)
    place_bid(r1["id"], q["id"], "PEA001", "CATEGORY_B", 1)
    close_round(r1["id"])

    # Inclusive boundary: 10,000,000 * 1000 >= 800 * 12,500,000 exactly -> no
    # reduction for P.
    assert get_applicant(p["id"])["eligibility_units"] == 12_500_000
    # 5,000,000 * 1000 < 800 * 12,500,000 -> floor(5,000,000*1000/800).
    assert get_applicant(q["id"])["eligibility_units"] == 6_250_000

    # Both demands are at or below supply, so the auction advances.
    assert get_auction(auction["id"])["status"] == "ASSIGNMENT_PHASE"


def test_unjust_enrichment_day_1824_vs_1825(api):
    """PRD §3.9: "Otherwise the schedule steps down over five 365-day years:
    100 percent during year 0, then 80, 60, 40, and 20 percent during years 1
    through 4 respectively, and 0 percent at five or more years — so a
    transfer filed exactly 1825 days after grant owes nothing, while one filed
    on day 1824 still owes 20 percent."
    PRD §3.9: "The repayment is the license's `credit_amount_cents` multiplied
    by the schedule percentage, divided by 100, and rounded half up to a whole
    cent."
    PRD §3.9: "The transferor may withdraw from `FILED` or `INFO_REQUESTED`,
    moving the application to `WITHDRAWN`."

    Design: Difficulty/boundary_precision_check/unjust_enrichment_day_1824_vs_1825
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
    # Transferee qualifies with the same 15% rural credit, so the schedule
    # arm (not the 100% down-qualification arm) applies.
    t2 = create_qualified_applicant(
        auction["id"],
        UPFRONT_ONE_UNIT,
        legal_name="T2 Rural Buyer",
        claims_rural_credit=True,
        service_population=100_000,
    )
    assert get_applicant(t2["id"])["credit_pct"] == 15
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])
    r1 = current_round(auction["id"])
    place_bid(r1["id"], r["id"], "PEA002", "CATEGORY_A", 1)
    close_round(r1["id"])
    file_assignment_bid(auction["id"], r["id"], "PEA002", "CATEGORY_A", 0)
    complete_assignment(auction["id"])
    lic = list_licenses(holder_applicant_id=r["id"])[0]
    assert lic["credit_amount_cents"] == 37_500_000

    set_clock(GRANT_DAY_ISO)  # grant lands at 2026-10-01
    lic = settle_license_in_full(lic)
    assert lic["status"] == "ACTIVE"
    assert lic["grant_date"] == GRANT_DAY_ISO

    # ACCEPTED is terminal for milestones: accepting both here keeps the
    # deep-future clock jumps from missing them and terminating the license.
    milestones = list_milestones(lic["id"])
    file_and_accept_milestone(milestones[0], r["id"], 500_000)  # >= 40% of 500,000
    file_and_accept_milestone(milestones[1], r["id"], 400_000)  # >= 70% of 500,000

    # 2031-09-29 is grant + 1824 days: years_elapsed 4 -> 20% of 37,500,000.
    assert days_between(GRANT_DAY_ISO, "2031-09-29T00:00:00Z") == 1824
    set_clock("2031-09-29T00:00:00Z")
    ta1 = file_transfer(lic, t2["id"])
    assert ta1["status"] == "FILED"
    assert ta1["unjust_enrichment_cents"] == 7_500_000

    transfer_withdraw(ta1["id"], r["id"])
    assert get_transfer(ta1["id"])["status"] == "WITHDRAWN"

    # 2031-09-30 is grant + 1825 days: years_elapsed 5 -> schedule bucket 0.
    assert days_between(GRANT_DAY_ISO, "2031-09-30T00:00:00Z") == 1825
    set_clock("2031-09-30T00:00:00Z")
    ta2 = file_transfer(lic, t2["id"])
    assert ta2["status"] == "FILED"
    assert ta2["unjust_enrichment_cents"] == 0

    # Both computations share the same recorded credit basis.
    assert get_license(lic["id"])["credit_amount_cents"] == 37_500_000
