"""Composite fixtures.

The harness restarts the API server before every individual test, so every
fixture below starts from an empty database and every fixture is function
scoped.

Layout:

* Tier 1 - clock and season state progression.
* Tier 2 - entity hierarchy (cabin, guest, horse, staff, slot).
* Tier 3 - lifecycle shortcuts (booking held/confirmed/checked-in, seat, mount).
* Tier 4 - accumulation and threshold targeting (multi-rider slots, multi-mount
  days, staffed slots).
* Tier 5 - finalisation and terminal states (completed slot, checked-out
  booking, closed incident).

Every builder is also exposed as a plain function so tests that need a second
(or differently parameterised) instance can call it directly.  Builders use
``get_success_data`` so a fixture never masks a real assertion failure with a
status-code mismatch of its own.
"""
from typing import Any, Dict, List, Optional, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import (
    ARRIVAL_DATE,
    CLOCK_STARTUP_DEFAULT,
    DEPARTURE_DATE,
    SLOT_ENDS_AT,
    SLOT_STARTS_AT,
)
from .factories import (
    check_in_payload,
    check_out_payload,
    close_incident_payload,
    complete_slot_payload,
    create_activity_slot_payload,
    create_booking_payload,
    create_cabin_payload,
    create_guest_payload,
    create_horse_payload,
    create_season_payload,
    create_staff_member_payload,
    dispose_payload,
    evaluate_assessment_payload,
    guide_assignment_payload,
    incident_report_payload,
    mount_assignment_payload,
    onboard_payload,
    party_member,
    payment_payload,
    reservation_payload,
    rider_assessment_payload,
    waiver_signature_payload,
)
from .test_users import (
    HORSE_PROGRAM_DIRECTOR,
    RANCH_MANAGER,
    RESERVATIONS_AGENT,
    SAFETY_OFFICER,
    SAFETY_OFFICER_TWO,
    make_activity_guide_headers,
)


# --------------------------------------------------------------------------
# session-free client
# --------------------------------------------------------------------------

@pytest.fixture
def client() -> ApiClient:
    """A fresh client bound to the harness-provided base URL."""
    return ApiClient()


# --------------------------------------------------------------------------
# Tier 1 - clock and season state progression
# --------------------------------------------------------------------------

def set_clock_to(client: ApiClient, instant: str) -> Dict[str, Any]:
    """Move the logical clock to ``instant`` (a full ISO-8601 UTC instant)."""
    return get_success_data(client.set_clock(instant, RANCH_MANAGER))


