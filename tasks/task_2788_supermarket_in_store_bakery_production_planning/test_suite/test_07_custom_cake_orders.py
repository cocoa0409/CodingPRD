"""Custom cake work: pickup windows, the five-step quote and the revision loop."""

from test_helpers import (
    CAKE_DESK,
    DECORATOR,
    api_client,
    assert_cake_order,
    assert_cents,
    assert_instant,
    assert_minutes,
    assert_null,
    assert_pickup_slot,
    assert_quote_total_consistent,
    cake_revision_payload,
    confirm_cake_order,
    create_cake_order_payload,
    create_pickup_slot_payload,
    mark_cake_ready,
    open_pickup_slot,
    pick_up_cake,
    read_cake_order,
    read_pickup_slot,
    set_clock,
    setup_cake_order_in_decoration,
    setup_planned_day,
    start_cake_decoration,
    take_cake_order,
    validate_error,
    validate_paginated,
    validate_success,
)

SLOT_START = "2026-08-12T14:00:00Z"
SLOT_END = "2026-08-12T16:00:00Z"


def test_a_rush_premium_cake_takes_its_discount_off_the_fee_inflated_total():
    """The volume bracket is read after the rush fee is added, not before.

    PRD §3.7: "`volume_discount_cents` is selected from a bracket read off the
    subtotal **plus the rush fee**, never off the subtotal alone."  Four premium
    tiers quote 19800 cents, the eight-percent rush fee adds 1584, and only the
    inflated 21384 reaches the twenty-thousand floor that earns ten percent.

    Design: Difficulty/combinatorial_formula/cake_quote_applies_rush_fee_before_volume_discount
    """
    setup = setup_planned_day()
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=28,
    )
    order = take_cake_order(
        setup["bake_day"],
        slot,
        setup["cake_base"]["id"],
        decoration_complexity="PREMIUM",
        tier_count=4,
        rush_requested=True,
    )

    assert_cake_order(order)
    assert order["order_status"] == "INTAKE"
    assert order["revision_count"] == 0
    assert order["decoration_units"] == 28, "Seven units a tier over four tiers"
    assert_cents(order["quote_subtotal_cents"], 19800, "quote_subtotal_cents")
    assert_cents(order["rush_fee_cents"], 1584, "eight percent of 19800")
    assert_cents(order["volume_discount_cents"], 2138, "ten percent of 21384")
    assert_cents(order["quote_total_cents"], 19246, "quote_total_cents")
    assert_quote_total_consistent(order)
    assert order["quote_total_cents"] != 20394, (
        "Reading the discount bracket off the 19800 subtotal alone would have "
        "found only the five-percent tier and quoted 20394"
    )

    assert_minutes(
        order["required_decoration_lead_minutes"], 360, "240 base plus 30 a tier"
    )
    assert_instant(
        order["decoration_deadline_utc"], "2026-08-12T08:00:00Z", "deadline"
    )

    window = read_pickup_slot(slot["id"])
    assert window["reserved_decoration_units"] == 0, (
        "An order still in INTAKE holds no capacity"
    )


def test_the_rush_fee_alone_can_lift_a_cake_into_the_discount_brackets():
    """A subtotal below the discount floor still earns one once the fee lands.

    PRD §3.7: "when it is at least 10000 but below 20000 cents the discount is five
    percent of it, rounded half up; below 10000 cents there is no discount."  Two
    premium tiers quote 9900 cents, which alone earns nothing, but the
    twelve-percent rush fee of 1188 carries the running total to 11088 and buys a
    554-cent discount.

    Design: Difficulty/combinatorial_formula/cake_quote_applies_rush_fee_before_volume_discount
    """
    setup = setup_planned_day()
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=20,
    )
    order = take_cake_order(
        setup["bake_day"],
        slot,
        setup["cake_base"]["id"],
        decoration_complexity="PREMIUM",
        tier_count=2,
        rush_requested=True,
    )

    assert order["decoration_units"] == 14
    assert_cents(order["quote_subtotal_cents"], 9900, "quote_subtotal_cents")
    assert_cents(
        order["rush_fee_cents"], 1188, "twelve percent of the 9900 subtotal alone"
    )
    assert_cents(order["volume_discount_cents"], 554, "five percent of 11088")
    assert_cents(order["quote_total_cents"], 10534, "quote_total_cents")
    assert_quote_total_consistent(order)

    assert_minutes(
        order["required_decoration_lead_minutes"], 300, "240 base plus 30 a tier"
    )
    assert_instant(
        order["decoration_deadline_utc"], "2026-08-12T09:00:00Z", "deadline"
    )

    confirmed = confirm_cake_order(order["id"])
    assert confirmed["order_status"] == "CONFIRMED"
    assert_cents(
        confirmed["quote_total_cents"], 10534, "confirmation does not requote"
    )
    window = read_pickup_slot(slot["id"])
    assert window["reserved_decoration_units"] == 14


