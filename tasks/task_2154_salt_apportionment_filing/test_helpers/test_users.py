"""Pre-built role headers for every practice role in the PRD.

Identity in this system is deliberately shallow: for all four roles the
``X-User-ID`` header is an opaque operator identifier that is never compared to
any entity's ``id``. The only place the recorded identifier carries force is
segregation of duties on approval, so tests that exercise that rule build
headers for a specific operator with the per-operator builders below.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — every role is opaque, so these are the canonical form for
# any call whose outcome does not depend on which operator is acting.
TEST_USERS = {
    "tax_manager_headers": build_user_headers("tax-manager-01", "TaxManager"),
    "state_analyst_headers": build_user_headers("analyst-01", "StateAnalyst"),
    "controller_headers": build_user_headers("controller-01", "Controller"),
    "auditor_headers": build_user_headers("auditor-01", "Auditor"),
}


def make_tax_manager_headers(user_id: str) -> dict:
    """Headers for a specific TaxManager operator."""
    return build_user_headers(user_id, "TaxManager")


def make_state_analyst_headers(user_id: str) -> dict:
    """Headers for a specific StateAnalyst operator.

    Used wherever the recorded ``preparer_user_id`` matters.
    """
    return build_user_headers(user_id, "StateAnalyst")


def make_controller_headers(user_id: str) -> dict:
    """Headers for a specific Controller operator.

    Used wherever ``preparer_user_id`` / ``approver_user_id`` matters, in
    particular for the segregation-of-duties rule on approval.
    """
    return build_user_headers(user_id, "Controller")


def make_auditor_headers(user_id: str) -> dict:
    """Headers for a specific Auditor operator."""
    return build_user_headers(user_id, "Auditor")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary operator / role pair."""
    return build_user_headers(user_id, role)


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
"""A request carrying neither X-User-ID nor X-User-Role."""
