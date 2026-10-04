"""Pre-built role headers for every role in the PRD (section 2.1).

Two roles are entity-backed: for `Taxpayer`, X-User-ID must be the acting
Taxpayer record's `id`; for `TaxPreparer`, the acting Preparer record's `id`.
For any ownership-gated call, use the per-instance builder
(`make_taxpayer_headers(taxpayer["id"])` / `make_tax_preparer_headers(...)`)
— never the shared constant, whose placeholder id matches no entity.

The four remaining roles are opaque operator identities; their shared
constants are canonical. Segregation-of-duties workflows (report confirm vs
creator; advocate resolve vs opener) need two DISTINCT users of the same
role — build them with the per-role builders, e.g.
`make_fraud_analyst_headers("analyst-1")` vs `make_fraud_analyst_headers("analyst-2")`.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole


# ─── Shared constants ────────────────────────────────
# Safe for opaque roles everywhere, and for entity-backed roles only in
# tests whose success does NOT depend on the caller owning the subject
# resource (e.g. 400-on-bad-payload or 404-on-missing-resource probes).

TEST_USERS = {
    # entity_backed:Taxpayer — fallback for non-ownership tests only.
    "taxpayer_headers": build_user_headers("test-taxpayer-1", UserRole.TAXPAYER.value),
    # entity_backed:Preparer — fallback for non-ownership tests only.
    "tax_preparer_headers": build_user_headers("test-preparer-1", UserRole.TAX_PREPARER.value),
    # opaque roles — canonical form.
    "verification_agent_headers": build_user_headers(
        "test-verification-agent-1", UserRole.VERIFICATION_AGENT.value
    ),
    "fraud_analyst_headers": build_user_headers(
        "test-fraud-analyst-1", UserRole.FRAUD_ANALYST.value
    ),
    "taxpayer_advocate_headers": build_user_headers(
        "test-advocate-1", UserRole.TAXPAYER_ADVOCATE.value
    ),
    "system_admin_headers": build_user_headers(
        "test-system-admin-1", UserRole.SYSTEM_ADMIN.value
    ),
}


# ─── Per-instance builders ───────────────────────────

def make_taxpayer_headers(user_id: str) -> dict:
    """Taxpayer is entity_backed:Taxpayer — pass the actual Taxpayer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, UserRole.TAXPAYER.value)


def make_tax_preparer_headers(user_id: str) -> dict:
    """TaxPreparer is entity_backed:Preparer — pass the actual Preparer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, UserRole.TAX_PREPARER.value)


def make_verification_agent_headers(user_id: str = "test-verification-agent-1") -> dict:
    """Opaque operator role; distinct user_ids are still useful for audit
    anchors (e.g. created_by_user_id)."""
    return build_user_headers(user_id, UserRole.VERIFICATION_AGENT.value)


def make_fraud_analyst_headers(user_id: str = "test-fraud-analyst-1") -> dict:
    """Opaque operator role. Use two distinct ids (e.g. 'analyst-1' vs
    'analyst-2') to satisfy the report-confirm segregation-of-duties rule."""
    return build_user_headers(user_id, UserRole.FRAUD_ANALYST.value)


def make_taxpayer_advocate_headers(user_id: str = "test-advocate-1") -> dict:
    """Opaque operator role. Use two distinct ids (e.g. 'adv-1' vs 'adv-2')
    to satisfy the advocate-case resolve segregation-of-duties rule."""
    return build_user_headers(user_id, UserRole.TAXPAYER_ADVOCATE.value)


def make_system_admin_headers(user_id: str = "test-system-admin-1") -> dict:
    """Opaque operator role (registries, configs, ops, disbursement release,
    logical clock)."""
    return build_user_headers(user_id, UserRole.SYSTEM_ADMIN.value)
