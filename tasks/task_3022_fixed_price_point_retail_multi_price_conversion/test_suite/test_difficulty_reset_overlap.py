"""Interval arithmetic on the aisle resource and on the store day."""

from test_helpers import (
    ANALYST_HEADERS,
    E,
    PLANNER_HEADERS,
    SOM_HEADERS,
    validate_error,
    validate_success,
    fixtures,
)



def _store_with_open_window(api, capacity=400.0):
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store(shelf_facing_capacity_sqft=capacity)
    window = fixtures.create_open_season_window(
        opens_on="2026-09-01T00:00:00Z", closes_on="2026-11-30T00:00:00Z")
    return price_point, store, window


def test_a_reset_that_starts_exactly_when_the_previous_one_ends_is_legal(api):
    """Adjacent intervals share an endpoint and must not be treated as a conflict.

    PRD §3.10: "Same-aisle conflict detection is half-open: the candidate interval must not
    overlap any non-terminal reset — that is, any reset currently in `PLANNED` or `EXECUTING` —
    on the same `aisle_code` of the same store, where two intervals conflict only when the
    existing reset starts strictly before the candidate's end and the candidate starts strictly
    before the existing reset's end."
    PRD §3.10: "Intervals that merely touch at an endpoint do not conflict and are permitted."
    PRD §3.10: "A same-aisle conflict is rejected with `ERR_AISLE_RESET_OVERLAP` and HTTP 409."

    Design: Difficulty/resource_temporal_overlap/half_open_same_aisle_overlap_leaves_adjacent_resets_legal
    """
    price_point, store, window = _store_with_open_window(api)

    first = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A14",
        starts_at="2026-09-05T00:00:00Z", ends_at="2026-09-20T00:00:00Z",
        allocated_shelf_sqft=50.0)
    assert first["status"] == "PLANNED"

    # The candidate begins on the very instant the first ends: adjacent, not overlapping.
    touching = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A14",
        starts_at="2026-09-20T00:00:00Z", ends_at="2026-09-25T00:00:00Z",
        allocated_shelf_sqft=50.0)
    assert touching["status"] == "PLANNED"

    overlapping = fixtures.plan_reset(
        store["id"], price_point["id"], window["id"], aisle_code="A14",
        starts_at="2026-09-19T00:00:00Z", ends_at="2026-09-24T00:00:00Z",
        allocated_shelf_sqft=50.0)
    validate_error(overlapping, E.ERR_AISLE_RESET_OVERLAP.value)

    resets = validate_success(api.list_store_aisle_resets(store["id"], ANALYST_HEADERS), 200)
    assert len(resets) == 2, "the touching reset persisted and the overlapping one did not"
    assert sum(row["allocated_shelf_sqft"] for row in resets) == 100.0, (
        "100.0 of the store's 400.0 is far under the day aggregate, so no capacity error fired"
    )


def test_touching_resets_share_a_store_day_and_one_abandonment_reopens_the_budget(api):
    """The closed aggregate counts touching intervals, and abandoning one frees its square feet.

    PRD §3.10: "The third rule is the store-day aggregate, and it uses the closed convention
    rather than the half-open one."
    PRD §3.10: "When a reset is planned, the system sums the `allocated_shelf_sqft` of every
    non-terminal reset on the same store whose interval overlaps the candidate under the closed
    reading — that is, where one interval's start is at or before the other's end and its end is
    at or after the other's start, so intervals sharing only an endpoint do share the day."
    PRD §3.10: "That sum must not exceed the store's `shelf_facing_capacity_sqft`; an
    over-commitment is rejected with `ERR_STORE_DAY_CAPACITY_EXCEEDED` and HTTP 422."
    PRD §3.10: "A reset may also be abandoned, which moves it to `ABANDONED` and is performed by
    a `StoreOperationsManager` rather than the planner"
    PRD §3.10: "abandonment is permitted only from `PLANNED` or from `EXECUTING`, and a reset that
    satisfies neither is rejected with `ERR_AISLE_RESET_NOT_PLANNED`."

    Design: Difficulty/resource_temporal_overlap/closed_store_day_capacity_aggregate_counts_touching_resets
    """
    price_point, store, window = _store_with_open_window(api, capacity=400.0)

    planned = []
    for aisle in ("A11", "A12", "A13"):
        planned.append(fixtures.plan_reset_ok(
            store["id"], price_point["id"], window["id"], aisle_code=aisle,
            starts_at="2026-09-02T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
            allocated_shelf_sqft=130.0))
    assert sum(row["allocated_shelf_sqft"] for row in planned) == 390.0

    # A fourth aisle on the same days pushes the closed aggregate to 520.0 against a 400.0 store.
    fourth = fixtures.plan_reset(
        store["id"], price_point["id"], window["id"], aisle_code="A14",
        starts_at="2026-09-02T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
        allocated_shelf_sqft=130.0)
    validate_error(fourth, E.ERR_STORE_DAY_CAPACITY_EXCEEDED.value)
    assert fourth.json()["data"]["error_id"] != E.ERR_AISLE_RESET_OVERLAP.value, (
        "A14 shares no aisle with the others, so only the aggregate could have failed"
    )

    abandoned = validate_success(
        api.abandon_aisle_reset(planned[2]["id"], SOM_HEADERS), 200)
    assert abandoned["status"] == "ABANDONED"

    # With one reset abandoned the day sum is back to 260.0, so the identical retry is accepted.
    retry = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A14",
        starts_at="2026-09-02T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
        allocated_shelf_sqft=130.0)
    assert retry["status"] == "PLANNED"

    resets = validate_success(api.list_store_aisle_resets(store["id"], ANALYST_HEADERS), 200)
    assert len(resets) == 4
    assert len([row for row in resets if row["status"] == "PLANNED"]) == 3

