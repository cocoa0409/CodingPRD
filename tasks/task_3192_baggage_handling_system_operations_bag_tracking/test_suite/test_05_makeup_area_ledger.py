"""Make-up area ledger: occupancy, intervals, capacity and the load/offload round trip."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    set_clock, base_scenario, get_area, get_flight, get_bag, list_rows,
    create_bag_payload, create_assign_makeup_payload, create_bulk_assign_item,
    weigh_ok, declare_outage,
)


def test_occupied_slots_counts_a_sorted_bag_aimed_at_the_area(api):
    """PRD §2.7: "The field `occupied_slots` counts the bags whose custody status
    is `SORTED` or `IN_MAKEUP` and whose `makeup_area_id` is this area — note that
    a bag still merely sorted already occupies a slot for the area it is destined
    to."

    Design: Corner/calculations/station_posture_suspends_at_capacity_and_guards_an_empty_makeup_set
    """
    from test_helpers import make_sorted_bag

    scenario = base_scenario()
    make_sorted_bag(scenario)
    set_clock("2026-09-01T13:12:00Z")
    bag = get_success_data(api.get_bag(
        get_success_data(api.list_bags(TEST_USERS["acceptance_agent_headers"],
                                       {"station_id": scenario["st"]}))[0]["id"],
        TEST_USERS["sortation_agent_headers"]))
    validate_success(api.assign_makeup(
        bag["id"],
        create_assign_makeup_payload(bag["version"], scenario["ma"], "2026-09-01T13:12:00Z"),
        TEST_USERS["sortation_agent_headers"]), 200)

    area = get_area(scenario["ma"])
    assert area["occupied_slots"] == 1
    assert area["free_slots"] == 1, "free_slots is capacity_slots minus occupied_slots"
    assert area["released_slots"] == 0


def test_loading_releases_the_make_up_slot(api):
    """PRD §2.7: "The field `released_slots` counts the bags that still carry
    this `makeup_area_id` but have moved on to `LOADED`, `OFFLOADED`, `DELIVERED`
    or `HELD`."

    Design: Difficulty/compensating_invariant/deliver_offload_returns_makeup_slot_to_ledger
    """
    from test_helpers import make_in_makeup_bag

    scenario = base_scenario()
    bag = make_in_makeup_bag(scenario)
    before = get_area(scenario["ma"])
    assert before["occupied_slots"] == 1
    assert before["released_slots"] == 0
    assert before["free_slots"] == 1

    set_clock("2026-09-01T13:50:00Z")
    loaded = validate_success(api.load_bag(bag["id"], TEST_USERS["load_agent_headers"]), 200)
    assert loaded["custody_status"] == "LOADED"

    after = get_area(scenario["ma"])
    assert after["occupied_slots"] == 0
    assert after["released_slots"] == 1
    assert after["free_slots"] == 2


def test_load_and_offload_round_trip_leaves_the_slot_ledger_identical(api):
    """PRD §2.7: "Together the two halves form the area's slot ledger"
    PRD §3.7: "A bag that reaches `LOADED` and then has to come back off the
    aircraft is `OFFLOADED`"

    Design: Difficulty/compensating_invariant/deliver_offload_returns_makeup_slot_to_ledger
    """
    from test_helpers import make_in_makeup_bag, board_and_depart

    scenario = base_scenario()
    bag = make_in_makeup_bag(scenario)
    before = get_area(scenario["ma"])

    set_clock("2026-09-01T13:50:00Z")
    validate_success(api.load_bag(bag["id"], TEST_USERS["load_agent_headers"]), 200)
    board_and_depart(scenario)

    offloaded = validate_success(api.offload_bag(bag["id"],
                                                 TEST_USERS["load_agent_headers"]), 200)
    after = get_area(scenario["ma"])

    assert offloaded["custody_status"] == "OFFLOADED"
    assert offloaded["makeup_area_id"] == scenario["ma"], \
        "the bag still carries the area it was made up in"
    assert before["occupied_slots"] + before["released_slots"] == \
        after["occupied_slots"] + after["released_slots"], \
        "the slot ledger must not drift across the round trip"
    assert after["free_slots"] == 2, \
        "free_slots is restored to its value before the bag was ever assigned"


def test_station_posture_returns_to_open_after_the_slot_is_handed_back(api):
    """PRD §2.6: "Otherwise, if the free make-up slots remaining across the
    station's active areas have fallen to fifteen percent of total capacity or
    below ... the posture is `CONGESTED`. In every other case the posture is
    `OPEN`."

    Design: Difficulty/compensating_invariant/deliver_offload_returns_makeup_slot_to_ledger
    """
    from test_helpers import make_in_makeup_bag
    from test_helpers.fixtures import run_ops

    scenario = base_scenario()
    bag = make_in_makeup_bag(scenario)
    set_clock("2026-09-01T13:50:00Z")
    validate_success(api.load_bag(bag["id"], TEST_USERS["load_agent_headers"]), 200)

    station = get_success_data(api.get_station(scenario["st"],
                                               TEST_USERS["platform_admin_headers"]))
    assert station["posture"] == "OPEN", \
        "a 2-slot area with 2 free slots is below no threshold"


def test_a_claim_in_the_same_identity_bucket_is_refused(api):
    """PRD §2.7: "Any existing occupied interval that falls in the same identity
    bucket conflicts with the claim regardless of how far apart the two intervals
    actually are"
    PRD §2.7: "A claim that collides is rejected with
    `ERR_MAKEUP_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/makeup_identity_bucket_membership_ignores_interval_magnitude
    """
    from test_helpers import make_sorted_bag

    scenario = base_scenario(makeup_capacity_slots=4)
    bag = make_sorted_bag(scenario)
    other = make_sorted_bag(scenario, bag_index=1,
                            passenger_ref="PNR4M1T")
    set_clock("2026-09-01T13:36:00Z")
    fresh = get_bag(bag["id"])
    first = validate_success(api.assign_makeup(
        fresh["id"],
        create_assign_makeup_payload(fresh["version"], scenario["ma"], "2026-09-01T13:36:00Z"),
        TEST_USERS["sortation_agent_headers"]), 200)
    assert first["custody_status"] == "IN_MAKEUP"
    assert get_area(scenario["ma"])["free_slots"] == 3

    second = get_bag(other["id"])
    response = api.assign_makeup(
        second["id"],
        create_assign_makeup_payload(second["version"], scenario["ma"],
                                     "2026-09-01T13:40:00Z"),
        TEST_USERS["sortation_agent_headers"])
    validate_error(response, ApiErrorId.ERR_MAKEUP_SLOT_CONFLICT, 409)


def test_areas_never_exceed_their_declared_capacity_of_distinct_buckets(api):
    """PRD §2.7: "the area may never hold more than `capacity_slots` distinct
    occupied identity buckets."

    Design: Difficulty/resource_temporal_overlap/makeup_identity_bucket_membership_ignores_interval_magnitude
    """
    from test_helpers import make_sorted_bag

    scenario = base_scenario(makeup_capacity_slots=2)
    from test_helpers.fixtures import run_ops
    set_clock("2026-09-01T12:30:00Z")
    run_ops(scenario["st"])

    bags = [make_sorted_bag(scenario, bag_index=index) for index in range(3)]
    for index, bag in enumerate(bags[:2]):
        fresh = get_bag(bag["id"])
        validate_success(api.assign_makeup(
            fresh["id"],
            create_assign_makeup_payload(fresh["version"], scenario["ma"],
                                         f"2026-09-01T13:{12 * (index + 1):02d}:00Z"),
            TEST_USERS["sortation_agent_headers"]), 200)

    assert get_area(scenario["ma"])["occupied_slots"] == 2
    third = get_bag(bags[2]["id"])
    response = api.assign_makeup(
        third["id"],
        create_assign_makeup_payload(third["version"], scenario["ma"],
                                     "2026-09-01T13:36:00Z"),
        TEST_USERS["sortation_agent_headers"])
    validate_error(response, ApiErrorId.ERR_MAKEUP_SLOT_CONFLICT, 409)


def test_bulk_assign_applies_the_accepted_items_and_reports_the_rejected_one(api):
    """PRD §3.6: "The response separates the two outcomes into an `assigned`
    collection of the bags that were accepted and a `rejected` collection in
    which each entry names its `bag_id` and the `error_code` that refused it."

    Design: Corner/endpoints/bulk_assign_makeup_reports_per_bag_outcomes
    """
    from test_helpers import make_sorted_bag
    from test_helpers.fixtures import run_ops

    scenario = base_scenario(makeup_capacity_slots=2)
    set_clock("2026-09-01T13:00:00Z")
    run_ops(scenario["st"])
    bags = [make_sorted_bag(scenario, bag_index=index) for index in range(3)]

    assignments = []
    for bag, induction in zip(bags, ("2026-09-01T13:36:00Z", "2026-09-01T13:48:00Z",
                                     "2026-09-01T13:36:00Z")):
        assignments.append(create_bulk_assign_item(
            bag["id"], bag["version"], scenario["ma"], induction))

    response = api.bulk_assign_makeup(assignments, TEST_USERS["sortation_agent_headers"])
    body = validate_success(response, 200)
    rejected = body.get("rejected", [])
    assigned = body.get("assigned", [])

    assert len(rejected) == 1, "exactly one item is refused"
    assert rejected[0]["error_code"] == "ERR_MAKEUP_SLOT_CONFLICT"
    assert rejected[0]["bag_id"] == bags[2]["id"], \
        "the rejected entry names its own bag"
    assert len(assigned) == 2, "the other two items are applied without aborting the batch"
    assert get_area(scenario["ma"])["occupied_slots"] == 2


def test_bulk_assign_surfaces_an_independently_failing_item(api):
    """PRD §3.6: "Each item in the batch is validated exactly as the single-bag
    claim is — independently of the others, in the order the items were supplied
    — and a rejected item never aborts the batch."

    Design: Corner/cross_cutting_complexity_layers/bulk_assign_makeup_surfaces_per_item_failures
    """
    from test_helpers import make_sorted_bag, create_bulk_assign_item
    from test_helpers.fixtures import run_ops

    scenario = base_scenario(makeup_capacity_slots=6, makeup_code="MA-9")
    set_clock("2026-09-01T13:00:00Z")
    run_ops(scenario["st"])

    first = make_sorted_bag(scenario, bag_index=0)
    third = make_sorted_bag(scenario, bag_index=1, passenger_ref="PNR4M1T")
    # The middle item's bag has been accepted but never weighed or screened, so
    # its own claim is refused while the others in the same batch are applied.
    unsorted = get_success_data(api.create_bag(
        create_bag_payload(scenario["st"], flight_id=scenario["f1"],
                           passenger_ref="PNR5T9K"),
        TEST_USERS["acceptance_agent_headers"]))
    assert unsorted["custody_status"] == "ACCEPTED"

    assignments = [
        create_bulk_assign_item(first["id"], first["version"], scenario["ma"],
                                "2026-09-01T13:00:00Z"),
        create_bulk_assign_item(unsorted["id"], unsorted["version"], scenario["ma"],
                                "2026-09-01T13:12:00Z"),
        create_bulk_assign_item(third["id"], third["version"], scenario["ma"],
                                "2026-09-01T13:24:00Z"),
    ]
    body = validate_success(api.bulk_assign_makeup(
        assignments, TEST_USERS["sortation_agent_headers"]), 200)

    assert len(body.get("rejected", [])) == 1, "the flagged bag is reported separately"
    assert body["rejected"][0]["bag_id"] == unsorted["id"]
    assert body["rejected"][0]["error_code"] == "ERR_SCREENING_NOT_CLEARED"
    assert get_bag(third["id"])["custody_status"] == "IN_MAKEUP"
    assert get_area(scenario["ma"])["occupied_slots"] == 2