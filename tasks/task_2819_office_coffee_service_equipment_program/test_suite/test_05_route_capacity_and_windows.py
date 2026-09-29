"""Route scheduling: the per-date minute budget filled to the minute, and the
half-open buffered window that abuts without colliding.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.assertions import assert_service_visit
from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    create_second_route,
    list_visits,
    read_day_load,
    read_route,
    schedule_visit,
    setup_planned_site,
    update_site,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]


def _tight_route_filled_to_ninety_minutes():
    """A ninety-minute route day filled exactly by two forty-five-minute stops."""
    base = setup_planned_site(clock=ANCHOR_MONDAY, capacity_minutes=90)
    base["first"] = schedule_visit(
        base["site"]["id"],
        window_start="2026-08-03T09:00:00Z",
        window_end="2026-08-03T09:45:00Z",
        planned_minutes=45,
    )
    base["second"] = schedule_visit(
        base["site"]["id"],
        window_start="2026-08-03T10:15:00Z",
        window_end="2026-08-03T11:00:00Z",
        planned_minutes=45,
    )
    return base


def test_a_route_day_may_be_filled_to_the_minute_but_not_one_minute_over():
    """Two stops take the day's budget to exactly its capacity and are accepted;
    a single further minute on the same date is refused and books nothing.

    "Scheduling is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED` (HTTP 422) when
    those booked minutes plus the new stop's `planned_minutes` would exceed the
    route's `capacity_minutes`. Exact equality is accepted — a day may be filled
    to the minute."

    "The same day-load arithmetic is exposed as a computed read for a
    `ProgramAdmin`, `AccountManager` or `RouteTechnician`: supplying a
    `service_date` returns that date's `service_date`, `booked_minutes_day`,
    `remaining_minutes` and the route's `capacity_minutes`, where the remaining
    minutes are the route's capacity minus the day's booked minutes."

    Design: Difficulty/boundary_precision_check/route_day_load_exact_capacity_fill_accepted_then_one_minute_over_rejected
    """
    base = _tight_route_filled_to_ninety_minutes()
    route_id = base["route"]["id"]
    assert_service_visit(base["first"])
    assert_service_visit(base["second"])

    filled = read_day_load(route_id, "2026-08-03")
    assert filled["service_date"] == "2026-08-03"
    assert filled["booked_minutes_day"] == 90
    assert filled["remaining_minutes"] == 0
    assert filled["capacity_minutes"] == 90

    one_minute_over = f.create_visit_payload(
        base["site"]["id"],
        window_start="2026-08-03T12:00:00Z",
        window_end="2026-08-03T12:01:00Z",
        planned_minutes=1,
    )
    validate_error(
        api_client.create_visit(one_minute_over, AM), "ERR_ROUTE_CAPACITY_EXCEEDED", 422
    )

    # The refusal contributed nothing at all.
    assert len(list_visits(site_id=base["site"]["id"])) == 2
    assert read_day_load(route_id, "2026-08-03")["booked_minutes_day"] == 90
    assert read_route(route_id)["booked_minutes_total"] == 90


def test_the_minute_budget_is_per_service_date_not_per_route():
    """The identical one-minute stop that the filled day refused is accepted on
    the route's next service date, and the route's running total spans both.

    "**Day capacity** is evaluated on the UTC calendar date of `window_start`,
    and only that date, even when `window_end` falls on the following day."

    "The booked minutes for a day are the sum of `planned_minutes` over the
    visits of that route whose status is `SCHEDULED` or `COMPLETED` and whose
    `window_start` falls on the same UTC date."

    "The route's `booked_minutes_total` is the same sum taken across every day of
    the route rather than a single date."

    Design: Difficulty/boundary_precision_check/route_day_load_exact_capacity_fill_accepted_then_one_minute_over_rejected
    """
    base = _tight_route_filled_to_ninety_minutes()
    route_id = base["route"]["id"]

    validate_error(
        api_client.create_visit(
            f.create_visit_payload(
                base["site"]["id"],
                window_start="2026-08-03T12:00:00Z",
                window_end="2026-08-03T12:01:00Z",
                planned_minutes=1,
            ),
            AM,
        ),
        "ERR_ROUTE_CAPACITY_EXCEEDED",
        422,
    )

    # The next Monday is a fresh budget for the same route.
    next_week = validate_success(
        api_client.create_visit(
            f.create_visit_payload(
                base["site"]["id"],
                window_start="2026-08-10T12:00:00Z",
                window_end="2026-08-10T12:01:00Z",
                planned_minutes=1,
            ),
            AM,
        ),
        201,
    )
    assert_service_visit(next_week)
    assert next_week["visit_status"] == "SCHEDULED"
    assert next_week["planned_minutes"] == 1

    later_day = read_day_load(route_id, "2026-08-10")
    assert later_day["booked_minutes_day"] == 1
    assert later_day["remaining_minutes"] == 89
    # The filled day is untouched by the following week's stop.
    assert read_day_load(route_id, "2026-08-03")["booked_minutes_day"] == 90
    assert read_route(route_id)["booked_minutes_total"] == 91


def _stop_ending_at_nine_forty_five():
    """A default-buffer route carrying one stop that ends at 09:45."""
    base = setup_planned_site(clock=ANCHOR_MONDAY)
    base["existing"] = schedule_visit(
        base["site"]["id"],
        window_start="2026-08-03T09:00:00Z",
        window_end="2026-08-03T09:45:00Z",
        planned_minutes=45,
    )
    return base


def test_buffered_candidate_collides_at_1014_and_abuts_freely_at_1015():
    """One minute decides it: a stop starting at 10:14 overlaps the buffered
    candidate window and is refused, while 10:15 abuts it exactly and is booked.

    "The candidate interval is widened symmetrically by the route's
    `travel_buffer_minutes` on both sides: it begins that many minutes before the
    requested `window_start` and ends that many minutes after the requested
    `window_end`, and it is treated as half-open — inclusive of its start instant,
    exclusive of its end instant."

    "With the default 30-minute buffer, an existing stop ending at 09:45 leaves a
    new stop starting at 10:15 free — the buffered candidate begins exactly at
    09:45, which abuts rather than overlaps — while a new stop starting at 10:14
    collides."

    "A collision is rejected with `ERR_ROUTE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/route_technician_day_halfopen_buffered_windows_abut_at_1015_but_collide_at_1014
    """
    base = _stop_ending_at_nine_forty_five()
    route_id = base["route"]["id"]

    colliding = f.create_visit_payload(
        base["site"]["id"],
        window_start="2026-08-03T10:14:00Z",
        window_end="2026-08-03T10:59:00Z",
        planned_minutes=45,
    )
    validate_error(api_client.create_visit(colliding, AM), "ERR_ROUTE_WINDOW_CONFLICT", 409)
    # The refusal booked nothing.
    assert read_route(route_id)["booked_minutes_total"] == 45
    assert len(list_visits(site_id=base["site"]["id"])) == 1

    abutting = validate_success(
        api_client.create_visit(
            f.create_visit_payload(
                base["site"]["id"],
                window_start="2026-08-03T10:15:00Z",
                window_end="2026-08-03T11:00:00Z",
                planned_minutes=45,
            ),
            AM,
        ),
        201,
    )
    assert_service_visit(abutting)
    assert abutting["visit_status"] == "SCHEDULED"
    assert abutting["window_start"] == "2026-08-03T10:15:00Z"

    assert read_route(route_id)["booked_minutes_total"] == 90
    day = read_day_load(route_id, "2026-08-03")
    assert day["booked_minutes_day"] == 90
    assert day["remaining_minutes"] == 390


def test_window_collision_is_evaluated_against_the_same_route_only():
    """The very window that collided on one route is accepted once the break room
    is moved to a second route, because occupancy is a route-local fact.

    "**Window collision** is evaluated against the other visits of the **same
    route only**; the same site may be visited by another route on the same day
    without conflict, and visits that are `CANCELLED` or `VOIDED` are ignored
    entirely."

    "The visit's `route_id` is **copied from the site's own route** and is never
    client-supplied; nor is `visit_status`, which starts at `SCHEDULED`, nor
    `lines`, which starts as an empty array."

    Design: Difficulty/resource_temporal_overlap/route_technician_day_halfopen_buffered_windows_abut_at_1015_but_collide_at_1014
    """
    base = _stop_ending_at_nine_forty_five()
    first_route_id = base["route"]["id"]
    colliding = f.create_visit_payload(
        base["site"]["id"],
        window_start="2026-08-03T10:14:00Z",
        window_end="2026-08-03T10:59:00Z",
        planned_minutes=45,
    )
    validate_error(api_client.create_visit(colliding, AM), "ERR_ROUTE_WINDOW_CONFLICT", 409)

    second_route = create_second_route()
    moved = update_site(base["site"]["id"], route_id=second_route["id"])
    assert moved["route_id"] == second_route["id"]
    # Re-routing the break room does not disturb the forecast it already has.
    assert moved["recommended_model_id"] == base["model"]["id"]

    accepted = validate_success(api_client.create_visit(colliding, AM), 201)
    assert accepted["route_id"] == second_route["id"]
    assert accepted["visit_status"] == "SCHEDULED"
    assert accepted["window_start"] == "2026-08-03T10:14:00Z"

    # Each route carries only its own minutes.
    assert read_route(first_route_id)["booked_minutes_total"] == 45
    assert read_route(second_route["id"])["booked_minutes_total"] == 45
    assert read_day_load(second_route["id"], "2026-08-03")["booked_minutes_day"] == 45
