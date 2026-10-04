"""Pre-built role headers for every role in the PRD (section 2.1).

Identity model: ``GrowerManager``'s X-User-ID is the acting Organization's
``id``, ``DealerTechnician``'s is the acting Dealer's ``id``, and
``PartnerApp``'s is the acting IntegrationPartner's ``id`` — for those three
roles the shared constant is only safe for tests that never exercise an
ownership check, and fixtures/tests MUST use the ``make_*_headers`` builders
with the real entity id instead.  The other five roles are opaque operator
identifiers; their shared constants are the canonical form.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Opaque operator identifiers ----------------------------------------------

ADMIN_USER_ID = "admin-1"
SYSTEM_USER_ID = "system-operator-1"
AGRONOMIST_USER_ID = "agron-ada"
AGRONOMIST_2_USER_ID = "agron-blake"
COOP_ANALYST_USER_ID = "coop-cora"
INDEPENDENT_USER_ID = "indep-ivan"
INDEPENDENT_2_USER_ID = "indep-irene"


# --- Shared header constants ----------------------------------------------------
#
# For the entity-backed roles (GrowerManager/DealerTechnician/PartnerApp) the
# placeholder user id below matches no real entity; use these constants only
# for tests whose outcome cannot depend on ownership (400 shape checks, 404s,
# role-list rejections).

TEST_USERS = {
    "grower_manager_headers": build_user_headers(
        "test-grower-manager-1", UserRole.GROWER_MANAGER.value
    ),
    "dealer_technician_headers": build_user_headers(
        "test-dealer-tech-1", UserRole.DEALER_TECHNICIAN.value
    ),
    "independent_technician_headers": build_user_headers(
        INDEPENDENT_USER_ID, UserRole.INDEPENDENT_TECHNICIAN.value
    ),
    "agronomist_headers": build_user_headers(
        AGRONOMIST_USER_ID, UserRole.AGRONOMIST.value
    ),
    "coop_analyst_headers": build_user_headers(
        COOP_ANALYST_USER_ID, UserRole.COOP_ANALYST.value
    ),
    "partner_app_headers": build_user_headers(
        "test-partner-app-1", UserRole.PARTNER_APP.value
    ),
    "platform_admin_headers": build_user_headers(
        ADMIN_USER_ID, UserRole.PLATFORM_ADMIN.value
    ),
    "system_headers": build_user_headers(SYSTEM_USER_ID, UserRole.SYSTEM.value),
}

# Convenient module-level aliases for the opaque identities.
ADMIN = TEST_USERS["platform_admin_headers"]
SYSTEM = TEST_USERS["system_headers"]
AGRONOMIST = TEST_USERS["agronomist_headers"]
COOP_ANALYST = TEST_USERS["coop_analyst_headers"]
INDEPENDENT = TEST_USERS["independent_technician_headers"]


# --- Per-instance builders for entity-backed roles ---------------------------------


def make_grower_manager_headers(organization_id):
    """GrowerManager caller acting as the Organization with this id.

    Required for every ownership-gated call: machine creation, plan
    lifecycle, field/prescription/grant writes, consent decisions.
    """
    return build_user_headers(organization_id, UserRole.GROWER_MANAGER.value)


def make_dealer_technician_headers(dealer_id):
    """DealerTechnician caller acting as the Dealer with this id.

    Required for activation, provisioning, consent requests, sessions and
    warranty claims, all of which bind the caller to a Dealer row.
    """
    return build_user_headers(dealer_id, UserRole.DEALER_TECHNICIAN.value)


def make_partner_app_headers(partner_id):
    """PartnerApp caller acting as the IntegrationPartner with this id.

    Required for data-pull and for the self-scoped partner read.
    """
    return build_user_headers(partner_id, UserRole.PARTNER_APP.value)


# --- Builders for opaque roles when a test must thread a chosen identity ----------


def make_agronomist_headers(user_id=AGRONOMIST_USER_ID):
    """Agronomist headers; user_id must equal the grant's grantee_ref_id
    whenever the call is grant-gated."""
    return build_user_headers(user_id, UserRole.AGRONOMIST.value)


def make_coop_analyst_headers(user_id=COOP_ANALYST_USER_ID):
    """CoopAnalyst headers; user_id must equal the grant's grantee_ref_id."""
    return build_user_headers(user_id, UserRole.COOP_ANALYST.value)


def make_independent_technician_headers(user_id=INDEPENDENT_USER_ID):
    """IndependentTechnician headers; the same user_id must be passed as the
    ticket's requester_ref_id for the caller to act as the requester."""
    return build_user_headers(user_id, UserRole.INDEPENDENT_TECHNICIAN.value)


def make_platform_admin_headers(user_id=ADMIN_USER_ID):
    return build_user_headers(user_id, UserRole.PLATFORM_ADMIN.value)


def make_system_headers(user_id=SYSTEM_USER_ID):
    return build_user_headers(user_id, UserRole.SYSTEM.value)


def headers_for(role, user_id):
    """Arbitrary role/identity pairing, including undeclared-role probes."""
    return build_user_headers(user_id, role)


# --- Malformed / undeclared authentication contexts ----------------------------------

UNKNOWN_ROLE_HEADERS = build_user_headers("ghost-1", "SuperUser")

MISSING_USER_ID_HEADERS = {
    "X-User-Role": UserRole.PLATFORM_ADMIN.value,
    "Content-Type": "application/json",
}

MISSING_USER_ROLE_HEADERS = {
    "X-User-ID": ADMIN_USER_ID,
    "Content-Type": "application/json",
}
