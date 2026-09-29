"""Visit scheduling: demand minutes, the buffered crew calendar, the zone's daily
slot cap and the two independent visit axes."""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import get_success_data, validate_error
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    HouseholdStatus,
    InstallStatus,
    EducationStatus,
    RouteStatus,
    VisitStatus,
)
from test_helpers.fixtures import (
    arrive,
    book_visit,
    complete_visit,
    create_assessed_zone,
    create_crew,
    create_household,
    create_published_route,
    create_route,
    deliver_education,
    pin_clock,
    publish_route,
    read_household,
    read_route,
    read_visit,
    read_zone,
)
from test_helpers.test_users import COORDINATOR, make_crr_technician_headers

# A household with three sleeping areas across two storeys, one mobility-impaired
# occupant and one child under five: 30 + 10 + 5 + max(15, 10) = 60 raw minutes.
VULNERABLE_HOUSEHOLD = {
    "address_line": "22 Birch Road",
    "occupant_count": 4,
    "sleeping_areas_count": 3,
    "storeys": 2,
    "children_under5": 1,
    "mobility_impaired_occupants": 1,
}


def _tier_2_canvass(api, planned_slots: int = 4) -> Dict[str, Any]:
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=planned_slots)
    return {"zone": zone, "crew": crew, "route": route}


def test_01_only_the_larger_vulnerability_allowance_is_applied(api):
    """A mobility-impaired occupant and a child under five contribute 15, not 25.

    PRD: "Only the **larger** of those two allowances is applied - they are not
    summed, so a home with both a mobility-impaired occupant and a child under five
    contributes 15 minutes, not 30."

    Design: Difficulty/combinatorial_formula/visit_demand_minutes_nested_max_then_grid_ceiling
    """
    ctx = _tier_2_canvass(api)
    assert ctx["zone"]["risk_score"] == 54.52
    assert ctx["zone"]["risk_tier"] == "TIER_2"

    household = create_household(api, ctx["zone"]["id"], **VULNERABLE_HOUSEHOLD)
    visit = book_visit(api, household["id"], ctx["route"]["id"])

    assert visit["demand_minutes"] == 70
    assert visit["demand_minutes"] != 80


def test_02_the_tiered_product_is_snapped_upward_onto_the_five_minute_grid(api):
    """60 raw minutes at the TIER_2 multiplier is 66, which snaps up to 70.

    PRD: "That product is snapped **upward** to the next whole multiple of 5
    minutes - always up, never to the nearest - then floored at a minimum of 30
    minutes and finally capped at a maximum of 120 minutes, which is to say no single
    visit may be scheduled for more than two hours."

    Design: Difficulty/combinatorial_formula/visit_demand_minutes_nested_max_then_grid_ceiling
    """
    ctx = _tier_2_canvass(api)
    household = create_household(api, ctx["zone"]["id"], **VULNERABLE_HOUSEHOLD)
    visit = book_visit(api, household["id"], ctx["route"]["id"])

    assert visit["demand_minutes"] == 70
    assert_instant_equals(
        visit["scheduled_end_utc"], "2026-08-03T15:10:00Z", "scheduled_end_utc"
    )
    assert visit["visit_status"] == VisitStatus.SCHEDULED
    assert read_route(api, ctx["route"]["id"])["booked_slot_count"] == 1


