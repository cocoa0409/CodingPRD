"""Pre-built role headers for every role the PRD declares.

``FranchisorAdmin``, ``FieldAuditor`` and ``Commissary`` are opaque identities:
their ``X-User-ID`` is never compared against any persisted entity's ``id``.
``Franchisee`` is entity-backed: its ``X-User-ID`` must be the acting
``Franchisee.id``, so every ownership-gated call has to use the per-instance
builder rather than the shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-franchisor-admin-1", "FranchisorAdmin"),
    "auditor_headers": build_user_headers("test-field-auditor-1", "FieldAuditor"),
    "commissary_headers": build_user_headers("test-commissary-1", "Commissary"),
    # entity_backed role: this shared constant is a fallback for non-ownership
    # calls only. Ownership-gated calls must use make_franchisee_headers().
    "franchisee_headers": build_user_headers("test-franchisee-1", "Franchisee"),
}


def make_franchisee_headers(franchisee_id: str) -> dict:
    """Headers for the Franchisee role acting as `franchisee_id`.

    Pass the actual Franchisee.id whenever the call is ownership-gated
    (fresh-order booking and cancellation, disputing a settlement, listing
    settlements as a franchisee).
    """
    return build_user_headers(franchisee_id, "Franchisee")


__all__ = ["TEST_USERS", "make_franchisee_headers"]