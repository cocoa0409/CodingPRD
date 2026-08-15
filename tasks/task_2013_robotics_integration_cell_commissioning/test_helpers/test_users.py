"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles are entity-backed by IntegratorUser: whenever a call is
ownership- or identity-gated (segregation of duties on approvals and peer
review, trainer scoring on training sessions, recorded_by stamping on
acceptance tests), X-User-ID must be the acting IntegratorUser's id — use
the per-role make_*_headers(user_id) builder with the actual entity id.
The shared TEST_USERS constants are safe only for calls whose success does
NOT depend on the caller owning a specific resource (e.g. org creation by
FinanceAdmin, or 404/400 negative tests).
"""
from prd_bench_local_runner.testing import build_user_headers

# A stable operator id for the FinanceAdmin actor; FinanceAdmin performs
# org/user administration and ledger adjustments that are not ownership-gated
# against an IntegratorUser row the test would otherwise have to create first.
FINANCE_ADMIN_OPERATOR_ID = "00000000-0000-0000-0000-0000000000fa"

TEST_USERS = {
    "finance_admin_headers": build_user_headers(
        FINANCE_ADMIN_OPERATOR_ID, "FinanceAdmin"
    ),
    # Fallbacks for non-ownership calls; prefer the make_* builders with a
    # real IntegratorUser.id whenever identity matters.
    "project_engineer_headers": build_user_headers(
        "test-project-engineer-1", "ProjectEngineer"
    ),
    "safety_lead_headers": build_user_headers("test-safety-lead-1", "SafetyLead"),
    "controls_programmer_headers": build_user_headers(
        "test-controls-programmer-1", "ControlsProgrammer"
    ),
    "site_supervisor_headers": build_user_headers(
        "test-site-supervisor-1", "SiteSupervisor"
    ),
    "trainer_headers": build_user_headers("test-trainer-1", "Trainer"),
    "service_manager_headers": build_user_headers(
        "test-service-manager-1", "ServiceManager"
    ),
}


def make_finance_admin_headers(user_id: str = FINANCE_ADMIN_OPERATOR_ID) -> dict:
    return build_user_headers(user_id, "FinanceAdmin")


def make_project_engineer_headers(user_id: str) -> dict:
    """ProjectEngineer (entity_backed:IntegratorUser)."""
    return build_user_headers(user_id, "ProjectEngineer")


def make_safety_lead_headers(user_id: str) -> dict:
    """SafetyLead (entity_backed:IntegratorUser)."""
    return build_user_headers(user_id, "SafetyLead")


def make_controls_programmer_headers(user_id: str) -> dict:
    """ControlsProgrammer (entity_backed:IntegratorUser)."""
    return build_user_headers(user_id, "ControlsProgrammer")


def make_site_supervisor_headers(user_id: str) -> dict:
    """SiteSupervisor (entity_backed:IntegratorUser)."""
    return build_user_headers(user_id, "SiteSupervisor")


def make_trainer_headers(user_id: str) -> dict:
    """Trainer (entity_backed:IntegratorUser)."""
    return build_user_headers(user_id, "Trainer")


def make_service_manager_headers(user_id: str) -> dict:
    """ServiceManager (entity_backed:IntegratorUser)."""
    return build_user_headers(user_id, "ServiceManager")
