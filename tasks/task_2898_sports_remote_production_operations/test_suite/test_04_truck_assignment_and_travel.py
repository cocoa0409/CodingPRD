"""Truck assignment: the asymmetric travel-occupation window, the rating and
ingest gates, the engine-hour service cycle and the assignment's OCC token."""

from test_helpers import (
    assert_instant_equals,
    assert_production,
    assert_status,
    assert_truck,
    validate_error,
    validate_success,
)
from test_helpers.factories import truck_assignment_payload
from test_helpers.fixtures import (
    assign_truck,
    create_approved_survey,
    new_crew_member,
    new_production,
    new_truck,
    offer_call,
    production_version,
    read_production,
    read_show,
    read_truck,
    setup_wrapped_production,
)

#: A five-position plot of 100 ft runs at 20 A each: 1.35 dB per position,
#: 6.75 dB in total and 100 A drawn.
FIVE_POSITION_PLOT = [
    {"label": "CAM_1", "position_type": "HARD", "cable_run_feet": 100,
     "power_draw_amps": 20},
    {"label": "CAM_2", "position_type": "HARD", "cable_run_feet": 100,
     "power_draw_amps": 20},
    {"label": "CAM_3", "position_type": "ROBO", "cable_run_feet": 100,
     "power_draw_amps": 20},
    {"label": "CAM_4", "position_type": "ROBO", "cable_run_feet": 100,
     "power_draw_amps": 20},
    {"label": "CAM_5", "position_type": "AERIAL", "cable_run_feet": 100,
     "power_draw_amps": 20},
]


# ---------------------------------------------------------------------------
# The asymmetric truck occupation window
# ---------------------------------------------------------------------------
def test_truck_travel_window_conflict_when_the_next_remote_lands_in_the_tail(api, pm_headers):
    """A remote starting one hour inside another remote's 12-hour tear-down tail
    cannot take the same truck.

    PRD: "A production occupies its truck from **24 hours before** its `scheduled_start_utc` until **12 hours after** its `scheduled_end_utc`, with the window inclusive of its start instant and exclusive of its end instant."
    PRD: "The assignment is refused with `ERR_TRUCK_TRAVEL_WINDOW_CONFLICT` when the requesting production's occupation window overlaps the occupation window of any *other* production that already holds this truck and whose stage is `PLANNED`, `SURVEYED`, `PROVISIONED`, `REHEARSED` or `ON_AIR`."
    Design: Difficulty/resource_temporal_overlap/truck_travel_occupation_window_asymmetric_buffers
    """
    truck = new_truck(
        api, engine_hours_since_service=100, service_interval_hours=500
    )
    # Production A airs 2026-08-15T18:00Z..22:00Z, so it occupies the truck over
    # [2026-08-14T18:00Z, 2026-08-16T10:00Z).
    production_a = new_production(api)
    assign_truck(api, production_a["id"], truck["id"])

    # Production B occupies [2026-08-16T09:00Z, 2026-08-18T01:00Z): one hour into
    # A's tail.
    production_b = new_production(
        api,
        venue_name="Harbour Dome",
        venue_roof_type="DOMED",
        scheduled_start_utc="2026-08-17T09:00:00Z",
        scheduled_end_utc="2026-08-17T13:00:00Z",
        venue_curfew_utc="2026-08-17T20:00:00Z",
    )
    version_before = production_version(api, production_b["id"])

    refusal = api.assign_truck(
        production_b["id"],
        truck_assignment_payload(truck["id"], version_before),
        pm_headers,
    )
    validate_error(refusal, "ERR_TRUCK_TRAVEL_WINDOW_CONFLICT")

    untouched = read_production(api, production_b["id"])
    assert_production(untouched)
    assert untouched["truck_id"] is None, (
        "a refused assignment must not set truck_id"
    )
    assert untouched["version"] == version_before, (
        "a refused assignment must not advance the production version"
    )


