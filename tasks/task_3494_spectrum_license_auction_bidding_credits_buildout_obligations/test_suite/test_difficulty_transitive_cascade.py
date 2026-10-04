"""Depth tests for depth-3 transitive cascades: the clock-sweep milestone
miss chain (milestone -> license -> transfer + supply) and the disqualify
chain (applicant -> bids -> live demand + forfeiture ledger)."""
from test_helpers import (
    GRANT_DAY_ISO,
    UPFRONT_10M_UNITS,
    UPFRONT_12_5M_UNITS,
    ApplicantReviewAction,
    assert_applicant,
    assert_upfront_ledger_conserved,
    begin_quiet_period,
    close_round,
    complete_assignment,
    create_open_auction,
    create_qualified_applicant,
    current_round,
    file_assignment_bid,
    file_transfer,
    get_applicant,
    get_auction,
    get_demand_entry,
    get_license,
    get_round,
    get_supply_entry,
    get_transfer,
    list_licenses,
    list_milestones,
    place_bid,
    register_applicant,
    review_applicant,
    set_clock,
    settle_license_in_full,
    setup_clock_active_auction,
    start_clock,
    transfer_begin_review,
    validate_paginated,
)


def test_final_milestone_miss_terminates_license_cascade(api, auction_admin_headers):
    """PRD §2.4: "Second, the milestone sweep: every buildout milestone in
    `PENDING`, `FILED`, or `REJECTED` whose `due_date` is earlier than the new
    instant becomes `MISSED`, with the consequences described in §3.8 — a
    missed `INTERIM` milestone accelerates its sibling `FINAL` milestone's due
    date by 365 days, and a missed `FINAL` milestone terminates the license
    with its own cascade."
    PRD §3.8: "A missed `FINAL` milestone terminates the license: the license
    moves `ACTIVE → TERMINATED`, every transfer application of that license
    still `FILED`, `UNDER_REVIEW`, or `INFO_REQUESTED` is moved to `DENIED`,
    and the product's `available_supply` entry increases by 1."

    Design: Difficulty/transitive_cascade/final_milestone_miss_terminates_license_cascade
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
    # Transferee is registered (never qualified) before the quiet period.
    t = register_applicant(auction["id"], legal_name="Transferee Co")
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])
    r1 = current_round(auction["id"])
    place_bid(r1["id"], r["id"], "PEA002", "CATEGORY_A", 1)
    close_round(r1["id"])
    file_assignment_bid(auction["id"], r["id"], "PEA002", "CATEGORY_A", 0)
    complete_assignment(auction["id"])
    lic = list_licenses(holder_applicant_id=r["id"])[0]

    set_clock(GRANT_DAY_ISO)  # 2026-10-01
    lic = settle_license_in_full(lic)
    assert lic["status"] == "ACTIVE"
    assert lic["paid_cents"] == 212_500_000

    # One of two units of supply was consumed by the grant.
    auction_mid = get_auction(auction["id"])
    assert get_supply_entry(auction_mid, "PEA002", "CATEGORY_A")["available"] == 1

    milestones = list_milestones(lic["id"])
    assert [m["milestone_type"] for m in milestones] == ["INTERIM", "FINAL"]
    assert all(m["status"] == "PENDING" for m in milestones)

    ta = file_transfer(lic, t["id"])
    transfer_begin_review(ta["id"])
    assert get_transfer(ta["id"])["status"] == "UNDER_REVIEW"

    # Hop 0 is the clock sweep: grant+1095d (INTERIM) and the 365-day-
    # accelerated grant+1825d (FINAL) both pass before 2032-09-30.
    set_clock("2032-09-30T00:00:00Z")

    milestones_after = {m["milestone_type"]: m for m in list_milestones(lic["id"])}
    assert milestones_after["INTERIM"]["status"] == "MISSED"
    assert milestones_after["FINAL"]["status"] == "MISSED"

    # Hop 1: FINAL MISSED terminates the license.
    lic_after = get_license(lic["id"])
    assert lic_after["status"] == "TERMINATED"
    # Termination does not rewrite settlement history.
    assert lic_after["paid_cents"] == 212_500_000

    # Hop 2: the termination itself denies the pending transfer and returns
    # the product's supply.
    assert get_transfer(ta["id"])["status"] == "DENIED"
    auction_after = get_auction(auction["id"])
    assert get_supply_entry(auction_after, "PEA002", "CATEGORY_A")["available"] == 2


def test_disqualify_voids_bids_recomputes_demand(api, auction_admin_headers):
    """PRD §3.3: "It moves an applicant `QUALIFIED → DISQUALIFIED` and is
    available only while the auction is `QUIET_PERIOD`, `CLOCK_ACTIVE`, or
    `CLOCK_PAUSED`; at any other auction phase the attempt fails with
    `ERR_APPLICANT_INVALID_STATE`. Disqualification cascades in two hops:
    first, every `SUBMITTED` bid the applicant holds in the currently open
    clock round becomes `VOIDED`; second, each voiding itself triggers live
    recomputation of that round's `aggregate_demand` with the voided
    quantities removed. The applicant's entire held deposit is then forfeit —
    `upfront_held_cents` moves into `upfront_forfeited_cents` — and the
    auction's `forfeited_deposits_cents` grows by the forfeited amount."

    Design: Difficulty/transitive_cascade/disqualify_voids_bids_recomputes_demand
    """
    ctx = setup_clock_active_auction(
        area_codes=("PEA001",),
        block_categories=("CATEGORY_A",),
        bidder_specs=[
            {"legal_name": "P Bidder", "upfront_cents": UPFRONT_12_5M_UNITS},
            {"legal_name": "Q Bidder", "upfront_cents": UPFRONT_12_5M_UNITS},
        ],
    )
    p, q = ctx["applicants"]
    auction_id = ctx["auction"]["id"]
    r1 = ctx["round"]

    place_bid(r1["id"], p["id"], "PEA001", "CATEGORY_A", 1)
    place_bid(r1["id"], q["id"], "PEA001", "CATEGORY_A", 1)
    demand_pre = get_demand_entry(get_round(r1["id"]), "PEA001", "CATEGORY_A")[
        "demand_quantity"
    ]
    assert demand_pre == 2

    # Hop 0 -> 1: the DISQUALIFY admin action (auction is CLOCK_ACTIVE).
    review_applicant(q["id"], ApplicantReviewAction.DISQUALIFY)

    q_after = get_applicant(q["id"])
    assert_applicant(q_after)
    assert q_after["status"] == "DISQUALIFIED"
    assert q_after["upfront_held_cents"] == 0
    assert q_after["upfront_forfeited_cents"] == UPFRONT_12_5M_UNITS
    assert_upfront_ledger_conserved(q_after)

    # Hop 1 -> 2: the disqualified bidder's SUBMITTED bid is VOIDED.
    q_bids, _ = validate_paginated(
        api.list_applicant_bids(q["id"], auction_admin_headers)
    )
    assert len(q_bids) == 1
    assert q_bids[0]["status"] == "VOIDED"

    # Hop 2 -> 3: the voiding itself recomputes the live round demand.
    demand_post = get_demand_entry(get_round(r1["id"]), "PEA001", "CATEGORY_A")[
        "demand_quantity"
    ]
    assert demand_post == 1

    # The forfeited deposit lands on the auction ledger.
    assert get_auction(auction_id)["forfeited_deposits_cents"] == UPFRONT_12_5M_UNITS

    # The other bidder is untouched by the cascade.
    p_bids, _ = validate_paginated(
        api.list_applicant_bids(p["id"], auction_admin_headers)
    )
    assert len(p_bids) == 1
    assert p_bids[0]["status"] == "SUBMITTED"
    assert get_applicant(p["id"])["status"] == "QUALIFIED"
