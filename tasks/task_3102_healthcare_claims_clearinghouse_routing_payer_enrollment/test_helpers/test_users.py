"""Caller identities for the three declared roles.

``ClearinghouseOps`` is opaque: the identifier is never matched against a
persisted row, so a stable constant is fine. ``ProviderAdmin`` is entity-backed
by a Provider and ``PayerOperator`` is entity-backed by a Payer, so both get
per-call builders that thread the real entity id (and, for a payer operator,
the payer's ``payer_id_code`` in the ``X-Payer-Code`` header).
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identity — never compared to a stored entity id.
OPS_USER_ID = "ops-operator-0001"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "clearinghouse_ops": {"id": OPS_USER_ID, "role": UserRole.CLEARINGHOUSE_OPS.value},
}

CLEARINGHOUSE_OPS_HEADERS = build_user_headers(OPS_USER_ID, UserRole.CLEARINGHOUSE_OPS.value)


def make_clearinghouse_ops_headers(user_id: str = OPS_USER_ID) -> Dict[str, str]:
    """Headers for a ClearinghouseOps operator (opaque identity)."""
    return build_user_headers(user_id, UserRole.CLEARINGHOUSE_OPS.value)


def make_provider_admin_headers(provider_id: str) -> Dict[str, str]:
    """Headers for a ProviderAdmin acting as the provider with this id.

    Ownership checks compare ``X-User-ID`` to the provider id of the addressed
    resource, so callers MUST pass the real provider id here.
    """
    return build_user_headers(provider_id, UserRole.PROVIDER_ADMIN.value)


def make_payer_operator_headers(payer_id: str, payer_id_code: str) -> Dict[str, str]:
    """Headers for a PayerOperator acting as the payer with this id.

    Payer-owned decision surfaces additionally require the ``X-Payer-Code``
    header carrying the payer's five-character ``payer_id_code``.
    """
    headers = build_user_headers(payer_id, UserRole.PAYER_OPERATOR.value)
    headers["X-Payer-Code"] = payer_id_code
    return headers