def test_03_a_visit_may_close_the_education_axis_first(api):
    """Education then install close-out: SURVEYED + DELIVERED, then COMPLETED.

    PRD: "Fourth, if `install_status` is `SURVEYED` and `education_status` is
    `DELIVERED` or `DECLINED`, the projection is `AWAITING_INSTALL_OUTCOME`."

    Design: Difficulty/non_linear_state_machine/visit_install_and_education_axes_terminate_in_either_order
    """
    ctx = _tier_2_canvass(api, planned_slots=2)
    household = create_household(api, ctx["zone"]["id"])
    visit = book_visit(api, household["id"], ctx["route"]["id"])
    arrive(api, visit["id"], ctx["crew"]["id"], pre_existing_working_smoke_alarms=2)

    after_education = deliver_education(api, visit["id"], ctx["crew"]["id"])
    assert after_education["install_status"] == InstallStatus.SURVEYED
    assert after_education["education_status"] == EducationStatus.DELIVERED
    assert after_education["visit_status"] == VisitStatus.AWAITING_INSTALL_OUTCOME

    completed = complete_visit(
        api, visit["id"], ctx["crew"]["id"], occupant_signature_name="A. Ibarra"
    )
    assert completed["install_status"] == InstallStatus.INSTALL_COMPLETE
    assert completed["visit_status"] == VisitStatus.COMPLETED
    assert_instant_equals(completed["completed_at"], "2026-08-01T00:00:00Z", "completed_at")


def test_04_a_visit_may_close_the_install_axis_first(api):
    """Install close-out then a declined education still converges on COMPLETED.

    PRD: "Third, if `install_status` is `INSTALL_COMPLETE` or `INSTALL_DEFERRED`
    while `education_status` is still `PENDING`, the projection is
    `AWAITING_EDUCATION`."

    Design: Difficulty/non_linear_state_machine/visit_install_and_education_axes_terminate_in_either_order
    """
    ctx = _tier_2_canvass(api, planned_slots=2)
    household = create_household(api, ctx["zone"]["id"], address_line="2 Birch Road")
    visit = book_visit(api, household["id"], ctx["route"]["id"])
    arrive(api, visit["id"], ctx["crew"]["id"], pre_existing_working_smoke_alarms=2)

    after_install = complete_visit(
        api, visit["id"], ctx["crew"]["id"], occupant_signature_name="B. Nwosu"
    )
    assert after_install["install_status"] == InstallStatus.INSTALL_COMPLETE
    assert after_install["education_status"] == EducationStatus.PENDING
    assert after_install["visit_status"] == VisitStatus.AWAITING_EDUCATION

    declined = get_success_data(
        api.record_education(
            visit["id"],
            f.education_declined_payload(),
            make_crr_technician_headers(ctx["crew"]["id"]),
        )
    )
    assert declined["education_status"] == EducationStatus.DECLINED
    assert declined["visit_status"] == VisitStatus.COMPLETED


def test_05_both_axis_orderings_close_out_their_zone_together(api):
    """Two visits finishing in opposite orders leave the zone SERVICE_COMPLETE.

    PRD: "The forward step from `SERVICE_ACTIVE` to `SERVICE_COMPLETE` is evaluated
    by the system after every household status change in the zone: it fires when the
    zone holds at least one household and every household in the zone sits in
    `VISIT_COMPLETED`, `REFUSED` or `NO_CONTACT`."

    Design: Difficulty/non_linear_state_machine/visit_install_and_education_axes_terminate_in_either_order
    """
    ctx = _tier_2_canvass(api, planned_slots=2)
    crew_id = ctx["crew"]["id"]
    first = create_household(api, ctx["zone"]["id"], address_line="1 Birch Road")
    second = create_household(api, ctx["zone"]["id"], address_line="2 Birch Road")
    visit_one = book_visit(api, first["id"], ctx["route"]["id"])
    visit_two = book_visit(
        api,
        second["id"],
        ctx["route"]["id"],
        scheduled_start_utc="2026-08-03T14:45:00Z",
    )
    arrive(api, visit_one["id"], crew_id, pre_existing_working_smoke_alarms=2)
    arrive(api, visit_two["id"], crew_id, pre_existing_working_smoke_alarms=2)

    deliver_education(api, visit_one["id"], crew_id)
    complete_visit(api, visit_one["id"], crew_id, occupant_signature_name="A. Ibarra")
    complete_visit(api, visit_two["id"], crew_id, occupant_signature_name="B. Nwosu")
    get_success_data(
        api.record_education(
            visit_two["id"], f.education_declined_payload(), make_crr_technician_headers(crew_id)
        )
    )

    assert read_visit(api, visit_one["id"])["visit_status"] == VisitStatus.COMPLETED
    assert read_visit(api, visit_two["id"])["visit_status"] == VisitStatus.COMPLETED
    assert read_household(api, first["id"])["status"] == HouseholdStatus.VISIT_COMPLETED
    assert read_household(api, second["id"])["status"] == HouseholdStatus.VISIT_COMPLETED

    zone = read_zone(api, ctx["zone"]["id"])
    assert zone["served_household_count"] == 2
    assert zone["assessment_status"] == "SERVICE_COMPLETE"
    assert read_route(api, ctx["route"]["id"])["status"] == RouteStatus.IN_PROGRESS


