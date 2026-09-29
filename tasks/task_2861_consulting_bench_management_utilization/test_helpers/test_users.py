"""Role headers for the Consulting Bench Management API (PRD §2.1).

Four of the five roles are opaque operator identities: X-User-ID is never
compared against any stored row, but it IS recorded on the rows the operator
mutates (requested_by_user_id, decided_by_user_id, separation_proposed_by_user_id,
separation_decided_by_user_id). Every distinct operator therefore gets its own
X-User-ID so that segregation-of-duties checks are exercised honestly.

The Consultant role is entity_backed: X-User-ID must equal the Consultant row's
own id, so Consultant headers must always be built per-row with
make_consultant_headers(consultant["id"]).
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --- Distinct operator identities (PRD §2.11) ------------------------------
SALES_LEAD_USER_ID = "u_sales_1"
SALES_LEAD_2_USER_ID = "u_sales_2"
RESOURCE_MANAGER_USER_ID = "u_rm_1"
RESOURCE_MANAGER_2_USER_ID = "u_rm_2"
PRACTICE_PARTNER_USER_ID = "u_partner_1"
PRACTICE_PARTNER_2_USER_ID = "u_partner_2"
FINANCE_CONTROLLER_USER_ID = "u_fin_1"
FINANCE_CONTROLLER_2_USER_ID = "u_fin_2"

# --- Pre-built headers for the four opaque operator roles ------------------
SALES_LEAD = build_user_headers(SALES_LEAD_USER_ID, Role.SALES_LEAD)
SALES_LEAD_2 = build_user_headers(SALES_LEAD_2_USER_ID, Role.SALES_LEAD)
RESOURCE_MANAGER = build_user_headers(RESOURCE_MANAGER_USER_ID, Role.RESOURCE_MANAGER)
RESOURCE_MANAGER_2 = build_user_headers(
    RESOURCE_MANAGER_2_USER_ID, Role.RESOURCE_MANAGER
)
PRACTICE_PARTNER = build_user_headers(PRACTICE_PARTNER_USER_ID, Role.PRACTICE_PARTNER)
PRACTICE_PARTNER_2 = build_user_headers(
    PRACTICE_PARTNER_2_USER_ID, Role.PRACTICE_PARTNER
)
FINANCE_CONTROLLER = build_user_headers(
    FINANCE_CONTROLLER_USER_ID, Role.FINANCE_CONTROLLER
)
FINANCE_CONTROLLER_2 = build_user_headers(
    FINANCE_CONTROLLER_2_USER_ID, Role.FINANCE_CONTROLLER
)

TEST_USERS = {
    Role.SALES_LEAD: SALES_LEAD,
    Role.RESOURCE_MANAGER: RESOURCE_MANAGER,
    Role.PRACTICE_PARTNER: PRACTICE_PARTNER,
    Role.FINANCE_CONTROLLER: FINANCE_CONTROLLER,
}


def make_consultant_headers(consultant_id: str) -> dict:
    """Headers for the entity-backed Consultant role.

    PRD §2.1: for the Consultant role the X-User-ID header value is the
    Consultant row's own id.
    """
    return build_user_headers(consultant_id, Role.CONSULTANT)


def make_sales_lead_headers(user_id: str) -> dict:
    return build_user_headers(user_id, Role.SALES_LEAD)


def make_resource_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, Role.RESOURCE_MANAGER)


def make_practice_partner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, Role.PRACTICE_PARTNER)


def make_finance_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, Role.FINANCE_CONTROLLER)


def make_headers(user_id: str, role: str) -> dict:
    return build_user_headers(user_id, role)


# Headers with no identity at all, and headers naming a role the API does not
# know: PRD §2.1 makes both ERR_UNAUTHENTICATED.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
EMPTY_USER_ID_HEADERS = build_user_headers("", Role.RESOURCE_MANAGER)
UNKNOWN_ROLE_HEADERS = build_user_headers("u_ghost_1", "Auditor")
