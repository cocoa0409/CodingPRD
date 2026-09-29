"""Pre-built role headers for every role in the PRD.

All six roles use an **opaque** identity model (PRD §2.1): ``X-User-ID`` is an
operator identifier that the server records but never compares to any entity's
``id``.  What the system does implement is segregation of duties (PRD §2.9),
which compares the acting ``X-User-ID`` against a user identifier stored at an
earlier step.  Because of that, this module hands out **distinct** identifiers
per role, plus a second identifier for the roles that appear on both sides of a
duty-separation comparison, so that a legitimate two-person workflow never
trips the rule by accident.
"""
from prd_bench_local_runner.testing import build_user_headers

# Distinct opaque operator identifiers.
QC_ANALYST_USER_ID = "user-qc-analyst-001"
QC_ANALYST_2_USER_ID = "user-qc-analyst-002"
PRODUCTION_OPERATOR_USER_ID = "user-production-operator-001"
QA_RELEASER_USER_ID = "user-qa-releaser-001"
QA_RELEASER_2_USER_ID = "user-qa-releaser-002"
QA_RELEASER_3_USER_ID = "user-qa-releaser-003"
REGULATORY_AFFAIRS_USER_ID = "user-regulatory-affairs-001"
REGULATORY_AFFAIRS_2_USER_ID = "user-regulatory-affairs-002"
DISTRIBUTION_PLANNER_USER_ID = "user-distribution-planner-001"
PLATFORM_ADMIN_USER_ID = "user-platform-admin-001"

TEST_USERS = {
    "qc_analyst_headers": build_user_headers(QC_ANALYST_USER_ID, "QCAnalyst"),
    "qc_analyst_2_headers": build_user_headers(QC_ANALYST_2_USER_ID, "QCAnalyst"),
    "production_operator_headers": build_user_headers(
        PRODUCTION_OPERATOR_USER_ID, "ProductionOperator"),
    "qa_releaser_headers": build_user_headers(QA_RELEASER_USER_ID, "QAReleaser"),
    "qa_releaser_2_headers": build_user_headers(QA_RELEASER_2_USER_ID, "QAReleaser"),
    "qa_releaser_3_headers": build_user_headers(QA_RELEASER_3_USER_ID, "QAReleaser"),
    "regulatory_affairs_headers": build_user_headers(
        REGULATORY_AFFAIRS_USER_ID, "RegulatoryAffairs"),
    "regulatory_affairs_2_headers": build_user_headers(
        REGULATORY_AFFAIRS_2_USER_ID, "RegulatoryAffairs"),
    "distribution_planner_headers": build_user_headers(
        DISTRIBUTION_PLANNER_USER_ID, "DistributionPlanner"),
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_USER_ID, "PlatformAdmin"),
}

# Convenience aliases used pervasively by fixtures and tests.
QC_ANALYST = TEST_USERS["qc_analyst_headers"]
QC_ANALYST_2 = TEST_USERS["qc_analyst_2_headers"]
PRODUCTION_OPERATOR = TEST_USERS["production_operator_headers"]
QA_RELEASER = TEST_USERS["qa_releaser_headers"]
QA_RELEASER_2 = TEST_USERS["qa_releaser_2_headers"]
QA_RELEASER_3 = TEST_USERS["qa_releaser_3_headers"]
REGULATORY_AFFAIRS = TEST_USERS["regulatory_affairs_headers"]
REGULATORY_AFFAIRS_2 = TEST_USERS["regulatory_affairs_2_headers"]
DISTRIBUTION_PLANNER = TEST_USERS["distribution_planner_headers"]
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]

ROLE_HEADERS = {
    "QCAnalyst": QC_ANALYST,
    "ProductionOperator": PRODUCTION_OPERATOR,
    "QAReleaser": QA_RELEASER,
    "RegulatoryAffairs": REGULATORY_AFFAIRS,
    "DistributionPlanner": DISTRIBUTION_PLANNER,
    "PlatformAdmin": PLATFORM_ADMIN,
}


def make_qc_analyst_headers(user_id: str) -> dict:
    """Headers for a specific QCAnalyst operator identifier."""
    return build_user_headers(user_id, "QCAnalyst")


def make_production_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProductionOperator")


def make_qa_releaser_headers(user_id: str) -> dict:
    """Headers for a specific QAReleaser operator identifier — used by the
    duty-separation tests, which need the acting identifier to match (or
    deliberately differ from) one recorded at an earlier step."""
    return build_user_headers(user_id, "QAReleaser")


def make_regulatory_affairs_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegulatoryAffairs")


def make_distribution_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DistributionPlanner")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def headers_for_role(role: str, user_id: str = None) -> dict:
    """Headers for an arbitrary (possibly undeclared) role string."""
    return build_user_headers(user_id or f"user-{role.lower()}-999", role)


# Deliberately malformed header sets for the authentication rung (PRD §2.6).
MISSING_USER_ID_HEADERS = {"X-User-Role": "QAReleaser",
                           "Content-Type": "application/json"}
MISSING_ROLE_HEADERS = {"X-User-ID": QA_RELEASER_USER_ID,
                        "Content-Type": "application/json"}
EMPTY_USER_ID_HEADERS = {"X-User-ID": "", "X-User-Role": "QAReleaser",
                         "Content-Type": "application/json"}
EMPTY_ROLE_HEADERS = {"X-User-ID": QA_RELEASER_USER_ID, "X-User-Role": "",
                      "Content-Type": "application/json"}
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
