"""Half-open ranges and buffered intervals: what counts as an overlap.

PRD 3.4 charges the group ceiling only on the dates a stay actually occupies,
so a programme that starts on another's departure date competes for nothing;
PRD 3.2 extends every existing meeting-space booking by a 45-minute turnover
before testing a new request, so intervals that merely touch do collide.
"""

from test_helpers import (
    SALES_MANAGER,
    ApiErrorId,
    HoldStatus,
    LeadStatus,
    MarketSegment,
    QuoteStatus,
    SpaceCode,
    assert_function_space_hold,
    assert_lead,
    assert_rate_quote,
    factories as F,
    held_rooms,
    read_lead,
    read_quote,
    reset_clock,
    seed_account,
    seed_calendar_and_package,
    seed_cleared_lead,
    seed_draft_quote,
    seed_function_space_hold,
    seed_lead,
    seed_package,
    seed_proposed_quote,
    seed_qualified_lead,
    validate_error,
    validate_paginated,
    validate_success,
)

_MERIDIAN_DATES = ["2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"]
_TIGHT_CEILING = {
    "group_ceiling_rooms": 5,
    "transient_demand_rooms": 100,
    "historical_pickup_rooms": 90,
}
_MERIDIAN_ACCOUNT = {
    "name": "Meridian Health Group",
    "billing_contact_email": "ap@meridian.example",
}


def _three_programs_under_one_ceiling(api):
    """One client organization with three cleared programmes on a house whose
    group ceiling is only 5 rooms a night.

    The incumbent programme is quoted and holding 4 rooms on 2026-11-09, -10 and
    -11; the second programme overlaps two of those dates; the third starts on
    the incumbent's departure date and therefore shares no occupied date with it
    (PRD 3.1, PRD 3.4).
    """
    base = seed_calendar_and_package(
        api,
        stay_dates=_MERIDIAN_DATES,
        inventory=_TIGHT_CEILING,
        account=_MERIDIAN_ACCOUNT,
    )
    small = seed_package(api, F.small_meetings_package_payload())

    incumbent = seed_qualified_lead(
        api, base, lead={"program_name": "Meridian National Meeting"}
    )
    seed_cleared_lead(api, incumbent)
    seed_draft_quote(api, incumbent)
    seed_proposed_quote(api, incumbent)

    overlapping = seed_qualified_lead(
        api,
        base,
        lead={
            "program_name": "Meridian Clinical Workshop",
            "arrival_date": "2026-11-10",
            "departure_date": "2026-11-12",
            "peak_rooms": 2,
            "total_requested_room_nights": 6,
            "meeting_space_sqft_needed": 60,
        },
    )
    overlapping["package_id"] = small["id"]
    seed_cleared_lead(api, overlapping)
    seed_draft_quote(
        api,
        overlapping,
        quote={
            "base_rate_cents": 20000,
            "quoted_peak_rooms": 2,
            "quoted_room_nights": 6,
        },
    )

    adjacent = seed_qualified_lead(
        api,
        base,
        lead={
            "program_name": "Meridian Post-Congress Board",
            "arrival_date": "2026-11-12",
            "departure_date": "2026-11-13",
            "peak_rooms": 2,
            "total_requested_room_nights": 2,
            "meeting_space_sqft_needed": 60,
        },
    )
    adjacent["package_id"] = small["id"]
    seed_cleared_lead(api, adjacent)
    seed_draft_quote(
        api,
        adjacent,
        quote={
            "base_rate_cents": 20000,
            "quoted_peak_rooms": 2,
            "quoted_room_nights": 2,
        },
    )

    return {"incumbent": incumbent, "overlapping": overlapping, "adjacent": adjacent}


def test_a_program_sharing_occupied_dates_breaches_the_group_ceiling(api):
    """Two rooms more than the ceiling allows on the shared dates is refused.

    PRD 3.4 places a soft hold only when "held_group_rooms plus
    committed_group_rooms plus the quoted peak rooms does not exceed
    group_ceiling_rooms on every occupied date". 2026-11-10 and -11 already hold
    4 of the 5 permitted rooms, so a second programme asking for 2 is refused and
    nothing about it moves.

    Design: Difficulty/resource_temporal_overlap/group_ceiling_half_open_stay_range_adjacency
    """
    worlds = _three_programs_under_one_ceiling(api)
    overlapping = worlds["overlapping"]

    validate_error(
        api.propose_rate_quote(overlapping["quote_id"], SALES_MANAGER),
        ApiErrorId.GROUP_CEILING_EXCEEDED,
        409,
    )

    assert_rate_quote(
        read_quote(api, overlapping["quote_id"]),
        status=QuoteStatus.DRAFT,
        hold_placed=False,
    )
    assert_lead(read_lead(api, overlapping["lead_id"]), status=LeadStatus.CLEARED)
    assert held_rooms(api, _MERIDIAN_DATES) == [4, 4, 4, 0], (
        "a refused propose must leave the calendar exactly as it was"
    )