def test_06_a_candidate_starting_exactly_at_the_buffer_edge_is_admitted(api):
    """V1 ends at 14:35, so 14:40 on the same route is exactly on the edge.

    PRD: "Touching exactly at the buffer edge is not a conflict: a candidate
    starting precisely at an existing appointment's end plus the buffer is
    accepted..."

    Design: Difficulty/boundary_precision_check/crew_buffer_edge_exactly_five_minutes_is_admitted
    """
    ctx = _tier_2_canvass(api, planned_slots=3)
    first = create_household(api, ctx["zone"]["id"], address_line="1 Birch Road")
    second = create_household(api, ctx["zone"]["id"], address_line="2 Birch Road")

    visit_one = book_visit(api, first["id"], ctx["route"]["id"])
    assert_instant_equals(
        visit_one["scheduled_end_utc"], "2026-08-03T14:35:00Z", "scheduled_end_utc"
    )

    visit_two = book_visit(
        api,
        second["id"],
        ctx["route"]["id"],
        scheduled_start_utc="2026-08-03T14:40:00Z",
    )
    assert visit_two["demand_minutes"] == 35
    assert visit_two["visit_status"] == VisitStatus.SCHEDULED
    assert_instant_equals(
        visit_two["scheduled_end_utc"], "2026-08-03T15:15:00Z", "scheduled_end_utc"
    )


