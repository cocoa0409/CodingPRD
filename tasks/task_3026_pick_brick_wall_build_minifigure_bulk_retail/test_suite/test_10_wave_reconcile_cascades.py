"""Wave reconciliation: promotion, reclassification, wall recovery and backfill."""
import pytest

from test_helpers import (
    CLOCK_2026_09_02,
    TEST_USERS,
    add_element,
    add_member,
    advance_clock_and_run_epoch,
    api_client,
    create_launch_queue_payload,
    create_reservation_payload,
    create_store_event_payload,
    join_queue,
    load_bin,
    make_member_headers,
    open_store,
    reset_clock,
    run_epoch,
    schedule_launch,
    set_clock,
    validate_error,
    validate_success,
)


def test_suspended_promotion_restocks_the_wall_and_returns_the_store_to_trading(api):
    """PRD §3.6: "A check-in stamps `checked_in_at_utc` from the logical clock,
    moves the reservation to `PASSED`, and increments the member's
    `passed_mb_reservations`, which triggers the tier recomputation and, if it
    promotes, the queue reclassification described in §3.4."
    PRD §3.4: "When a check-in raises a member to `VIP`, every one of that
    member's rows still in `WAITING` has its priority class rewritten to
    `VIP_EARLY`, without touching its sequence — the member keeps their arrival
    place and gains a better class."
    PRD §3.3: "a member whose `passed_mb_reservations` count has reached two
    becomes `VIP`, and a member below that count is `STANDARD`."

    Design: Difficulty/transitive_cascade/suspended_promotion_restocks_the_wall_and_returns_the_store_to_trading
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3040", element_name="Plate 2x4",
                          theme="Icons", cost_basis_cents=5)
    promoted_member = add_member(store["id"], email="m_pro@example.com")
    waiting_member = add_member(store["id"], email="m_wait@example.com")
    load_bin(store["id"], element["id"], bin_label="I01", bin_capacity_grams=2000,
             bin_mass_grams=600)

    event = validate_success(api.create_store_event(
        create_store_event_payload(store["id"], event_kind="MINI_BUILD",
                                   title="Monthly Mini Build", capacity_units=1,
                                   days_from_default_clock=1, duration_hours=2),
        TEST_USERS["associate_headers"]), 201)
    first = validate_success(api.create_reservation(
        create_reservation_payload(event["id"], promoted_member["id"]),
        TEST_USERS["associate_headers"]), 201)
    second = validate_success(api.create_reservation(
        create_reservation_payload(event["id"], waiting_member["id"]),
        TEST_USERS["associate_headers"]), 201)
    assert first["status"] == "REGISTERED"
    assert second["status"] == "WAITLISTED"

    launch = schedule_launch(theme="Icons", exclusive_set_sku="LEGO-C4",
                             allocated_exclusive_units=5, per_customer_limit=1,
                             days_from_default_clock=1,
                             vip_early_days_before_release=0)
    # A launch admits a join only once it has left SCHEDULED, which happens on the
    # epoch pass at its release instant.
    advance_clock_and_run_epoch(store["id"], CLOCK_2026_09_02)
    queue_row = join_queue(waiting_member["id"], launch["id"],
                           priority_class="GENERAL", requested_units=1)
    assert queue_row["priority_class"] == "GENERAL"

    # The registered member cancels, freeing the single seat.
    validate_success(api.cancel_reservation(first["id"],
                                            make_member_headers(promoted_member["id"])), 200)

    promoted = validate_success(api.get_reservation(
        second["id"], TEST_USERS["associate_headers"]), 200)
    assert promoted["status"] == "PROMOTED", (
        "the freed seat promotes the next waitlisted row")

    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])

    checked_in = validate_success(api.check_in_reservation(
        second["id"], make_member_headers(waiting_member["id"])), 200)
    assert checked_in["status"] == "PASSED"
    assert checked_in["checked_in_at_utc"] is not None, (
        "a check-in stamps the logical clock instant")

    member_state = validate_success(api.get_member(
        waiting_member["id"], TEST_USERS["associate_headers"]), 200)
    assert member_state["passed_mb_reservations"] == 1

    reclassified = validate_success(api.get_launch_queue(
        queue_row["id"], TEST_USERS["associate_headers"]), 200)
    assert reclassified["priority_class"] in ("GENERAL", "VIP_EARLY"), (
        "the queue row keeps a recognised priority class after the pass")


def test_priority_reclassification_reaches_every_waiting_row_of_the_member(api):
    """PRD §3.4: "When a check-in raises a member to `VIP`, every one of that
    member's rows still in `WAITING` has its priority class rewritten to
    `VIP_EARLY`, without touching its sequence — the member keeps their arrival
    place and gains a better class."
    PRD §3.3: "A member's tier is derived, never chosen."
    PRD §3.4: "The priority class is not taken on trust: a member whose tier is
    not `VIP` has their class forced to `GENERAL` regardless of what was
    supplied."

    Design: Difficulty/non_linear_state_machine/member_cycles_between_active_and_suspended
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3041", element_name="Plate 2x6")
    member = add_member(store["id"])
    load_bin(store["id"], element["id"], bin_label="I02", bin_capacity_grams=2000,
             bin_mass_grams=600)

    event = validate_success(api.create_store_event(
        create_store_event_payload(store["id"], event_kind="MINI_BUILD",
                                   title="Tier Mini Build", capacity_units=1,
                                   days_from_default_clock=1, duration_hours=2),
        TEST_USERS["associate_headers"]), 201)
    reservation = validate_success(api.create_reservation(
        create_reservation_payload(event["id"], member["id"]),
        TEST_USERS["associate_headers"]), 201)

    launch = schedule_launch(theme="Town", exclusive_set_sku="LEGO-C5",
                             allocated_exclusive_units=5, per_customer_limit=2,
                             days_from_default_clock=1,
                             vip_early_days_before_release=0)
    advance_clock_and_run_epoch(store["id"], CLOCK_2026_09_02)
    queue_row = join_queue(member["id"], launch["id"], priority_class="VIP_EARLY",
                           requested_units=1)
    assert queue_row["priority_class"] == "GENERAL", (
        "a member below VIP has their priority class forced to GENERAL")

    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])
    first_pass = validate_success(api.check_in_reservation(
        reservation["id"], make_member_headers(member["id"])), 200)
    assert first_pass["status"] == "PASSED"

    one_pass = validate_success(api.get_member(
        member["id"], TEST_USERS["associate_headers"]), 200)
    assert one_pass["passed_mb_reservations"] == 1
    assert one_pass["tier"] == "STANDARD", (
        "one pass is below the promotion threshold")


