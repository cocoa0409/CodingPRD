"""Composite world builders.

Every builder here drives real API calls and returns the response's `data`
payload directly — never the whole envelope — so no call site ever needs to
reach into `["data"]` itself. Builders assert success as they go, so a broken
precondition surfaces as a setup failure naming the endpoint that refused.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from . import test_users as users
from .constants import (
    CERT_LIFEGUARD,
    CERT_PARAMEDIC,
    DECISION_APPROVED,
    STAFF_MEDIC_1,
    STAFF_PERSON_1,
    STAFF_ROLE_MARSHAL,
    STAFF_ROLE_MEDIC,
    STAFF_ROLE_WATER_SAFETY,
    STAFF_SWIMMER_1,
)

Json = Dict[str, Any]


# ─── The logical clock (PRD §2.5) ───────────────────────────────────────


def set_clock(api, to_iso8601: str, headers: Optional[Dict[str, str]] = None) -> Json:
    """Move the clock and return `{current_utc, expired_permit_ids}`."""
    response = api.set_clock(to_iso8601, headers or users.OFFICER)
    return get_success_data(response)


# ─── Venues and permits (PRD §3.1) ──────────────────────────────────────


def venue(api, **overrides: Any) -> Json:
    return get_success_data(api.create_venue(f.venue_payload(**overrides), users.OFFICER))


def read_venue(api, venue_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_venue(venue_id, headers or users.OFFICER))


def draft_permit(api, venue_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_permit(venue_id, f.permit_payload(**overrides), users.DESIGNER)
    )


def submitted_permit(api, venue_id: str, **overrides: Any) -> Json:
    permit = draft_permit(api, venue_id, **overrides)
    return get_success_data(api.submit_permit(permit["id"], users.DESIGNER))


def approved_permit(api, venue_id: str, **overrides: Any) -> Json:
    """A governing permit: drafted and submitted by the designer, approved by
    a *different* operator identifier, as PRD §2.7 demands."""
    permit = submitted_permit(api, venue_id, **overrides)
    return get_success_data(
        api.decide_permit(
            permit["id"], f.decision_payload(DECISION_APPROVED), users.OFFICER
        )
    )


def read_permit(api, permit_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_permit(permit_id, headers or users.OFFICER))


def permitted_venue(api, venue_kwargs: Optional[dict] = None, **permit_overrides: Any):
    """A parcel with exactly one governing permit. Returns (venue, permit)."""
    parcel = venue(api, **(venue_kwargs or {}))
    permit = approved_permit(api, parcel["id"], **permit_overrides)
    return parcel, permit


# ─── Courses and obstacles (PRD §3.2) ───────────────────────────────────


def course(api, venue_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_course(venue_id, f.course_payload(**overrides), users.DESIGNER)
    )


def read_course(api, course_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_course(course_id, headers or users.DESIGNER))


def obstacle(api, course_id: str, station_index: int = 1, **overrides: Any) -> Json:
    return get_success_data(
        api.create_obstacle(
            course_id, f.obstacle_payload(station_index, **overrides), users.DESIGNER
        )
    )


def read_obstacle(
    api, obstacle_id: str, headers: Optional[Dict[str, str]] = None
) -> Json:
    return get_success_data(api.get_obstacle(obstacle_id, headers or users.DESIGNER))


def validated_course(api, course_id: str) -> Json:
    return get_success_data(api.validate_course(course_id, users.DESIGNER))


def published_course(api, course_id: str) -> Json:
    validated_course(api, course_id)
    return get_success_data(api.publish_course(course_id, users.DIRECTOR))


def three_station_course(
    api,
    venue_id: str,
    course_kwargs: Optional[dict] = None,
    station_kwargs: Optional[List[dict]] = None,
) -> Tuple[Json, List[Json]]:
    """A DRAFT course carrying three ascending-difficulty primary stations.

    The default ratings 4, 6 and 8 give two rises of 2, so the progression
    score is 2.00 and no pair drops at all — the course clears the §3.2 design
    gate. Returns (course, [obstacles in station order]).
    """
    laid = course(api, venue_id, **(course_kwargs or {}))
    defaults = [
        {"difficulty_rating": 4},
        {"difficulty_rating": 6},
        {"difficulty_rating": 8},
    ]
    per_station = station_kwargs or defaults
    stations = [
        obstacle(api, laid["id"], index + 1, **kwargs)
        for index, kwargs in enumerate(per_station)
    ]
    return laid, stations


# ─── Staffing (PRD §3.3) ────────────────────────────────────────────────


def marshal_shift(
    api,
    course_id: str,
    obstacle_id: str,
    staff_person_id: str = STAFF_PERSON_1,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_staff_assignment(
            course_id,
            f.staff_payload(
                STAFF_ROLE_MARSHAL,
                obstacle_id,
                staff_person_id=staff_person_id,
                **overrides,
            ),
            users.SAFETY,
        )
    )


def medic_shift(
    api, course_id: str, staff_person_id: str = STAFF_MEDIC_1, **overrides: Any
) -> Json:
    return get_success_data(
        api.create_staff_assignment(
            course_id,
            f.staff_payload(
                STAFF_ROLE_MEDIC,
                None,
                staff_person_id=staff_person_id,
                certification_level=CERT_PARAMEDIC,
                **overrides,
            ),
            users.SAFETY,
        )
    )


def water_safety_shift(
    api,
    course_id: str,
    obstacle_id: str,
    staff_person_id: str = STAFF_SWIMMER_1,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_staff_assignment(
            course_id,
            f.staff_payload(
                STAFF_ROLE_WATER_SAFETY,
                obstacle_id,
                staff_person_id=staff_person_id,
                certification_level=CERT_LIFEGUARD,
                **overrides,
            ),
            users.SAFETY,
        )
    )


def fully_marshal(
    api,
    course_id: str,
    station: Json,
    person_prefix: str = "person",
    **overrides: Any,
) -> List[Json]:
    """Roster exactly `marshals_required` marshals onto one station.

    Each shift names a distinct human, so the travel-buffered collision rule of
    PRD §3.3 never fires between them.
    """
    shifts = []
    for slot in range(station["marshals_required"]):
        shifts.append(
            marshal_shift(
                api,
                course_id,
                station["id"],
                staff_person_id=f"{person_prefix}-{station['station_index']}-{slot}",
                **overrides,
            )
        )
    return shifts


def vacate(api, assignment_id: str, reason: str = "Walked off the station") -> Json:
    return get_success_data(
        api.vacate_staff_assignment(
            assignment_id, f.vacate_payload(reason), users.SAFETY
        )
    )


# ─── Divisions and heats (PRD §3.4, §3.6) ───────────────────────────────


def division(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_division(f.division_payload(**overrides), users.DIRECTOR)
    )


def wave(api, course_id: str, division_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_wave(
            course_id, f.wave_payload(division_id, **overrides), users.DIRECTOR
        )
    )


def read_wave(api, wave_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_wave(wave_id, headers or users.DIRECTOR))


def lock_roster(api, wave_id: str) -> Json:
    return get_success_data(api.lock_roster(wave_id, users.DIRECTOR))


def hold(api, wave_id: str, reason: str = "Weather cell overhead") -> Json:
    return get_success_data(
        api.hold_wave(wave_id, f.hold_payload(True, reason=reason), users.DIRECTOR)
    )


def unhold(api, wave_id: str) -> Json:
    return get_success_data(
        api.hold_wave(wave_id, f.hold_payload(False), users.DIRECTOR)
    )


def release(api, wave_id: str) -> Json:
    return get_success_data(api.release_wave(wave_id, users.DIRECTOR))


def start(api, wave_id: str) -> Json:
    return get_success_data(api.start_wave(wave_id, users.DIRECTOR))


def close(api, wave_id: str) -> Json:
    return get_success_data(api.close_wave(wave_id, users.DIRECTOR))


# ─── Participants and entries (PRD §3.5) ────────────────────────────────


def participant(api, **overrides: Any) -> Json:
    return get_success_data(
        api.create_participant(f.participant_payload(**overrides), users.OPS)
    )


def cleared_participant(api, **overrides: Any) -> Json:
    """An enrolled human who has signed the waiver and reads CLEARED."""
    human = participant(api, **overrides)
    return get_success_data(
        api.sign_waiver(
            human["id"],
            f.waiver_payload(),
            users.participant_headers(human["id"]),
        )
    )


def held_participant(api, medical_flags: List[str], **overrides: Any) -> Json:
    """An enrolled human whose declared flags drive them to MEDICALLY_HELD."""
    human = participant(api, **overrides)
    return get_success_data(
        api.sign_waiver(
            human["id"],
            f.waiver_payload(medical_flags=medical_flags),
            users.participant_headers(human["id"]),
        )
    )


def read_participant(
    api, participant_id: str, headers: Optional[Dict[str, str]] = None
) -> Json:
    return get_success_data(api.get_participant(participant_id, headers or users.OPS))


def entry(api, wave_id: str, participant_id: str, bib_number: int = 1, **overrides: Any):
    return get_success_data(
        api.create_entry(
            wave_id,
            f.entry_payload(participant_id, bib_number, **overrides),
            users.OPS,
        )
    )


def registered_entry(api, wave_id: str, bib_number: int = 1, **overrides: Any) -> Json:
    """Enrol a fresh cleared human and register them into the heat."""
    human = cleared_participant(api)
    return entry(api, wave_id, human["id"], bib_number, **overrides)


def check_in(api, entry_id: str, chip_start_offset_seconds: int = 0, **overrides: Any):
    return get_success_data(
        api.check_in_entry(
            entry_id,
            f.check_in_payload(chip_start_offset_seconds, **overrides),
            users.OPS,
        )
    )


def checked_in_entry(
    api,
    wave_id: str,
    bib_number: int = 1,
    chip_start_offset_seconds: int = 0,
    **overrides: Any,
) -> Json:
    created = registered_entry(api, wave_id, bib_number, **overrides)
    return check_in(api, created["id"], chip_start_offset_seconds)


def read_entry(api, entry_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_entry(entry_id, headers or users.DIRECTOR))


# ─── Attempts, finishes and protests (PRD §3.7, §3.8) ───────────────────


def attempt(
    api,
    entry_id: str,
    obstacle_id: str,
    outcome: str,
    headers: Optional[Dict[str, str]] = None,
) -> Json:
    return get_success_data(
        api.create_attempt(
            entry_id,
            f.attempt_payload(obstacle_id, outcome),
            headers or users.MARSHAL,
        )
    )


def finish(api, entry_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.finish_entry(entry_id, headers or users.DIRECTOR))


def protest(api, entry_id: str, participant_id: str, disputed_attempt_id: str) -> Json:
    return get_success_data(
        api.create_protest(
            entry_id,
            f.protest_payload(disputed_attempt_id),
            users.participant_headers(participant_id),
        )
    )


def adjudicate(
    api,
    entry_id: str,
    outcome: str,
    expected_entry_version: int,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Json:
    return get_success_data(
        api.create_adjudication(
            entry_id,
            f.adjudication_payload(outcome, expected_entry_version, **overrides),
            headers or users.DIRECTOR,
        )
    )


# ─── Festival area, restoration and the bond (PRD §3.9) ─────────────────


def festival_service(api, venue_id: str, **overrides: Any) -> Json:
    return get_success_data(
        api.create_festival_service(
            venue_id, f.festival_service_payload(**overrides), users.OPS
        )
    )


def restoration_task(api, venue_id: str, area_sqm: int = 1500, **overrides: Any) -> Json:
    return get_success_data(
        api.create_restoration_task(
            venue_id, f.restoration_task_payload(area_sqm, **overrides), users.OFFICER
        )
    )


def inspect(api, task_id: str, outcome: str, **overrides: Any) -> Json:
    return get_success_data(
        api.inspect_restoration_task(
            task_id, f.inspection_payload(outcome, **overrides), users.OFFICER
        )
    )


def read_task(api, task_id: str, headers: Optional[Dict[str, str]] = None) -> Json:
    return get_success_data(api.get_restoration_task(task_id, headers or users.OFFICER))


def settle_bond(
    api, venue_id: str, expected_venue_version: int, settlement_type: str
) -> Json:
    return get_success_data(
        api.create_bond_release(
            venue_id,
            f.bond_release_payload(expected_venue_version, settlement_type),
            users.OFFICER,
        )
    )
