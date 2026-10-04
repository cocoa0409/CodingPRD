"""Collection routes: farm-state gates, capacity, date exclusivity, conservation."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_route_conservation,
    collect_stop,
    create_active_farm,
    create_farm,
    create_route,
    get_farm,
    get_route,
    set_clock,
    setup_route_with_stop,
    skip_stop,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS
from test_helpers import DOZENS_PER_CASE

PO = TEST_USERS["plant_operator_headers"]


def _two_active_farms():
    """Two ACTIVE farms; the second's audit completes at 10:00 so the logical
    clock stays monotonic across the two base chains."""
    farm_a = create_active_farm(name="Farm Alpha")["farm"]
    farm_b = create_active_farm(
        name="Farm Beta", audit_complete_at="2026-09-03T10:00:00Z"
    )["farm"]
    return farm_a, farm_b


def test_route_stop_rejected_while_farm_onboarding(api):
    """PRD §3.5: "The farm must be operationally `ACTIVE` — stops are never
    planned against `ONBOARDING`, `PROBATION`, or `SUSPENDED` farms, and a
    violation is `ERR_FARM_NOT_ACTIVE` (HTTP 409)"
    PRD §2.11: "With a well-formed body in hand, state legality is checked"

    Design: Difficulty/cross_entity_state_dependency/route_stop_gated_by_farm_operational_status
    """
    farm = create_farm(name="Newcomer Farm")
    route = create_route(route_date="2026-09-08", capacity_cases=4)

    resp = api.add_stop(
        route["id"],
        {"farm_id": farm["id"], "stop_sequence": 1, "planned_cases": 2},
        PO,
    )
    validate_error(resp, ApiErrorId.ERR_FARM_NOT_ACTIVE, 409)


def test_route_stop_accepted_once_farm_active(api):
    """PRD §3.5: "A successful add appends the stop in `SCHEDULED` status,
    recomputes the route's load per §2.9, and increments the route's `version`
    by one"

    Design: Difficulty/cross_entity_state_dependency/route_stop_gated_by_farm_operational_status
    """
    farm = create_active_farm(name="Newcomer Farm")["farm"]
    route = create_route(route_date="2026-09-08", capacity_cases=4)

    resp = api.add_stop(
        route["id"],
        {"farm_id": farm["id"], "stop_sequence": 1, "planned_cases": 2},
        PO,
    )
    updated = validate_success(resp, 201)
    stop = next(s for s in updated["stops"] if s["stop_sequence"] == 1)
    assert stop["status"] == "SCHEDULED"
    assert stop["farm_id"] == farm["id"]


def test_route_capacity_exact_equality_accepted(api):
    """PRD §3.5: "the stop's `planned_cases` must fit within the route's current
    `available_cases`, else `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422)"
    PRD §2.9: "the truck's `capacity_cases` always equals `committed_cases` plus
    `available_cases`"

    Design: Difficulty/boundary_precision_check/route_capacity_exact_equality_boundary
    """
    farm_a, _ = _two_active_farms()
    route = create_route(route_date="2026-09-08", capacity_cases=4)

    resp = api.add_stop(
        route["id"],
        {"farm_id": farm_a["id"], "stop_sequence": 1, "planned_cases": 4},
        PO,
    )
    updated = validate_success(resp, 201)
    assert updated["committed_cases"] == 4
    assert updated["available_cases"] == 0, "planned 4 on capacity 4 is the inclusive boundary"
    assert_route_conservation(updated)


def test_route_capacity_overage_rejected_without_partial_consumption(api):
    """PRD §3.5: "the stop's `planned_cases` must fit within the route's current
    `available_cases`, else `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422)"

    Design: Difficulty/boundary_precision_check/route_capacity_exact_equality_boundary
    """
    farm_a, farm_b = _two_active_farms()
    route = create_route(route_date="2026-09-08", capacity_cases=4)
    validate_success(
        api.add_stop(
            route["id"],
            {"farm_id": farm_a["id"], "stop_sequence": 1, "planned_cases": 4},
            PO,
        ),
        201,
    )

    resp = api.add_stop(
        route["id"],
        {"farm_id": farm_b["id"], "stop_sequence": 2, "planned_cases": 1},
        PO,
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED, 422)

    route = get_route(route["id"])
    assert route["committed_cases"] == 4
    assert route["available_cases"] == 0, "the rejected add consumes nothing"
    assert len(route["stops"]) == 1


def test_farm_route_date_conflict_same_date(api):
    """PRD §3.5: "A farm may occupy at most one stop per calendar day across the
    whole network: if the same farm already sits on a `SCHEDULED` or `COLLECTED`
    stop of another route sharing this `route_date`, the add is rejected with
    `ERR_STOP_DATE_CONFLICT` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/farm_route_date_exclusivity_point_semantics
    """
    farm = create_active_farm(name="Twin Route Farm")["farm"]
    r1 = setup_route_with_stop(farm["id"], route_date="2026-09-08", planned_cases=2,
                               capacity_cases=4)["route"]
    assert r1["stops"][0]["status"] == "SCHEDULED"
    r2 = create_route(route_date="2026-09-08", driver_name="Erin", capacity_cases=4)

    resp = api.add_stop(
        r2["id"], {"farm_id": farm["id"], "stop_sequence": 1, "planned_cases": 2}, PO
    )
    validate_error(resp, ApiErrorId.ERR_STOP_DATE_CONFLICT, 409)


def test_farm_route_date_free_on_next_date(api):
    """PRD §3.5: "A farm may occupy at most one stop per calendar day across the
    whole network: if the same farm already sits on a `SCHEDULED` or `COLLECTED`
    stop of another route sharing this `route_date`, the add is rejected with
    `ERR_STOP_DATE_CONFLICT` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/farm_route_date_exclusivity_point_semantics
    """
    farm = create_active_farm(name="Twin Route Farm")["farm"]
    setup_route_with_stop(farm["id"], route_date="2026-09-08", planned_cases=2,
                          capacity_cases=4)
    r3 = create_route(route_date="2026-09-09", driver_name="Erin", capacity_cases=4)

    resp = api.add_stop(
        r3["id"], {"farm_id": farm["id"], "stop_sequence": 1, "planned_cases": 2}, PO
    )
    updated = validate_success(resp, 201)
    assert updated["stops"][0]["status"] == "SCHEDULED", (
        "the exclusivity predicate is date equality — the next date is free"
    )


def test_route_conservation_adds_and_undercollection(api):
    """PRD §2.9: "the truck's `capacity_cases` always equals `committed_cases`
    plus `available_cases`"
    PRD §2.9: "recording a collection may consume more or fewer cases than
    planned, and the difference settles against `available_cases`"

    Design: Difficulty/compensating_invariant/route_case_conservation_add_collect_skip
    """
    farm_a, farm_b = _two_active_farms()
    route = create_route(route_date="2026-09-08", capacity_cases=10)
    validate_success(
        api.add_stop(route["id"], {"farm_id": farm_a["id"], "stop_sequence": 1,
                                   "planned_cases": 6}, PO), 201)
    updated = validate_success(
        api.add_stop(route["id"], {"farm_id": farm_b["id"], "stop_sequence": 2,
                                   "planned_cases": 4}, PO), 201)
    assert updated["committed_cases"] == 10
    assert updated["available_cases"] == 0
    assert_route_conservation(updated)

    set_clock("2026-09-08T10:00:00Z")
    collect_stop(route["id"], 1, 5)

    route = get_route(route["id"])
    assert route["committed_cases"] == 9, (
        f"5 collected + 4 still planned == 9, got {route['committed_cases']}"
    )
    assert route["available_cases"] == 1, "the 1-case under-collection frees capacity"
    assert_route_conservation(route)


def test_route_conservation_skip_restores_planned_cases(api):
    """PRD §2.9: "skipping a stop restores its full `planned_cases`"
    PRD §2.9: "the truck's `capacity_cases` always equals `committed_cases`
    plus `available_cases`"

    Design: Difficulty/compensating_invariant/route_case_conservation_add_collect_skip
    """
    farm_a, farm_b = _two_active_farms()
    route = create_route(route_date="2026-09-08", capacity_cases=10)
    validate_success(
        api.add_stop(route["id"], {"farm_id": farm_a["id"], "stop_sequence": 1,
                                   "planned_cases": 6}, PO), 201)
    validate_success(
        api.add_stop(route["id"], {"farm_id": farm_b["id"], "stop_sequence": 2,
                                   "planned_cases": 4}, PO), 201)

    set_clock("2026-09-08T10:00:00Z")
    collect_stop(route["id"], 1, 5)
    skip_stop(route["id"], 2)

    route = get_route(route["id"])
    assert route["committed_cases"] == 5, (
        f"only the 5 collected cases remain committed, got {route['committed_cases']}"
    )
    assert route["available_cases"] == 5, "the skip restores the full planned 4"
    assert_route_conservation(route)


def test_stop_skip_frees_farm_for_same_date_route(api):
    """PRD §3.5: "a stop that was `SKIPPED` does not block a re-plan"
    PRD §3.5: "skipping a `SCHEDULED` stop, with an optional `reason`, flips it
    to `SKIPPED`, restores its full `planned_cases` to the route's
    `available_cases`, recomputes the load, and increments the route's
    `version`."

    Design: Corner/state_machines/stop_skip_frees_farm_for_same_date_route
    """
    farm = create_active_farm(name="Reschedule Farm")["farm"]
    r1 = setup_route_with_stop(farm["id"], route_date="2026-09-08", planned_cases=2,
                               capacity_cases=4)["route"]
    skip_stop(r1["id"], 1)
    r2 = create_route(route_date="2026-09-08", driver_name="Erin", capacity_cases=4)

    resp = api.add_stop(
        r2["id"], {"farm_id": farm["id"], "stop_sequence": 1, "planned_cases": 3}, PO
    )
    validate_success(resp, 201)

    r1_after = get_route(r1["id"])
    assert r1_after["committed_cases"] == 0
    assert r1_after["available_cases"] == 4
    r2_after = get_route(r2["id"])
    assert r2_after["committed_cases"] == 3
    assert r2_after["available_cases"] == 1


def test_route_complete_with_open_stop_returns_422(api):
    """PRD §3.5: "Once every stop on a route is either `COLLECTED` or `SKIPPED`,
    the operator closes the run: completion moves the route `PLANNED →
    COMPLETED` and increments its `version`, while any stop still `SCHEDULED`
    blocks the close with `ERR_ROUTE_STOPS_OPEN` (HTTP 409)."

    Design: Corner/state_machines/route_complete_with_open_stop_returns_422
    """
    farm = create_active_farm(name="Open Stop Farm")["farm"]
    route = setup_route_with_stop(farm["id"], route_date="2026-09-08", planned_cases=2,
                                  capacity_cases=4)["route"]

    resp = api.complete_route(route["id"], PO)
    validate_error(resp, ApiErrorId.ERR_ROUTE_STOPS_OPEN, 409)

    reread = get_route(route["id"])
    assert reread["status"] == "PLANNED"


def test_collect_on_skipped_stop_returns_invalid_state(api):
    """PRD §3.5: "collecting a `SCHEDULED` stop (any other stop status is
    `ERR_INVALID_STATE`)"

    Design: Corner/state_machines/collect_on_skipped_stop_returns_invalid_state
    """
    farm = create_active_farm(name="Skip Collect Farm")["farm"]
    route = setup_route_with_stop(farm["id"], route_date="2026-09-08", planned_cases=2,
                                  capacity_cases=4)["route"]
    skip_stop(route["id"], 1)

    set_clock("2026-09-08T10:00:00Z")
    resp = api.collect_stop(
        route["id"], 1,
        {"collected_cases": 2, "laid_start_date": "2026-09-06",
         "laid_end_date": "2026-09-07"},
        PO,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    rows, meta = validate_paginated(
        api.list_lots(PO, params={"route_id": route["id"]})
    )
    assert meta["total_count"] == 0 and rows == [], (
        "the rejected collect creates no lot"
    )


def test_stop_sequence_conflict_on_same_route(api):
    """PRD §3.5: "The `stop_sequence` must not already exist on this route, else
    `ERR_STOP_SEQUENCE_CONFLICT` (HTTP 409)"

    Design: Corner/errors_remaining_triggers/stop_sequence_conflict_on_same_route
    """
    farm_a, farm_b = _two_active_farms()
    route = create_route(route_date="2026-09-08", capacity_cases=10)
    validate_success(
        api.add_stop(route["id"], {"farm_id": farm_a["id"], "stop_sequence": 1,
                                   "planned_cases": 2}, PO), 201)

    resp = api.add_stop(
        route["id"], {"farm_id": farm_b["id"], "stop_sequence": 1, "planned_cases": 2}, PO
    )
    validate_error(resp, ApiErrorId.ERR_STOP_SEQUENCE_CONFLICT, 409)

    reread = get_route(route["id"])
    assert len(reread["stops"]) == 1, "the conflicting add creates nothing"


def test_stop_add_on_lapsed_farm_returns_cert_not_current(api):
    """PRD §3.5: "its `certification_status` must be `CERTIFIED`, with
    `CERTIFICATION_PENDING`, `CERT_LAPSED`, or `DECERTIFIED` farms refused as
    `ERR_CERTIFICATION_NOT_CURRENT` (HTTP 422)"
    PRD §2.7: "if the current logical instant is strictly later than
    `last_passed_audit_at` plus 365 days, the certification has lapsed and the
    value is `CERT_LAPSED`"

    Design: Corner/validations/stop_add_on_lapsed_farm_returns_cert_not_current
    """
    farm = create_active_farm(
        name="Lapsed Farm", contract_overrides={"end_date": "2027-12-31"}
    )["farm"]
    route = create_route(route_date="2027-09-06", capacity_cases=4)

    # Last pass 2026-09-03T09:00:00Z + 365 days < 2027-09-04: certification lapses.
    set_clock("2027-09-04T00:00:00Z")
    farm_now = get_farm(farm["id"])
    assert farm_now["status"] == "ACTIVE"
    assert farm_now["certification_status"] == "CERT_LAPSED"

    resp = api.add_stop(
        route["id"], {"farm_id": farm["id"], "stop_sequence": 1, "planned_cases": 2}, PO
    )
    validate_error(resp, ApiErrorId.ERR_CERTIFICATION_NOT_CURRENT, 422)


def test_collect_creates_lot_with_thirty_dozens_per_case(api):
    """PRD §3.5: "Collection is the moment an egg lot is born: the server mints
    the next sequential human-facing `lot_code` (`LOT-000001`, `LOT-000002`, and
    so on), copies the `farm_id` from the stop and the `route_id` and
    `stop_sequence` of its origin, records `received_cases` equal to the
    `collected_cases`, and derives `received_dozens` as the collected cases
    multiplied by 30 dozen per case."
    PRD §3.5: "The lot enters `RECEIVED` with `quality_score` and `graded_at`
    null, `grade` `NONE`, `packed_dozens` and `destroyed_dozens` at zero, and
    `remaining_dozens` equal to `received_dozens`."

    Design: Corner/endpoints/collect_creates_lot_with_thirty_dozens_per_case
    """
    farm = create_active_farm(name="Collection Farm")["farm"]
    route = setup_route_with_stop(farm["id"], route_date="2026-09-08", planned_cases=4,
                                  capacity_cases=10)["route"]
    set_clock("2026-09-08T10:00:00Z")

    resp = api.collect_stop(
        route["id"], 1,
        {"collected_cases": 4, "laid_start_date": "2026-09-06",
         "laid_end_date": "2026-09-07"},
        PO,
    )
    lot = validate_success(resp, 201)
    assert lot["received_cases"] == 4
    assert lot["received_dozens"] == 4 * DOZENS_PER_CASE, "4 cases x 30 dozen per case"
    assert lot["remaining_dozens"] == 120
    assert lot["status"] == "RECEIVED"
    assert lot["farm_id"] == farm["id"]
    assert lot["route_id"] == route["id"]
    assert lot["stop_sequence"] == 1
