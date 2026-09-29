"""Validation breadth: the referential, temporal, capacity, uniqueness and life-safety
gates, each fired in isolation so the error identity and the untouched side-effects
both pin the rule that answered."""

from typing import Any, Dict

from test_helpers import factories as f
from test_helpers import get_success_data, validate_error, validate_paginated
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import (
    CertificationLevel,
    DeviceType,
    FollowUpOutcome,
    HouseholdStatus,
    InstallationStatus,
    PlacementLocation,
    VisitStatus,
)
from test_helpers.fixtures import (
    arrive,
    book_visit,
    create_active_grant,
    create_assessed_zone,
    create_crew,
    create_household,
    create_lot,
    create_published_route,
    create_zone,
    defer_visit,
    deliver_education,
    funded_arrived_visit,
    log_follow_up,
    pin_clock,
    read_household,
    read_installation,
    read_lot,
    read_route,
    read_visit,
    reserve_installation,
)
from test_helpers.test_users import (
    ANALYST,
    COORDINATOR,
    OFFICER,
    make_crr_technician_headers,
)


def _served_household(
    api,
    sleeping_areas_count: int = 1,
    storeys: int = 1,
    pre_existing_working_smoke_alarms: int = 3,
    **household_overrides: Any,
) -> Dict[str, Any]:
    """One household closed out through the deferred branch at the program epoch."""
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(
        api,
        zone["id"],
        address_line="9 Birch Road",
        sleeping_areas_count=sleeping_areas_count,
        storeys=storeys,
        **household_overrides,
    )
    visit = book_visit(api, household["id"], route["id"])
    arrive(
        api,
        visit["id"],
        crew["id"],
        pre_existing_working_smoke_alarms=pre_existing_working_smoke_alarms,
    )
    deliver_education(api, visit["id"], crew["id"])
    defer_visit(api, visit["id"], crew["id"])
    return {
        "zone": zone,
        "crew": crew,
        "route": route,
        "household": read_household(api, household["id"]),
        "visit": visit,
    }


def test_01_a_route_in_another_zone_cannot_take_the_households_visit(api):
    """Both zones are assessed and both routes are open; the only defect is that the
    route belongs to the wrong zone.

    PRD: "The route's zone must be the household's zone; a mismatch is rejected with
    `ERR_ROUTE_ZONE_MISMATCH`."

    Design: Corner/validations/visit_booked_on_a_route_of_another_zone_returns_route_zone_mismatch
    """
    pin_clock(api)
    home_zone = create_assessed_zone(api)
    other_zone = create_assessed_zone(api, zone_code="Z-C54", name="Cedar Leaf")
    household = create_household(api, home_zone["id"], address_line="9 Birch Road")
    crew = create_crew(api, crew_code="CREW-B1")
    other_route = create_published_route(
        api, other_zone["id"], crew["id"], planned_slots=4
    )

    response = api.create_visit(
        f.visit_payload(household["id"], other_route["id"]), COORDINATOR
    )
    validate_error(response, ApiErrorId.ROUTE_ZONE_MISMATCH, 422)

    assert read_route(api, other_route["id"])["booked_slot_count"] == 0
    stored = read_household(api, household["id"])
    assert stored["status"] == HouseholdStatus.INTAKE_QUEUED
    assert stored["canvass_attempt_count"] == 0


