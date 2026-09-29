"""Pre-built role headers for every role in the PRD (§2.1).

The five broker-side and platform-side roles carry opaque identities that the
server never compares to any entity id, and the recognised opaque identities are
fixed: ``admin-1``, ``lead-1``, ``lead-2``, ``act-1``, ``acct-1``, ``acct-2``
and ``compl-1``.

The two counterparty roles are entity-backed: a ``CedentUnderwriter`` sends the
acting cedent's ``id`` as ``X-User-ID`` and a ``ReinsurerUnderwriter`` sends the
acting reinsurer's ``id``. Ownership-gated calls MUST therefore be built with
``make_cedent_underwriter_headers(cedent["id"])`` /
``make_reinsurer_underwriter_headers(reinsurer["id"])`` rather than with a shared
constant.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Fixed opaque identities (PRD §2.1).
PLATFORM_ADMIN_ID = "admin-1"
PLACEMENT_LEAD_ID = "lead-1"
PLACEMENT_LEAD_2_ID = "lead-2"
ACTUARY_ID = "act-1"
ACCOUNTANT_ID = "acct-1"
ACCOUNTANT_2_ID = "acct-2"
COMPLIANCE_ID = "compl-1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is the canonical form.
    "admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "placement_lead_headers": build_user_headers(PLACEMENT_LEAD_ID, "BrokerPlacementLead"),
    "placement_lead_2_headers": build_user_headers(PLACEMENT_LEAD_2_ID, "BrokerPlacementLead"),
    "actuary_headers": build_user_headers(ACTUARY_ID, "BrokerActuary"),
    "accountant_headers": build_user_headers(ACCOUNTANT_ID, "BrokerAccountant"),
    "accountant_2_headers": build_user_headers(ACCOUNTANT_2_ID, "BrokerAccountant"),
    "compliance_headers": build_user_headers(COMPLIANCE_ID, "ComplianceOfficer"),
    # Entity-backed roles — these fallbacks resolve to no entity at all, so they
    # are only for tests that assert the unknown-actor rejection.
    "unknown_cedent_underwriter_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "CedentUnderwriter"
    ),
    "unknown_reinsurer_underwriter_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000000", "ReinsurerUnderwriter"
    ),
}


def make_platform_admin_headers(user_id: str = PLATFORM_ADMIN_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_placement_lead_headers(user_id: str = PLACEMENT_LEAD_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "BrokerPlacementLead")


def make_actuary_headers(user_id: str = ACTUARY_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "BrokerActuary")


def make_accountant_headers(user_id: str = ACCOUNTANT_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "BrokerAccountant")


def make_compliance_headers(user_id: str = COMPLIANCE_ID) -> Dict[str, str]:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_cedent_underwriter_headers(cedent_id: str) -> Dict[str, str]:
    """For CedentUnderwriter — pass the acting Cedent's own id (PRD §2.1)."""
    return build_user_headers(cedent_id, "CedentUnderwriter")


def make_reinsurer_underwriter_headers(reinsurer_id: str) -> Dict[str, str]:
    """For ReinsurerUnderwriter — pass the acting Reinsurer's own id (PRD §2.1)."""
    return build_user_headers(reinsurer_id, "ReinsurerUnderwriter")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for auth-band tests that need an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role but an empty X-User-ID (PRD §2.1 rejects it)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying an identity but an empty X-User-Role (PRD §2.1 rejects it)."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_missing_both() -> Dict[str, str]:
    """Headers carrying neither identity nor role."""
    return {"Content-Type": "application/json"}
