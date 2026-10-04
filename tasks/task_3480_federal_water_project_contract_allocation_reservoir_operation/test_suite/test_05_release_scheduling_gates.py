"""Release scheduling and execution gates.

Covers the environmental safety sub-order (minimum flow before maximum
release before the flood gate), the safety gate's priority over the temporal
past-schedule check, aggregate per-day outlet capacity at and beyond the
boundary, the execution-time ordering of the storage check before the window
check, the half-open execution window, the past-schedule rejection in
isolation, and the release-execution role restriction - PRD §2.1, §2.9 and
§3.5.
"""

from test_helpers import (
    ApiErrorId,
    HYDROLOGY_OFFICER_HEADERS,
    RECLAMATION_OPERATOR_HEADERS,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
)

OPERATOR = RECLAMATION_OPERATOR_HEADERS
READ = fixtures.READ_HEADERS


def test_env_min_flow_beats_past_schedule(api):
    """A release that violates an intersecting MIN_FLOW constraint AND is
    scheduled in the past returns ERR_ENV_MIN_FLOW_VIOLATION - safety (tier
    7) runs before temporal windows (tier 9).

    PRD §2.9: "7. **Environmental and regulatory safety** — evaluated in this
    exact sub-order: (a) minimum-flow adequacy (`ERR_ENV_MIN_FLOW_VIOLATION`),
    then (b) maximum-release ceilings (`ERR_MAX_RELEASE_EXCEEDED`), then (c)
    the flood-control gate (`ERR_FLOOD_CONTROL_REQUIRED`), then (d)
    pulse-window overlap on constraint registration
    (`ERR_PULSE_WINDOW_OVERLAP`)."
    PRD §2.9: "9. **Temporal windows** — scheduling into the past
    (`ERR_SCHEDULE_IN_PAST`), execution outside the release window
    (`ERR_RELEASE_WINDOW_INVALID`), execution before the objection window
    closes (`ERR_OBJECTION_WINDOW_OPEN`), and filing a review after the
    objection window closes (`ERR_OBJECTION_WINDOW_CLOSED`)."

    Design: Difficulty/priority_pair_validation_conflict/env_min_flow_beats_past_schedule
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    fixtures.create_constraint(
        api, reservoir_id, factories.min_flow_constraint_payload(500)
    )
    fixtures.set_clock(api, "2027-01-15T00:00:00Z")

    response = api.create_release_order(
        reservoir_id,
        factories.release_order_payload(
            purpose="POWER", release_cfs=400, duration_days=5,
            scheduled_start="2027-01-10T00:00:00Z",
        ),
        OPERATOR,
    )
    error = validate_error(response, ApiErrorId.ERR_ENV_MIN_FLOW_VIOLATION)
    assert response.status_code == 422
    assert error["error_id"] != "ERR_SCHEDULE_IN_PAST", (
        "the safety violation masks the temporal one"
    )

    releases, meta = validate_paginated(api.list_release_orders(reservoir_id, READ))
    assert meta["total_count"] == 0 and releases == []


def test_outlet_capacity_aggregate_day(api):
    """Aggregate per-day capacity: two releases summing to exactly
    outlet_capacity_cfs on a shared day are accepted; one more cfs is
    rejected - the comparison is strict greater-than.

    PRD §3.5: "for every calendar day touched by the new order's window, the
    day's existing load — the summed `release_cfs` of the reservoir's
    `SCHEDULED` and `EXECUTED` release orders whose own windows touch that
    day — plus the new `release_cfs` must not exceed `outlet_capacity_cfs`;
    exceeding it yields `ERR_OUTLET_CAPACITY_EXCEEDED`, while exactly
    reaching capacity is allowed."

    Design: Difficulty/resource_temporal_overlap/outlet_capacity_aggregate_day
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    fixtures.set_clock(api, "2027-01-15T00:00:00Z")

    fixtures.create_release(
        api, reservoir_id, purpose="DELIVERY", release_cfs=10_000,
        duration_days=10, scheduled_start="2027-02-01T00:00:00Z",
    )
    at_capacity = fixtures.create_release(
        api, reservoir_id, purpose="ENVIRONMENTAL", release_cfs=5_000,
        duration_days=2, scheduled_start="2027-02-02T00:00:00Z",
    )
    assert at_capacity["status"] == "SCHEDULED", "day load 15,000 == capacity is allowed"

    validate_error(
        api.create_release_order(
            reservoir_id,
            factories.release_order_payload(
                purpose="POWER", release_cfs=1, duration_days=1,
                scheduled_start="2027-02-02T00:00:00Z",
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_OUTLET_CAPACITY_EXCEEDED,
    )

    releases, meta = validate_paginated(api.list_release_orders(reservoir_id, READ, {"limit": 100}))
    assert meta["total_count"] == 2 and len(releases) == 2


def test_min_and_max_both_violated_returns_min_flow_first(api):
    """With MIN_FLOW 500 and MAX_RELEASE 300 both covering the window, a
    400 cfs release violates both and must report ERR_ENV_MIN_FLOW_VIOLATION.

    PRD §3.5: "First, minimum flow: a `release_cfs` below the
    `required_min_cfs` of any `MIN_FLOW` or `PULSE_FLOW` constraint whose
    window intersects the release window is rejected with
    `ERR_ENV_MIN_FLOW_VIOLATION`. Second, maximum release: a `release_cfs`
    above the `max_release_cfs` of any intersecting `MAX_RELEASE` constraint
    is rejected with `ERR_MAX_RELEASE_EXCEEDED`."

    Design: Corner/validations/min_and_max_both_violated_returns_min_flow_first
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    fixtures.create_constraint(api, reservoir_id, factories.min_flow_constraint_payload(500))
    fixtures.create_constraint(api, reservoir_id, factories.max_release_constraint_payload(300))

    response = api.create_release_order(
        reservoir_id,
        factories.release_order_payload(
            purpose="POWER", release_cfs=400, duration_days=5,
            scheduled_start="2027-02-01T00:00:00Z",
        ),
        OPERATOR,
    )
    error = validate_error(response, ApiErrorId.ERR_ENV_MIN_FLOW_VIOLATION)
    assert response.status_code == 422
    assert error["error_id"] != "ERR_MAX_RELEASE_EXCEEDED", "minimum flow is checked first"


def test_max_release_violation_alone_returns_max_release_exceeded(api):
    """With only a MAX_RELEASE 300 constraint in force, a 400 cfs release is
    rejected 422 ERR_MAX_RELEASE_EXCEEDED.

    PRD §3.5: "Second, maximum release: a `release_cfs` above the
    `max_release_cfs` of any intersecting `MAX_RELEASE` constraint is
    rejected with `ERR_MAX_RELEASE_EXCEEDED`."

    Design: Corner/validations/max_release_violation_alone_returns_max_release_exceeded
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    fixtures.create_constraint(api, reservoir_id, factories.max_release_constraint_payload(300))

    validate_error(
        api.create_release_order(
            reservoir_id,
            factories.release_order_payload(
                purpose="POWER", release_cfs=400, duration_days=5,
                scheduled_start="2027-02-01T00:00:00Z",
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_MAX_RELEASE_EXCEEDED,
    )

    releases, meta = validate_paginated(api.list_release_orders(reservoir_id, READ))
    assert meta["total_count"] == 0 and releases == []


def test_flood_gate_blocks_non_flood_release_and_allows_flood_release(api):
    """In a flood month with storage above flood_control_max_storage_af, a
    POWER release is rejected 422 ERR_FLOOD_CONTROL_REQUIRED while a
    FLOOD_CONTROL release for the same window is accepted.

    PRD §3.5: "Third, flood control: when the logical-clock month at creation
    is one of the flood-control months and `current_storage_af` exceeds
    `flood_control_max_storage_af`, any `purpose` other than `FLOOD_CONTROL`
    is rejected with `ERR_FLOOD_CONTROL_REQUIRED`."

    Design: Corner/validations/flood_gate_blocks_non_flood_release_and_allows_flood_release
    """
    # The flood profile starts with storage 4,000,000 above the flood maximum
    # of 3,600,000, so the gate engages whenever the clock is in a flood month.
    world = fixtures.setup_project(api, reservoir_profile="flood", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    fixtures.set_clock(api, "2027-01-15T00:00:00Z")

    validate_error(
        api.create_release_order(
            reservoir_id,
            factories.release_order_payload(
                purpose="POWER", release_cfs=100, duration_days=2,
                scheduled_start="2027-02-01T00:00:00Z",
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_FLOOD_CONTROL_REQUIRED,
    )

    flood_release = fixtures.create_release(
        api, reservoir_id, purpose="FLOOD_CONTROL", release_cfs=100,
        duration_days=2, scheduled_start="2027-02-01T00:00:00Z",
    )
    assert flood_release["status"] == "SCHEDULED"


def test_execute_with_insufficient_storage_checked_before_window(api):
    """The storage check runs before the window check: a 19,835 af release
    against 10,500 af of storage fails 422 ERR_INSUFFICIENT_STORAGE both
    outside and inside its window, and nothing is debited.

    PRD §3.5: "The storage check runs before the window check: if the
    reservoir's `current_storage_af` is below the order's `volume_af`,
    execution fails with `ERR_INSUFFICIENT_STORAGE`; only then is the logical
    clock required to fall inside the half-open window from `scheduled_start`
    to `scheduled_end`, failing with `ERR_RELEASE_WINDOW_INVALID` when it
    does not."

    Design: Corner/validations/execute_with_insufficient_storage_checked_before_window
    """
    world = fixtures.setup_project(api, reservoir_profile="small", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    # round_half_up(1,000 * 10 * 1.9835) = 19,835 af > 10,500 af storage.
    release = fixtures.create_release(
        api, reservoir_id, purpose="DELIVERY", release_cfs=1_000,
        duration_days=10, scheduled_start="2027-02-01T00:00:00Z",
    )

    fixtures.set_clock(api, "2027-01-31T23:59:59Z")  # one second before the window
    early = api.execute_release_order(release["id"], OPERATOR)
    early_error = validate_error(early, ApiErrorId.ERR_INSUFFICIENT_STORAGE)
    assert early.status_code == 422
    assert early_error["error_id"] != "ERR_RELEASE_WINDOW_INVALID", (
        "storage is evaluated before the window"
    )

    fixtures.set_clock(api, "2027-02-03T00:00:00Z")  # inside [Feb 1, Feb 11)
    validate_error(
        api.execute_release_order(release["id"], OPERATOR),
        ApiErrorId.ERR_INSUFFICIENT_STORAGE,
    )

    after = fixtures.find_release(api, reservoir_id, release["id"])
    assert after["status"] == "SCHEDULED"
    reservoir = fixtures.get_reservoir(api, reservoir_id)
    assert reservoir["current_storage_af"] == 10_500, "a rejected execution debits nothing"


def test_schedule_in_past_alone_returns_scheduled_in_past(api):
    """With no safety issue in play, a release whose scheduled_start precedes
    the logical clock fails 422 ERR_SCHEDULE_IN_PAST.

    PRD §3.5: "a `scheduled_start` that must not precede the current logical
    clock — scheduling into the past fails with `ERR_SCHEDULE_IN_PAST`."

    Design: Corner/validations/schedule_in_past_alone_returns_scheduled_in_past
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    fixtures.set_clock(api, "2027-01-15T00:00:00Z")

    validate_error(
        api.create_release_order(
            reservoir_id,
            factories.release_order_payload(
                purpose="DELIVERY", release_cfs=600, duration_days=2,
                scheduled_start="2027-01-10T00:00:00Z",
            ),
            OPERATOR,
        ),
        ApiErrorId.ERR_SCHEDULE_IN_PAST,
    )

    releases, meta = validate_paginated(api.list_release_orders(reservoir_id, READ))
    assert meta["total_count"] == 0 and releases == []


def test_release_execute_outside_window_and_at_bounds(api):
    """The execution window is half-open [scheduled_start, scheduled_end):
    one second before the start and exactly at the end both fail 422
    ERR_RELEASE_WINDOW_INVALID; an instant inside succeeds.

    PRD §3.5: "only then is the logical clock required to fall inside the
    half-open window from `scheduled_start` to `scheduled_end`, failing with
    `ERR_RELEASE_WINDOW_INVALID` when it does not."

    Design: Corner/state_machines/release_execute_outside_window_and_at_bounds
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    release = fixtures.create_release(
        api, reservoir_id, purpose="DELIVERY", release_cfs=100,
        duration_days=2, scheduled_start="2027-02-01T00:00:00Z",
    )  # window [2027-02-01T00:00:00Z, 2027-02-03T00:00:00Z)

    fixtures.set_clock(api, "2027-01-31T23:59:59Z")
    validate_error(
        api.execute_release_order(release["id"], OPERATOR),
        ApiErrorId.ERR_RELEASE_WINDOW_INVALID,
    )

    fixtures.set_clock(api, "2027-02-03T00:00:00Z")  # exactly scheduled_end: exclusive
    validate_error(
        api.execute_release_order(release["id"], OPERATOR),
        ApiErrorId.ERR_RELEASE_WINDOW_INVALID,
    )

    fixtures.set_clock(api, "2027-02-01T12:00:00Z")
    executed = fixtures.execute_release(api, release["id"])
    assert executed["status"] == "EXECUTED"


def test_hydrology_officer_cannot_execute_release_returns_forbidden(api):
    """Release execution is exclusive to ReclamationOperator; the
    HydrologyOfficer is rejected 403 ERR_FORBIDDEN and the order stays
    SCHEDULED.

    PRD §2.1: "A request whose role is authenticated but not listed among the
    roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."
    PRD §2.1: "`HydrologyOfficer` (the hydrology data steward who posts
    snowpack, runoff-forecast, and measured-inflow observations)"

    Design: Corner/rbac/hydrology_officer_cannot_execute_release_returns_forbidden
    """
    world = fixtures.setup_project(api, reservoir_profile="big", contract_plan=None)
    reservoir_id = world["reservoir"]["id"]
    release = fixtures.create_release(
        api, reservoir_id, purpose="POWER", release_cfs=1_000,
        duration_days=10, scheduled_start="2027-02-01T00:00:00Z",
    )
    fixtures.set_clock(api, "2027-02-03T00:00:00Z")

    validate_error(
        api.execute_release_order(release["id"], HYDROLOGY_OFFICER_HEADERS),
        ApiErrorId.ERR_FORBIDDEN,
    )

    after = fixtures.find_release(api, reservoir_id, release["id"])
    assert after["status"] == "SCHEDULED"