def test_truck_occupation_starting_exactly_at_another_windows_end_is_accepted(api, pm_headers):
    """A remote whose occupation begins exactly when another remote's occupation
    ends may take the same truck, and the unit is then held by both.

    PRD: "A production occupies its truck from **24 hours before** its `scheduled_start_utc` until **12 hours after** its `scheduled_end_utc`, with the window inclusive of its start instant and exclusive of its end instant."
    PRD: "Because both windows are half-open, an occupation that begins exactly when another ends is accepted, and a `WRAPPED` or `SETTLED` production releases its claim on the truck entirely and never blocks a new assignment."
    PRD: "That an already-`ASSIGNED` truck is accepted is deliberate: a unit booked for tonight's game legitimately gets booked for the next event of the same road trip, so the truck stays `ASSIGNED` and is simply held by one more remote."
    Design: Difficulty/resource_temporal_overlap/truck_travel_occupation_window_asymmetric_buffers
    """
    truck = new_truck(
        api, engine_hours_since_service=100, service_interval_hours=500
    )
    production_a = new_production(api)
    assign_truck(api, production_a["id"], truck["id"])

    # Production C occupies [2026-08-16T10:00Z, 2026-08-18T02:00Z): its start
    # instant is exactly A's exclusive end instant.
    production_c = new_production(
        api,
        venue_name="Northgate Field",
        venue_roof_type="RETRACTABLE",
        scheduled_start_utc="2026-08-17T10:00:00Z",
        scheduled_end_utc="2026-08-17T14:00:00Z",
        venue_curfew_utc="2026-08-17T22:00:00Z",
    )
    version_before = production_version(api, production_c["id"])

    assigned = validate_success(
        api.assign_truck(
            production_c["id"],
            truck_assignment_payload(truck["id"], version_before),
            pm_headers,
        ),
        200,
    )
    assert_production(assigned)
    assert assigned["truck_id"] == truck["id"]

    held = read_truck(api, truck["id"])
    assert_truck(held)
    assert_status(held, "ASSIGNED")
    assert held["engine_hours_since_service"] == 100, (
        "an assignment never touches the engine-hour ledger"
    )
    assert held["hours_to_service"] == 400


def test_truck_occupation_ending_exactly_at_another_windows_start_is_accepted(api, pm_headers):
    """The 12-hour tear-down leg on the earlier remote is shorter than the
    24-hour travel-in leg, so a remote that wrapped 12 hours before another
    remote's travel-in begins does not collide with it.

    PRD: "A production occupies its truck from **24 hours before** its `scheduled_start_utc` until **12 hours after** its `scheduled_end_utc`, with the window inclusive of its start instant and exclusive of its end instant."
    PRD: "Because both windows are half-open, an occupation that begins exactly when another ends is accepted, and a `WRAPPED` or `SETTLED` production releases its claim on the truck entirely and never blocks a new assignment."
    Design: Difficulty/resource_temporal_overlap/truck_travel_occupation_window_asymmetric_buffers
    """
    truck = new_truck(
        api, engine_hours_since_service=100, service_interval_hours=500
    )
    production_a = new_production(api)
    assign_truck(api, production_a["id"], truck["id"])

    # Production D airs 2026-08-14T02:00Z..06:00Z, so it occupies
    # [2026-08-13T02:00Z, 2026-08-14T18:00Z) - its exclusive end instant is
    # exactly A's inclusive start instant.
    production_d = new_production(
        api,
        venue_name="Lakeside Field",
        venue_roof_type="DOMED",
        scheduled_start_utc="2026-08-14T02:00:00Z",
        scheduled_end_utc="2026-08-14T06:00:00Z",
        venue_curfew_utc="2026-08-14T12:00:00Z",
    )
    version_before = production_version(api, production_d["id"])

    assigned = validate_success(
        api.assign_truck(
            production_d["id"],
            truck_assignment_payload(truck["id"], version_before),
            pm_headers,
        ),
        200,
    )
    assert assigned["truck_id"] == truck["id"]
    assert_status(read_truck(api, truck["id"]), "ASSIGNED")