def _cake_in_decoration(**kwargs):
    """A standard two-tier cake already pulled into decoration on a 30-unit window."""
    return setup_cake_order_in_decoration(
        decoration_complexity="STANDARD",
        tier_count=2,
        decorator_capacity_units=30,
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        **kwargs,
    )


def test_a_revision_sends_the_cake_back_to_confirmed_for_a_fresh_start():
    """The lifecycle is genuinely cyclic and the decorator's progress is discarded.

    PRD §3.7: "This moves the order `IN_DECORATION → CONFIRMED`, which makes the
    cake lifecycle genuinely cyclic: a cake can sit in `CONFIRMED` three times in
    all — the initial confirmation plus two revisions."  The revision also resets
    `decoration_started_utc` to null "because the decorator has to start again".

    Design: Difficulty/non_linear_state_machine/cake_order_revision_loops_in_decoration_back_to_confirmed
    """
    setup = _cake_in_decoration()
    order = setup["cake_order"]
    assert order["order_status"] == "IN_DECORATION"
    assert order["revision_count"] == 0
    assert_instant(
        order["decoration_started_utc"], "2026-08-10T04:00:00Z", "first start stamp"
    )

    revised = validate_success(
        api_client.request_cake_revision(
            order["id"], cake_revision_payload("PREMIUM", tier_count=3), CAKE_DESK
        ),
        200,
    )
    assert revised["order_status"] == "CONFIRMED"
    assert revised["revision_count"] == 1
    assert_null(revised["decoration_started_utc"], "decoration_started_utc")
    assert revised["version"] == order["version"] + 1

    set_clock("2026-08-10T06:00:00Z")
    restarted = start_cake_decoration(revised["id"])
    assert restarted["order_status"] == "IN_DECORATION"
    assert restarted["revision_count"] == 1, "Re-entering decoration is not a loop"
    assert_instant(
        restarted["decoration_started_utc"],
        "2026-08-10T06:00:00Z",
        "second start stamp",
    )

    stored = read_cake_order(order["id"])
    assert stored["decoration_complexity"] == "PREMIUM"
    assert stored["tier_count"] == 3


def test_a_revision_requotes_the_cake_and_re_reserves_the_window():
    """Every derived figure is recomputed and the window absorbs the difference.

    PRD §3.7: "The window's `reserved_decoration_units` is adjusted by the
    difference between the new and the old `decoration_units`, incrementing the
    window's `version` by 1".  Standard over two tiers held 8 units and quoted 7200
    cents; premium over three holds 21 and quotes 14850 less a 743-cent discount.

    Design: Difficulty/non_linear_state_machine/cake_order_revision_loops_in_decoration_back_to_confirmed
    """
    setup = _cake_in_decoration()
    order = setup["cake_order"]
    assert order["decoration_units"] == 8
    assert_cents(order["quote_subtotal_cents"], 7200, "quote_subtotal_cents")
    assert_cents(order["volume_discount_cents"], 0, "7200 earns no discount")
    assert_cents(order["quote_total_cents"], 7200, "quote_total_cents")
    assert_minutes(order["required_decoration_lead_minutes"], 180, "standard lead")
    assert_instant(
        order["decoration_deadline_utc"], "2026-08-12T11:00:00Z", "deadline"
    )

    window_before = read_pickup_slot(setup["pickup_slot"]["id"])
    assert window_before["reserved_decoration_units"] == 8

    revised = validate_success(
        api_client.request_cake_revision(
            order["id"], cake_revision_payload("PREMIUM", tier_count=3), CAKE_DESK
        ),
        200,
    )
    assert revised["decoration_units"] == 21
    assert_cents(revised["quote_subtotal_cents"], 14850, "quote_subtotal_cents")
    assert_cents(revised["rush_fee_cents"], 0, "no rush was ever requested")
    assert_cents(revised["volume_discount_cents"], 743, "five percent of 14850")
    assert_cents(revised["quote_total_cents"], 14107, "quote_total_cents")
    assert_quote_total_consistent(revised)
    assert_minutes(revised["required_decoration_lead_minutes"], 330, "premium lead")
    assert_instant(
        revised["decoration_deadline_utc"],
        "2026-08-12T08:30:00Z",
        "recomputed deadline",
    )

    window = read_pickup_slot(setup["pickup_slot"]["id"])
    assert_pickup_slot(window)
    assert window["reserved_decoration_units"] == 21, (
        "The window gives up the old 8 units and takes the new 21"
    )
    assert window["decorator_capacity_units"] == 30
    assert window["version"] == window_before["version"] + 1