def test_07_one_minute_inside_the_buffer_is_a_conflict(api):
    """14:39 is one minute short of the five-minute same-route buffer.

    PRD: "...while a candidate starting one minute earlier than that is rejected
    with `ERR_CREW_INTERVAL_CONFLICT`. Instants are compared at millisecond
    resolution."

    Design: Difficulty/boundary_precision_check/crew_buffer_edge_exactly_five_minutes_is_admitted
    """
    ctx = _tier_2_canvass(api, planned_slots=3)
    first = create_household(api, ctx["zone"]["id"], address_line="1 Birch Road")
    second = create_household(api, ctx["zone"]["id"], address_line="2 Birch Road")
    third = create_household(api, ctx["zone"]["id"], address_line="3 Birch Road")

    book_visit(api, first["id"], ctx["route"]["id"])
    book_visit(
        api, second["id"], ctx["route"]["id"], scheduled_start_utc="2026-08-03T14:40:00Z"
    )

    response = api.create_visit(
        f.visit_payload(
            third["id"], ctx["route"]["id"], scheduled_start_utc="2026-08-03T14:39:00Z"
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.CREW_INTERVAL_CONFLICT, 409)

    assert read_route(api, ctx["route"]["id"])["booked_slot_count"] == 2
    assert read_household(api, third["id"])["status"] == HouseholdStatus.INTAKE_QUEUED


def test_08_the_cross_route_buffer_is_three_times_the_same_route_buffer(api):
    """14:45 collides across routes because the buffer there is fifteen minutes.

    PRD: "...with a travel buffer that depends on whether the two appointments belong
    to the same route: 5 minutes when the candidate and the existing appointment share
    the same `route_id`, and 15 minutes when they belong to different routes - three
    times the allowance, because a cross-route hop implies leaving the walking loop."

    Design: Difficulty/resource_temporal_overlap/crew_calendar_buffer_is_wider_across_routes_than_within_one
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    route_one = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    route_two = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    first = create_household(api, zone["id"], address_line="1 Birch Road")
    second = create_household(api, zone["id"], address_line="2 Birch Road")

    book_visit(api, first["id"], route_one["id"])

    response = api.create_visit(
        f.visit_payload(
            second["id"], route_two["id"], scheduled_start_utc="2026-08-03T14:45:00Z"
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.CREW_INTERVAL_CONFLICT, 409)
    assert read_route(api, route_two["id"])["booked_slot_count"] == 0


def test_09_the_same_instant_is_bookable_on_the_route_that_owns_the_first_visit(api):
    """The 14:45 candidate refused across routes is accepted on the incumbent route.

    PRD: "The set of existing occupations comprises every visit whose
    `occupies_crew_calendar` is true, whose `visit_status` is anything other than
    `CANCELLED`, whose route names the same crew as the candidate's route, and whose
    route carries the same `service_date` as the candidate's route..."

    Design: Difficulty/resource_temporal_overlap/crew_calendar_buffer_is_wider_across_routes_than_within_one
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api)
    route_one = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    route_two = create_published_route(api, zone["id"], crew["id"], planned_slots=2)
    first = create_household(api, zone["id"], address_line="1 Birch Road")
    second = create_household(api, zone["id"], address_line="2 Birch Road")

    book_visit(api, first["id"], route_one["id"])
    visit_two = book_visit(
        api, second["id"], route_one["id"], scheduled_start_utc="2026-08-03T14:45:00Z"
    )

    assert visit_two["route_id"] == route_one["id"]
    assert_instant_equals(
        visit_two["scheduled_end_utc"], "2026-08-03T15:20:00Z", "scheduled_end_utc"
    )
    assert read_route(api, route_one["id"])["booked_slot_count"] == 2
    assert read_route(api, route_two["id"])["booked_slot_count"] == 0


def _capped_zone_routes(api) -> Dict[str, Any]:
    """A zone capped at three slots a day, with one published route of two slots and
    two further planned routes whose windows do not overlap it at all."""
    pin_clock(api)
    zone = create_assessed_zone(api, zone_code="Z-CAP3", name="Capped Leaf", daily_visit_cap=3)
    crew = create_crew(api, crew_code="CREW-C1")
    route_one = create_route(
        api,
        zone["id"],
        crew["id"],
        planned_slots=2,
        window_start_utc="2026-08-03T13:00:00Z",
        window_end_utc="2026-08-03T15:00:00Z",
    )
    publish_route(api, route_one["id"])
    evening = {
        "window_start_utc": "2026-08-03T18:00:00Z",
        "window_end_utc": "2026-08-03T20:00:00Z",
    }
    route_two = create_route(api, zone["id"], crew["id"], planned_slots=2, **evening)
    route_three = create_route(api, zone["id"], crew["id"], planned_slots=1, **evening)
    return {
        "zone": zone,
        "route_one": route_one,
        "route_two": route_two,
        "route_three": route_three,
    }


def test_10_the_daily_cap_sums_slots_across_routes_with_disjoint_windows(api):
    """Two slots plus two slots exceeds a cap of three even at different hours.

    PRD: "Before it succeeds, the system totals `planned_slots` across every other
    route sharing this route's `zone_id` and `service_date` that sits in `PUBLISHED`,
    `IN_PROGRESS` or `CLOSED`, adds this route's own `planned_slots`, and requires the
    total to be no greater than the zone's `daily_visit_cap`."

    Design: Difficulty/resource_temporal_overlap/zone_daily_slot_cap_is_pure_aggregate_capacity_without_intervals
    """
    ctx = _capped_zone_routes(api)

    response = api.publish_route(ctx["route_two"]["id"], COORDINATOR)
    validate_error(response, ApiErrorId.ZONE_DAILY_CAP_EXCEEDED, 409)

    assert read_route(api, ctx["route_two"]["id"])["status"] == RouteStatus.PLANNED
    assert read_route(api, ctx["route_one"]["id"])["status"] == RouteStatus.PUBLISHED


