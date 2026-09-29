"""Actor headers for the six declared roles.

Five roles are opaque operator identities, so a fixed `X-User-ID` per role is
enough. `PropertyOwner` is entity-backed on `Property`: its `X-User-ID` must be
the id of the very property being acted on, so ownership-gated calls always go
through `make_property_owner_headers(property_id)` rather than a shared entry.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

# Opaque operator identities. Two independent reviewer identities exist so the
# segregation-of-duties rule can be exercised with a completer and a distinct
# verifier.
HOUSING_AGENCY_INSPECTOR_ID = "insp-1"
MAINTENANCE_TECHNICIAN_ID = "tech-1"
QUALITY_ASSURANCE_REVIEWER_ID = "qa-1"
QUALITY_ASSURANCE_REVIEWER_ALT_ID = "qa-2"
APPEALS_OFFICER_ID = "appeals-1"
PLATFORM_ADMIN_ID = "admin-1"

# A PropertyOwner id that belongs to no property at all, for reads that must
# not depend on ownership.
UNOWNED_PROPERTY_OWNER_ID = "owner-unknown"

ROLE_PROPERTY_OWNER = "PropertyOwner"
ROLE_HOUSING_AGENCY_INSPECTOR = "HousingAgencyInspector"
ROLE_MAINTENANCE_TECHNICIAN = "MaintenanceTechnician"
ROLE_QUALITY_ASSURANCE_REVIEWER = "QualityAssuranceReviewer"
ROLE_APPEALS_OFFICER = "AppealsOfficer"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    ROLE_PROPERTY_OWNER,
    ROLE_HOUSING_AGENCY_INSPECTOR,
    ROLE_MAINTENANCE_TECHNICIAN,
    ROLE_QUALITY_ASSURANCE_REVIEWER,
    ROLE_APPEALS_OFFICER,
    ROLE_PLATFORM_ADMIN,
)


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_property_owner_headers(property_id: str) -> Headers:
    """Headers for the owner of `property_id`; the id *is* the user id."""
    return build_user_headers(property_id, ROLE_PROPERTY_OWNER)


def make_housing_agency_inspector_headers(
    user_id: str = HOUSING_AGENCY_INSPECTOR_ID,
) -> Headers:
    return build_user_headers(user_id, ROLE_HOUSING_AGENCY_INSPECTOR)


def make_maintenance_technician_headers(
    user_id: str = MAINTENANCE_TECHNICIAN_ID,
) -> Headers:
    return build_user_headers(user_id, ROLE_MAINTENANCE_TECHNICIAN)


def make_quality_assurance_reviewer_headers(
    user_id: str = QUALITY_ASSURANCE_REVIEWER_ID,
) -> Headers:
    return build_user_headers(user_id, ROLE_QUALITY_ASSURANCE_REVIEWER)


def make_appeals_officer_headers(user_id: str = APPEALS_OFFICER_ID) -> Headers:
    return build_user_headers(user_id, ROLE_APPEALS_OFFICER)


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> Headers:
    return build_user_headers(user_id, ROLE_PLATFORM_ADMIN)


def make_headers(role: str, user_id: str) -> Headers:
    """Headers for any role/user pair, including undeclared role names."""
    return build_user_headers(user_id, role)


def make_headers_without_user_id(role: str) -> Headers:
    """Headers carrying a role but no `X-User-ID` header at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# Shared actors
# ---------------------------------------------------------------------------
TEST_USERS = {
    "property_owner_id": UNOWNED_PROPERTY_OWNER_ID,
    "housing_agency_inspector_id": HOUSING_AGENCY_INSPECTOR_ID,
    "maintenance_technician_id": MAINTENANCE_TECHNICIAN_ID,
    "quality_assurance_reviewer_id": QUALITY_ASSURANCE_REVIEWER_ID,
    "quality_assurance_reviewer_alt_id": QUALITY_ASSURANCE_REVIEWER_ALT_ID,
    "appeals_officer_id": APPEALS_OFFICER_ID,
    "platform_admin_id": PLATFORM_ADMIN_ID,
    # A PropertyOwner entry that reaches no property; ownership-gated calls
    # must use make_property_owner_headers(property_id) instead.
    "property_owner_headers": build_user_headers(
        UNOWNED_PROPERTY_OWNER_ID, ROLE_PROPERTY_OWNER
    ),
    "housing_agency_inspector_headers": build_user_headers(
        HOUSING_AGENCY_INSPECTOR_ID, ROLE_HOUSING_AGENCY_INSPECTOR
    ),
    "maintenance_technician_headers": build_user_headers(
        MAINTENANCE_TECHNICIAN_ID, ROLE_MAINTENANCE_TECHNICIAN
    ),
    "quality_assurance_reviewer_headers": build_user_headers(
        QUALITY_ASSURANCE_REVIEWER_ID, ROLE_QUALITY_ASSURANCE_REVIEWER
    ),
    "quality_assurance_reviewer_alt_headers": build_user_headers(
        QUALITY_ASSURANCE_REVIEWER_ALT_ID, ROLE_QUALITY_ASSURANCE_REVIEWER
    ),
    "appeals_officer_headers": build_user_headers(
        APPEALS_OFFICER_ID, ROLE_APPEALS_OFFICER
    ),
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, ROLE_PLATFORM_ADMIN
    ),
}