# ---------------------------------------------------------------------------
# The engine-hour service cycle
# ---------------------------------------------------------------------------
def test_truck_service_cycle_runs_from_wrap_through_arrive_to_service_complete(api, pm_headers):
    """A unit at 485 engine hours accrues 15 hours on the wrap, arrives at exactly
    its 500-hour interval and therefore goes into the shop, and the service
    close-out rebaselines the whole ledger.

    PRD: "The assigned unit moves `ASSIGNED → IN_TRANSIT`, and engine hours accrue for the event: a fixed **8 hours** of travel per event, a fixed **4 hours** of setup and tear-down, and the show's own air time converted from `air_minutes_total` into hours **rounded up** to the next whole hour — which contributes zero when the show never went on air."
    PRD: "Recording the unit's arrival at its next base requires it to be `IN_TRANSIT`, or `ERR_TRUCK_STATE_INVALID`, and the engine-hour threshold then decides where it lands, with **at-or-above** semantics: when `engine_hours_since_service` has reached `service_interval_hours` the unit goes `IN_TRANSIT → IN_MAINTENANCE` and is excluded from any further assignment until its service is closed out, and when `engine_hours_since_service` is still strictly below `service_interval_hours` it goes `IN_TRANSIT → AVAILABLE` and is immediately eligible for the next remote."
    PRD: "Closing out a maintenance cycle requires the unit to be `IN_MAINTENANCE`, or `ERR_TRUCK_STATE_INVALID`; it moves the unit `IN_MAINTENANCE → AVAILABLE`, resets `engine_hours_since_service` to 0, resets `hours_to_service` to the full `service_interval_hours`, and stamps `last_service_completed_at` with the logical clock."
    Design: Corner/state_machines/truck_maintenance_cycle_triggered_at_service_interval
    """
    truck = new_truck(
        api, engine_hours_since_service=485, service_interval_hours=500
    )
    # The remote goes on air at 18:00Z and off air at 21:00Z: 180 air minutes,
    # which is 3 whole hours, so the wrap accrues 8 + 4 + 3 = 15 hours.
    ctx = setup_wrapped_production(api, truck=truck)

    show = read_show(api, ctx["show"]["id"])
    assert show["air_minutes_total"] == 180
    assert_status(ctx["production"], "WRAPPED")

    after_wrap = read_truck(api, truck["id"])
    assert_truck(after_wrap)
    assert_status(after_wrap, "IN_TRANSIT")
    assert after_wrap["engine_hours_since_service"] == 500, (
        "485 + 8 travel + 4 setup and tear-down + ceil(180/60) air hours == 500"
    )
    assert after_wrap["hours_to_service"] == 0

    arrived = validate_success(api.truck_arrive(truck["id"], pm_headers), 200)
    assert_truck(arrived)
    assert_status(arrived, "IN_MAINTENANCE")
    assert arrived["engine_hours_since_service"] == 500, (
        "arrive reads the counter; it never advances it"
    )
    assert arrived["hours_to_service"] == 0

    serviced = validate_success(
        api.truck_service_complete(truck["id"], pm_headers), 200
    )
    assert_truck(serviced)
    assert_status(serviced, "AVAILABLE")
    assert serviced["engine_hours_since_service"] == 0
    assert serviced["hours_to_service"] == 500
    assert_instant_equals(
        serviced["last_service_completed_at"],
        "2026-08-15T21:00:00Z",
        "last_service_completed_at",
    )


def test_arrive_and_service_complete_are_refused_on_an_available_truck(api, pm_headers):
    """Neither the return leg nor the service close-out is declared out of
    `AVAILABLE`, and a refused attempt leaves the engine-hour ledger untouched.

    PRD: "Recording the unit's arrival at its next base requires it to be `IN_TRANSIT`, or `ERR_TRUCK_STATE_INVALID`, and the engine-hour threshold then decides where it lands, with **at-or-above** semantics: when `engine_hours_since_service` has reached `service_interval_hours` the unit goes `IN_TRANSIT → IN_MAINTENANCE` and is excluded from any further assignment until its service is closed out, and when `engine_hours_since_service` is still strictly below `service_interval_hours` it goes `IN_TRANSIT → AVAILABLE` and is immediately eligible for the next remote."
    PRD: "Closing out a maintenance cycle requires the unit to be `IN_MAINTENANCE`, or `ERR_TRUCK_STATE_INVALID`; it moves the unit `IN_MAINTENANCE → AVAILABLE`, resets `engine_hours_since_service` to 0, resets `hours_to_service` to the full `service_interval_hours`, and stamps `last_service_completed_at` with the logical clock."
    PRD: "`last_service_completed_at` starts null and stays null until the first service is closed out."
    Design: Corner/state_machines/truck_arrive_from_available_rejected_as_undeclared_transition
    """
    truck = new_truck(
        api,
        truck_code="TRK-07",
        tier_rating="TIER_2",
        camera_channel_capacity=8,
        power_draw_amps=90,
        home_base_code="DEN",
        engine_hours_since_service=100,
        service_interval_hours=500,
    )

    validate_error(api.truck_arrive(truck["id"], pm_headers), "ERR_TRUCK_STATE_INVALID")
    validate_error(
        api.truck_service_complete(truck["id"], pm_headers), "ERR_TRUCK_STATE_INVALID"
    )

    unchanged = read_truck(api, truck["id"])
    assert_truck(unchanged)
    assert_status(unchanged, "AVAILABLE")
    assert unchanged["engine_hours_since_service"] == 100
    assert unchanged["hours_to_service"] == 400
    assert unchanged["last_service_completed_at"] is None


