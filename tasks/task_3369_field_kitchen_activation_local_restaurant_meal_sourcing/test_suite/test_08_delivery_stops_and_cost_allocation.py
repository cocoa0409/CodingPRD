"""Stop outcomes, cascades and run cost allocation."""
from test_helpers import (
    ApiErrorId,
    add_stop,
    api_client,
    create_distribution_run,
    create_distribution_site,
    deliver_stop,
    get_run,
    get_stop,
    make_site_coordinator_headers,
    setup_delivering_run,
    setup_operational_field_kitchen,
    setup_loaded_run_with_stops,
    transition_distribution_run,
    transition_field_kitchen,
    transition_stop,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

LOGISTICS = TEST_USERS["logistics_coordinator_headers"]
SAFETY = TEST_USERS["food_safety_officer_headers"]


def test_kitchen_suspension_aborts_the_run_and_skips_its_pending_stops(api):
    """PRD §3.2: "Suspension stamps `suspended_at` and cascades one hop: every
    delivery run of that kitchen whose `status` is `PLANNED` or `LOADING` is
    moved to `ABORTED` with `abort_reason` set to `ORIGIN_KITCHEN_SUSPENDED`,
    and each of those runs' pending stops is skipped with `failure_reason` set
    to `ORIGIN_KITCHEN_SUSPENDED`."

    Design: Difficulty/transitive_cascade/kitchen_suspension_aborts_runs_skips_stops_and_alerts_sites
    """
    incident, _, field_kitchen = setup_operational_field_kitchen()
    first_site = create_distribution_site(incident["id"])
    second_site = create_distribution_site(
        incident["id"], site_name="Valley Hospital", site_type="HOSPITAL"
    )
    run = create_distribution_run(incident["id"], field_kitchen["id"])
    transition_distribution_run(run["id"], "LOADING", loaded_meals=9)
    first_stop = add_stop(run["id"], first_site["id"], 1, 4)
    second_stop = add_stop(run["id"], second_site["id"], 2, 5)

    suspended = transition_field_kitchen(field_kitchen["id"], "SUSPENDED", SAFETY)
    assert suspended["site_status"] == "SUSPENDED"

    aborted = get_run(run["id"])
    assert aborted["status"] == "ABORTED"
    assert aborted["abort_reason"] == "ORIGIN_KITCHEN_SUSPENDED"
    assert get_stop(first_stop["id"])["status"] == "SKIPPED"
    assert get_stop(second_stop["id"])["status"] == "SKIPPED"
    assert get_stop(second_stop["id"])["failure_reason"] == "ORIGIN_KITCHEN_SUSPENDED"


def test_skipped_stops_push_the_receiving_sites_into_service_alert(api):
    """PRD §3.7: "if the affected site now has strictly more stops in `SKIPPED`
    than in `DELIVERED`, the site's status is set to `SERVICE_ALERT`, flagging
    that the site is being missed more often than it is served."

    Design: Difficulty/transitive_cascade/kitchen_suspension_aborts_runs_skips_stops_and_alerts_sites
    """
    incident, _, field_kitchen = setup_operational_field_kitchen()
    first_site = create_distribution_site(incident["id"])
    second_site = create_distribution_site(
        incident["id"], site_name="Valley Hospital", site_type="HOSPITAL"
    )
    run = create_distribution_run(incident["id"], field_kitchen["id"])
    transition_distribution_run(run["id"], "LOADING", loaded_meals=9)
    add_stop(run["id"], first_site["id"], 1, 4)
    add_stop(run["id"], second_site["id"], 2, 5)

    transition_field_kitchen(field_kitchen["id"], "SUSPENDED", SAFETY)

    sites, _ = validate_paginated(
        api_client.list_incident_distribution_sites(incident["id"], LOGISTICS, {"limit": 50})
    )
    by_id = {row["id"]: row for row in sites}
    assert by_id[first_site["id"]]["status"] == "SERVICE_ALERT"
    assert by_id[first_site["id"]]["skipped_stop_count"] == 1
    assert by_id[second_site["id"]]["status"] == "SERVICE_ALERT"
    assert by_id[second_site["id"]]["delivered_stop_count"] == 0


def test_cost_allocation_rounds_each_share_then_gives_the_residual_to_the_first_stop(api):
    """PRD §3.8: "The difference between the run's total cost and the sum of the
    rounded shares is the residual, and it is added to the eligible stop with
    the lowest `stop_sequence`, so the allocated shares always sum exactly to
    the run's total cost and `unallocated_cost_cents` is 0."

    Design: Difficulty/combinatorial_formula/run_cost_allocation_per_stop_rounding_then_residual
    """
    incident, _, field_kitchen = setup_operational_field_kitchen()
    sites = [create_distribution_site(incident["id"], site_name=f"Site {i + 1}")
             for i in range(3)]
    run = create_distribution_run(
        incident["id"], field_kitchen["id"], fuel_cost_cents=6000, handling_cost_cents=4000
    )
    transition_distribution_run(run["id"], "LOADING", loaded_meals=9)
    stops = [add_stop(run["id"], site["id"], index + 1, 3)
             for index, site in enumerate(sites)]
    transition_distribution_run(run["id"], "EN_ROUTE", loaded_meals=9)
    transition_distribution_run(run["id"], "DELIVERING")
    for stop, site in zip(stops, sites):
        deliver_stop(stop["id"], site["id"], 3)

    completed = transition_distribution_run(run["id"], "COMPLETED")
    assert completed["total_cost_cents"] == 10_000
    assert get_stop(stops[0]["id"])["allocated_cost_cents"] == 3334
    assert get_stop(stops[1]["id"])["allocated_cost_cents"] == 3333
    assert get_stop(stops[2]["id"])["allocated_cost_cents"] == 3333
    assert completed["unallocated_cost_cents"] == 0


def test_allocated_shares_sum_exactly_to_the_run_total(api):
    """PRD §3.8: "Each share is rounded independently and the rounded shares are
    then summed; the shares are never summed unrounded and rounded once at the
    end."
    PRD §3.8: "The final allocations are 3,334, 3,333 and 3,333, and
    `unallocated_cost_cents` is 0."

    Design: Difficulty/combinatorial_formula/run_cost_allocation_per_stop_rounding_then_residual
    """
    incident, _, field_kitchen = setup_operational_field_kitchen()
    sites = [create_distribution_site(incident["id"], site_name=f"Site {i + 1}")
             for i in range(3)]
    run = create_distribution_run(
        incident["id"], field_kitchen["id"], fuel_cost_cents=6000, handling_cost_cents=4000
    )
    transition_distribution_run(run["id"], "LOADING", loaded_meals=9)
    stops = [add_stop(run["id"], site["id"], index + 1, 3)
             for index, site in enumerate(sites)]
    transition_distribution_run(run["id"], "EN_ROUTE", loaded_meals=9)
    transition_distribution_run(run["id"], "DELIVERING")
    for stop, site in zip(stops, sites):
        deliver_stop(stop["id"], site["id"], 3)
    completed = transition_distribution_run(run["id"], "COMPLETED")

    shares = [get_stop(stop["id"])["allocated_cost_cents"] for stop in stops]
    assert shares == [3334, 3333, 3333]
    assert sum(shares) == completed["total_cost_cents"] == 10_000


def test_completed_run_with_no_delivered_stop_leaves_the_pool_unallocated(api):
    """PRD §3.8: "when the total delivered meals across eligible stops is 0,
    every eligible stop is allocated 0 and the entire cost pool is left in
    `unallocated_cost_cents` rather than being divided by zero or discarded."

    Design: Corner/calculations/run_cost_allocation_zero_delivered_denominator_leaves_pool_unallocated
    """
    incident, _, run, sites, stops = setup_delivering_run(
        [(4, None), (5, None)], loaded_meals=9
    )
    transition_stop(stops[0]["id"], "FAILED", failure_reason="ROAD_BLOCKED")
    transition_stop(stops[1]["id"], "FAILED", failure_reason="SITE_CLOSED")
    completed = transition_distribution_run(run["id"], "COMPLETED")

    assert completed["status"] == "COMPLETED"
    assert completed["delivered_meals"] == 0
    assert completed["returned_meals"] == 9
    assert completed["unallocated_cost_cents"] == 10_000
    assert get_stop(stops[0]["id"])["allocated_cost_cents"] == 0
    assert get_stop(stops[1]["id"])["allocated_cost_cents"] == 0


def test_reversal_moves_delivered_meals_into_returned_meals(api):
    """PRD §3.7: "The reversal decrements the site's `received_meals_total` by
    that stop's `delivered_meals`, sets the stop's `delivered_meals` back to 0,
    and recomputes the run's `delivered_meals` and `returned_meals`."
    PRD §3.7: "`loaded_meals` is the conserved quantity: it must be identical
    before and after a forward-and-reversal pair, and no stop outcome ever
    changes it."

    Design: Difficulty/compensating_invariant/stop_reversal_conserves_run_loaded_meals
    """
    incident, _, run, sites, stops = setup_delivering_run(
        [(40, None), (60, None)], loaded_meals=100
    )
    deliver_stop(stops[0]["id"], sites[0]["id"], 40)
    deliver_stop(stops[1]["id"], sites[1]["id"], 60)

    reversal = api_client.transition_distribution_stop(
        stops[1]["id"],
        {"to_state": "FAILED", "failure_reason": "SITE_CLOSED_BEFORE_HANDOVER"},
        LOGISTICS,
    )
    validate_success(reversal)

    run_row = get_run(run["id"])
    assert run_row["loaded_meals"] == 100
    assert run_row["delivered_meals"] == 40
    assert run_row["returned_meals"] == 60
    assert run_row["loaded_meals"] == (
        run_row["delivered_meals"] + run_row["returned_meals"]
    )
    assert get_stop(stops[1]["id"])["delivered_meals"] == 0


def test_reversal_decrements_the_receiving_sites_meal_total(api):
    """PRD §3.7: "A stop that was recorded as `DELIVERED` can be reversed to
    `FAILED`, with a `failure_reason`, as long as the parent run is in
    `DELIVERING` or `COMPLETED`."
    PRD §3.7: "This is the compensating action of the handover, and it exists so
    that a handover entered in error — or a load later found to have been
    mis-recorded — can be corrected after the run has already closed."

    Design: Difficulty/compensating_invariant/stop_reversal_conserves_run_loaded_meals
    """
    incident, _, run, sites, stops = setup_delivering_run(
        [(40, None), (60, None)], loaded_meals=100
    )
    deliver_stop(stops[0]["id"], sites[0]["id"], 40)
    deliver_stop(stops[1]["id"], sites[1]["id"], 60)

    sites_before, _ = validate_paginated(
        api_client.list_incident_distribution_sites(incident["id"], LOGISTICS, {"limit": 50})
    )
    totals_before = {row["id"]: row["received_meals_total"] for row in sites_before}
    assert totals_before[sites[0]["id"]] == 40
    assert totals_before[sites[1]["id"]] == 60

    api_client.transition_distribution_stop(
        stops[1]["id"],
        {"to_state": "FAILED", "failure_reason": "SITE_CLOSED_BEFORE_HANDOVER"},
        LOGISTICS,
    )
    sites_after, _ = validate_paginated(
        api_client.list_incident_distribution_sites(incident["id"], LOGISTICS, {"limit": 50})
    )
    totals_after = {row["id"]: row["received_meals_total"] for row in sites_after}
    assert totals_after[sites[0]["id"]] == 40
    assert totals_after[sites[1]["id"]] == 0


def test_first_delivered_stop_activates_the_receiving_site(api):
    """PRD §3.7: "A successful handover stamps `delivered_at`, increases the
    site's `received_meals_total` by the delivered quantity, promotes the site
    from `REGISTERED` to `ACTIVE` if it had not yet been served"

    Design: Corner/state_machines/distribution_site_side_effect_on_first_delivered_stop
    """
    incident, _, run, sites, stops = setup_delivering_run([(30, None)], loaded_meals=30)
    deliver_stop(stops[0]["id"], sites[0]["id"], 30)

    site_rows, _ = validate_paginated(
        api_client.list_incident_distribution_sites(incident["id"], LOGISTICS, {"limit": 50})
    )
    assert site_rows[0]["status"] == "ACTIVE"
    assert site_rows[0]["received_meals_total"] == 30
    assert get_stop(stops[0]["id"])["delivered_at"] is not None
    assert get_run(run["id"])["delivered_meals"] == 30


def test_stop_is_discoverable_from_both_sides_of_the_run_site_pairing(api):
    """PRD §3.7: "Stops are added to a planned run by a `LogisticsCoordinator`.
    Each stop carries a `distribution_run_id`, a `distribution_site_id`, a
    1-based `stop_sequence` that orders it inside the run, and a `planned_meals`
    figure of at least 0 for the handover."
    PRD §4: "List stops, filterable by run and by receiving site"

    Design: Corner/endpoints/distribution_stop_creation_links_run_and_site
    """
    incident, _, run, sites, stops = setup_loaded_run_with_stops(
        [(25, None)], loaded_meals=25
    )
    stop = stops[0]

    by_run, _ = validate_paginated(
        api_client.list_distribution_stops(LOGISTICS, {"distribution_run_id": run["id"]})
    )
    by_site, _ = validate_paginated(
        api_client.list_distribution_stops(LOGISTICS, {"distribution_site_id": sites[0]["id"]})
    )
    assert [row["id"] for row in by_run] == [stop["id"]]
    assert [row["id"] for row in by_site] == [stop["id"]]
    assert stop["status"] == "PENDING"
    assert stop["planned_meals"] == 25


def test_site_coordinator_cannot_confirm_handover_at_another_site(api):
    """PRD §2.1: "a `SiteCoordinator` may only confirm handover at a stop whose
    `distribution_site_id` equals its own `X-User-ID`."
    PRD §2.1: "A mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/site_coordinator_cannot_confirm_another_sites_stop
    """
    incident, _, run, sites, stops = setup_delivering_run([(30, None)], loaded_meals=30)
    other_site = create_distribution_site(
        incident["id"], site_name="Valley Hospital", site_type="HOSPITAL"
    )

    refused = api_client.transition_distribution_stop(
        stops[0]["id"],
        {"to_state": "DELIVERED", "delivered_meals": 30},
        make_site_coordinator_headers(other_site["id"]),
    )
    validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_stop(stops[0]["id"])["status"] == "PENDING"