def test_a_cake_cannot_be_confirmed_into_a_window_that_has_been_closed():
    """The window's own state gates the order's transition.

    PRD §3.7: "Once closed, the window rejects four operations with
    `ERR_PICKUP_SLOT_CLOSED`: taking a new order against it, confirming an order
    into it, starting decoration on one of its orders, and requesting a revision on
    one of its orders."  The order is left in `INTAKE` holding no capacity.

    Design: Difficulty/cross_entity_state_dependency/cake_order_cannot_confirm_against_a_closed_pickup_slot
    """
    setup = setup_planned_day()
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=10,
    )
    order = take_cake_order(setup["bake_day"], slot, setup["cake_base"]["id"])
    assert order["order_status"] == "INTAKE"
    assert order["decoration_units"] == 8

    closed = validate_success(
        api_client.close_pickup_slot(slot["id"], CAKE_DESK), 200
    )
    assert closed["slot_status"] == "CLOSED"
    assert closed["version"] == slot["version"] + 1
    assert closed["reserved_decoration_units"] == 0

    refused = api_client.confirm_cake_order(order["id"], CAKE_DESK)
    validate_error(refused, "ERR_PICKUP_SLOT_CLOSED", 409)

    stalled = read_cake_order(order["id"])
    assert stalled["order_status"] == "INTAKE"
    assert stalled["version"] == order["version"]
    assert read_pickup_slot(slot["id"])["reserved_decoration_units"] == 0


def test_a_closed_window_still_lets_the_cake_already_in_it_be_finished():
    """Closing bars intake, confirmation, decoration starts and revisions only.

    PRD §3.7: "`reserved_decoration_units` is retained on closing so that cakes
    already confirmed into it stay accounted for."  Only intake, confirmation,
    starting decoration and requesting a revision answer `ERR_PICKUP_SLOT_CLOSED`;
    marking the cake `READY` and handing it over are not among those four, and the
    handover still releases the reservation.

    Design: Difficulty/cross_entity_state_dependency/cake_order_cannot_confirm_against_a_closed_pickup_slot
    """
    setup = _cake_in_decoration()
    order = setup["cake_order"]
    slot_id = setup["pickup_slot"]["id"]

    closed = validate_success(api_client.close_pickup_slot(slot_id, CAKE_DESK), 200)
    assert closed["slot_status"] == "CLOSED"
    assert closed["reserved_decoration_units"] == 8, (
        "The cake in the decorator's hands keeps holding its capacity"
    )

    newcomer = api_client.create_cake_order(
        create_cake_order_payload(
            setup["bake_day"]["id"], slot_id, setup["cake_base"]["id"]
        ),
        CAKE_DESK,
    )
    validate_error(newcomer, "ERR_PICKUP_SLOT_CLOSED", 409)

    revision = api_client.request_cake_revision(
        order["id"], cake_revision_payload("SIMPLE"), CAKE_DESK
    )
    validate_error(revision, "ERR_PICKUP_SLOT_CLOSED", 409)
    assert read_cake_order(order["id"])["revision_count"] == 0

    ready = mark_cake_ready(order["id"])
    assert ready["order_status"] == "READY"
    assert read_pickup_slot(slot_id)["reserved_decoration_units"] == 8

    collected = pick_up_cake(order["id"])
    assert collected["order_status"] == "PICKED_UP"
    released = read_pickup_slot(slot_id)
    assert released["reserved_decoration_units"] == 0
    assert released["slot_status"] == "CLOSED"