# ---------------------------------------------------------------------------
# The rating and ingest gates
# ---------------------------------------------------------------------------
def test_tier_three_truck_is_refused_on_a_tier_one_event(api, pm_headers):
    """`TIER_3` ranks behind `TIER_1`, so the third-tier unit does not cover a
    first-tier event and the assignment is refused outright.

    PRD: "Read as an ordering where `TIER_1` ranks first, `TIER_2` second and `TIER_3` third, the rule is that the truck's rank must be at or ahead of the production's tier rank."
    PRD: "A truck whose rating does not cover the event is refused with `ERR_TRUCK_TIER_INSUFFICIENT`."
    Design: Corner/validations/truck_tier_rating_must_cover_the_event_tier
    """
    production = new_production(
        api,
        event_tier="TIER_1",
        venue_name="Grand Coliseum",
        venue_power_capacity_amps=1200,
        labor_budget_total_cents=9_000_000,
    )
    truck = new_truck(api, truck_code="TRK-03", tier_rating="TIER_3")
    version_before = production_version(api, production["id"])

    refusal = api.assign_truck(
        production["id"],
        truck_assignment_payload(truck["id"], version_before),
        pm_headers,
    )
    validate_error(refusal, "ERR_TRUCK_TIER_INSUFFICIENT")

    untouched = read_production(api, production["id"])
    assert untouched["truck_id"] is None
    assert untouched["version"] == version_before
    assert_status(read_truck(api, truck["id"]), "AVAILABLE")


def test_tier_one_truck_covers_a_tier_three_event(api, pm_headers):
    """The covering relation is an ordering and not an equality, so the
    first-tier unit is accepted on a third-tier event.

    PRD: "Tier ratings are a covering relation, not an equality."
    PRD: "A `TIER_1`-rated truck covers events at every tier; a `TIER_2`-rated truck covers `TIER_2` and `TIER_3` events; a `TIER_3`-rated truck covers only `TIER_3` events."
    Design: Corner/validations/truck_tier_rating_must_cover_the_event_tier
    """
    production = new_production(api)
    assert production["event_tier"] == "TIER_3"
    truck = new_truck(
        api,
        truck_code="TRK-01",
        tier_rating="TIER_1",
        camera_channel_capacity=24,
        power_draw_amps=200,
        home_base_code="ATL",
    )

    assigned = assign_truck(api, production["id"], truck["id"])
    assert_production(assigned)
    assert assigned["truck_id"] == truck["id"]
    assert_status(read_truck(api, truck["id"]), "ASSIGNED")


def test_five_position_plot_is_refused_by_a_four_channel_truck(api, pm_headers):
    """The ingest gate compares the approved plot's position count with the
    truck's channel capacity, and five positions overflow four channels.

    PRD: "The second is ingest: the approved survey's `camera_position_count` must be no greater than the truck's `camera_channel_capacity`, again with equality accepted; exceeding it is `ERR_TRUCK_CHANNEL_CAPACITY_EXCEEDED`."
    PRD: "`signal_loss_db` is the cable loss on that run: the coax budget is **1.35 dB per 100 feet**, so the position's loss is its cable run in feet multiplied by 1.35, divided by 100, and rounded half up to two decimal places."
    Design: Corner/validations/approved_plot_must_fit_the_trucks_camera_channels
    """
    production = new_production(api)
    survey = create_approved_survey(api, production["id"], FIVE_POSITION_PLOT)
    assert survey["camera_position_count"] == 5
    assert survey["total_signal_loss_db"] == 6.75, (
        "five 100 ft runs at 1.35 dB per 100 feet each"
    )
    assert survey["total_power_draw_amps"] == 100

    truck = new_truck(api, truck_code="TRK-04", camera_channel_capacity=4)
    version_before = production_version(api, production["id"])

    refusal = api.assign_truck(
        production["id"],
        truck_assignment_payload(truck["id"], version_before),
        pm_headers,
    )
    validate_error(refusal, "ERR_TRUCK_CHANNEL_CAPACITY_EXCEEDED")

    assert_status(read_truck(api, truck["id"]), "AVAILABLE")
    assert read_production(api, production["id"])["truck_id"] is None


