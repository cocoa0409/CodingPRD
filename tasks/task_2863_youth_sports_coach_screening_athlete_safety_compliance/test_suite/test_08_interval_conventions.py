"""Two overlap rules with deliberately opposite interval conventions.

A room slot is half-open, so touching endpoints are legal.  An interim-measure
window is closed and carries a trailing cooling buffer, so a request landing
exactly on the buffered end is a conflict.  Each pair pins the boundary from both
sides with requests that differ by one minute, or by one day.
"""

from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant_equals, assert_state, assert_version_is
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    NGB_ADMIN_HEADERS,
    OFFICER_IMPOSE_HEADERS,
    OFFICER_INTAKE_HEADERS,
    make_club_admin_headers,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}
ADULT_STAY = {
    "occupant_kind": "ADULT_MEMBER",
    "trip_label": "NATIONALS_2026",
    "room_number": "301",
    "check_in": "2026-09-01T15:00:00Z",
    "check_out": "2026-09-03T11:00:00Z",
}


def _slot_with_one_adult_stay(api: ApiClient) -> Dict[str, Any]:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Nils Barrow",
                "email": "nils.barrow@alpha.test",
                "role_type": "CHAPERONE",
                "has_minor_athlete_contact": True,
                "date_of_birth": "1979-06-06",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    stay = get_success_data(
        api.book_room_stay(club["id"], dict(ADULT_STAY, member_id=member["id"]), admin), 201
    )
    assert_state(stay, "status", "BOOKED")
    return {"club": club, "member": member, "stay": stay, "admin": admin}


def test_a_minor_stay_starting_exactly_when_the_adult_stay_ends_is_accepted(
    api: ApiClient,
) -> None:
    """The room-slot interval is half-open, so touching endpoints do not overlap.

    PRD 3.7 says:
    "`check_in` and `check_out` bound the occupancy interval, with `check_out` strictly after `check_in`, and the interval is half-open — the stay occupies `check_in` inclusively and releases the bed before `check_out`."
    "Adjacency is therefore explicitly legal: a new stay whose `check_in` falls exactly on an existing stay's `check_out` does not overlap it, and two coaches may hand a room over on the same instant."

    Design: Difficulty/resource_temporal_overlap/room_slot_half_open_adjacency_is_legal_one_minute_overlap_is_not
    """
    setup = _slot_with_one_adult_stay(api)

    stay = validate_success(
        api.book_room_stay(
            setup["club"]["id"],
            {
                "occupant_kind": "MINOR_ATHLETE",
                "trip_label": "NATIONALS_2026",
                "room_number": "301",
                "check_in": "2026-09-03T11:00:00Z",
                "check_out": "2026-09-05T11:00:00Z",
                "minor_athlete_age": 15,
            },
            setup["admin"],
        ),
        201,
    )

    assert_state(stay, "status", "BOOKED")
    assert_state(stay, "occupant_kind", "MINOR_ATHLETE")
    assert_instant_equals(stay["check_in"], "2026-09-03T11:00:00.000Z")
    assert stay["cancel_reason"] is None


def test_pulling_the_same_check_in_back_one_minute_trips_the_lodging_safety_rule(
    api: ApiClient,
) -> None:
    """One minute of intersection is enough to make the two occupant kinds conflict.

    PRD 3.7 says:
    "The platform first collects the neighbouring stays: those in the same slot, in status `BOOKED`, whose interval intersects the requested one, where intersection means the requested `check_in` falls strictly before the neighbour's `check_out` and the neighbour's `check_in` falls strictly before the requested `check_out`."
    "If any neighbour has a different `occupant_kind` from the requested booking, the request is refused with `ERR_MINOR_ADULT_LODGING_PROHIBITED`: an adult member and a minor athlete may never share a room slot across overlapping time, in either direction."

    Design: Difficulty/resource_temporal_overlap/room_slot_half_open_adjacency_is_legal_one_minute_overlap_is_not
    """
    setup = _slot_with_one_adult_stay(api)

    response = api.book_room_stay(
        setup["club"]["id"],
        {
            "occupant_kind": "MINOR_ATHLETE",
            "trip_label": "NATIONALS_2026",
            "room_number": "301",
            "check_in": "2026-09-03T10:59:00Z",
            "check_out": "2026-09-03T11:00:00Z",
            "minor_athlete_age": 16,
        },
        setup["admin"],
    )

    validate_error(response, ApiErrorId.MINOR_ADULT_LODGING_PROHIBITED.value, 409)
    assert_state(
        validate_success(api.get_room_stay(setup["stay"]["id"], NGB_ADMIN_HEADERS)),
        "status",
        "BOOKED",
    )


