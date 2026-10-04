"""Pre-built role headers for the nine declared roles (PRD §2.1).

Two roles are entity-backed: for Grower the X-User-ID must be the acting
Grower's id, and for ChainCustomer it must be the acting CustomerChain's id.
Those roles get per-instance builders — always call them with the real
entity id for any ownership-gated call. The seven opaque roles are never
compared against a stored row, so a stable identifier is enough.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_ACCOUNT_MANAGER,
    ROLE_CHAIN_CUSTOMER,
    ROLE_GROWER,
    ROLE_GROWER_RELATIONS_MANAGER,
    ROLE_LOGISTICS_COORDINATOR,
    ROLE_PLATFORM_ADMIN,
    ROLE_PRODUCTION_PLANNER,
    ROLE_QA_LEAD,
    ROLE_STORAGE_OPERATOR,
)

# Shared header dicts for the opaque roles (safe anywhere).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("op-platform-admin-1", ROLE_PLATFORM_ADMIN),
    "grower_relations_manager_headers": build_user_headers("op-grm-1", ROLE_GROWER_RELATIONS_MANAGER),
    "storage_operator_headers": build_user_headers("op-storage-1", ROLE_STORAGE_OPERATOR),
    "qa_lead_headers": build_user_headers("op-qa-1", ROLE_QA_LEAD),
    "production_planner_headers": build_user_headers("op-planner-1", ROLE_PRODUCTION_PLANNER),
    "account_manager_headers": build_user_headers("op-account-1", ROLE_ACCOUNT_MANAGER),
    "logistics_coordinator_headers": build_user_headers("op-logistics-1", ROLE_LOGISTICS_COORDINATOR),
    # Fallbacks for the entity-backed roles — only for tests whose outcome
    # does not depend on owning the subject resource (e.g. 404s, 400s).
    "grower_headers": build_user_headers("test-grower-1", ROLE_GROWER),
    "chain_customer_headers": build_user_headers("test-chain-1", ROLE_CHAIN_CUSTOMER),
}


def make_grower_headers(grower_id: str) -> dict:
    """Grower is entity-backed: pass the real Grower.id for any lot delivery."""
    return build_user_headers(grower_id, ROLE_GROWER)


def make_chain_customer_headers(chain_id: str) -> dict:
    """ChainCustomer is entity-backed: pass the real CustomerChain.id for spec
    authoring and revision requests."""
    return build_user_headers(chain_id, ROLE_CHAIN_CUSTOMER)
