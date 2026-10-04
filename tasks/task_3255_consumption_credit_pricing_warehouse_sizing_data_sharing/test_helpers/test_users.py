"""Pre-built role headers for every role in the PRD (PRD §2.1).

``PlatformOperator``, ``FinanceController`` and ``DataEngineer`` carry opaque
operator identifiers — any non-empty string works, and the server stamps the
value as ``activated_by_user_id`` / ``disputed_by_user_id`` where the
segregation-of-duties rules require it.

``ShareAdmin`` is entity-backed by ``Account``: ``X-User-ID`` must be the ``id``
of an existing ``Account`` whenever the call is ownership-gated. Use
``make_share_admin_headers(account["id"])`` for those calls; the shared
constant is only a fallback for calls that are not ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_operator_headers": build_user_headers("ops-platform-1", "PlatformOperator"),
    "finance_controller_headers": build_user_headers("fin-controller-1", "FinanceController"),
    "data_engineer_headers": build_user_headers("eng-data-1", "DataEngineer"),
    # ShareAdmin is entity-backed: fallback for non-ownership contexts only.
    "share_admin_headers": build_user_headers("test-share-admin", "ShareAdmin"),
}


def make_platform_operator_headers(user_id: str = "ops-platform-1") -> dict:
    """PlatformOperator (opaque operator identity)."""
    return build_user_headers(user_id, "PlatformOperator")


def make_finance_controller_headers(user_id: str = "fin-controller-1") -> dict:
    """FinanceController (opaque operator identity). The value is stamped as
    ``activated_by_user_id`` on contract activation, so pass a distinct
    identifier when exercising the segregation-of-duties rules."""
    return build_user_headers(user_id, "FinanceController")


def make_data_engineer_headers(user_id: str = "eng-data-1") -> dict:
    """DataEngineer (opaque operator identity)."""
    return build_user_headers(user_id, "DataEngineer")


def make_share_admin_headers(account_id: str) -> dict:
    """ShareAdmin (entity-backed:Account). Pass the acting provider
    ``Account.id`` whenever the call is ownership-gated — every share, listing
    and usage-event write compares against the provider account."""
    return build_user_headers(account_id, "ShareAdmin")