def test_a_program_starting_on_the_departure_date_competes_for_nothing(api):
    """The stay range is half-open, so the departure date is free.

    PRD 3.1 makes the occupied dates of a stay the half-open range from arrival
    to departure, so the incumbent's 2026-11-09 to -12 programme occupies only
    three dates and leaves 2026-11-12 untouched. The third programme, arriving on
    that very date, therefore passes the same ceiling test that refused the
    overlapping one, and its 2 rooms land on 2026-11-12 alone.

    Design: Difficulty/resource_temporal_overlap/group_ceiling_half_open_stay_range_adjacency
    """
    worlds = _three_programs_under_one_ceiling(api)
    validate_error(
        api.propose_rate_quote(worlds["overlapping"]["quote_id"], SALES_MANAGER),
        ApiErrorId.GROUP_CEILING_EXCEEDED,
        409,
    )
    adjacent = worlds["adjacent"]

    proposed = validate_success(
        api.propose_rate_quote(adjacent["quote_id"], SALES_MANAGER)
    )

    assert_rate_quote(
        proposed,
        status=QuoteStatus.PROPOSED,
        hold_placed=True,
        effective_net_rate_cents=15167,
        total_quote_value_cents=30334,
    )
    assert held_rooms(api, _MERIDIAN_DATES) == [4, 4, 4, 2]
    assert_lead(read_lead(api, adjacent["lead_id"]), status=LeadStatus.QUOTED)
    assert_lead(
        read_lead(api, worlds["overlapping"]["lead_id"]), status=LeadStatus.CLEARED
    )


_AURORA_ACCOUNT = {
    "name": "Aurora Foundation",
    "market_segment": MarketSegment.ASSOCIATION,
    "billing_contact_email": "ap@aurora.example",
}
_MORNING_SESSION = {
    "start_at": "2026-11-09T09:00:00Z",
    "end_at": "2026-11-09T12:00:00Z",
    "attendee_count": 120,
}


def _ballroom_held_until_noon(api):
    """A lead holding GRAND_BALLROOM from 09:00Z to 12:00Z on 2026-11-09.

    Holding meeting space needs nothing but a lead, so the programme is left in
    NEW and no house calendar is required (PRD 3.2).
    """
    reset_clock(api)
    account = seed_account(api, **_AURORA_ACCOUNT)
    lead = seed_lead(api, account["id"], program_name="Aurora Symposium")
    hold = seed_function_space_hold(
        api, lead["id"], space_code=SpaceCode.GRAND_BALLROOM, **_MORNING_SESSION
    )
    return {"lead_id": lead["id"], "hold_id": hold["id"], "hold": hold}


def test_a_session_starting_at_noon_collides_with_the_turnover_buffer(api):
    """Touching intervals conflict once the turnover is added.

    PRD 3.2 tests a new booking against every existing HELD booking of the same
    space "after extending each existing end_at by the 45-minute turnover", so
    the morning session occupies the ballroom until 12:45Z and a request starting
    at 12:00Z is refused. The buffer is a property of the room, so the identical
    window in a different space is admitted.

    Design: Difficulty/resource_temporal_overlap/function_space_hold_45_minute_turnover_buffer
    """
    world = _ballroom_held_until_noon(api)
    assert_function_space_hold(world["hold"], status=HoldStatus.HELD)

    validate_error(
        api.create_function_space_hold(
            F.function_space_hold_payload(
                world["lead_id"],
                space_code=SpaceCode.GRAND_BALLROOM,
                start_at="2026-11-09T12:00:00Z",
                end_at="2026-11-09T13:00:00Z",
                attendee_count=40,
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.FUNCTION_SPACE_CONFLICT,
        409,
    )

    elsewhere = seed_function_space_hold(
        api,
        world["lead_id"],
        space_code=SpaceCode.SALON_A,
        start_at="2026-11-09T12:00:00Z",
        end_at="2026-11-09T13:00:00Z",
        attendee_count=40,
    )
    assert_function_space_hold(
        elsewhere, status=HoldStatus.HELD, space_code=SpaceCode.SALON_A
    )


def test_a_session_starting_exactly_at_the_buffer_end_is_admitted(api):
    """The buffered interval is half-open at its far end, and a release frees it.

    PRD 3.2 makes the buffered interval half-open, so 12:45Z is the first free
    instant after a session ending at 12:00Z and a booking may start there.
    Releasing the morning session then vacates the whole buffered window, so the
    12:00Z slot the buffer had refused becomes bookable.

    Design: Difficulty/resource_temporal_overlap/function_space_hold_45_minute_turnover_buffer
    """
    world = _ballroom_held_until_noon(api)

    at_buffer_end = seed_function_space_hold(
        api,
        world["lead_id"],
        space_code=SpaceCode.GRAND_BALLROOM,
        start_at="2026-11-09T12:45:00Z",
        end_at="2026-11-09T14:00:00Z",
        attendee_count=60,
    )
    assert_function_space_hold(at_buffer_end, status=HoldStatus.HELD)

    seed_function_space_hold(
        api,
        world["lead_id"],
        space_code=SpaceCode.SALON_A,
        start_at="2026-11-09T12:00:00Z",
        end_at="2026-11-09T13:00:00Z",
        attendee_count=40,
    )

    released = validate_success(
        api.release_function_space_hold(world["hold_id"], SALES_MANAGER)
    )
    assert_function_space_hold(released, status=HoldStatus.RELEASED)

    after_release = seed_function_space_hold(
        api,
        world["lead_id"],
        space_code=SpaceCode.GRAND_BALLROOM,
        start_at="2026-11-09T12:00:00Z",
        end_at="2026-11-09T12:30:00Z",
        attendee_count=40,
    )
    assert_function_space_hold(after_release, status=HoldStatus.HELD)

    rows, meta = validate_paginated(
        api.list_lead_function_space_holds(world["lead_id"], SALES_MANAGER)
    )
    assert meta["total_count"] == 4, f"the lead should own four bookings: {rows}"
    statuses = sorted(row["status"] for row in rows)
    assert statuses == [
        HoldStatus.HELD,
        HoldStatus.HELD,
        HoldStatus.HELD,
        HoldStatus.RELEASED,
    ], f"one released booking and three live ones, got {statuses}"
