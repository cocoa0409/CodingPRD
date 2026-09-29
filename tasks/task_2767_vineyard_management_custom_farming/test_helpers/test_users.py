"""Pre-built role headers for every role in the PRD (§2.1).

Five roles carry an opaque operator identifier, so the shared constants below
are the canonical form for them. Two roles do not: a `CrewSupervisor`'s
`X-User-ID` is the `id` of the acting `LaborCrew` and a `ClientOwner`'s
`X-User-ID` is the `id` of the acting `Vineyard`. Every ownership-gated call
for those two roles MUST go through the per-instance builders at the bottom of
this module, passing the real entity `id`.
"""
from prd_bench_local_runner.testing import build_user_headers

# ─── Shared constants ─────────────────────────────────
# Safe for the five opaque roles, and for CrewSupervisor / ClientOwner only in
# tests that never reach an ownership comparison (401/403/400/404 paths).
TEST_USERS = {
    # Opaque operator identifiers (PRD §2.1).
    "vineyard_manager_headers": build_user_headers("u-vm-1", "VineyardManager"),
    "vineyard_manager_alt_headers": build_user_headers("u-vm-2", "VineyardManager"),
    "agronomist_headers": build_user_headers("u-ag-1", "Agronomist"),
    "agronomist_alt_headers": build_user_headers("u-ag-2", "Agronomist"),
    "applicator_headers": build_user_headers("u-app-1", "Applicator"),
    "applicator_alt_headers": build_user_headers("u-app-2", "Applicator"),
    "compliance_officer_headers": build_user_headers("u-co-1", "ComplianceOfficer"),
    "controller_headers": build_user_headers("u-ctl-1", "Controller"),
    "controller_alt_headers": build_user_headers("u-ctl-2", "Controller"),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "crew_supervisor_headers": build_user_headers("u-cs-1", "CrewSupervisor"),
    "client_owner_headers": build_user_headers("u-co-owner-1", "ClientOwner"),
}

# Operators who act under two roles in the segregation-of-duties scenarios.
DUAL_ROLE_USER_IDS = {
    "PLAN_SUBMITTER_AND_APPROVER": "u-dual-1",
    "SPRAY_RECOMMENDER_AND_APPLICATOR": "u-dual-2",
}


# ─── Per-instance builders (mandatory for the entity-backed roles) ───

def make_crew_supervisor_headers(crew_id: str) -> dict:
    """Headers for the `CrewSupervisor` of a specific `LaborCrew`.

    PRD §2.1: `X-User-ID` is the `id` of the acting `LaborCrew`, so always pass
    the real crew `id` when the call is ownership-gated (work-order start and
    complete, harvest-load dispatch).
    """
    return build_user_headers(crew_id, "CrewSupervisor")


def make_client_owner_headers(vineyard_id: str) -> dict:
    """Headers for the `ClientOwner` of a specific `Vineyard`.

    PRD §2.1: `X-User-ID` is the `id` of the acting `Vineyard`, so always pass
    the real ranch `id` when the call is ownership-gated (ranch read, contract
    read/list, contract countersignature).
    """
    return build_user_headers(vineyard_id, "ClientOwner")


def make_vineyard_manager_headers(user_id: str) -> dict:
    """Headers for a specific operator acting as `VineyardManager`."""
    return build_user_headers(user_id, "VineyardManager")


def make_agronomist_headers(user_id: str) -> dict:
    """Headers for a specific operator acting as `Agronomist`."""
    return build_user_headers(user_id, "Agronomist")


def make_applicator_headers(user_id: str) -> dict:
    """Headers for a specific operator acting as `Applicator`."""
    return build_user_headers(user_id, "Applicator")


def make_compliance_officer_headers(user_id: str) -> dict:
    """Headers for a specific operator acting as `ComplianceOfficer`."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_controller_headers(user_id: str) -> dict:
    """Headers for a specific operator acting as `Controller`."""
    return build_user_headers(user_id, "Controller")
