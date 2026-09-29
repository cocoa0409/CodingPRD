"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ADMIN_USER_ID,
    AUDITOR_USER_ID,
    OFFICER_ONE_USER_ID,
    OFFICER_TWO_USER_ID,
    REGULATOR_USER_ID,
)

# Shared constants. The four opaque roles carry operator identifiers that are
# never compared against any entity id, so these are the canonical form for
# PlatformAdmin, ComplianceOfficer, NetworkAuditor and StateRegulator.
# For MerchantOperator and TerminalAgent the shared constants are only safe in
# tests that do not depend on the caller owning the subject resource.
TEST_USERS = {
    "platform_admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers(OFFICER_ONE_USER_ID, "ComplianceOfficer"),
    "second_compliance_officer_headers": build_user_headers(
        OFFICER_TWO_USER_ID, "ComplianceOfficer"
    ),
    "network_auditor_headers": build_user_headers(AUDITOR_USER_ID, "NetworkAuditor"),
    "state_regulator_headers": build_user_headers(REGULATOR_USER_ID, "StateRegulator"),
    "merchant_operator_headers": build_user_headers("test-merchant-operator-1", "MerchantOperator"),
    "terminal_agent_headers": build_user_headers("test-terminal-agent-1", "TerminalAgent"),
}


def make_platform_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    """Headers for a PlatformAdmin; the identifier is opaque."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_officer_headers(user_id: str = OFFICER_ONE_USER_ID) -> dict:
    """Headers for a ComplianceOfficer; the identifier is opaque but is compared
    against other opaque identifiers by the segregation-of-duties rules."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_network_auditor_headers(user_id: str = AUDITOR_USER_ID) -> dict:
    """Headers for a NetworkAuditor; the identifier is opaque."""
    return build_user_headers(user_id, "NetworkAuditor")


def make_state_regulator_headers(user_id: str = REGULATOR_USER_ID) -> dict:
    """Headers for a StateRegulator; the identifier is opaque."""
    return build_user_headers(user_id, "StateRegulator")


def make_merchant_operator_headers(merchant_id: str) -> dict:
    """For MerchantOperator, whose X-User-ID is the id of the acting Merchant.
    Always pass the real merchant id when the call is ownership-gated."""
    return build_user_headers(merchant_id, "MerchantOperator")


def make_terminal_agent_headers(terminal_id: str) -> dict:
    """For TerminalAgent, whose X-User-ID is the id of the acting Terminal.
    Always pass the real terminal id when capturing a sale."""
    return build_user_headers(terminal_id, "TerminalAgent")


def make_headers(user_id: str, role: str) -> dict:
    """Arbitrary identity/role pair, for authentication and authorisation tests."""
    return build_user_headers(user_id, role)