def test_two_resets_that_merely_touch_are_still_measured_against_the_store_day(api):
    """Intervals sharing only an endpoint both count toward the closed store-day aggregate.

    PRD §2.10: "The store-day aggregate, by contrast, uses the closed convention: a reset shares a
    day with another when its start is at or before the other's end and its end is at or after the
    other's start, so intervals that touch at an endpoint do share the day and their shelf square
    footage is summed together."
    PRD §3.10: "That sum must not exceed the store's `shelf_facing_capacity_sqft`; an
    over-commitment is rejected with `ERR_STORE_DAY_CAPACITY_EXCEEDED` and HTTP 422."
    PRD §3.10: "Intervals that merely touch at an endpoint do not conflict and are permitted."

    Design: Difficulty/resource_temporal_overlap/half_open_same_aisle_overlap_leaves_adjacent_resets_legal
    """
    price_point, store, window = _store_with_open_window(api, capacity=400.0)

    first = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A11",
        starts_at="2026-09-05T00:00:00Z", ends_at="2026-09-20T00:00:00Z",
        allocated_shelf_sqft=200.0)
    assert first["status"] == "PLANNED"

    # A different aisle, but its interval begins on the instant the first one ends.
    touching = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A12",
        starts_at="2026-09-20T00:00:00Z", ends_at="2026-09-25T00:00:00Z",
        allocated_shelf_sqft=200.0)
    assert touching["status"] == "PLANNED"

    # The same-aisle rule passes on A13, so only the closed aggregate can refuse this one.
    third = fixtures.plan_reset(
        store["id"], price_point["id"], window["id"], aisle_code="A13",
        starts_at="2026-09-20T00:00:00Z", ends_at="2026-09-22T00:00:00Z",
        allocated_shelf_sqft=10.0)
    validate_error(third, E.ERR_STORE_DAY_CAPACITY_EXCEEDED.value)
    assert third.json()["data"]["error_id"] != E.ERR_AISLE_RESET_OVERLAP.value

    resets = validate_success(api.list_store_aisle_resets(store["id"], ANALYST_HEADERS), 200)
    assert len(resets) == 2, "the refused request persisted nothing"
    assert sum(row["allocated_shelf_sqft"] for row in resets) == 400.0


def test_an_abandoned_executing_reset_no_longer_occupies_the_store_day(api):
    """Abandonment is legal from EXECUTING too, and it releases the square feet it held.

    PRD §3.10: "A reset may also be abandoned, which moves it to `ABANDONED` and is performed by
    a `StoreOperationsManager` rather than the planner"
    PRD §3.10: "abandonment is permitted only from `PLANNED` or from `EXECUTING`, and a reset that
    satisfies neither is rejected with `ERR_AISLE_RESET_NOT_PLANNED`."
    PRD §3.10: "That sum must not exceed the store's `shelf_facing_capacity_sqft`; an
    over-commitment is rejected with `ERR_STORE_DAY_CAPACITY_EXCEEDED` and HTTP 422."
    PRD §3.10: "When a reset is planned, the system sums the `allocated_shelf_sqft` of every
    non-terminal reset on the same store whose interval overlaps the candidate under the closed
    reading"

    Design: Difficulty/resource_temporal_overlap/closed_store_day_capacity_aggregate_counts_touching_resets
    """
    price_point, store, window = _store_with_open_window(api, capacity=400.0)

    first = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A11",
        starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
        allocated_shelf_sqft=250.0)
    second = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A12",
        starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
        allocated_shelf_sqft=130.0)
    assert first["status"] == "PLANNED" and second["status"] == "PLANNED"

    assert api.create_aisle_reset(
        fixtures.factories.create_aisle_reset_payload(
            store["id"], price_point["id"], window["id"], aisle_code="A13",
            starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
            allocated_shelf_sqft=30.0),
        PLANNER_HEADERS,
    ).status_code == 422

    # A reset in EXECUTING still occupies the day; abandoning it is what frees the square feet.
    # The reset starts on the clock's own instant, so the begin edge's clock check has been reached.
    validate_success(api.begin_aisle_reset(second["id"], PLANNER_HEADERS), 200)
    blocked = fixtures.plan_reset(
        store["id"], price_point["id"], window["id"], aisle_code="A13",
        starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
        allocated_shelf_sqft=30.0)
    validate_error(blocked, E.ERR_STORE_DAY_CAPACITY_EXCEEDED.value)

    abandoned = validate_success(api.abandon_aisle_reset(second["id"], SOM_HEADERS), 200)
    assert abandoned["status"] == "ABANDONED"

    accepted = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A13",
        starts_at="2026-09-01T00:00:00Z", ends_at="2026-09-08T00:00:00Z",
        allocated_shelf_sqft=30.0)
    assert accepted["status"] == "PLANNED", (
        "250.0 + 30.0 is back under the 400.0 ceiling once the abandoned reset stopped counting"
    )
