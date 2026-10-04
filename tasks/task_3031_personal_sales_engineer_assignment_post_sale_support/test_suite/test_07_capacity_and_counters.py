"""Depth: aggregate service-center capacity and the conserved book-occupancy count."""
from test_helpers import validate_success
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_book_occupancy_reconciles
from test_helpers.fixtures import (
    SALES_OPS,
    SUPPORT_AGENT,
    accept_assignment,
    activate_warranty_plan,
    close_claim,
    count_active_assignments,
    create_assignment,
    create_customer,
    create_service_center,
    create_warranty_claim,
    create_warranty_plan,
    end_assignment,
    get_customer as read_customer,
    get_engineer as read_engineer,
    route_claim,
    set_clock,
    setup_book_world,
    setup_reserved_quote,
    setup_shipped_instrument,
)


def _shipped_world_with_active_plan(clock="2026-09-23T00:00:00.000Z"):
    world = setup_book_world(clock=clock)
    setup_reserved_quote(world)
    shipped = setup_shipped_instrument(world)
    plan = activate_warranty_plan(
        create_warranty_plan(world["customer"], shipped), clock)
    world.update({"plan": plan, "plan_id": plan["id"]})
    return world


def test_closing_a_claim_releases_the_aggregate_slot_it_held():
    """PRD 3.6: "The routed center's `open_ticket_count` is decremented,
    releasing the slot the claim was holding, and the service fee is stored in
    its final form."

    Design: Difficulty/resource_temporal_overlap/service_center_concurrent_capacity_aggregate_not_interval
    """
    world = _shipped_world_with_active_plan()
    center = create_service_center(name="Muncie Bench", capacity_slots=2,
                                   accepted_families=["GUITAR"])
    claim = create_warranty_claim(plan=world["plan"], service_center=center,
                                  reported_fault="Output jack crackle")
    route_claim(claim)

    closed = close_claim(claim)
    assert closed["status"] == "CLOSED"

    rows = api_client.list_service_centers(SUPPORT_AGENT, {"region": "MIDWEST"}).json()["data"]
    stored = [row for row in rows if row["id"] == center["id"]][0]
    assert stored["open_ticket_count"] == 0


def test_a_second_claim_routes_once_the_slot_is_free_again():
    """PRD 3.6: "the center's capacity is a count of concurrently open tickets
    rather than a pairwise time check; a full desk refuses with
    `ERR_SERVICE_CENTER_CAPACITY_FULL` at HTTP 422."

    Design: Difficulty/resource_temporal_overlap/service_center_concurrent_capacity_aggregate_not_interval
    """
    world = _shipped_world_with_active_plan()
    center = create_service_center(name="Muncie Bench", capacity_slots=2,
                                   accepted_families=["GUITAR"])
    first = create_warranty_claim(plan=world["plan"], service_center=center,
                                  reported_fault="Output jack crackle")
    route_claim(first)
    close_claim(first)

    second = create_warranty_claim(plan=world["plan"], service_center=center,
                                   reported_fault="Tuner slips under tension")
    routed = route_claim(second)
    assert routed["status"] == "ROUTED"
    rows = api_client.list_service_centers(SUPPORT_AGENT, {"region": "MIDWEST"}).json()["data"]
    stored = [row for row in rows if row["id"] == center["id"]][0]
    assert stored["open_ticket_count"] == 1


def test_closing_one_of_several_rounds_keeps_the_plan_in_service():
    """PRD 3.6: "The plan then either returns to `ACTIVE` when the allowance is
    still positive or moves to `EXPIRED` when it has reached zero." PRD 3.6:
    "`remaining_repair_rounds` is three minus that count, floored at zero so
    that it never goes negative."

    Design: Difficulty/resource_temporal_overlap/service_center_concurrent_capacity_aggregate_not_interval
    """
    world = _shipped_world_with_active_plan()
    center = create_service_center(name="Muncie Bench", capacity_slots=2,
                                   accepted_families=["GUITAR"])
    claim = create_warranty_claim(plan=world["plan"], service_center=center)
    route_claim(claim)
    close_claim(claim)

    plan = validate_success(api_client.get_warranty_plan(world["plan_id"], SUPPORT_AGENT))
    assert plan["status"] == "ACTIVE"
    assert plan["repair_rounds_used"] == 1
    assert plan["remaining_repair_rounds"] == 2