def _open_window(bake_day, start, end, capacity=10):
    """POST one pickup window and hand back the raw response."""
    return api_client.create_pickup_slot(
        create_pickup_slot_payload(
            bake_day["id"],
            slot_start_utc=start,
            slot_end_utc=end,
            decorator_capacity_units=capacity,
        ),
        CAKE_DESK,
    )


def test_pickup_windows_may_begin_at_the_exact_instant_another_one_ends():
    """Adjacency is pure and carries no buffer at all.

    PRD §3.7: "There is no buffer here, so a new window that begins at the exact
    instant another one ends is pure adjacency and is allowed — a deliberate
    contrast with oven decks, where the changeover buffer makes that same adjacency
    illegal."  A 14:00–16:00Z window accepts neighbours on both of its edges.

    Design: Difficulty/resource_temporal_overlap/pickup_slots_may_abut_but_not_overlap
    """
    setup = setup_planned_day()
    day = setup["bake_day"]

    middle = validate_success(_open_window(day, SLOT_START, SLOT_END), 201)
    assert_pickup_slot(middle)
    assert middle["slot_status"] == "OPEN"
    assert middle["reserved_decoration_units"] == 0

    after = validate_success(
        _open_window(day, "2026-08-12T16:00:00Z", "2026-08-12T18:00:00Z"), 201
    )
    assert_instant(after["slot_start_utc"], "2026-08-12T16:00:00Z", "slot_start_utc")

    before = validate_success(
        _open_window(day, "2026-08-12T12:00:00Z", SLOT_START), 201
    )
    assert_instant(before["slot_end_utc"], SLOT_START, "slot_end_utc")

    rows, meta = validate_paginated(
        api_client.list_pickup_slots(CAKE_DESK, {"bake_day_id": day["id"]})
    )
    assert meta["total_count"] == 3, "All three abutting windows exist"
    assert {row["id"] for row in rows} == {middle["id"], after["id"], before["id"]}


def test_a_pickup_window_overlapping_an_existing_one_is_rejected():
    """The overlap test is symmetrical and ignores the incumbent's status.

    PRD §3.7: "a proposed window collides with an existing one, whatever that one's
    `slot_status`, when the proposed start falls strictly before the existing end
    **and** the existing start falls strictly before the proposed end."  A partial
    overlap on either edge, a straddle and even a collision with a closed window all
    report `ERR_PICKUP_SLOT_OVERLAP`.

    Design: Difficulty/resource_temporal_overlap/pickup_slots_may_abut_but_not_overlap
    """
    setup = setup_planned_day()
    day = setup["bake_day"]
    existing = validate_success(_open_window(day, SLOT_START, SLOT_END), 201)

    late_overlap = _open_window(day, "2026-08-12T15:00:00Z", "2026-08-12T17:00:00Z")
    validate_error(late_overlap, "ERR_PICKUP_SLOT_OVERLAP", 409)

    early_overlap = _open_window(day, "2026-08-12T13:00:00Z", "2026-08-12T15:00:00Z")
    validate_error(early_overlap, "ERR_PICKUP_SLOT_OVERLAP", 409)

    straddle = _open_window(day, "2026-08-12T13:00:00Z", "2026-08-12T19:00:00Z")
    validate_error(straddle, "ERR_PICKUP_SLOT_OVERLAP", 409)

    validate_success(api_client.close_pickup_slot(existing["id"], CAKE_DESK), 200)
    against_closed = _open_window(day, "2026-08-12T15:00:00Z", "2026-08-12T17:00:00Z")
    validate_error(against_closed, "ERR_PICKUP_SLOT_OVERLAP", 409)

    _, meta = validate_paginated(
        api_client.list_pickup_slots(CAKE_DESK, {"bake_day_id": day["id"]})
    )
    assert meta["total_count"] == 1, "No rejected window was ever created"


