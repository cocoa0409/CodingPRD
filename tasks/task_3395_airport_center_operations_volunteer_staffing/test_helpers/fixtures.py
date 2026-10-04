"""Composite setup helpers.

Each helper drives the real API and returns parsed response data. Setup
calls use the lenient get_success_data validator so a setup failure
surfaces as a clear error naming the step, not an assertion deep inside a
test body.

Identity threading: volunteers and guests are entity-backed identities —
every ownership-gated call is made with make_volunteer_headers(v["id"]) /
make_guest_headers(g["id"]). Screening claim and decision always use two
different managers (segregation of duties).

Clock discipline: helpers that depend on the business date set the logical
clock explicitly first. Nothing here reads wall-clock time.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_UTC
from .factories import (
    activate_agreement_payload,
    complete_assignment_payload,
    create_assignment_payload,
    create_center_payload,
    create_check_in_payload,
    create_donation_lot_payload,
    create_event_payload,
    create_expense_payload,
    create_funding_grant_payload,
    create_guest_payload,
    create_screening_payload,
    create_service_booking_payload,
    create_shift_payload,
    create_site_agreement_payload,
    create_tour_event_payload,
    create_volunteer_payload,
    decide_screening_payload,
    renew_agreement_payload,
    reverify_guest_payload,
    consume_lot_payload,
)
from .test_users import (
    MANAGER_1_USER_ID,
    MANAGER_2_USER_ID,
    TEST_USERS,
    make_guest_headers,
    make_manager_headers,
    make_volunteer_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ANON = TEST_USERS["anonymous_headers"]
MGR1 = TEST_USERS["manager_1_headers"]  # claims screenings
MGR2 = TEST_USERS["manager_2_headers"]  # decides screenings


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str = CLOCK_DEFAULT_UTC, api=api_client) -> str:
    """Set the logical clock; returns the resulting current_utc.

    With no argument, resets to the default start (2026-09-01T00:00:00Z).
    """
    data = get_success_data(api.set_clock(to_iso8601, ADMIN))
    return data.get("current_utc", to_iso8601)


def reset_clock(api=api_client) -> str:
    """Return the logical clock to its default start (2026-09-01T00:00:00Z)."""
    return set_clock(CLOCK_DEFAULT_UTC, api=api)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation (thin, validated)
# ---------------------------------------------------------------------------
def create_center(api=api_client, **overrides) -> dict:
    resp = api.create_center(create_center_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_volunteer(center_id, api=api_client, **overrides) -> dict:
    resp = api.create_volunteer(create_volunteer_payload(center_id, **overrides), ANON)
    return get_success_data(resp)


def create_guest(api=api_client, **overrides) -> dict:
    resp = api.create_guest(create_guest_payload(**overrides), ANON)
    return get_success_data(resp)


def create_shift(center_id, api=api_client, **overrides) -> dict:
    resp = api.create_shift(center_id, create_shift_payload(**overrides), MGR1)
    return get_success_data(resp)


def create_donation_lot(center_id, api=api_client, **overrides) -> dict:
    resp = api.create_donation_lot(
        center_id, create_donation_lot_payload(**overrides), MGR1
    )
    return get_success_data(resp)


def create_event(center_id, api=api_client, **overrides) -> dict:
    resp = api.create_event(center_id, create_event_payload(**overrides), MGR1)
    return get_success_data(resp)


def create_tour_event(center_id, api=api_client, **overrides) -> dict:
    resp = api.create_event(
        center_id, create_tour_event_payload(**overrides), MGR1
    )
    return get_success_data(resp)


def create_funding_grant(center_id, api=api_client, **overrides) -> dict:
    resp = api.create_funding_grant(
        create_funding_grant_payload(center_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def get_center(center_id, api=api_client) -> dict:
    return get_success_data(api.get_center(center_id, MGR1))


def get_volunteer(volunteer_id, api=api_client) -> dict:
    return get_success_data(api.get_volunteer(volunteer_id, MGR1))


def get_shift(shift_id, api=api_client) -> dict:
    return get_success_data(api.get_shift(shift_id, MGR1))


def get_assignment(assignment_id, api=api_client) -> dict:
    return get_success_data(api.get_assignment(assignment_id, MGR1))


def run_ops(center_id, api=api_client) -> dict:
    """Run the operations checkpoint; returns the updated center."""
    return get_success_data(api.run_ops(center_id, MGR1))


# ---------------------------------------------------------------------------
# Tier 2: site agreement lifecycle
# ---------------------------------------------------------------------------
def draft_agreement(center_id, api=api_client, **overrides) -> dict:
    resp = api.create_site_agreement(
        center_id, create_site_agreement_payload(**overrides), ADMIN
    )
    return get_success_data(resp)


def activate_agreement(agreement_id, expected_center_version, api=api_client) -> dict:
    resp = api.activate_site_agreement(
        agreement_id,
        activate_agreement_payload(expected_center_version),
        ADMIN,
    )
    return get_success_data(resp)


def create_center_with_active_agreement(
    api=api_client, center_overrides=None, agreement_overrides=None
) -> tuple:
    """Center + one SUBMITTED agreement + activation.

    Returns (center, agreement) where center is re-read after activation
    (posture recomputed, active_agreement_id set, version bumped).
    """
    center = create_center(api=api, **(center_overrides or {}))
    agreement = draft_agreement(center["id"], api=api, **(agreement_overrides or {}))
    agreement = activate_agreement(agreement["id"], center["version"], api=api)
    center = get_center(center["id"], api=api)
    return center, agreement


def renew_agreement(agreement_id, new_end_date, api=api_client) -> dict:
    resp = api.renew_site_agreement(
        agreement_id, renew_agreement_payload(new_end_date), ADMIN
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: volunteer vetting (segregation of duties built in)
# ---------------------------------------------------------------------------
def open_screening(volunteer_id, expected_volunteer_version, api=api_client) -> dict:
    resp = api.create_screening(
        volunteer_id,
        create_screening_payload(expected_volunteer_version),
        MGR1,
    )
    return get_success_data(resp)


def claim_screening(screening_id, api=api_client, manager_user_id=MANAGER_1_USER_ID) -> dict:
    resp = api.claim_screening(
        screening_id, make_manager_headers(manager_user_id)
    )
    return get_success_data(resp)


def decide_screening(
    screening_id, verdict="CLEARED", api=api_client,
    decider_user_id=MANAGER_2_USER_ID,
) -> dict:
    """Decide an IN_REVIEW screening. decider defaults to MANAGER_2 so the
    decider always differs from the default claimer (MANAGER_1)."""
    resp = api.decide_screening(
        screening_id,
        decide_screening_payload(verdict),
        make_manager_headers(decider_user_id),
    )
    return get_success_data(resp)


def create_cleared_volunteer(center_id, api=api_client, **overrides) -> dict:
    """Volunteer driven through APPLIED -> SCREENING -> CLEARED.

    Claim as manager 1, decide as manager 2 (segregation of duties).
    Returns the re-read volunteer (status CLEARED).
    """
    volunteer = create_volunteer(center_id, api=api, **overrides)
    screening = open_screening(volunteer["id"], volunteer["version"], api=api)
    claim_screening(screening["id"], api=api)
    decide_screening(screening["id"], "CLEARED", api=api)
    return get_volunteer(volunteer["id"], api=api)


# ---------------------------------------------------------------------------
# Tier 4: shifts, assignments, coverage
# ---------------------------------------------------------------------------
def assign_volunteer(shift_id, volunteer_id, api=api_client) -> dict:
    resp = api.create_assignment(
        shift_id, create_assignment_payload(volunteer_id), MGR1
    )
    return get_success_data(resp)


def confirm_assignment(assignment_id, volunteer_id, api=api_client) -> dict:
    """Confirm as the owning volunteer (entity-backed identity)."""
    resp = api.confirm_assignment(
        assignment_id, make_volunteer_headers(volunteer_id)
    )
    return get_success_data(resp)


def cancel_assignment_as_manager(assignment_id, api=api_client) -> dict:
    return get_success_data(api.cancel_assignment(assignment_id, MGR1))


def complete_assignment(assignment_id, actual_hours=2.0, api=api_client) -> dict:
    resp = api.complete_assignment(
        assignment_id, complete_assignment_payload(actual_hours), MGR1
    )
    return get_success_data(resp)


def mark_no_show(assignment_id, api=api_client) -> dict:
    return get_success_data(api.mark_no_show(assignment_id, MGR1))


def create_shift_with_confirmed_volunteer(
    center_id, api=api_client, shift_overrides=None, volunteer_overrides=None
) -> tuple:
    """Cleared volunteer assigned and confirmed on one shift.

    Returns (volunteer, shift, assignment) with the volunteer re-read
    (status ACTIVE after first confirm) and the shift re-read.
    """
    volunteer = create_cleared_volunteer(
        center_id, api=api, **(volunteer_overrides or {})
    )
    shift = create_shift(center_id, api=api, **(shift_overrides or {}))
    assignment = assign_volunteer(shift["id"], volunteer["id"], api=api)
    assignment = confirm_assignment(assignment["id"], volunteer["id"], api=api)
    volunteer = get_volunteer(volunteer["id"], api=api)
    shift = get_shift(shift["id"], api=api)
    return volunteer, shift, assignment


def setup_open_center(
    api=api_client,
    clock_iso=CLOCK_DEFAULT_UTC,
    center_overrides=None,
    shift_overrides=None,
) -> tuple:
    """Center at posture OPEN: ACTIVE agreement plus one volunteer confirmed
    on a shift whose start_at falls on the clock's current date, with
    required_daily_confirmed_assignments == 1 (coverage 1.0 >= 0.75).

    Sets the clock first. Returns (center, volunteer, shift, assignment).
    """
    set_clock(clock_iso, api=api)
    overrides = {"required_daily_confirmed_assignments": 1}
    overrides.update(center_overrides or {})
    center, _agreement = create_center_with_active_agreement(
        api=api, center_overrides=overrides
    )
    shift_defaults = {
        "start_at": f"{clock_iso[:10]}T06:00:00Z",
        "end_at": f"{clock_iso[:10]}T10:00:00Z",
        "capacity": 1,
    }
    shift_defaults.update(shift_overrides or {})
    volunteer, shift, assignment = create_shift_with_confirmed_volunteer(
        center["id"], api=api, shift_overrides=shift_defaults
    )
    center = get_center(center["id"], api=api)
    return center, volunteer, shift, assignment


# ---------------------------------------------------------------------------
# Tier 5: guests, visits, bookings
# ---------------------------------------------------------------------------
def check_in_guest(center_id, guest_id, api=api_client) -> dict:
    resp = api.create_check_in(
        center_id, create_check_in_payload(guest_id), MGR1
    )
    return get_success_data(resp)


def book_service(center_id, guest_id, api=api_client, as_guest=False, **overrides) -> dict:
    headers = make_guest_headers(guest_id) if as_guest else MGR1
    resp = api.create_service_booking(
        center_id, create_service_booking_payload(guest_id, **overrides), headers
    )
    return get_success_data(resp)


def reverify_guest(guest_id, verification_expires_on, api=api_client) -> dict:
    resp = api.reverify_guest(
        guest_id, reverify_guest_payload(verification_expires_on), MGR1
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 6: donations, events, money
# ---------------------------------------------------------------------------
def consume_lot(lot_id, quantity=1, api=api_client) -> dict:
    resp = api.consume_donation_lot(lot_id, consume_lot_payload(quantity), MGR1)
    return get_success_data(resp)


def post_expense(center_id, api=api_client, **overrides) -> dict:
    """Post an expense with a freshly-read center version (OCC)."""
    center = get_center(center_id, api=api)
    resp = api.create_expense(
        center_id, create_expense_payload(center["version"], **overrides), MGR1
    )
    return get_success_data(resp)


def approve_event_security(event_id, api=api_client) -> dict:
    return get_success_data(api.approve_event_security(event_id, ADMIN))


def confirm_event(event_id, api=api_client) -> dict:
    return get_success_data(api.confirm_event(event_id, MGR1))


def cancel_event(event_id, api=api_client) -> dict:
    return get_success_data(api.cancel_event(event_id, MGR1))


def get_cost_report(center_id, api=api_client) -> dict:
    return get_success_data(api.get_cost_report(center_id, MGR1))
