"""Pre-built role headers for every role in the PRD (§2.1).

Six roles carry an opaque identity: their X-User-ID is an operator identifier that is
never compared against any entity id, so a shared constant is the canonical form.
The Household role is entity-backed: its X-User-ID must be the acting Household's id,
so ownership-gated calls MUST use make_household_headers(household["id"]).
"""

from prd_bench_local_runner.testing import build_user_headers

# Canonical operator identifiers used by the design recipes.
DEVELOPER_PRINCIPAL_USER_ID = "u_dev_1"
DEVELOPER_PRINCIPAL_ALT_USER_ID = "u_dev_2"
ENTITLEMENT_OFFICER_USER_ID = "u_ent_1"
ENTITLEMENT_OFFICER_ALT_USER_ID = "u_ent_2"
CONSTRUCTION_MANAGER_USER_ID = "u_cm_1"
LEASING_AGENT_USER_ID = "u_la_1"
LEASING_AGENT_ALT_USER_ID = "u_la_2"
ASSET_MANAGER_USER_ID = "u_am_1"
ASSET_MANAGER_ALT_USER_ID = "u_am_2"
PROPERTY_MANAGER_USER_ID = "u_pm_1"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "developer_principal_headers": build_user_headers(
        DEVELOPER_PRINCIPAL_USER_ID, "DeveloperPrincipal"
    ),
    "entitlement_officer_headers": build_user_headers(
        ENTITLEMENT_OFFICER_USER_ID, "EntitlementOfficer"
    ),
    "construction_manager_headers": build_user_headers(
        CONSTRUCTION_MANAGER_USER_ID, "ConstructionManager"
    ),
    "leasing_agent_headers": build_user_headers(LEASING_AGENT_USER_ID, "LeasingAgent"),
    "asset_manager_headers": build_user_headers(ASSET_MANAGER_USER_ID, "AssetManager"),
    "property_manager_headers": build_user_headers(
        PROPERTY_MANAGER_USER_ID, "PropertyManager"
    ),
    # entity_backed role: fallback for tests that do not exercise ownership.
    "household_headers": build_user_headers("test-household-1", "Household"),
}


def make_household_headers(household_id: str) -> dict:
    """For the Household role (entity_backed:Household). Pass the real Household.id
    as user_id whenever the call is ownership-gated (GET one lease, signature, notice)."""
    return build_user_headers(household_id, "Household")


def make_developer_principal_headers(user_id: str) -> dict:
    """Opaque DeveloperPrincipal with an explicit operator id (segregation of duties)."""
    return build_user_headers(user_id, "DeveloperPrincipal")


def make_entitlement_officer_headers(user_id: str) -> dict:
    """Opaque EntitlementOfficer with an explicit operator id (segregation of duties)."""
    return build_user_headers(user_id, "EntitlementOfficer")


def make_construction_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConstructionManager")


def make_leasing_agent_headers(user_id: str) -> dict:
    """Opaque LeasingAgent with an explicit operator id (segregation of duties)."""
    return build_user_headers(user_id, "LeasingAgent")


def make_asset_manager_headers(user_id: str) -> dict:
    """Opaque AssetManager with an explicit operator id (segregation of duties)."""
    return build_user_headers(user_id, "AssetManager")


def make_property_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PropertyManager")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary (user_id, role) pair — used by authentication tests."""
    return build_user_headers(user_id, role)


# Headers that omit or blank out the authentication values (PRD §2.1).
# A blank header value must be the empty string, never a whitespace string.
NO_ROLE_HEADERS = {"X-User-ID": DEVELOPER_PRINCIPAL_USER_ID, "Content-Type": "application/json"}
BLANK_ROLE_HEADERS = {
    "X-User-ID": DEVELOPER_PRINCIPAL_USER_ID,
    "X-User-Role": "",
    "Content-Type": "application/json",
}
UNKNOWN_ROLE_HEADERS = build_user_headers(DEVELOPER_PRINCIPAL_USER_ID, "SiteSuperintendent")
NO_USER_ID_HOUSEHOLD_HEADERS = {
    "X-User-Role": "Household",
    "Content-Type": "application/json",
}
BLANK_USER_ID_HOUSEHOLD_HEADERS = {
    "X-User-ID": "",
    "X-User-Role": "Household",
    "Content-Type": "application/json",
}