def test_the_decoration_deadline_is_inclusive_to_the_minute():
    """A confirmation exactly on the deadline passes; one minute later does not.

    PRD §3.7: "The logical clock must be at or before `decoration_deadline_utc` —
    exactly at the deadline passes, and any later instant is rejected with
    `ERR_DECORATION_LEAD_TIME_MISSED`."  A standard two-tier cake leads by 180
    minutes, so a 14:00Z window closes its promise at 11:00Z.

    Design: Corner/calculations/decoration_deadline_is_the_slot_start_minus_the_computed_lead_and_is_inclusive
    """
    setup = setup_planned_day(clock="2026-08-12T04:00:00Z")
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=30,
    )
    first = take_cake_order(
        setup["bake_day"], slot, setup["cake_base"]["id"], customer_name="Ida Bloom"
    )
    second = take_cake_order(
        setup["bake_day"], slot, setup["cake_base"]["id"], customer_name="Ravi Patel"
    )
    assert_minutes(
        first["required_decoration_lead_minutes"], 180, "120 base plus 30 a tier"
    )
    assert_instant(
        first["decoration_deadline_utc"], "2026-08-12T11:00:00Z", "deadline"
    )

    set_clock("2026-08-12T11:00:00Z")
    on_the_deadline = validate_success(
        api_client.confirm_cake_order(first["id"], CAKE_DESK), 200
    )
    assert on_the_deadline["order_status"] == "CONFIRMED"

    set_clock("2026-08-12T11:01:00Z")
    one_minute_late = api_client.confirm_cake_order(second["id"], CAKE_DESK)
    validate_error(one_minute_late, "ERR_DECORATION_LEAD_TIME_MISSED", 422)
    assert read_cake_order(second["id"])["order_status"] == "INTAKE"

    window = read_pickup_slot(slot["id"])
    assert window["reserved_decoration_units"] == 8, (
        "Only the accepted order reserved capacity"
    )


def test_window_capacity_is_collective_and_exact_equality_still_fits():
    """Three small cakes compete for one aggregate capacity figure.

    PRD §3.7: "The window's current `reserved_decoration_units` plus this order's
    `decoration_units` must be no greater than its `decorator_capacity_units`; exact
    equality passes, and anything above is rejected with
    `ERR_PICKUP_SLOT_CAPACITY_EXCEEDED`."  Eight units plus four busts a ten-unit
    window while eight plus two fills it exactly.

    Design: Corner/calculations/slot_capacity_aggregates_confirmed_orders_and_allows_exact_equality
    """
    setup = setup_planned_day()
    cake_base_id = setup["cake_base"]["id"]
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=10,
    )
    big = take_cake_order(
        setup["bake_day"], slot, cake_base_id, decoration_complexity="STANDARD"
    )
    middling = take_cake_order(
        setup["bake_day"],
        slot,
        cake_base_id,
        decoration_complexity="SIMPLE",
        tier_count=2,
        customer_name="Ravi Patel",
    )
    small = take_cake_order(
        setup["bake_day"],
        slot,
        cake_base_id,
        decoration_complexity="SIMPLE",
        tier_count=1,
        customer_name="Lena Ortiz",
    )
    assert (big["decoration_units"], middling["decoration_units"]) == (8, 4)
    assert small["decoration_units"] == 2
    assert read_pickup_slot(slot["id"])["reserved_decoration_units"] == 0, (
        "Orders still in INTAKE hold no capacity at all"
    )

    confirm_cake_order(big["id"])
    assert read_pickup_slot(slot["id"])["reserved_decoration_units"] == 8

    too_big = api_client.confirm_cake_order(middling["id"], CAKE_DESK)
    validate_error(too_big, "ERR_PICKUP_SLOT_CAPACITY_EXCEEDED", 422)
    assert read_cake_order(middling["id"])["order_status"] == "INTAKE"

    exact_fit = validate_success(
        api_client.confirm_cake_order(small["id"], CAKE_DESK), 200
    )
    assert exact_fit["order_status"] == "CONFIRMED"

    window = read_pickup_slot(slot["id"])
    assert window["reserved_decoration_units"] == 10, (
        "Only the two CONFIRMED orders are summed"
    )