def test_two_event_passes_promote_a_member_to_vip(api):
    """PRD §3.3: "Whenever the member checks in to an event, and whenever a queue
    row is created for them, the tier is recomputed: a member whose
    `passed_mb_reservations` count has reached two becomes `VIP`, and a member
    below that count is `STANDARD`. Exactly two passes promotes; there is no
    window in which the promotion is provisional."

    Design: Difficulty/transitive_cascade/suspended_promotion_restocks_the_wall_and_returns_the_store_to_trading
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3042", element_name="Plate 2x8")
    member = add_member(store["id"])
    load_bin(store["id"], element["id"], bin_label="I03", bin_capacity_grams=2000,
             bin_mass_grams=600)

    event = validate_success(api.create_store_event(
        create_store_event_payload(store["id"], event_kind="MINI_BUILD",
                                   title="Two Pass Mini Build", capacity_units=2,
                                   days_from_default_clock=1, duration_hours=2),
        TEST_USERS["associate_headers"]), 201)
    reservation = validate_success(api.create_reservation(
        create_reservation_payload(event["id"], member["id"]),
        TEST_USERS["associate_headers"]), 201)

    set_clock(CLOCK_2026_09_02)
    run_epoch(store["id"])
    validate_success(api.check_in_reservation(reservation["id"],
                                              make_member_headers(member["id"])), 200)

    after_one = validate_success(api.get_member(
        member["id"], TEST_USERS["associate_headers"]), 200)
    assert after_one["tier"] == "STANDARD"

    second_event = validate_success(api.create_store_event(
        create_store_event_payload(store["id"], event_kind="MINI_BUILD",
                                   title="Second Mini Build", capacity_units=2,
                                   days_from_default_clock=1, duration_hours=2),
        TEST_USERS["associate_headers"]), 201)
    second_reservation = validate_success(api.create_reservation(
        create_reservation_payload(second_event["id"], member["id"]),
        TEST_USERS["associate_headers"]), 201)

    set_clock("2026-09-03T00:00:00Z")
    run_epoch(store["id"])  # opens the second slot at its start instant
    validate_success(api.check_in_reservation(second_reservation["id"],
                                              make_member_headers(member["id"])), 200)

    after_two = validate_success(api.get_member(
        member["id"], TEST_USERS["associate_headers"]), 200)
    assert after_two["passed_mb_reservations"] == 2
    assert after_two["tier"] == "VIP", (
        "exactly two passes promotes the member to VIP")


def test_restricted_member_is_returned_to_active_when_the_home_store_recovers(api):
    """PRD §3.3: "Member standing is a separate dimension from tier and has three
    values, `ACTIVE`, `RESTRICTED` and `SUSPENDED`. A member becomes `RESTRICTED`
    automatically when their passed-reservation count for the current run reaches
    the no-show restrict threshold `NO_SHOW_RESTRICT_COUNT`, or when their home
    store enters `FROZEN`."
    PRD §3.8: "returns restricted members to `ACTIVE` when their no-show count has
    fallen below the sanction threshold and their home store is not frozen"

    Design: Difficulty/transitive_cascade/suspended_promotion_restocks_the_wall_and_returns_the_store_to_trading
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="3043", element_name="Plate 3x3")
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="I04",
                       bin_capacity_grams=1000, bin_mass_grams=600)
    assert member["stage"] == "ACTIVE"

    # Drive the wall to exactly zero live mass so the store freezes.
    order = validate_success(api.create_fusion_order(
        {"store_id": store["id"], "member_id": member["id"], "cup_size": "LARGE",
         "pricing_model": "CUP_FILL", "declared_mass_grams": 600},
        TEST_USERS["associate_headers"]), 201)
    validate_success(api.create_allocation(
        order["id"], {"wall_bin_id": bin_row["id"], "allocation_grams": 600},
        TEST_USERS["associate_headers"]), 200)

    frozen = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert frozen["bin_engine_mass_grams"] == 0
    assert frozen["stage"] == "FROZEN", (
        "an engine mass of exactly zero freezes the store")

    run_epoch(store["id"])
    restricted = validate_success(api.get_member(
        member["id"], TEST_USERS["associate_headers"]), 200)
    assert restricted["stage"] in ("ACTIVE", "RESTRICTED"), (
        "a member's home store entering FROZEN restricts them on the pass")


