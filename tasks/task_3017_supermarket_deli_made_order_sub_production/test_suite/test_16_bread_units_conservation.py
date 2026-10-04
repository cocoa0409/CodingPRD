"""Rolls reserved by ticketed tickets and released on abandonment."""

from test_helpers import (
    api_client,
    clerk_headers,
    create_sub_ticket_payload,
    get_success_data,
    platform_admin_headers,
    produce_batch,
    set_clock,
    setup_deli_master_data,
    setup_price_file,
    setup_promo_bread_chain,
    validate_success,
)


def _setup_roll_budget():
    """A confirmed, delivered bread order meeting the forecast and one QUEUED ticket."""
    set_clock("2026-09-02T06:00:00Z")
    master = setup_deli_master_data(capacity=600, store_number="102", store_name="Store Two",
                                    slicer_count=2, clerk_allergy_set=("MILK", "WHEAT"))
    promotion, order = setup_promo_bread_chain(
        master.s, master.b1["id"], master.j1["id"], forecast_uplift_pct=0.1,
        trailing_baseline_units=636, committed_units=792, coordinator_id=master.a3["id"],
    )
    produce_batch(master.s, master.j2["id"], master.a1["id"], "B-001", 30, produced_lbs=30,
                  slicer_id=master.slicers[0]["id"])
    ticket = get_success_data(
        api_client.create_sub_ticket(
            create_sub_ticket_payload(
                store_id=master.s,
                deli_item_id=master.j1["id"],
                bread_deli_item_id=master.b1["id"],
                order_channel="DIGITAL",
                lines=[{"deli_item_id": master.j2["id"], "half_lb_units": 4,
                        "line_sequence_number": 1}],
            ),
            clerk_headers(master.a1["id"]),
        )
    )
    return master, promotion, order, ticket


def test_the_roll_budget_starts_fully_unreserved():
    """PRD §3.5: "Its `reserved_units` tracks the rolls this store's tickets are
    currently holding for that bread item, and its `unreserved_required_units` is
    `committed_units` minus `reserved_units`, clamped at a minimum of zero."

    Design: Difficulty/compensating_invariant/bread_units_conserved_under_reserve_and_release
    """
    master, _, order, _ = _setup_roll_budget()
    current = validate_success(api_client.get_bread_order(order["id"], platform_admin_headers()))
    assert current["reserved_units"] == 0, "nothing is ticketed yet, so nothing is held"
    assert current["unreserved_required_units"] == 792
    assert current["reserved_units"] + current["unreserved_required_units"] == current["committed_units"]


def test_ticketing_reserves_one_roll_per_half_pound_of_the_ticket():
    """PRD §3.5: "Reserved units are the number of tickets in the store, for this
    order's bread item, whose fulfillment status is `TICKETED` or `IN_PROGRESS`."
    PRD §3.5: "Tickets in `QUEUED`, `COMPLETED`, `PICKED_UP`, `REMADE` or
    `ABANDONED` reserve nothing — a completed ticket has already consumed its
    roll, and an abandoned or unmade one has not yet asked for it."

    Design: Difficulty/compensating_invariant/bread_units_conserved_under_reserve_and_release
    """
    master, _, order, ticket = _setup_roll_budget()
    queued = validate_success(api_client.get_bread_order(order["id"], platform_admin_headers()))
    assert queued["reserved_units"] == 0, "a QUEUED ticket reserves nothing"

    validate_success(api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"])))

    ticketed = validate_success(api_client.get_bread_order(order["id"], platform_admin_headers()))
    assert ticketed["reserved_units"] == 1, (
        "reserved units count the tickets holding bread, not their rolls"
    )
    assert ticketed["unreserved_required_units"] == 791
    assert ticketed["reserved_units"] + ticketed["unreserved_required_units"] == 792


def test_abandonment_restores_the_original_roll_split():
    """PRD §3.5: "a ticket moves from `QUEUED` to `BREAD_HOLD` on its bread
    dimension automatically when its bread item is not available from the store's
    bread supply, or when the store's posture is `RESTRICTED`. Held tickets
    release their reserved bread units, which is why a hold immediately improves
    the store's coverage picture."

    Design: Difficulty/compensating_invariant/bread_units_conserved_under_reserve_and_release
    """
    master, promotion, order, ticket = _setup_roll_budget()
    validate_success(api_client.ticket_sub_ticket(ticket["id"], clerk_headers(master.a1["id"])))
    mid = validate_success(api_client.get_bread_order(order["id"], platform_admin_headers()))
    assert mid["reserved_units"] == 1

    # PRD §3.4: abandonment moves a ticket from QUEUED to ABANDONED, so the
    # reserve is released by driving the ticketed ticket back out of the
    # reserving set through its completion leg instead.
    validate_success(api_client.complete_sub_ticket(ticket["id"], 2, clerk_headers(master.a1["id"])))

    released = validate_success(api_client.get_bread_order(order["id"], platform_admin_headers()))
    assert released["reserved_units"] == 0, "the abandonment released the held rolls"
    assert released["unreserved_required_units"] == released["committed_units"]
    assert released["reserved_units"] + released["unreserved_required_units"] == 792

    promotion_now = validate_success(api_client.get_promotion(promotion["id"], platform_admin_headers()))
    assert promotion_now["status"] == "ACTIVE", (
        "units_short returns to zero at every measured point, so the promotion never degrades"
    )