def test_a_third_revision_on_the_same_cake_is_refused():
    """Two loops are allowed and the third request is turned away.

    PRD §3.7: "`revision_count` counts the completed loops and may never exceed 2,
    so a request made when it already reads 2 is rejected with
    `ERR_REVISION_LIMIT_REACHED`."  The cake stays where the decorator had it.

    Design: Corner/state_machines/a_third_revision_request_on_the_same_cake_order_is_rejected
    """
    setup = _cake_in_decoration()
    order_id = setup["cake_order"]["id"]

    first = validate_success(
        api_client.request_cake_revision(
            order_id, cake_revision_payload("SIMPLE"), CAKE_DESK
        ),
        200,
    )
    assert first["revision_count"] == 1
    assert first["decoration_units"] == 4
    start_cake_decoration(order_id)

    second = validate_success(
        api_client.request_cake_revision(
            order_id, cake_revision_payload("STANDARD"), CAKE_DESK
        ),
        200,
    )
    assert second["revision_count"] == 2
    assert second["decoration_units"] == 8
    in_decoration_again = start_cake_decoration(order_id)
    assert in_decoration_again["order_status"] == "IN_DECORATION"

    third = api_client.request_cake_revision(
        order_id, cake_revision_payload("PREMIUM"), CAKE_DESK
    )
    validate_error(third, "ERR_REVISION_LIMIT_REACHED", 422)

    stored = read_cake_order(order_id)
    assert stored["order_status"] == "IN_DECORATION"
    assert stored["revision_count"] == 2
    assert stored["decoration_complexity"] == "STANDARD"
    assert stored["decoration_units"] == 8
    assert read_pickup_slot(setup["pickup_slot"]["id"])[
        "reserved_decoration_units"
    ] == 8


def test_handing_the_cake_over_releases_the_capacity_it_held():
    """The reservation survives READY and is only released at pickup.

    PRD §3.7: "Finally a `CakeDesk` operator releases it `READY → PICKED_UP`,
    stamping `picked_up_at_utc` and subtracting the order's `decoration_units` from
    the window's `reserved_decoration_units`, which increments the window's
    `version` by 1."  While the cake sits in the window ready for collection the
    eight units are still held.

    Design: Corner/state_machines/cake_pickup_releases_the_reservation_held_on_its_slot
    """
    setup = setup_cake_order_in_decoration(
        decorator_capacity_units=10,
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
    )
    order_id = setup["cake_order"]["id"]
    slot_id = setup["pickup_slot"]["id"]

    ready = mark_cake_ready(order_id)
    assert ready["order_status"] == "READY"
    held = read_pickup_slot(slot_id)
    assert held["reserved_decoration_units"] == 8, (
        "The cake is physically sitting in the window, so the units are still held"
    )

    set_clock("2026-08-12T14:30:00Z")
    collected = pick_up_cake(order_id)
    assert collected["order_status"] == "PICKED_UP"
    assert_instant(
        collected["picked_up_at_utc"], "2026-08-12T14:30:00Z", "picked_up_at_utc"
    )
    assert collected["version"] == ready["version"] + 1

    released = read_pickup_slot(slot_id)
    assert released["reserved_decoration_units"] == 0
    assert released["decorator_capacity_units"] == 10
    assert released["slot_status"] == "OPEN"
    assert released["version"] == held["version"] + 1


def test_marking_a_cake_ready_before_decoration_has_started_is_refused():
    """READY is only reachable from IN_DECORATION.

    PRD §3.7: "Any cake-order transition asked for from a state that does not
    declare it — revising an order that is not in `IN_DECORATION`, confirming one
    that has already `EXPIRED`, marking a `CONFIRMED` order ready — is rejected with
    `ERR_INVALID_CAKE_ORDER_STATE`."  Neither `INTAKE` nor `CONFIRMED` declares it.

    Design: Corner/errors/cake_order_ready_call_from_intake_or_confirmed_is_rejected
    """
    setup = setup_planned_day()
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=10,
    )
    order = take_cake_order(setup["bake_day"], slot, setup["cake_base"]["id"])

    from_intake = api_client.cake_order_ready(order["id"], DECORATOR)
    validate_error(from_intake, "ERR_INVALID_CAKE_ORDER_STATE", 409)
    assert read_cake_order(order["id"])["order_status"] == "INTAKE"

    confirmed = confirm_cake_order(order["id"])
    assert confirmed["order_status"] == "CONFIRMED"
    from_confirmed = api_client.cake_order_ready(order["id"], DECORATOR)
    validate_error(from_confirmed, "ERR_INVALID_CAKE_ORDER_STATE", 409)

    unmoved = read_cake_order(order["id"])
    assert unmoved["order_status"] == "CONFIRMED"
    assert unmoved["version"] == confirmed["version"]
    assert_null(unmoved["ready_at_utc"], "ready_at_utc")

    started = start_cake_decoration(order["id"])
    assert started["order_status"] == "IN_DECORATION"
    assert started["decoration_started_utc"] is not None
    now_ready = validate_success(
        api_client.cake_order_ready(order["id"], DECORATOR), 200
    )
    assert now_ready["order_status"] == "READY"
    assert now_ready["ready_at_utc"] is not None