def test_02_containment_is_tested_against_the_derived_end_not_the_start(api):
    """A 20:40 start sits inside the window, but the derived 21:15 end does not.

    PRD: "A start earlier than the window's start, or an unbuffered end later than the
    window's end, is rejected with `ERR_VISIT_OUTSIDE_ROUTE_WINDOW`."

    Design: Corner/validations/visit_whose_demand_overruns_the_route_window_returns_visit_outside_route_window
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="9 Birch Road")

    response = api.create_visit(
        f.visit_payload(
            household["id"], route["id"], scheduled_start_utc="2026-08-03T20:40:00Z"
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.VISIT_OUTSIDE_ROUTE_WINDOW, 422)
    assert read_route(api, route["id"])["booked_slot_count"] == 0


def test_03_an_appointment_ending_exactly_on_the_window_end_is_admitted(api):
    """20:25 plus 35 minutes lands exactly on 21:00, which is not "later than".

    PRD: "The appointment's own half-open span, from `scheduled_start_utc` inclusive to
    `scheduled_end_utc` exclusive, must lie entirely inside the route's half-open
    working window from `window_start_utc` inclusive to `window_end_utc` exclusive."

    Design: Corner/validations/visit_ending_exactly_at_the_route_window_end_is_admitted
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="9 Birch Road")

    visit = get_success_data(
        api.create_visit(
            f.visit_payload(
                household["id"], route["id"], scheduled_start_utc="2026-08-03T20:25:00Z"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert visit["demand_minutes"] == 35
    assert_instant_equals(
        visit["scheduled_end_utc"], "2026-08-03T21:00:00Z", "scheduled_end_utc"
    )
    assert visit["visit_status"] == VisitStatus.SCHEDULED
    assert read_route(api, route["id"])["booked_slot_count"] == 1
    assert (
        read_household(api, household["id"])["status"]
        == HouseholdStatus.APPOINTMENT_SCHEDULED
    )


def test_04_the_daily_budget_fails_even_when_the_two_visits_are_hours_apart(api):
    """35 + 35 minutes against a 60-minute crew day, with the intervals far enough
    apart that the buffered conflict rule stays silent.

    PRD: "The system also sums `demand_minutes` across that same set of existing
    occupations and adds the candidate's own `demand_minutes`; the total must not
    exceed the crew's `max_daily_minutes`, and an overrun is rejected with
    `ERR_CREW_DAILY_MINUTES_EXCEEDED`."

    Design: Corner/validations/two_far_apart_visits_exceeding_the_crew_day_returns_crew_daily_minutes_exceeded
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-TINY", member_count=1, max_daily_minutes=60)
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    first = create_household(api, zone["id"], address_line="1 Birch Road")
    second = create_household(api, zone["id"], address_line="2 Birch Road")

    visit = book_visit(api, first["id"], route["id"])
    assert visit["demand_minutes"] == 35

    response = api.create_visit(
        f.visit_payload(
            second["id"], route["id"], scheduled_start_utc="2026-08-03T18:00:00Z"
        ),
        COORDINATOR,
    )
    error = validate_error(response, ApiErrorId.CREW_DAILY_MINUTES_EXCEEDED, 422)
    assert error["error_id"] != ApiErrorId.CREW_INTERVAL_CONFLICT

    assert read_route(api, route["id"])["booked_slot_count"] == 1
    assert read_household(api, second["id"])["status"] == HouseholdStatus.INTAKE_QUEUED


def test_05_an_open_appointment_blocks_a_second_booking_for_the_same_household(api):
    """The state gate of PRD 2.7 step 9 precedes the open-visit rule of step 26, so
    the household must legitimately pass the state gate for the open-visit rule to be
    the one that answers. A visit closed out on its install axis as DEFERRED but never
    educated still projects as `AWAITING_EDUCATION`, and a failed follow-up then carries
    its household to `REVISIT_REQUIRED` - a bookable state holding an open visit.

    PRD: "The household must additionally have no visit already open - no visit of that
    household may sit in `SCHEDULED`, `IN_PROGRESS`, `AWAITING_EDUCATION` or
    `AWAITING_INSTALL_OUTCOME` - and a violation is rejected with
    `ERR_HOUSEHOLD_HAS_OPEN_VISIT`."

    Design: Corner/validations/booking_a_second_visit_while_one_is_open_returns_household_has_open_visit
    """
    pin_clock(api)
    zone = create_assessed_zone(api)
    crew = create_crew(api, crew_code="CREW-B1")
    route = create_published_route(api, zone["id"], crew["id"], planned_slots=4)
    household = create_household(api, zone["id"], address_line="9 Birch Road")
    visit = book_visit(api, household["id"], route["id"])

    # Close the install axis without ever delivering education: the visit projects as
    # AWAITING_EDUCATION, which is one of the four open projections, while the
    # household reaches VISIT_COMPLETED.
    arrive(api, visit["id"], crew["id"], pre_existing_working_smoke_alarms=2)
    defer_visit(api, visit["id"], crew["id"])
    assert read_visit(api, visit["id"])["visit_status"] == VisitStatus.AWAITING_EDUCATION

    # A failed follow-up past day 30 carries the household into REVISIT_REQUIRED, which
    # PRD 3.5 names as a bookable state - so the state gate no longer masks step 26.
    pin_clock(api, "2026-09-05T00:00:00Z")
    log_follow_up(
        api, household["id"], outcome=FollowUpOutcome.REACHED_ALARM_MISSING
    )
    assert read_household(api, household["id"])["status"] == HouseholdStatus.REVISIT_REQUIRED

    response = api.create_visit(
        f.visit_payload(
            household["id"], route["id"], scheduled_start_utc="2026-08-03T18:00:00Z"
        ),
        COORDINATOR,
    )
    error = validate_error(response, ApiErrorId.HOUSEHOLD_HAS_OPEN_VISIT, 409)
    assert error["error_id"] != ApiErrorId.INVALID_HOUSEHOLD_STATE

    assert read_route(api, route["id"])["booked_slot_count"] == 1
    stored = read_household(api, household["id"])
    assert stored["status"] == HouseholdStatus.REVISIT_REQUIRED
    assert stored["canvass_attempt_count"] == 1


def test_06_a_second_device_at_the_same_storey_and_location_is_a_duplicate(api):
    """The uniqueness key spans visit, device type, location and storey; the same
    device on another storey would have been accepted.

    PRD: "Finally, at most one non-voided installation may exist for a given
    combination of visit, `device_type`, `placement_location` and `storey`; a duplicate
    is rejected with `ERR_DUPLICATE_PLACEMENT`."

    Design: Corner/validations/second_alarm_at_the_same_storey_and_location_returns_duplicate_placement
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=0,
        household_overrides={
            "address_line": "9 Birch Road",
            "occupant_count": 4,
            "sleeping_areas_count": 2,
            "storeys": 2,
        },
        route_overrides={"planned_slots": 4},
    )
    first = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        device_lot_id=ctx["lot"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
    )

    response = api.create_installation(
        f.installation_payload(
            ctx["visit"]["id"],
            device_lot_id=ctx["lot"]["id"],
            placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
            storey=1,
        ),
        make_crr_technician_headers(ctx["crew"]["id"]),
    )
    validate_error(response, ApiErrorId.DUPLICATE_PLACEMENT, 409)

    assert read_lot(api, ctx["lot"]["id"])["reserved_qty"] == 1
    assert read_installation(api, first["id"])["status"] == InstallationStatus.RESERVED
    rows, meta = validate_paginated(
        api.list_installations(OFFICER, params={"visit_id": ctx["visit"]["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]


def test_07_only_the_strobe_reservation_needs_an_advanced_crew(api):
    """The same BASIC crew reserves a smoke alarm on the same visit; only the strobe
    is refused.

    PRD: "A third safety rule follows immediately: a `STROBE_HOH` device may only be
    reserved by a crew whose `certification_level` is `ADVANCED`, and a `BASIC` crew
    attempting it is rejected with `ERR_CREW_NOT_CERTIFIED`."

    Design: Corner/validations/strobe_reserved_by_a_basic_crew_returns_crew_not_certified
    """
    ctx = funded_arrived_visit(
        api,
        pre_existing_working_smoke_alarms=0,
        grant_overrides={
            "grant_code": "G-STROBE-1",
            "allowed_device_types": [DeviceType.SMOKE_10YR, DeviceType.STROBE_HOH],
            "unit_rate_cents_by_type": {
                DeviceType.SMOKE_10YR: 2195,
                DeviceType.STROBE_HOH: 4995,
            },
        },
        crew_overrides={
            "crew_code": "CREW-BASIC",
            "certification_level": CertificationLevel.BASIC,
        },
        household_overrides={
            "address_line": "9 Birch Road",
            "hearing_impaired_occupants": 1,
        },
        route_overrides={"planned_slots": 4},
    )
    strobe_lot = create_lot(
        api,
        ctx["grant"]["id"],
        sku="STR-A",
        device_type=DeviceType.STROBE_HOH,
        unit_cost_cents=4200,
        received_qty=5,
    )
    assert read_household(api, ctx["household"]["id"])["required_strobe_devices"] == 1

    smoke = reserve_installation(
        api,
        ctx["visit"]["id"],
        ctx["crew"]["id"],
        device_lot_id=ctx["lot"]["id"],
        placement_location=PlacementLocation.HALLWAY_OUTSIDE_SLEEPING,
        storey=1,
    )

    response = api.create_installation(
        f.installation_payload(
            ctx["visit"]["id"],
            device_type=DeviceType.STROBE_HOH,
            placement_location=PlacementLocation.SLEEPING_AREA,
            storey=1,
            device_lot_id=strobe_lot["id"],
        ),
        make_crr_technician_headers(ctx["crew"]["id"]),
    )
    validate_error(response, ApiErrorId.CREW_NOT_CERTIFIED, 422)

    assert read_installation(api, smoke["id"])["status"] == InstallationStatus.RESERVED
    assert read_lot(api, strobe_lot["id"])["reserved_qty"] == 0
    assert read_lot(api, ctx["lot"]["id"])["reserved_qty"] == 1


def test_08_a_plan_with_fewer_secondary_exits_than_sleeping_areas_is_incomplete(api):
    """Two sleeping areas need two documented secondary exits, and the version guard
    being current does not rescue a plan that is one exit short.

    PRD: "Life-safety completeness is checked before the plan is accepted:
    `primary_exit_per_sleeping_area` must be true **and** `secondary_exit_count` must
    be at least the household's `sleeping_areas_count`. A plan failing either condition
    is rejected with `ERR_ESCAPE_PLAN_INCOMPLETE`."

    Design: Corner/validations/escape_plan_with_too_few_secondary_exits_returns_escape_plan_incomplete
    """
    ctx = _served_household(api, sleeping_areas_count=2, storeys=1, occupant_count=4)
    household = ctx["household"]
    assert household["sleeping_areas_count"] == 2
    assert household["status"] == HouseholdStatus.VISIT_COMPLETED

    response = api.create_escape_plan(
        f.escape_plan_payload(
            household["id"],
            household["version"],
            secondary_exit_count=1,
            meeting_point_description="Oak tree across the street",
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ESCAPE_PLAN_INCOMPLETE, 422)

    _, meta = validate_paginated(
        api.list_escape_plans(COORDINATOR, params={"household_id": household["id"]})
    )
    assert meta["total_count"] == 0
    assert read_household(api, household["id"])["version"] == household["version"]


def test_09_a_follow_up_on_day_twenty_nine_is_too_early(api):
    """The visit closed on 2026-08-01; at 2026-08-30 only 29 whole days have elapsed.

    PRD: "A follow-up is therefore only accepted once `days_since_visit` is at least 30
    - a full month must have elapsed since the household's most recent completed visit
    - and an earlier attempt is rejected with `ERR_FOLLOWUP_TOO_EARLY`."

    Design: Corner/validations/follow_up_logged_on_day_twenty_nine_returns_followup_too_early
    """
    ctx = _served_household(api, pre_existing_working_smoke_alarms=2)
    household = ctx["household"]
    assert_instant_equals(
        household["last_visit_completed_at"], "2026-08-01T00:00:00Z", "last_visit_completed_at"
    )
    pin_clock(api, "2026-08-30T00:00:00Z")

    response = api.create_follow_up(
        f.follow_up_reached_present_payload(
            household["id"], alarms_present_count=2, plan_practiced=True
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.FOLLOWUP_TOO_EARLY, 422)

    _, meta = validate_paginated(
        api.list_household_follow_ups(household["id"], COORDINATOR)
    )
    assert meta["total_count"] == 0
    stored = read_household(api, household["id"])
    assert stored["status"] == HouseholdStatus.VISIT_COMPLETED
    assert stored["alarm_retention_flag"] is None


def test_10_a_report_period_that_pokes_out_of_the_grant_period_is_refused(api):
    """June is outside the grant's July-to-December period, and containment is required
    on both ends.

    PRD: "The reported period must lie entirely inside the grant's own period, inclusive
    on both ends; a period that pokes out either side is rejected with
    `ERR_REPORT_PERIOD_OUTSIDE_GRANT`."

    Design: Corner/validations/report_period_starting_before_the_grant_returns_report_period_outside_grant
    """
    pin_clock(api, "2026-09-05T00:00:00Z")
    grant = create_active_grant(api)
    assert grant["period_start_date"] == "2026-07-01"
    assert grant["period_end_date"] == "2026-12-31"

    response = api.create_grant_report(
        f.grant_report_payload(
            grant["id"], period_start_date="2026-06-01", period_end_date="2026-08-31"
        ),
        OFFICER,
    )
    validate_error(response, ApiErrorId.REPORT_PERIOD_OUTSIDE_GRANT, 422)

    _, meta = validate_paginated(
        api.list_grant_reports(OFFICER, params={"grant_id": grant["id"]})
    )
    assert meta["total_count"] == 0


def test_11_a_second_zone_cannot_reuse_a_zone_code(api):
    """Every other input differs, so the collision is on the code alone.

    PRD: "`zone_code` must be non-empty and globally unique; a collision is rejected
    with `ERR_ZONE_CODE_TAKEN`."

    Design: Corner/validations/second_zone_with_the_same_code_returns_zone_code_taken
    """
    pin_clock(api)
    first = create_zone(api)
    assert first["zone_code"] == "Z-B54"

    response = api.create_zone(
        f.zone_payload(
            zone_code="Z-B54",
            name="Duplicate Code Leaf",
            occupied_units=900,
            structure_fire_count_5yr=3,
            fire_injury_count_5yr=0,
            pre_1980_unit_pct=10.0,
            senior_household_pct=5.0,
            under5_household_pct=2.0,
            disability_household_pct=1.0,
            assumed_alarm_absence_pct=20.0,
            daily_visit_cap=3,
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ZONE_CODE_TAKEN, 409)

    rows, meta = validate_paginated(api.list_zones(ANALYST))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["name"] == "Birchwood Leaf"