def test_11_a_route_that_exactly_fills_the_remaining_cap_publishes(api):
    """The third route's single slot brings the day to exactly the cap of three.

    PRD: "...requires the total to be no greater than the zone's `daily_visit_cap`. If
    the total would exceed the cap the request is rejected with
    `ERR_ZONE_DAILY_CAP_EXCEEDED`..."

    Design: Difficulty/resource_temporal_overlap/zone_daily_slot_cap_is_pure_aggregate_capacity_without_intervals
    """
    ctx = _capped_zone_routes(api)
    validate_error(
        api.publish_route(ctx["route_two"]["id"], COORDINATOR),
        ApiErrorId.ZONE_DAILY_CAP_EXCEEDED,
        409,
    )

    published = publish_route(api, ctx["route_three"]["id"])
    assert published["status"] == RouteStatus.PUBLISHED

    zone = read_zone(api, ctx["zone"]["id"])
    assert zone["daily_visit_cap"] == 3
    assert zone["assessment_status"] == "TARGETED"


def test_12_the_crew_interval_answers_before_the_slot_ceiling(api):
    """A candidate that both overlaps the buffer and finds no free slot gets the
    temporal error, because the interval test runs first.

    PRD: "Both the interval test and the daily-minutes test run **before** any slot or
    fiscal check."

    Design: Difficulty/priority_pair_validation_conflict/crew_interval_conflict_precedes_route_slot_exhaustion
    """
    ctx = _tier_2_canvass(api, planned_slots=1)
    first = create_household(api, ctx["zone"]["id"], address_line="1 Birch Road")
    second = create_household(api, ctx["zone"]["id"], address_line="2 Birch Road")
    visit_one = book_visit(api, first["id"], ctx["route"]["id"])
    assert_instant_equals(
        visit_one["scheduled_end_utc"], "2026-08-03T14:35:00Z", "scheduled_end_utc"
    )

    response = api.create_visit(
        f.visit_payload(
            second["id"], ctx["route"]["id"], scheduled_start_utc="2026-08-03T14:30:00Z"
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.CREW_INTERVAL_CONFLICT, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ROUTE_SLOTS_EXHAUSTED


def test_13_the_refused_booking_leaves_the_route_and_household_untouched(api):
    """Nothing is consumed by the rejected booking: no slot, no attempt.

    PRD: "And the route must still have a free slot - `booked_slot_count` must be
    strictly less than `planned_slots`, or the request is rejected with
    `ERR_ROUTE_SLOTS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/crew_interval_conflict_precedes_route_slot_exhaustion
    """
    ctx = _tier_2_canvass(api, planned_slots=1)
    first = create_household(api, ctx["zone"]["id"], address_line="1 Birch Road")
    second = create_household(api, ctx["zone"]["id"], address_line="2 Birch Road")
    book_visit(api, first["id"], ctx["route"]["id"])

    validate_error(
        api.create_visit(
            f.visit_payload(
                second["id"], ctx["route"]["id"], scheduled_start_utc="2026-08-03T14:30:00Z"
            ),
            COORDINATOR,
        ),
        ApiErrorId.CREW_INTERVAL_CONFLICT,
        409,
    )

    route = read_route(api, ctx["route"]["id"])
    assert route["booked_slot_count"] == 1
    household = read_household(api, second["id"])
    assert household["status"] == HouseholdStatus.INTAKE_QUEUED
    assert household["canvass_attempt_count"] == 0