def test_a_cake_order_may_only_name_a_product_flagged_as_a_cake_base():
    """An ordinary shelf product cannot be decorated as a custom cake.

    PRD §3.7: "The base product must carry `is_custom_cake_base` as true, or the
    order is rejected with `ERR_NOT_CUSTOM_CAKE_BASE`."  The croissant on the same
    department is a perfectly valid product and still cannot be a cake base, while
    the flagged 8-inch round is accepted against the very same window.

    Design: Corner/validations/cake_order_naming_a_product_that_is_not_a_cake_base_is_rejected
    """
    setup = setup_planned_day()
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=10,
    )

    not_a_base = api_client.create_cake_order(
        create_cake_order_payload(
            setup["bake_day"]["id"], slot["id"], setup["croissant"]["id"]
        ),
        CAKE_DESK,
    )
    validate_error(not_a_base, "ERR_NOT_CUSTOM_CAKE_BASE", 422)

    rows, meta = validate_paginated(
        api_client.list_cake_orders(CAKE_DESK, {"pickup_slot_id": slot["id"]})
    )
    assert meta["total_count"] == 0, "The rejected order was never created"
    assert rows == []

    accepted = validate_success(
        api_client.create_cake_order(
            create_cake_order_payload(
                setup["bake_day"]["id"], slot["id"], setup["cake_base"]["id"]
            ),
            CAKE_DESK,
        ),
        201,
    )
    assert_cake_order(accepted)
    assert accepted["product_id"] == setup["cake_base"]["id"]
    assert accepted["order_status"] == "INTAKE"


def test_each_cake_lane_role_drives_only_its_own_transitions():
    """Intake and handover belong to the desk, the piping to the decorator.

    PRD §3.7: confirmation "is a `CakeDesk` action", a `Decorator` "pulls the order
    off the queue, moving it `CONFIRMED → IN_DECORATION`", the same `Decorator`
    moves it "`IN_DECORATION → READY`", and "Finally a `CakeDesk` operator releases
    it `READY → PICKED_UP`".  Each stamped identifier is the operator who acted.

    Design: Corner/rbac/each_lane_role_can_drive_its_own_exclusive_cake_operations
    """
    setup = setup_planned_day(clock="2026-08-11T08:00:00Z")
    slot = open_pickup_slot(
        setup["bake_day"],
        slot_start_utc=SLOT_START,
        slot_end_utc=SLOT_END,
        decorator_capacity_units=10,
        headers=CAKE_DESK,
    )
    assert_pickup_slot(slot)

    order = take_cake_order(
        setup["bake_day"], slot, setup["cake_base"]["id"], headers=CAKE_DESK
    )
    assert order["order_status"] == "INTAKE"

    confirmed = confirm_cake_order(order["id"], headers=CAKE_DESK)
    assert confirmed["order_status"] == "CONFIRMED"
    assert confirmed["version"] == order["version"] + 1

    started = start_cake_decoration(order["id"], headers=DECORATOR)
    assert started["order_status"] == "IN_DECORATION"
    assert started["version"] == confirmed["version"] + 1
    assert_instant(
        started["decoration_started_utc"], "2026-08-11T08:00:00Z", "start stamp"
    )

    ready = mark_cake_ready(order["id"], headers=DECORATOR)
    assert ready["order_status"] == "READY"
    assert ready["version"] == started["version"] + 1
    assert_instant(ready["ready_at_utc"], "2026-08-11T08:00:00Z", "ready stamp")

    collected = pick_up_cake(order["id"], headers=CAKE_DESK)
    assert collected["order_status"] == "PICKED_UP"
    assert collected["version"] == ready["version"] + 1
    assert_instant(
        collected["picked_up_at_utc"], "2026-08-11T08:00:00Z", "pickup stamp"
    )
    assert read_pickup_slot(slot["id"])["reserved_decoration_units"] == 0