def test_five_position_plot_exactly_fills_a_five_channel_truck(api, pm_headers):
    """Equality is accepted on the ingest gate, and the refusal that preceded it
    never consumed the production's version token.

    PRD: "The second is ingest: the approved survey's `camera_position_count` must be no greater than the truck's `camera_channel_capacity`, again with equality accepted; exceeding it is `ERR_TRUCK_CHANNEL_CAPACITY_EXCEEDED`."
    PRD: "Two of the assignment gates depend on survey evidence and are evaluated **only when the production already has an `APPROVED` survey**; when no approved survey exists yet, both are skipped and a truck may be assigned to a bare production."
    Design: Corner/validations/approved_plot_must_fit_the_trucks_camera_channels
    """
    production = new_production(api)
    survey = create_approved_survey(api, production["id"], FIVE_POSITION_PLOT)
    assert survey["camera_position_count"] == 5

    narrow = new_truck(api, truck_code="TRK-04", camera_channel_capacity=4)
    exact = new_truck(api, truck_code="TRK-05", camera_channel_capacity=5)
    version_before = production_version(api, production["id"])

    validate_error(
        api.assign_truck(
            production["id"],
            truck_assignment_payload(narrow["id"], version_before),
            pm_headers,
        ),
        "ERR_TRUCK_CHANNEL_CAPACITY_EXCEEDED",
    )

    assigned = validate_success(
        api.assign_truck(
            production["id"],
            truck_assignment_payload(exact["id"], version_before),
            pm_headers,
        ),
        200,
    )
    assert assigned["truck_id"] == exact["id"], (
        "the refused attempt must not have consumed the version token"
    )
    assert_status(read_truck(api, exact["id"]), "ASSIGNED")
    assert_status(read_truck(api, narrow["id"]), "AVAILABLE")


# ---------------------------------------------------------------------------
# The assignment's optimistic-concurrency token
# ---------------------------------------------------------------------------
def test_reassignment_replaying_a_superseded_version_is_refused_then_succeeds(api, pm_headers):
    """A crew-call offer moves the production forward, so a reassignment holding
    the pre-offer version is refused; presenting the fresh version supersedes the
    first truck and hands the old unit back to the fleet.

    PRD: "If that value does not equal the referenced production's current `version`, the request is rejected with `ERR_STALE_PRODUCTION_VERSION` (HTTP 412) and nothing is written."
    PRD: "When the assignment succeeds, the production's `truck_id` is set to the named truck, the production's `version` is incremented by 1, and the derivation of §2.9 runs — which is how a production that was waiting only on transport can jump `SURVEYED → PROVISIONED` inside the assignment request."
    PRD: "If the production had previously been assigned a *different* truck, that earlier unit is released first: it moves `ASSIGNED → AVAILABLE` when no other production that is neither `WRAPPED` nor `SETTLED` still holds it, and it stays `ASSIGNED` when another holder remains."
    Design: Corner/cross_cutting_complexity_layers/truck_assignment_occ_token_must_match_the_current_production_version
    """
    production = new_production(api)
    truck_a = new_truck(
        api,
        truck_code="TRK-A1",
        tier_rating="TIER_2",
        camera_channel_capacity=8,
        power_draw_amps=90,
    )
    truck_b = new_truck(
        api,
        truck_code="TRK-B1",
        tier_rating="TIER_2",
        camera_channel_capacity=8,
        power_draw_amps=90,
    )

    version_one = production_version(api, production["id"])
    first = validate_success(
        api.assign_truck(
            production["id"],
            truck_assignment_payload(truck_a["id"], version_one),
            pm_headers,
        ),
        200,
    )
    version_two = first["version"]
    assert version_two == version_one + 1

    # A second writer commits labor against the production, which advances the
    # version the first writer is still holding.
    crew_member = new_crew_member(api)
    offer_call(api, production["id"], crew_member["id"], expected_version=version_two)
    version_three = production_version(api, production["id"])
    assert version_three > version_two

    validate_error(
        api.assign_truck(
            production["id"],
            truck_assignment_payload(truck_b["id"], version_two),
            pm_headers,
        ),
        "ERR_STALE_PRODUCTION_VERSION",
    )

    unchanged = read_production(api, production["id"])
    assert unchanged["truck_id"] == truck_a["id"], "nothing is written on a stale token"
    assert unchanged["version"] == version_three
    assert_status(read_truck(api, truck_a["id"]), "ASSIGNED")
    assert_status(read_truck(api, truck_b["id"]), "AVAILABLE")

    reassigned = validate_success(
        api.assign_truck(
            production["id"],
            truck_assignment_payload(truck_b["id"], version_three),
            pm_headers,
        ),
        200,
    )
    assert_production(reassigned)
    assert reassigned["truck_id"] == truck_b["id"]
    assert reassigned["version"] == version_three + 1
    assert_status(read_truck(api, truck_a["id"]), "AVAILABLE")
    assert_status(read_truck(api, truck_b["id"]), "ASSIGNED")
