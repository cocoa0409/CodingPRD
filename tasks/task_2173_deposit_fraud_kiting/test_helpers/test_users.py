"""Pre-built role headers for every role in the PRD (§2.1)."""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants.  Every role except AccountHolder carries an opaque
# X-User-ID that the server never compares to an entity id, so a shared
# constant is the canonical form for those five roles.
TEST_USERS = {
    "ops_admin_headers": build_user_headers("ops-1", "OperationsAdmin"),
    "ops_admin_2_headers": build_user_headers("ops-2", "OperationsAdmin"),
    "analyst_headers": build_user_headers("analyst-1", "FraudAnalyst"),
    "analyst_2_headers": build_user_headers("analyst-2", "FraudAnalyst"),
    "supervisor_headers": build_user_headers("sup-1", "FraudSupervisor"),
    "supervisor_2_headers": build_user_headers("sup-2", "FraudSupervisor"),
    "bsa_officer_headers": build_user_headers("bsa-1", "BsaOfficer"),
    "counsel_headers": build_user_headers("counsel-1", "LegalCounsel"),
    "counsel_2_headers": build_user_headers("counsel-2", "LegalCounsel"),
    # Fallback only — never use for an ownership-gated call.
    "account_holder_headers": build_user_headers("holder-1", "AccountHolder"),
}

OPS_ADMIN_USER_ID = "ops-1"
ANALYST_USER_ID = "analyst-1"
ANALYST_2_USER_ID = "analyst-2"
SUPERVISOR_USER_ID = "sup-1"
SUPERVISOR_2_USER_ID = "sup-2"
BSA_OFFICER_USER_ID = "bsa-1"
COUNSEL_USER_ID = "counsel-1"
COUNSEL_2_USER_ID = "counsel-2"


def make_account_holder_headers(customer_id: str) -> dict:
    """For AccountHolder, whose X-User-ID is the acting Customer's id.

    Pass the real Customer id whenever the call is ownership-gated — reading a
    deposit account or answering that account's step-up challenge.
    """
    return build_user_headers(customer_id, "AccountHolder")


def make_ops_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsAdmin")


def make_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FraudAnalyst")


def make_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FraudSupervisor")


def make_bsa_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "BsaOfficer")


def make_counsel_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LegalCounsel")


def make_headers(user_id: str, role: str) -> dict:
    return build_user_headers(user_id, role)
