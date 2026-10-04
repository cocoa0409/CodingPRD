"""Optimistic concurrency on Season.version and Allocation.version, plus the
clearance waterfall's pinned snapshot evaluation order (PRD 2.7, 3.4).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_season,
    create_allocation,
    create_allocation_payload,
    create_channel,
    create_sale,
    make_channel_rep_headers,
    refetch_allocation,
    refetch_season,
    respond_allocation_payload,
    respond_to_allocation,
    set_logical_clock,
    setup_offered_allocation,
    setup_season_in_allocation,
    unique_suffix,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]


def test_allocation_create_with_stale_season_version_returns_412(api):
    """PRD 2.7: "If `expected_season_version` does not equal the season's current
    `version`, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD 3.4: "and — critically for the OCC rule of §2.7 — increments the season's
    `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/allocation_create_with_stale_season_version_returns_412
    """
    bundle = setup_season_in_allocation(units_built=20)
    season_id, model_id = bundle["season"]["id"], bundle["model"]["id"]
    ch_a = create_channel(name="CH-A", channel_type="HOME_CENTER", allocation_priority=10, credit_limit_cents=100000000)
    ch_b = create_channel(name="CH-B", channel_type="SPECIALTY_DEALER", allocation_priority=20, credit_limit_cents=100000000)
    observed = refetch_season(season_id)["version"]
    first = create_allocation(season_id, ch_a["id"], model_id, 5)
    assert first["status"] == "OFFERED"
    # The first create bumped the season version; the writer holding the old view is stale.
    stale = api.create_allocation(
        create_allocation_payload(season_id, ch_b["id"], model_id, 5, observed), headers=PLANNER)
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    refreshed = refetch_season(season_id)["version"]
    assert refreshed == observed + 1, f"alloc-1's side effect must bump the season version: {observed} -> {refreshed}"
    retry = api.create_allocation(
        create_allocation_payload(season_id, ch_b["id"], model_id, 5, refreshed), headers=PLANNER)
    second = validate_success(retry, 201)
    assert second["status"] == "OFFERED", "a fresh version retries cleanly: OCC is a stale-view check, not a lockout"


def test_accept_after_revise_with_stale_allocation_version_returns_412(api):
    """PRD 2.7: "If `expected_allocation_version` does not equal the allocation's
    current `version`, the respond call is rejected with `ERR_STALE_VERSION`
    (HTTP 412)."
    PRD 3.4: "A **revise** is the `PlannerAdmin`'s re-offer: it supplies a new
    `allocated_units`, recaptures the current offer first, then re-runs the capacity
    and credit checks against the refreshed numbers, and rewrites the offer in place
    (`OFFERED → OFFERED`) — this version bump is exactly what makes a concurrently
    held acceptance go stale."

    Design: Corner/cross_cutting_complexity_layers/accept_after_revise_with_stale_allocation_version_returns_412
    """
    bundle = setup_offered_allocation(allocated_units=5, units_built=20)
    allocation, channel = bundle["allocation"], bundle["channel"]
    stale_version = allocation["version"]
    revised = validate_success(api.respond_allocation(
        allocation["id"],
        respond_allocation_payload("REVISE", stale_version, allocated_units=7),
        headers=PLANNER), 200)
    assert revised["version"] == stale_version + 1, "REVISE re-offers in place and bumps the version"
    assert revised["status"] == "OFFERED"
    rep = make_channel_rep_headers(channel["id"])
    stale_accept = api.respond_allocation(
        allocation["id"], respond_allocation_payload("ACCEPT", stale_version), headers=rep)
    validate_error(stale_accept, ApiErrorId.ERR_STALE_VERSION)
    accepted = validate_success(api.respond_allocation(
        allocation["id"], respond_allocation_payload("ACCEPT", revised["version"]), headers=rep), 200)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["allocated_units"] == 7, "the channel accepted the revised terms, not the stale ones"


def test_clearance_waterfall_snapshot_evaluation_order(api):
    """PRD 3.4: "Step one snapshots every allocation of the season in `ACCEPTED` or
    `PARTIALLY_CONSUMED` and computes each one's consumption rate as the floor of
    10000 times `committed_units` divided by `allocated_units`; these rates are frozen
    on this pre-release snapshot and never recomputed during the run."
    PRD 3.4: "Step two releases the laggards: any allocation whose rate falls strictly
    below 5000 basis points — under 50 percent consumed — gives up its unconsumed
    remainder"
    PRD 3.4: "Step three ranks the survivors — allocations still `ACCEPTED` or
    `PARTIALLY_CONSUMED` with a rate of at least 5000 basis points — by their
    channel's `allocation_priority`, highest first, breaking ties by the channel's
    `created_at` in ascending order, never by identifier."
    PRD 3.4: "Step four deals the pool out in that order: each candidate absorbs a
    share equal to the smaller of two figures — the floor of the original pool times
    4000 divided by 10000 (that is, 40 percent of the pool as it stood when
    redistribution began) and whatever units remain in the pool at that moment"

    Design: Difficulty/combinatorial_formula/clearance_waterfall_snapshot_evaluation_order
    """
    bundle = setup_season_in_allocation(units_built=100, season_over={"demand_forecast_units": 2000})
    season_id, model_id = bundle["season"]["id"], bundle["model"]["id"]
    ch_a = create_channel(name="CH-A", channel_type="HOME_CENTER", allocation_priority=10, credit_limit_cents=100000000)
    ch_b = create_channel(name="CH-B", channel_type="HOME_CENTER", allocation_priority=20, credit_limit_cents=100000000)
    ch_c = create_channel(name="CH-C", channel_type="HOME_CENTER", allocation_priority=30, credit_limit_cents=100000000)
    alloc_a = create_allocation(season_id, ch_a["id"], model_id, 40)
    alloc_b = create_allocation(season_id, ch_b["id"], model_id, 30)
    alloc_c = create_allocation(season_id, ch_c["id"], model_id, 25)
    for alloc in (alloc_a, alloc_b, alloc_c):
        respond_to_allocation(alloc, "ACCEPT")
    set_logical_clock("2026-04-01T00:00:00Z")
    advance_season(season_id, "IN_SEASON")
    create_sale(season_id, model_id, ch_a["id"], quantity=10, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    create_sale(season_id, model_id, ch_b["id"], quantity=20, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    create_sale(season_id, model_id, ch_c["id"], quantity=20, proof_of_purchase_token=f"RCPT-{unique_suffix()}")
    set_logical_clock("2026-09-01T00:00:00Z")
    cleared = validate_success(
        api.advance_season(season_id, {"target_status": "CLEARANCE"}, headers=PLANNER), 200)
    assert cleared["status"] == "CLEARANCE"
    # Pre-release snapshot rates: A 10/40 = 2500bp (released), B 20/30 = 6666bp, C 20/25 = 8000bp.
    after_a = refetch_allocation(alloc_a["id"])
    after_b = refetch_allocation(alloc_b["id"])
    after_c = refetch_allocation(alloc_c["id"])
    assert after_a["status"] == "RELEASED" and after_a["allocated_units"] == 10, (
        f"A is a laggard: allocated collapses to committed 10, got {after_a['status']}/{after_a['allocated_units']}"
    )
    # Pool 30; C (priority 30) absorbs min(floor(30*0.4)=12, 30) = 12 first, then B takes min(12, 18) = 12.
    assert after_c["allocated_units"] == 37, f"C 25 + 12 = 37, got {after_c['allocated_units']}"
    assert after_b["allocated_units"] == 42, f"B 30 + 12 = 42, got {after_b['allocated_units']}"
    lots, _meta = validate_paginated(api.list_season_lots(season_id, headers=PLANNER))
    assert lots[0]["units_available"] == 11, (
        f"unit conservation: 5 pre-waterfall + 30 released - 24 redistributed = 11, got {lots[0]['units_available']}"
    )


def test_allocations_list_filters_by_status(api):
    """PRD 4: "List allocations; filters `season_id`, `channel_account_id`, `model_id`,
    `status`; ChannelRep sees only own".
    PRD 2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/allocations_list_filters_by_status
    """
    bundle = setup_season_in_allocation(units_built=20)
    season_id, model_id = bundle["season"]["id"], bundle["model"]["id"]
    ch_a = create_channel(name="CH-A", channel_type="HOME_CENTER", allocation_priority=10, credit_limit_cents=100000000)
    ch_b = create_channel(name="CH-B", channel_type="SPECIALTY_DEALER", allocation_priority=20, credit_limit_cents=100000000)
    alloc_a = create_allocation(season_id, ch_a["id"], model_id, 5)
    alloc_b = create_allocation(season_id, ch_b["id"], model_id, 5)
    respond_to_allocation(alloc_b, "DECLINE")
    offered, meta_offered = validate_paginated(
        api.list_allocations(headers=PLANNER, params={"status": "OFFERED"}))
    assert meta_offered["total_count"] == 1
    assert offered[0]["id"] == alloc_a["id"], "the surviving OFFERED allocation is CH-A's"
    declined, meta_declined = validate_paginated(
        api.list_allocations(headers=PLANNER, params={"status": "DECLINED"}))
    assert meta_declined["total_count"] == 1
    assert declined[0]["id"] == alloc_b["id"], "the DECLINED allocation is CH-B's"
