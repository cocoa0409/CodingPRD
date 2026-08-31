"""Pre-built role headers for every role in the PRD.

`PlatformAdmin`, `OperationsManager`, `SafetyOfficer` and `SettlementAccountant`
present an opaque operator identifier that is never compared to an entity id, so
the shared constants below are the canonical form for them.

`HaulContractor` and `MillScaler` are identity-bound: the caller's `X-User-ID` is
the id of the acting carrier or mill, so ownership-gated calls MUST use the
per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

ADMIN_USER_ID = "admin-1"
OPS_USER_ID = "ops-1"
SAFETY_USER_ID = "safety-1"
ACCOUNTANT_COMPILER_USER_ID = "acct-1"
ACCOUNTANT_APPROVER_USER_ID = "acct-2"

TEST_USERS = {
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "ops_headers": build_user_headers(OPS_USER_ID, "OperationsManager"),
    "safety_headers": build_user_headers(SAFETY_USER_ID, "SafetyOfficer"),
    "accountant_headers": build_user_headers(
        ACCOUNTANT_COMPILER_USER_ID, "SettlementAccountant"
    ),
    "accountant_two_headers": build_user_headers(
        ACCOUNTANT_APPROVER_USER_ID, "SettlementAccountant"
    ),
    # Identity-bound roles: these shared constants are only safe for calls that
    # never reach an ownership check (for example a 404 on an unknown resource).
    "carrier_headers": build_user_headers("carrier-unknown", "HaulContractor"),
    "scaler_headers": build_user_headers("scaler-unknown", "MillScaler"),
}


def make_carrier_headers(haul_contractor_id: str) -> dict:
    """Headers for a `HaulContractor` acting as itself.

    Pass the real `HaulContractor.id`: ownership checks compare the resource's
    `haul_contractor_id` to `X-User-ID`.
    """
    return build_user_headers(haul_contractor_id, "HaulContractor")


def make_scaler_headers(mill_id: str) -> dict:
    """Headers for a `MillScaler` acting on behalf of one mill.

    Pass the real `Mill.id`: ownership checks compare the resource's `mill_id`
    to `X-User-ID`.
    """
    return build_user_headers(mill_id, "MillScaler")


def make_admin_headers(user_id: str = ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_ops_headers(user_id: str = OPS_USER_ID) -> dict:
    return build_user_headers(user_id, "OperationsManager")


def make_safety_headers(user_id: str = SAFETY_USER_ID) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_accountant_headers(user_id: str = ACCOUNTANT_COMPILER_USER_ID) -> dict:
    return build_user_headers(user_id, "SettlementAccountant")
