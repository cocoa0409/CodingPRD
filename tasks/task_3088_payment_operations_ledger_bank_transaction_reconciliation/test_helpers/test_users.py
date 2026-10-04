"""Pre-built role headers for every role in the PRD.

``CounterpartyUser`` is the one ``entity_backed`` role: its ``X-User-ID`` must be
the ``id`` of an existing ``Counterparty``, so any ownership-gated call must use
``make_counterparty_user_headers(counterparty["id"])`` rather than the shared
constant below.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import TEST_DEFAULTS

# ─── Shared constants ─────────────────────────────────
# Safe for the opaque roles, and for entity_backed roles on calls whose success
# does not depend on the caller owning the subject resource.
TEST_USERS = {
    "platform_admin_headers": build_user_headers(
        TEST_DEFAULTS["PLATFORM_ADMIN_ID"], "PlatformAdmin"),
    "ledger_controller_headers": build_user_headers(
        TEST_DEFAULTS["LEDGER_CONTROLLER_ID"], "LedgerController"),
    "payment_initiator_headers": build_user_headers(
        TEST_DEFAULTS["PAYMENT_INITIATOR_ID"], "PaymentInitiator"),
    "payment_approver_headers": build_user_headers(
        TEST_DEFAULTS["PAYMENT_APPROVER_ID"], "PaymentApprover"),
    "payment_ops_analyst_headers": build_user_headers(
        TEST_DEFAULTS["PAYMENT_OPS_ANALYST_ID"], "PaymentOpsAnalyst"),
    "payment_ops_approver_headers": build_user_headers(
        TEST_DEFAULTS["PAYMENT_OPS_APPROVER_ID"], "PaymentOpsApprover"),
    "auditor_headers": build_user_headers(
        TEST_DEFAULTS["AUDITOR_ID"], "Auditor"),
}

# Named operator identities used by segregation-of-duties scenarios.
INITIATOR_USER_ID = TEST_DEFAULTS["PAYMENT_INITIATOR_ID"]
APPROVER_USER_ID = TEST_DEFAULTS["PAYMENT_APPROVER_ID"]


def make_counterparty_user_headers(counterparty_id: str) -> dict:
    """CounterpartyUser (entity_backed:Counterparty).

    Pass the actual Counterparty.id whenever the call is ownership-gated — a
    shared constant would never equal a real entity id and every ownership
    check would reject the request.
    """
    return build_user_headers(counterparty_id, "CounterpartyUser")


def headers_for(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary operator identity in an arbitrary role."""
    return build_user_headers(user_id, role)