def test_engineer_book_counter_equals_the_active_assignment_count():
    """PRD 2.4: "Every engineer carries a `max_book_size`, the ceiling on how
    many book rows they may hold, and a derived `active_book_size` that counts
    their `Assignment` rows currently in `ACTIVE` status."

    Design: Difficulty/compensating_invariant/assignment_book_and_customer_slot_counters_reconcile
    """
    world = setup_book_world(clock="2026-09-25T00:00:00.000Z", with_catalog=False)
    second_customer = create_customer("Ken Ives", "ken.ives@example.com", "OH")
    second = create_assignment(second_customer, world["engineer"])
    accept_assignment(second)

    engineer = read_engineer(world["engineer_id"])
    assert engineer["active_book_size"] == 2
    assert_book_occupancy_reconciles(engineer,
                                     count_active_assignments(world["engineer_id"]))


def test_ending_one_assignment_drops_the_counter_and_clears_the_mirror():
    """PRD 3.1: "When an `ACTIVE` assignment is ended, the customer's
    `assigned_engineer_id` is cleared to null, the holding engineer's
    `active_book_size` drops by one".

    Design: Difficulty/compensating_invariant/assignment_book_and_customer_slot_counters_reconcile
    """
    world = setup_book_world(clock="2026-09-25T00:00:00.000Z", with_catalog=False)
    second_customer = create_customer("Ken Ives", "ken.ives@example.com", "OH")
    second = create_assignment(second_customer, world["engineer"])
    accept_assignment(second)

    end_assignment(second, SALES_OPS)

    engineer = read_engineer(world["engineer_id"])
    assert engineer["active_book_size"] == 1
    assert_book_occupancy_reconciles(engineer,
                                     count_active_assignments(world["engineer_id"]))
    assert read_customer(second_customer["id"])["assigned_engineer_id"] is None


def test_suspending_a_customer_ends_the_book_row_and_empties_the_counter():
    """PRD 3.1: "Suspending an `ACTIVE` customer returns it to `PENDING` and
    ends every assignment on that book that is in either `PENDING_ACCEPT` or
    `ACTIVE`, decrementing `active_book_size` by one for each affected engineer
    and clearing `assigned_engineer_id`."

    Design: Difficulty/compensating_invariant/assignment_book_and_customer_slot_counters_reconcile
    """
    world = setup_book_world(clock="2026-09-25T00:00:00.000Z", with_catalog=False)
    second_customer = create_customer("Ken Ives", "ken.ives@example.com", "OH")
    second = create_assignment(second_customer, world["engineer"])
    accept_assignment(second)
    end_assignment(second, SALES_OPS)

    validate_success(api_client.activate_customer(world["customer_id"], SALES_OPS))
    suspended = validate_success(
        api_client.suspend_customer(world["customer_id"],
                                    {"X-User-ID": "test-platform-admin-1",
                                     "X-User-Role": "PlatformAdmin",
                                     "Content-Type": "application/json"})
    )
    assert suspended["status"] == "PENDING"

    engineer = read_engineer(world["engineer_id"])
    assert engineer["active_book_size"] == 0
    assert_book_occupancy_reconciles(engineer,
                                     count_active_assignments(world["engineer_id"]))
    assert read_customer(world["customer_id"])["assigned_engineer_id"] is None


def test_occupancy_count_stays_equal_to_active_rows_across_every_step():
    """PRD 2.8: "`active_book_size` counts an engineer's `ACTIVE` assignments."
    PRD 2.8: "None of these is client-settable; each is recomputed by the
    operation that would change its inputs."

    Design: Difficulty/compensating_invariant/assignment_book_and_customer_slot_counters_reconcile
    """
    set_clock("2026-09-25T00:00:00.000Z")
    world = setup_book_world(clock="2026-09-25T00:00:00.000Z", with_catalog=False)
    second_customer = create_customer("Ken Ives", "ken.ives@example.com", "OH")

    second = create_assignment(second_customer, world["engineer"])
    accept_assignment(second)
    assert_book_occupancy_reconciles(read_engineer(world["engineer_id"]),
                                     count_active_assignments(world["engineer_id"]))

    end_assignment(second, SALES_OPS)
    assert_book_occupancy_reconciles(read_engineer(world["engineer_id"]),
                                     count_active_assignments(world["engineer_id"]))

    validate_success(api_client.activate_customer(world["customer_id"], SALES_OPS))
    validate_success(api_client.suspend_customer(
        world["customer_id"],
        {"X-User-ID": "test-platform-admin-1", "X-User-Role": "PlatformAdmin",
         "Content-Type": "application/json"}))
    assert_book_occupancy_reconciles(read_engineer(world["engineer_id"]),
                                     count_active_assignments(world["engineer_id"]))
    assert read_engineer(world["engineer_id"])["active_book_size"] == 0