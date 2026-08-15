"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (the server never compares their X-User-ID to an entity id) have
shared constants. Entity-backed roles (Parent -> Family, Volunteer ->
Volunteer) MUST be built per-instance with the acting entity's id via the
builders below whenever the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

from . import constants


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "check_in_staff_headers": build_user_headers(constants.CHECKIN_DESK_ID, "CheckInStaff"),
    "registration_coordinator_headers": build_user_headers(
        constants.REGISTRATION_COORDINATOR_ID, "RegistrationCoordinator"
    ),
    "volunteer_coordinator_headers": build_user_headers(
        constants.VOLUNTEER_COORDINATOR_ID, "VolunteerCoordinator"
    ),
    "safety_officer_headers": build_user_headers(constants.SAFETY_OFFICER_ID, "SafetyOfficer"),
    "program_director_headers": build_user_headers(constants.DIRECTOR_ID, "ProgramDirector"),
    # Entity-backed roles — fallback constants ONLY for tests that do not
    # exercise ownership (bad-payload / missing-resource calls).
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
}


def make_parent_headers(family_id: str) -> dict:
    """Parent is entity-backed by Family: X-User-ID must equal the Family.id
    whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(family_id, "Parent")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """Volunteer is entity-backed by Volunteer: X-User-ID must equal the
    Volunteer.id whenever the call is ownership-gated (PRD §2.1)."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_safety_officer_headers(officer_id: str) -> dict:
    """SafetyOfficer with a caller-chosen id (used to exercise self-review,
    where X-User-ID is compared to the check's volunteer_id)."""
    return build_user_headers(officer_id, "SafetyOfficer")