def _member_under_one_no_contact_directive(api: ApiClient) -> Dict[str, Any]:
    """One ACTIVE NO_CONTACT_DIRECTIVE running 2026-08-05 through 2026-09-05."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Tess Okoro",
                "email": "tess.okoro@alpha.test",
                "role_type": "OFFICIAL",
                "has_minor_athlete_contact": True,
                "date_of_birth": "1984-07-07",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Center for SafeSport",
                "scope_categories": ["PHYSICAL_ABUSE"],
                "max_open_cases": 5,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "PHYSICAL_ABUSE",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "conduct reported during a travel meet",
                "occurred_at": "2026-07-31T22:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    get_success_data(
        api.route_case(case["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS)
    )
    first = get_success_data(
        api.impose_interim_measure(
            case["id"],
            {
                "member_id": member["id"],
                "measure_kind": "NO_CONTACT_DIRECTIVE",
                "effective_from": "2026-08-05T00:00:00Z",
                "effective_to": "2026-09-05T00:00:00Z",
                "expected_member_version": member["version"],
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )
    assert_state(first, "status", "ACTIVE")
    assert_instant_equals(first["effective_to"], "2026-09-05T00:00:00.000Z")
    pinned = get_success_data(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    return {"case": case, "member": pinned, "first": first}


def _second_measure(api: ApiClient, case_id: str, member_id: str, version: int, start: str):
    return api.impose_interim_measure(
        case_id,
        {
            "member_id": member_id,
            "measure_kind": "NO_CONTACT_DIRECTIVE",
            "effective_from": start,
            "effective_to": "2026-10-01T00:00:00Z",
            "expected_member_version": version,
        },
        OFFICER_IMPOSE_HEADERS,
    )


def test_a_measure_starting_exactly_on_the_buffered_end_is_still_a_conflict(
    api: ApiClient,
) -> None:
    """Fourteen days after 2026-09-05 the window is blocked through 2026-09-19 inclusive.

    PRD 3.8 says:
    "Each participating measure occupies its interval from `effective_from` through `effective_to` **plus a trailing 14-day cooling buffer**, and a null `effective_to` extends that occupation indefinitely into the future."
    "A conflict exists when the requested `effective_from` falls at or before the existing measure's buffered end **and** the existing measure's `effective_from` falls at or before the requested end. These endpoints are closed, unlike the room-slot rule: a requested `effective_from` landing exactly on an existing measure's buffered end **is** a conflict."

    Design: Difficulty/resource_temporal_overlap/interim_measure_window_closed_buffer_end_is_still_a_conflict
    """
    setup = _member_under_one_no_contact_directive(api)

    response = _second_measure(
        api,
        setup["case"]["id"],
        setup["member"]["id"],
        setup["member"]["version"],
        "2026-09-19T00:00:00Z",
    )

    validate_error(response, ApiErrorId.MEASURE_WINDOW_CONFLICT.value, 409)
    after = validate_success(api.get_member(setup["member"]["id"], NGB_ADMIN_HEADERS))
    assert_version_is(after, setup["member"]["version"])
    assert_state(
        validate_success(api.get_interim_measure(setup["first"]["id"], NGB_ADMIN_HEADERS)),
        "status",
        "ACTIVE",
    )


def test_a_measure_starting_one_day_past_the_buffered_end_is_accepted(api: ApiClient) -> None:
    """The day after the buffered end the same request is written as a second measure.

    PRD 3.8 says:
    "Only measures for the same member with the same `measure_kind` in status `ACTIVE` participate; `LIFTED` measures are ignored, and a `PERMANENT` measure has already blocked the request earlier at the restriction gate."
    "Hop one creates the measure in status `ACTIVE` with `permanence` of `TEMPORARY` and `imposed_by_user_id` set from the acting `X-User-ID`, leaving `converted_by_user_id`, `lifted_at`, `lift_reason`, and `rationale` null."

    Design: Difficulty/resource_temporal_overlap/interim_measure_window_closed_buffer_end_is_still_a_conflict
    """
    setup = _member_under_one_no_contact_directive(api)
    validate_error(
        _second_measure(
            api,
            setup["case"]["id"],
            setup["member"]["id"],
            setup["member"]["version"],
            "2026-09-19T00:00:00Z",
        ),
        ApiErrorId.MEASURE_WINDOW_CONFLICT.value,
        409,
    )

    measure = validate_success(
        _second_measure(
            api,
            setup["case"]["id"],
            setup["member"]["id"],
            setup["member"]["version"],
            "2026-09-20T00:00:00Z",
        ),
        201,
    )

    assert_state(measure, "status", "ACTIVE")
    assert_state(measure, "permanence", "TEMPORARY")
    assert_instant_equals(measure["effective_from"], "2026-09-20T00:00:00.000Z")
    assert_state(
        validate_success(api.get_interim_measure(setup["first"]["id"], NGB_ADMIN_HEADERS)),
        "status",
        "ACTIVE",
    )
