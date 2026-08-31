"""Pre-built role headers for every role in the PRD (§2.1).

All six roles carry an opaque X-User-ID: the server never compares it to any
row's id. The one place a recorded user id matters is a purchase contract's
created_by_user_id at cancellation time, so tests that exercise the
segregation-of-duties rule build headers for a named user id with the
make_* builders below.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "desk_admin_headers": build_user_headers("u-admin-1", "DeskAdmin"),
    "merchandiser_headers": build_user_headers("u-merch-1", "Merchandiser"),
    "futures_trader_headers": build_user_headers("u-trader-1", "FuturesTrader"),
    "risk_officer_headers": build_user_headers("u-risk-1", "RiskOfficer"),
    "grain_inspector_headers": build_user_headers("u-insp-1", "GrainInspector"),
    "freight_coordinator_headers": build_user_headers("u-freight-1", "FreightCoordinator"),
}

# Bare identity headers with no role attached at all — used only to exercise
# the priority-1 authentication check.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_desk_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DeskAdmin")


def make_merchandiser_headers(user_id: str) -> dict:
    """Use when the acting X-User-ID must be pinned, e.g. to become a
    contract's created_by_user_id."""
    return build_user_headers(user_id, "Merchandiser")


def make_futures_trader_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FuturesTrader")


def make_risk_officer_headers(user_id: str) -> dict:
    """Use when the acting X-User-ID must match — or deliberately differ
    from — a contract's created_by_user_id at cancellation time."""
    return build_user_headers(user_id, "RiskOfficer")


def make_grain_inspector_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GrainInspector")


def make_freight_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FreightCoordinator")
