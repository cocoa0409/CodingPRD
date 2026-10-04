"""Depth tests: non-linear state-machine shapes on different entities."""
from test_helpers import (
    AGENCY_OPERATOR,
    ATTRACTION_HOST,
    DEAL_DESK_CLERK,
    EVENTS_COORDINATOR,
    PLATFORM_ADMIN,
    STORE_MANAGER,
    create_member,
    create_open_attraction,
    create_store,
    get_success_data,
    request_session,
    set_clock,
    setup_delivered_deal,
)


# ===========================================================================
# boat_deal_cyclic_title_rejection_revert  (queue A / non_linear_state_machine)
# ===========================================================================

def _delivered_deal_ready_for_rejection(api):
    ctx = setup_delivered_deal(api)
    deal = get_success_data(api.get_deal(ctx["deal"]["id"], DEAL_DESK_CLERK), 200)
    return ctx, deal


def test_agency_rejection_drags_a_delivered_deal_back_to_contracted(api):
    """PRD §3.5: "When the rejected filing is the unit's"

    Design: Difficulty/non_linear_state_machine/boat_deal_cyclic_title_rejection_revert
    """
    ctx, deal = _delivered_deal_ready_for_rejection(api)
    assert deal["deal_stage"] == "DELIVERED"
    assert deal["settlement_variance_cents"] > 0, (
        "the delivered-settlement basis exceeds the quote variant, so the "
        f"variance is positive; got {deal['settlement_variance_cents']}"
    )

    filing = get_success_data(
        api.reject_title_filing(
            ctx["filing_id"],
            {"rejection_reason": "agency rejected the lien block"},
            AGENCY_OPERATOR,
        ),
        200,
    )
    assert filing["status"] == "REJECTED"

    reverted = get_success_data(api.get_deal(deal["id"], DEAL_DESK_CLERK), 200)
    assert reverted["deal_stage"] == "CONTRACTED", (
        "the cyclic revert hop lands on CONTRACTED, not a terminal state; got "
        f"{reverted['deal_stage']}"
    )
    assert reverted["deal_stage"] != "SETTLED", (
        "the deal is left with a further CONTRACTED -> DELIVERED hop available"
    )
    assert reverted["settlement_variance_cents"] == 0, (
        "the settlement variance is reset to zero on the revert hop; got "
        f"{reverted['settlement_variance_cents']}"
    )


def test_rejection_resets_the_title_dimension_and_reopens_the_hull_and_rigging(api):
    """PRD §3.5: "The deal's `title_status` moves from `ISSUED` to `REJECTED`
    and then immediately back to `NOT_STARTED`, so a fresh filing is permitted
    and the deal is not stranded in a terminal-looking title state."
    PRD §3.5: "The hull's `status` moves from `SOLD` back to `DEAL_PENDING`,
    which re-opens the unit's rigging work."
    PRD §3.5: "Because that order has left `DELIVERED`, the deal's rigging
    dimension drops with it, from `COMPLETE` back to `SCHEDULED`."

    Design: Difficulty/non_linear_state_machine/boat_deal_cyclic_title_rejection_revert
    """
    ctx, deal = _delivered_deal_ready_for_rejection(api)
    get_success_data(
        api.reject_title_filing(
            ctx["filing_id"],
            {"rejection_reason": "agency rejected the lien block"},
            AGENCY_OPERATOR,
        ),
        200,
    )

    reverted = get_success_data(api.get_deal(deal["id"], DEAL_DESK_CLERK), 200)
    assert reverted["title_status"] == "NOT_STARTED", (
        f"Expected NOT_STARTED, got {reverted['title_status']}"
    )
    assert reverted["rigging_status"] == "SCHEDULED", (
        "the deal's rigging dimension drops from COMPLETE to SCHEDULED; got "
        f"{reverted['rigging_status']}"
    )

    unit = get_success_data(api.get_boat_unit(ctx["unit"]["id"], DEAL_DESK_CLERK), 200)
    assert unit["status"] == "DEAL_PENDING", (
        f"the hull returns to DEAL_PENDING, got {unit['status']}"
    )


# ===========================================================================
# attraction_session_fork_join_posture_gate  (queue A / non_linear_state_machine)
# ===========================================================================