def build_season(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a season; it starts in its declared initial lifecycle state."""
    return get_success_data(client.create_season(create_season_payload(**overrides), RANCH_MANAGER))


def advance_season_to(client: ApiClient, season_id: str, target_status: str) -> Dict[str, Any]:
    return get_success_data(client.advance_season(season_id, target_status, RANCH_MANAGER))


def build_open_season(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Season advanced one lifecycle step, to OPEN."""
    season = build_season(client, **overrides)
    return advance_season_to(client, season["id"], "OPEN")


def build_in_season(client: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Season advanced two lifecycle steps, to IN_SEASON."""
    season = build_open_season(client, **overrides)
    return advance_season_to(client, season["id"], "IN_SEASON")


@pytest.fixture
def planning_season(client: ApiClient) -> Dict[str, Any]:
    return build_season(client)


@pytest.fixture
def open_season(client: ApiClient) -> Dict[str, Any]:
    return build_open_season(client)


@pytest.fixture
def in_season(client: ApiClient) -> Dict[str, Any]:
    return build_in_season(client)


# --------------------------------------------------------------------------
# Tier 2 - entity hierarchy
# --------------------------------------------------------------------------

def build_cabin(client: ApiClient, name: str = "Aspen", bed_capacity: int = 4, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        client.create_cabin(create_cabin_payload(name, bed_capacity, **overrides), RANCH_MANAGER)
    )


@pytest.fixture
def ready_cabin(client: ApiClient) -> Dict[str, Any]:
    return build_cabin(client)


def build_guest(
    client: ApiClient,
    full_name: str = "Ann Adult",
    birth_date: str = "1985-04-02",
    weight_lb: float = 165,
    **overrides: Any,
) -> Dict[str, Any]:
    """A bare guest: no waiver, no assessment."""
    return get_success_data(
        client.create_guest(
            create_guest_payload(full_name, birth_date, weight_lb, **overrides),
            RESERVATIONS_AGENT,
        )
    )


def sign_guest_waiver(
    client: ApiClient,
    guest_id: str,
    signed_on: str = "2026-08-01",
    equine_statute_ack: bool = True,
    guardian_guest_id: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        client.sign_waiver(
            guest_id,
            waiver_signature_payload(signed_on, equine_statute_ack, guardian_guest_id),
            RESERVATIONS_AGENT,
        )
    )


def assess_guest_ability(
    client: ApiClient,
    guest_id: str,
    ability: str = "BEGINNER",
    evaluated_at: str = "2026-08-01T12:00:00Z",
) -> Dict[str, Any]:
    """Raise a rider assessment and evaluate it to ``ability``.

    The assessment write is version-pinned, so the guest row is re-read first.
    """
    guest = get_success_data(client.get_guest(guest_id, RESERVATIONS_AGENT))
    assessment = get_success_data(
        client.create_rider_assessment(
            guest_id,
            rider_assessment_payload(ability, guest["version"]),
            HORSE_PROGRAM_DIRECTOR,
        )
    )
    return get_success_data(
        client.evaluate_rider_assessment(
            assessment["id"],
            evaluate_assessment_payload(ability, "walk-trot in arena", evaluated_at),
            HORSE_PROGRAM_DIRECTOR,
        )
    )


def build_ready_rider(
    client: ApiClient,
    full_name: str = "Ann Adult",
    birth_date: str = "1985-04-02",
    weight_lb: float = 165,
    ability: str = "BEGINNER",
    signed_on: str = "2026-08-01",
    guardian_guest_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Guest with a live waiver and an evaluated ability rank."""
    guest = build_guest(client, full_name, birth_date, weight_lb, **overrides)
    sign_guest_waiver(client, guest["id"], signed_on, True, guardian_guest_id)
    assess_guest_ability(client, guest["id"], ability)
    return get_success_data(client.get_guest(guest["id"], RESERVATIONS_AGENT))


@pytest.fixture
def adult_guest(client: ApiClient) -> Dict[str, Any]:
    return build_guest(client)


@pytest.fixture
def adult_rider(client: ApiClient) -> Dict[str, Any]:
    return build_ready_rider(client)


def build_horse(
    client: ApiClient,
    name: str = "Comet",
    min_rider_ability: str = "BEGINNER",
    max_rider_ability: str = "ADVANCED",
    weight_limit_lb: float = 240,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        client.create_horse(
            create_horse_payload(name, min_rider_ability, max_rider_ability, weight_limit_lb, **overrides),
            HORSE_PROGRAM_DIRECTOR,
        )
    )


@pytest.fixture
def horse(client: ApiClient) -> Dict[str, Any]:
    return build_horse(client)


def build_staff_member(
    client: ApiClient,
    season_id: str,
    full_name: str = "Gus Guide",
    role_type: str = "GUIDE",
    certifications: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Staff member in the freshly-hired state (not yet onboarded)."""
    return get_success_data(
        client.create_staff_member(
            season_id,
            create_staff_member_payload(
                full_name=full_name,
                role_type=role_type,
                certifications=certifications,
                **overrides,
            ),
            RANCH_MANAGER,
        )
    )


def build_active_guide(
    client: ApiClient,
    season_id: str,
    full_name: str = "Gus Guide",
    certifications: Optional[List[str]] = None,
    housing_unit_code: str = "BUNKHOUSE-A",
    housing_bunk_number: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    """Hired then onboarded guide, ready to be scheduled onto a slot."""
    staff = build_staff_member(
        client, season_id, full_name=full_name, certifications=certifications, **overrides
    )
    return get_success_data(
        client.onboard_staff_member(
            staff["id"], onboard_payload(housing_unit_code, housing_bunk_number), RANCH_MANAGER
        )
    )


def build_activity_slot(client: ApiClient, season_id: str, **overrides: Any) -> Dict[str, Any]:
    """Activity slot in its declared initial state (not yet opened)."""
    return get_success_data(
        client.create_activity_slot(
            season_id, create_activity_slot_payload(**overrides), RANCH_MANAGER
        )
    )


def assign_guide(
    client: ApiClient,
    slot_id: str,
    staff_member_id: str,
    guide_role: str = "LEAD",
) -> Dict[str, Any]:
    return get_success_data(
        client.create_guide_assignment(
            slot_id, guide_assignment_payload(staff_member_id, guide_role), RANCH_MANAGER
        )
    )


def build_staffed_slot(
    client: ApiClient,
    season_id: str,
    guide_count: int = 1,
    slot_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Slot plus ``guide_count`` scheduled guides, still unopened.

    Returns ``(slot, staff_members)`` where the staff list is in assignment
    order; ``staff_members[0]`` holds the LEAD role.
    """
    slot = build_activity_slot(client, season_id, **(slot_overrides or {}))
    staff: List[Dict[str, Any]] = []
    for index in range(guide_count):
        guide = build_active_guide(
            client,
            season_id,
            full_name=f"Gus Guide {index + 1}",
            housing_bunk_number=index + 1,
        )
        assign_guide(
            client, slot["id"], guide["id"], "LEAD" if index == 0 else "ASSISTANT"
        )
        staff.append(guide)
    slot = get_success_data(client.get_activity_slot(slot["id"], RANCH_MANAGER))
    return slot, staff


def open_slot(client: ApiClient, slot_id: str) -> Dict[str, Any]:
    return get_success_data(client.open_slot(slot_id, RANCH_MANAGER))


def build_open_slot(
    client: ApiClient,
    season_id: str,
    guide_count: int = 1,
    slot_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Staffed slot advanced to the seat-selling state."""
    slot, staff = build_staffed_slot(client, season_id, guide_count, slot_overrides)
    slot = open_slot(client, slot["id"])
    return slot, staff


# --------------------------------------------------------------------------
# Tier 3 - booking lifecycle shortcuts
# --------------------------------------------------------------------------

def build_booking(
    client: ApiClient,
    season_id: str,
    cabin_id: str,
    members: List[Dict[str, Any]],
    package_tier_code: str = "CLASSIC",
    arrival_date: str = ARRIVAL_DATE,
    departure_date: str = DEPARTURE_DATE,
    is_buyout: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Booking in its declared initial state, awaiting its deposit.

    ``members`` are ``party_member`` dicts; the first one is the lead guest.
    """
    return get_success_data(
        client.create_booking(
            create_booking_payload(
                season_id,
                cabin_id,
                members[0]["guest_id"],
                members,
                package_tier_code,
                arrival_date,
                departure_date,
                is_buyout,
                **overrides,
            ),
            RESERVATIONS_AGENT,
        )
    )


def pay_deposit(client: ApiClient, booking_id: str, amount_cents: Optional[int] = None) -> Dict[str, Any]:
    """Pay exactly the required deposit (or ``amount_cents`` when supplied)."""
    booking = get_success_data(client.get_booking(booking_id, RESERVATIONS_AGENT))
    amount = booking["deposit_required_cents"] if amount_cents is None else amount_cents
    return get_success_data(
        client.post_payment(booking_id, payment_payload(amount, "DEPOSIT"), RESERVATIONS_AGENT)
    )


def confirm_booking(client: ApiClient, booking_id: str) -> Dict[str, Any]:
    return get_success_data(client.confirm_booking(booking_id, RESERVATIONS_AGENT))


def build_confirmed_booking(
    client: ApiClient,
    season_id: str,
    cabin_id: str,
    members: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    """Booking with its deposit settled and its hold converted."""
    booking = build_booking(client, season_id, cabin_id, members, **overrides)
    pay_deposit(client, booking["id"])
    return confirm_booking(client, booking["id"])


def check_in(client: ApiClient, booking_id: str, dietary_briefing_ack: bool = True) -> Dict[str, Any]:
    return get_success_data(
        client.check_in_booking(booking_id, check_in_payload(dietary_briefing_ack), RESERVATIONS_AGENT)
    )


def build_checked_in_booking(
    client: ApiClient,
    season_id: str,
    cabin_id: str,
    members: List[Dict[str, Any]],
    dietary_briefing_ack: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """In-house booking: confirmed, then checked in against its cabin."""
    booking = build_confirmed_booking(client, season_id, cabin_id, members, **overrides)
    return check_in(client, booking["id"], dietary_briefing_ack)


def take_seat(client: ApiClient, slot_id: str, booking_id: str, guest_id: str) -> Dict[str, Any]:
    """Reserve a seat on ``slot_id``, pinning the slot version read just now."""
    slot = get_success_data(client.get_activity_slot(slot_id, RANCH_MANAGER))
    return get_success_data(
        client.create_reservation(
            slot_id,
            reservation_payload(booking_id, guest_id, slot["version"]),
            RESERVATIONS_AGENT,
        )
    )


def attach_mount(client: ApiClient, reservation_id: str, horse_id: str) -> Dict[str, Any]:
    """Assign ``horse_id`` to a seat, pinning the horse version read just now."""
    horse_row = get_success_data(client.get_horse(horse_id, HORSE_PROGRAM_DIRECTOR))
    return get_success_data(
        client.assign_mount(
            reservation_id,
            mount_assignment_payload(horse_id, horse_row["version"]),
            HORSE_PROGRAM_DIRECTOR,
        )
    )


# --------------------------------------------------------------------------
# Tier 4 - accumulation and threshold targeting
# --------------------------------------------------------------------------

def build_ride_scenario(
    client: ApiClient,
    rider_specs: Optional[List[Dict[str, Any]]] = None,
    guide_count: int = 1,
    slot_overrides: Optional[Dict[str, Any]] = None,
    season_overrides: Optional[Dict[str, Any]] = None,
    cabin_bed_capacity: int = 4,
    package_tier_code: str = "CLASSIC",
    horse_count: int = 0,
    seat_riders: bool = True,
) -> Dict[str, Any]:
    """One in-service season with a checked-in booking and an open ride slot.

    ``rider_specs`` is a list of dicts accepted by ``build_ready_rider`` plus an
    optional ``member_type`` and ``dietary_restrictions`` key each; the first
    rider is the lead guest.  Returns a dict with keys ``season``, ``cabin``,
    ``guests``, ``booking``, ``slot``, ``staff``, ``horses`` and
    ``reservations``.
    """
    specs = rider_specs if rider_specs is not None else [{}]
    season = build_in_season(client, **(season_overrides or {}))
    cabin = build_cabin(client, bed_capacity=cabin_bed_capacity)

    guests: List[Dict[str, Any]] = []
    members: List[Dict[str, Any]] = []
    for index, spec in enumerate(specs):
        spec = dict(spec)
        member_type = spec.pop("member_type", "ADULT")
        dietary = spec.pop("dietary_restrictions", None)
        spec.setdefault("full_name", f"Rider {index + 1}")
        guest = build_ready_rider(client, **spec)
        guests.append(guest)
        members.append(party_member(guest["id"], member_type, dietary))

    booking = build_checked_in_booking(
        client,
        season["id"],
        cabin["id"],
        members,
        package_tier_code=package_tier_code,
    )

    slot, staff = build_open_slot(client, season["id"], guide_count, slot_overrides)

    horses = [
        build_horse(client, name=f"Horse {index + 1}") for index in range(horse_count)
    ]

    reservations: List[Dict[str, Any]] = []
    if seat_riders:
        for guest in guests:
            reservations.append(take_seat(client, slot["id"], booking["id"], guest["id"]))
        slot = get_success_data(client.get_activity_slot(slot["id"], RANCH_MANAGER))

    return {
        "season": season,
        "cabin": cabin,
        "guests": guests,
        "booking": booking,
        "slot": slot,
        "staff": staff,
        "horses": horses,
        "reservations": reservations,
    }


@pytest.fixture
def ride_scenario(client: ApiClient) -> Dict[str, Any]:
    """Single adult BEGINNER rider, one guide, one horse, seat already taken."""
    return build_ride_scenario(client, horse_count=1)


# --------------------------------------------------------------------------
# Tier 5 - finalisation and terminal states
# --------------------------------------------------------------------------

def run_and_complete_slot(
    client: ApiClient,
    slot_id: str,
    lead_staff_member_id: str,
    run_at: str = SLOT_STARTS_AT,
    actual_duration_hours: float = 2.0,
) -> Dict[str, Any]:
    """Move the clock to the scheduled start, run the slot, then complete it.

    Both writes are made by the guide whose scheduled assignment covers the
    slot, so ``lead_staff_member_id`` must be that staff member's id.
    """
    guide_headers = make_activity_guide_headers(lead_staff_member_id)
    set_clock_to(client, run_at)
    get_success_data(client.run_slot(slot_id, guide_headers))
    return get_success_data(
        client.complete_slot(
            slot_id, complete_slot_payload(actual_duration_hours), guide_headers
        )
    )


def check_out(client: ApiClient, booking_id: str, settle_payment_cents: Optional[int] = None) -> Dict[str, Any]:
    """Check out, settling exactly the outstanding folio balance by default."""
    booking = get_success_data(client.get_booking(booking_id, RESERVATIONS_AGENT))
    amount = (
        booking["folio_balance_cents"] if settle_payment_cents is None else settle_payment_cents
    )
    return get_success_data(
        client.check_out_booking(booking_id, check_out_payload(amount), RESERVATIONS_AGENT)
    )


def build_filed_incident(
    client: ApiClient,
    reservation_id: str,
    severity: str = "MINOR",
    horse_id: Optional[str] = None,
    guide_staff_member_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File a report against a seat.

    A report is filed by the guide working the slot, so
    ``guide_staff_member_id`` must be the staff member whose scheduled guide
    assignment covers the seat's slot.
    """
    headers = (
        make_activity_guide_headers(guide_staff_member_id)
        if guide_staff_member_id is not None
        else SAFETY_OFFICER
    )
    return get_success_data(
        client.create_incident_report(
            reservation_id,
            incident_report_payload(severity=severity, horse_id=horse_id, **overrides),
            headers,
        )
    )


def dispose_incident(
    client: ApiClient,
    incident_report_id: str,
    disposition: str = "CLEARED",
    disposition_note: str = "no equipment defect found",
) -> Dict[str, Any]:
    """Disposition by safety officer one."""
    return get_success_data(
        client.dispose_incident_report(
            incident_report_id, dispose_payload(disposition, disposition_note), SAFETY_OFFICER
        )
    )


def close_incident(
    client: ApiClient, incident_report_id: str, remediation_completed: bool = False
) -> Dict[str, Any]:
    """Close by safety officer two - a different acting identity from the one
    that recorded the disposition."""
    return get_success_data(
        client.close_incident_report(
            incident_report_id,
            close_incident_payload(remediation_completed),
            SAFETY_OFFICER_TWO,
        )
    )
