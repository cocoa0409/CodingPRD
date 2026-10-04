"""Depth tests for resource temporal overlap: half-open lease windows on a
license (adjacency allowed) versus closed-interval incumbent relocation
windows with a mandatory 30-day buffer (adjacency alone insufficient)."""
from test_helpers import (
    GRANT_DAY_ISO,
    UPFRONT_10M_UNITS,
    ApiErrorId,
    begin_quiet_period,
    close_round,
    complete_assignment,
    create_incumbent_transition_payload,
    create_open_auction,
    create_published_plan,
    create_qualified_applicant,
    create_transfer_application_payload,
    current_round,
    file_assignment_bid,
    file_transfer,
    get_incumbent,
    get_license,
    get_transfer,
    incumbent_begin_relocation,
    incumbent_submit_plan,
    iso_after_days,
    list_licenses,
    make_bidder_headers,
    place_bid,
    register_applicant,
    register_incumbent,
    set_clock,
    settle_license_in_full,
    start_clock,
    transfer_approve,
    transfer_begin_review,
    validate_error,
    validate_paginated,
)


def test_lease_windows_half_open_on_license(api, auction_admin_headers):
    """PRD §3.9: "A lease additionally requires `lease_start` and `lease_end`
    with the end strictly after the start (`ERR_LEASE_DATES_INVALID`, 422),
    and its window — half-open, containing every instant from `lease_start`
    up to but not including `lease_end` — must not intersect any
    already-approved lease window on the same license; the overlap scan
    covers all approved windows of the license, not only the currently active
    one, while merely touching endpoints is allowed
    (`ERR_LEASE_WINDOW_OVERLAP`, 409)."
    PRD §3.9: "When the license's `credit_amount_cents` is 0, the repayment
    is 0."

    Design: Difficulty/resource_temporal_overlap/lease_windows_half_open_on_license
    """
    ctx = create_open_auction(area_codes=("PEA002",), block_categories=("CATEGORY_A",))
    auction = ctx["auction"]
    w1 = create_qualified_applicant(
        auction["id"], UPFRONT_10M_UNITS, legal_name="Winner One LLC"
    )
    t1 = register_applicant(auction["id"], legal_name="T1 Co")
    t2 = register_applicant(auction["id"], legal_name="T2 Co")
    t3 = register_applicant(auction["id"], legal_name="T3 Co")
    begin_quiet_period(auction["id"], auction["application_deadline"])
    start_clock(auction["id"])
    r1 = current_round(auction["id"])
    place_bid(r1["id"], w1["id"], "PEA002", "CATEGORY_A", 1)
    close_round(r1["id"])
    file_assignment_bid(auction["id"], w1["id"], "PEA002", "CATEGORY_A", 0)
    complete_assignment(auction["id"])
    lic = list_licenses(holder_applicant_id=w1["id"])[0]
    assert lic["credit_amount_cents"] == 0  # no-credit winner

    set_clock(GRANT_DAY_ISO)
    lic = settle_license_in_full(lic)
    assert lic["status"] == "ACTIVE"

    # Lease 1: [2028-01-01, 2028-07-01).
    lease1 = file_transfer(
        lic,
        t1["id"],
        transfer_type="LEASE",
        lease_start="2028-01-01T00:00:00Z",
        lease_end="2028-07-01T00:00:00Z",
    )
    assert lease1["unjust_enrichment_cents"] == 0
    transfer_begin_review(lease1["id"])
    transfer_approve(lease1["id"])
    assert get_transfer(lease1["id"])["status"] == "APPROVED"

    # Lease 2 starts exactly at lease1's end: half-open adjacency is NOT an
    # overlap, so it approves.
    lease2 = file_transfer(
        lic,
        t2["id"],
        transfer_type="LEASE",
        lease_start="2028-07-01T00:00:00Z",
        lease_end="2029-01-01T00:00:00Z",
    )
    assert lease2["unjust_enrichment_cents"] == 0
    transfer_begin_review(lease2["id"])
    transfer_approve(lease2["id"])
    assert get_transfer(lease2["id"])["status"] == "APPROVED"

    # Lease 3 starts one day earlier: [2028-06-30, 2028-12-01) intersects
    # lease1 by one day and is rejected at filing time.
    resp = api.create_transfer_application(
        lic["id"],
        create_transfer_application_payload(
            t3["id"],
            "LEASE",
            lease_start="2028-06-30T00:00:00Z",
            lease_end="2028-12-01T00:00:00Z",
        ),
        make_bidder_headers(w1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEASE_WINDOW_OVERLAP)

    transfers, _ = validate_paginated(
        api.list_license_transfers(lic["id"], auction_admin_headers)
    )
    assert len(transfers) == 2

    # Both approved windows are in the future, so no lease is active yet.
    lic_after = get_license(lic["id"])
    assert lic_after["active_lease_start"] is None
    assert lic_after["active_lease_end"] is None
    assert lic_after["leased_to_applicant_id"] is None


def test_incumbent_windows_buffer_gap_in_area(api, auction_admin_headers):
    """PRD §3.7: "An `AuctionAdmin` then begins relocation
    (`BEGIN_RELOCATION`, moving `PLAN_SUBMITTED → RELOCATING`), recording
    `transition_window_start` and `transition_window_end`; the end must be
    strictly after the start (`ERR_INVALID_REQUEST`), and the new window must
    keep a buffer against every other `RELOCATING` incumbent in the same area
    — the windows are closed intervals, so the new window must start at least
    30 days after the existing window's end or end at least 30 days before
    the existing window's start, and any tighter fit fails with
    `ERR_TRANSITION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/incumbent_windows_buffer_gap_in_area
    """
    ctx = create_published_plan(("PEA001",), ("CATEGORY_A",))
    plan_id = ctx["plan"]["id"]
    area_id = ctx["areas"]["PEA001"]["id"]
    i1 = register_incumbent(plan_id, area_id, callsign="I1-AA", relocation_cost_cents=1_000_000)
    i2 = register_incumbent(plan_id, area_id, callsign="I2-BB", relocation_cost_cents=2_000_000)
    i3 = register_incumbent(plan_id, area_id, callsign="I3-CC", relocation_cost_cents=3_000_000)
    for inc in (i1, i2, i3):
        incumbent_submit_plan(inc["id"])

    i1_after = incumbent_begin_relocation(
        i1["id"], "2027-01-01T00:00:00Z", "2027-03-01T00:00:00Z"
    )
    assert i1_after["status"] == "RELOCATING"
    assert i1_after["transition_window_start"] == "2027-01-01T00:00:00Z"
    assert i1_after["transition_window_end"] == "2027-03-01T00:00:00Z"

    # Exactly 30 days after I1's window end meets the buffer (inclusive).
    assert iso_after_days("2027-03-01T00:00:00Z", 30) == "2027-03-31T00:00:00Z"
    i2_after = incumbent_begin_relocation(
        i2["id"], "2027-03-31T00:00:00Z", "2027-05-01T00:00:00Z"
    )
    assert i2_after["status"] == "RELOCATING"

    # A 29-day gap against I1 is tighter than the buffer (and the window also
    # overlaps I2's): rejected, and I3's record is untouched.
    resp = api.transition_incumbent(
        i3["id"],
        create_incumbent_transition_payload(
            "BEGIN_RELOCATION",
            transition_window_start="2027-03-30T00:00:00Z",
            transition_window_end="2027-04-20T00:00:00Z",
        ),
        auction_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_TRANSITION_WINDOW_CONFLICT)

    i3_after = get_incumbent(i3["id"])
    assert i3_after["status"] == "PLAN_SUBMITTED"
    assert i3_after["version"] == 2  # creation + SUBMIT_PLAN only
    assert i3_after["transition_window_start"] is None
    assert i3_after["transition_window_end"] is None