def _fork_join_world(api):
    """Aquarium of capacity 25, a published free demo, and one 24-guest party."""
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=25, dwell_cost_minutes=30)
    member_one = create_member(api, store["id"], email="m_w1@x.com",
                               full_name="Wren One")
    member_two = create_member(api, store["id"], email="m_w2@x.com",
                               full_name="Wren Two")

    offering = get_success_data(
        api.create_event_offering(
            store["id"],
            {
                "offering_kind": "FREE_DEMO",
                "title": "Reel Care Basics",
                "starts_at_utc": "2026-10-01T10:00:00Z",
                "ends_at_utc": "2026-10-01T11:00:00Z",
                "registration_cap": 0,
                "attraction_id": attraction["id"],
            },
            EVENTS_COORDINATOR,
        ),
        201,
    )
    get_success_data(api.publish_event_offering(offering["id"], EVENTS_COORDINATOR), 200)

    session_one = get_success_data(
        request_session(api, store["id"], attraction["id"], member_one["id"],
                        party_size=25, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )
    return store, attraction, member_one, member_two, session_one


def test_a_party_that_overshoots_venue_capacity_parks_in_the_waitlist(api):
    """PRD §3.1: "When the venue's `in_use_units` plus the party size would
    exceed its `capacity_units` but the store's posture is still `OPEN` rather
    than `FROZEN`, the session enters `WAITLIST_FALLBACK`, consumes no capacity
    and no dwell minutes at that instant, and waits."

    Design: Difficulty/non_linear_state_machine/attraction_session_fork_join_posture_gate
    """
    store, attraction, member_one, member_two, session_one = _fork_join_world(api)
    assert session_one["status"] == "CONFIRMED", (
        f"a 25-guest party fits inside capacity 25, got {session_one['status']}"
    )

    response = request_session(api, store["id"], attraction["id"], member_two["id"],
                               party_size=2,
                               slot_start_utc="2026-11-01T12:00:00Z",
                               slot_end_utc="2026-11-01T13:00:00Z")
    session_two = get_success_data(response, 201)
    assert session_two["status"] == "WAITLIST_FALLBACK", (
        "25 + 2 exceeds capacity_units 25, so the request forks to the waitlist "
        f"branch; got {session_two['status']}"
    )
    assert session_two["dwell_charge_minutes"] == 30, (
        "a parked session pins the charge it would have had at its original "
        f"request instant; got {session_two['dwell_charge_minutes']}"
    )

    summary = get_success_data(
        api.get_dwell_summary(store["id"], STORE_MANAGER), 200
    )
    assert summary["dwell_committed_minutes"] == 15 + session_one["dwell_charge_minutes"], (
        "15 from the published free demo plus the confirmed party's own charge; "
        f"got {summary['dwell_committed_minutes']}"
    )
    assert summary["dwell_capacity_minutes"] - summary["dwell_committed_minutes"] >= 30, (
        "the confirmed party leaves the store comfortably away from the "
        f"thirty-minute band; got {summary['dwell_free_minutes']} free"
    )
    assert summary["attraction_posture"] == "OPEN", (
        f"the store still has free capacity, got {summary['attraction_posture']}"
    )


def test_cancelling_the_blocker_then_running_the_checkpoint_confirms_the_parked_party(api):
    """PRD §3.1: "A promoted session adds its `party_size` to the venue's
    `in_use_units`, and its `dwell_charge_minutes` is pinned to the value it
    would have had at the original request instant rather than recomputed at
    promotion."

    Design: Difficulty/non_linear_state_machine/attraction_session_fork_join_posture_gate
    """
    store, attraction, member_one, member_two, session_one = _fork_join_world(api)

    parked = get_success_data(
        request_session(api, store["id"], attraction["id"], member_two["id"],
                        party_size=2,
                        slot_start_utc="2026-11-01T12:00:00Z",
                        slot_end_utc="2026-11-01T13:00:00Z"),
        201,
    )
    assert parked["status"] == "WAITLIST_FALLBACK"

    get_success_data(api.cancel_session(session_one["id"], ATTRACTION_HOST), 200)
    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)

    promoted = get_success_data(api.get_session(parked["id"], ATTRACTION_HOST), 200)
    assert promoted["status"] == "CONFIRMED", (
        f"the fork branches rejoin at CONFIRMED; got {promoted['status']}"
    )
    assert promoted["dwell_charge_minutes"] == parked["dwell_charge_minutes"], (
        "the charge stays pinned to the request-instant value rather than being "
        f"recomputed at promotion; got {promoted['dwell_charge_minutes']} "
        f"against {parked['dwell_charge_minutes']}"
    )

    venue = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert venue["in_use_units"] == 2, (
        f"only the promoted party holds capacity now, got {venue['in_use_units']}"
    )
    summary = get_success_data(api.get_dwell_summary(store["id"], STORE_MANAGER), 200)
    assert summary["dwell_committed_minutes"] == 15 + promoted["dwell_charge_minutes"], (
        "15 from the published free demo plus the promoted party's pinned charge; "
        f"got {summary['dwell_committed_minutes']}"
    )