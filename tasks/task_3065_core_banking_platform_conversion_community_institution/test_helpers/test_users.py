"""Pre-built role headers for every role in the PRD (§2.1).

For every role, X-User-ID is an opaque operator identifier not tied to any
persisted entity (PRD §2.1), so shared constants are the canonical form.
Per-instance builders exist only to give segregation-of-duties tests
explicit control over the user id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "pm_headers": build_user_headers("pm-alice", "ProjectManager"),
    "ce_headers": build_user_headers("ce-erin", "ConversionEngineer"),
    "ops_headers": build_user_headers("ops-bob", "OperationsLead"),
    "trainer_headers": build_user_headers("tr-tina", "Trainer"),
    "co_headers": build_user_headers("co-cleo", "CommunicationsOfficer"),
    "vtl_headers": build_user_headers("vtl-nina", "VendorTriageLead"),
    "fc_headers": build_user_headers("fc-carol", "FinanceController"),
}

# Empty header set — unauthenticated caller.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


def make_pm_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProjectManager")


def make_ce_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConversionEngineer")


def make_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "OperationsLead")


def make_trainer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Trainer")


def make_co_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CommunicationsOfficer")


def make_vtl_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "VendorTriageLead")


def make_fc_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceController")
