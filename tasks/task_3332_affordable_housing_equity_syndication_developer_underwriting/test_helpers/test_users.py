"""Pre-built role headers for all seven roles (PRD §2.1).

Two of the seven roles are entity-backed: for ``Developer`` and ``Investor``
the ``X-User-ID`` header is not a label but the ``id`` of a persisted record,
and every ownership check compares it to that record. Whenever a call is
ownership-gated — a Developer reading its own projects, an Investor paying into
its own subscription, an Investor settling a call in its own fund — the header
must be built from the *actual entity's* id:

    investor = onboard_investor()["..."]
    headers = make_investor_headers(investor["id"])

Falling back to the shared ``TEST_USERS`` constant for an entity-backed role
produces a header whose id matches no entity, so every scoped call is rejected
and whole fixtures cascade into "Setup failed" errors.

The shared constants remain correct for opaque roles, and for entity-backed
tests whose success does not depend on ownership (a 400 on a malformed payload,
a 404 on a missing resource, or a role-authority denial).
"""

from prd_bench_local_runner.testing import build_user_headers

__all__ = [
    "TEST_USERS",
    "NO_ROLE_HEADERS",
    "ROLE_NAMES",
    "ENTITY_BACKED_ROLES",
    "OPAQUE_ROLES",
    "make_developer_headers",
    "make_investor_headers",
    "make_underwriter_headers",
    "make_asset_manager_headers",
    "make_compliance_officer_headers",
    "make_platform_admin_headers",
    "make_anonymous_headers",
    "headers_for",
]


#: The seven declared role names, in PRD §2.1 order.
ROLE_NAMES = (
    "Developer",
    "Investor",
    "Underwriter",
    "AssetManager",
    "ComplianceOfficer",
    "Anonymous",
    "PlatformAdmin",
)

#: Roles whose ``X-User-ID`` must be the id of a persisted entity.
ENTITY_BACKED_ROLES = ("Developer", "Investor")

#: Roles whose ``X-User-ID`` is an opaque operator identifier.
OPAQUE_ROLES = ("Underwriter", "AssetManager", "ComplianceOfficer", "Anonymous", "PlatformAdmin")


#: Headers with no ``X-User-Role`` at all — the 401 authentication-failure path.
NO_ROLE_HEADERS = {"Content-Type": "application/json"}


#: Shared header constants. Safe for opaque roles and for non-ownership tests;
#: entity-backed roles should prefer the ``make_*_headers(entity_id)`` builders.
TEST_USERS = {
    # entity_backed:Developer — shared constant is a fallback for tests that do
    # not exercise ownership. Ownership-gated calls MUST use the builder.
    "developer_headers": build_user_headers("test-developer-1", "Developer"),
    # entity_backed:Investor — same rule.
    "investor_headers": build_user_headers("test-investor-1", "Investor"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "asset_manager_headers": build_user_headers("test-asset-manager-1", "AssetManager"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    # The sentinel role: never permitted on any endpoint, always 401.
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_developer_headers(user_id: str) -> dict:
    """Headers for a Developer (entity_backed:Developer).

    Pass the actual ``Developer.id`` whenever the call is ownership-gated.
    """
    return build_user_headers(user_id, "Developer")


def make_investor_headers(user_id: str) -> dict:
    """Headers for an Investor (entity_backed:Investor).

    Pass the actual ``Investor.id`` whenever the call is ownership-gated — in
    particular for pay-ins and for settling a call in the investor's fund.
    """
    return build_user_headers(user_id, "Investor")


def make_underwriter_headers(user_id: str = "test-underwriter-1") -> dict:
    """Headers for an Underwriter (opaque)."""
    return build_user_headers(user_id, "Underwriter")


def make_asset_manager_headers(user_id: str = "test-asset-manager-1") -> dict:
    """Headers for an AssetManager (opaque)."""
    return build_user_headers(user_id, "AssetManager")


def make_compliance_officer_headers(user_id: str = "test-compliance-officer-1") -> dict:
    """Headers for a ComplianceOfficer (opaque)."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    """Headers for a PlatformAdmin (opaque)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    """Headers carrying the Anonymous sentinel — always rejected with 401."""
    return build_user_headers(user_id, "Anonymous")


def headers_for(role: str, user_id=None) -> dict:
    """Build headers for any declared role.

    ``user_id`` defaults to a per-role operator label; for the two
    entity-backed roles it must be the owning entity's id whenever the call is
    ownership-gated.
    """
    if role not in ROLE_NAMES:
        raise ValueError(f"Unknown role {role!r}; declared roles are {ROLE_NAMES}")
    if user_id is None:
        if role in ENTITY_BACKED_ROLES:
            raise ValueError(
                f"{role} is entity-backed; pass the owning entity's id as user_id"
            )
        user_id = f"test-{role.lower()}-1"
    return build_user_headers(user_id, role)
