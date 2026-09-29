"""Pre-built auth headers for every role in the PRD.

Three roles are entity-backed: `DesignEngineer` and `SealingEngineer` carry the
acting `Engineer` id in `X-User-ID`, and `DealerPrincipal` carries the acting
`Dealer` id.  Every ownership-gated call MUST use the matching
``make_*_headers(<entity id>)`` builder; the shared constants below are only
safe for the four opaque roles and for calls whose outcome does not depend on
the caller owning the subject row.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque roles — the server never compares X-User-ID to any row's id.
TEST_USERS = {
    "plant_admin_headers": build_user_headers("op-plant-admin-1", "PlantAdmin"),
    "production_planner_headers": build_user_headers(
        "op-production-planner-1", "ProductionPlanner"
    ),
    "logistics_coordinator_headers": build_user_headers(
        "op-logistics-1", "LogisticsCoordinator"
    ),
    "quality_inspector_headers": build_user_headers("op-quality-1", "QualityInspector"),
    # Entity-backed roles — these shared constants name no stored row, so they
    # are only valid where the PRD expects a scope violation or where no
    # ownership check runs (for example every read endpoint).
    "design_engineer_headers": build_user_headers("unknown-engineer", "DesignEngineer"),
    "sealing_engineer_headers": build_user_headers(
        "unknown-engineer", "SealingEngineer"
    ),
    "dealer_principal_headers": build_user_headers("unknown-dealer", "DealerPrincipal"),
}


def make_design_engineer_headers(engineer_id: str) -> dict:
    """Headers for a `DesignEngineer`; pass the acting Engineer's id."""
    return build_user_headers(engineer_id, "DesignEngineer")


def make_sealing_engineer_headers(engineer_id: str) -> dict:
    """Headers for a `SealingEngineer`; pass the acting Engineer's id."""
    return build_user_headers(engineer_id, "SealingEngineer")


def make_dealer_principal_headers(dealer_id: str) -> dict:
    """Headers for a `DealerPrincipal`; pass the acting Dealer's id."""
    return build_user_headers(dealer_id, "DealerPrincipal")


def make_plant_admin_headers(user_id: str = "op-plant-admin-1") -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_production_planner_headers(user_id: str = "op-production-planner-1") -> dict:
    return build_user_headers(user_id, "ProductionPlanner")


def make_logistics_coordinator_headers(user_id: str = "op-logistics-1") -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_quality_inspector_headers(user_id: str = "op-quality-1") -> dict:
    return build_user_headers(user_id, "QualityInspector")


def headers_for_role(role: str, user_id: str = "op-generic-1") -> dict:
    """Build headers for an arbitrary role name — used by role-matrix tests."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str = "op-generic-1") -> dict:
    """Headers carrying X-User-ID but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str = "PlantAdmin") -> dict:
    """Headers carrying X-User-Role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