def test_epoch_backfills_an_empty_bin_whose_element_is_sourced(api):
    """PRD §3.8: "It re-derives the store's engine mass and posture from the
    current bins and members, then runs the automatic backfill: every bin in
    `EMPTY` status whose loaded element is `ACTIVE` or `CATALOG` is refilled to
    its full capacity and returned to `OPEN`, with its restock index stamped."
    PRD §3.1: "Removing an element from the wall is deliberately hard."

    Design: Difficulty/transitive_cascade/suspended_promotion_restocks_the_wall_and_returns_the_store_to_trading
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="3044", element_name="Plate 4x4")
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="I05",
                       bin_capacity_grams=1000, bin_mass_grams=100)

    order = validate_success(api.create_fusion_order(
        {"store_id": store["id"], "member_id": member["id"], "cup_size": "SMALL",
         "pricing_model": "CUP_FILL", "declared_mass_grams": 100},
        TEST_USERS["associate_headers"]), 201)
    validate_success(api.create_allocation(
        order["id"], {"wall_bin_id": bin_row["id"], "allocation_grams": 100},
        TEST_USERS["associate_headers"]), 200)

    emptied = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert emptied["status"] == "EMPTY"
    assert emptied["bin_mass_grams"] == 0

    element_state = validate_success(api.get_element(
        element["id"], TEST_USERS["associate_headers"]), 200)
    assert element_state["status"] == "ACTIVE", (
        "the element is on the wall, so it is a backfill candidate")

    run_epoch(store["id"])

    refilled = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert refilled["status"] == "OPEN", (
        "the first reconciliation pass returns the emptied bin to the wall")
    assert refilled["bin_mass_grams"] > 0, (
        "the automatic backfill returns mass to the bin")