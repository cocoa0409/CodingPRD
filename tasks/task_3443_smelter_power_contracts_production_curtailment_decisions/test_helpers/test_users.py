"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles are opaque: X-User-ID is not tied to any persisted entity.
Segregation-of-duties checks compare X-User-ID against operator stamps
recorded on curtailment decisions, so the approval-chain tests need headers
with specific user ids — use the per-instance builders for those.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "energy_manager_headers": build_user_headers("energy-1", "EnergyManager"),
    "trading_analyst_headers": build_user_headers("trader-1", "TradingAnalyst"),
    "smelter_manager_headers": build_user_headers("mgr-1", "SmelterManager"),
    "controller_headers": build_user_headers("ctrl-1", "Controller"),
    "vp_operations_headers": build_user_headers("vp-1", "VPOperations"),
    "ehs_manager_headers": build_user_headers("ehs-1", "EHSManager"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_energy_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EnergyManager")


def make_trading_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TradingAnalyst")


def make_smelter_manager_headers(user_id: str) -> dict:
    """SmelterManager headers with a specific X-User-ID (decision proposer)."""
    return build_user_headers(user_id, "SmelterManager")


def make_controller_headers(user_id: str) -> dict:
    """Controller headers with a specific X-User-ID (economic reviewer)."""
    return build_user_headers(user_id, "Controller")


def make_vp_operations_headers(user_id: str) -> dict:
    """VPOperations headers with a specific X-User-ID (labor approver)."""
    return build_user_headers(user_id, "VPOperations")


def make_ehs_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EHSManager")
