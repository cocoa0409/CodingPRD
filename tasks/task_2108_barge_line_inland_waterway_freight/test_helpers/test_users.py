"""Pre-built role headers for every role named in PRD §2.1.

Two roles are entity-backed and their ``X-User-ID`` must be the id of a stored
row: ``LockMaster`` carries the id of the ``Lock`` it masters, and ``Shipper``
carries the id of the acting ``Shipper``.  For any ownership-gated call the
per-instance builders below MUST be used with the real entity id; the shared
constants for those two roles are safe only where ownership is irrelevant
(unauthenticated / forbidden-role / not-found probes).

The seven remaining roles carry an opaque operator identity.  Distinct
operators are still required in two places (a filing may not be effectuated by
its filer, and a claim may not be approved or denied by its assessor), so each
opaque builder accepts an explicit operator id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Canonical operator identities for the segregation-of-duties pairs.
ANALYST_USER_ID = "analyst-1"
RATE_AUTHORITY_USER_ID = "rate-1"
ADJUSTER_ASSESSOR_USER_ID = "adj-1"
ADJUSTER_APPROVER_USER_ID = "adj-2"


TEST_USERS = {
    "waterway_admin_headers": build_user_headers("admin-1", "WaterwayAdmin"),
    "tariff_analyst_headers": build_user_headers(ANALYST_USER_ID, "TariffAnalyst"),
    "rate_authority_headers": build_user_headers(RATE_AUTHORITY_USER_ID, "RateAuthority"),
    "towboat_dispatcher_headers": build_user_headers("disp-1", "TowboatDispatcher"),
    "harbor_agent_headers": build_user_headers("harbor-1", "HarborAgent"),
    "contract_manager_headers": build_user_headers("cm-1", "ContractManager"),
    "claims_adjuster_headers": build_user_headers(ADJUSTER_ASSESSOR_USER_ID, "ClaimsAdjuster"),
    # Entity-backed roles: these constants never match a stored row, so they are
    # only safe for tests whose outcome does not depend on ownership.
    "lock_master_headers": build_user_headers("lock-master-1", "LockMaster"),
    "shipper_headers": build_user_headers("shipper-1", "Shipper"),
}


def make_waterway_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "WaterwayAdmin")


def make_tariff_analyst_headers(user_id: str = ANALYST_USER_ID) -> dict:
    return build_user_headers(user_id, "TariffAnalyst")


def make_rate_authority_headers(user_id: str = RATE_AUTHORITY_USER_ID) -> dict:
    return build_user_headers(user_id, "RateAuthority")


def make_towboat_dispatcher_headers(user_id: str = "disp-1") -> dict:
    return build_user_headers(user_id, "TowboatDispatcher")


def make_harbor_agent_headers(user_id: str = "harbor-1") -> dict:
    return build_user_headers(user_id, "HarborAgent")


def make_contract_manager_headers(user_id: str = "cm-1") -> dict:
    return build_user_headers(user_id, "ContractManager")


def make_claims_adjuster_headers(user_id: str = ADJUSTER_ASSESSOR_USER_ID) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_lock_master_headers(lock_id: str) -> dict:
    """For LockMaster. ``X-User-ID`` is the id of the Lock the caller masters —
    pass the real chamber id for grant, deny, reschedule and set-status."""
    return build_user_headers(lock_id, "LockMaster")


def make_shipper_headers(shipper_id: str) -> dict:
    """For Shipper. ``X-User-ID`` is the id of the acting Shipper row — pass the
    real shipper id when filing or withdrawing a cargo claim."""
    return build_user_headers(shipper_id, "Shipper")
