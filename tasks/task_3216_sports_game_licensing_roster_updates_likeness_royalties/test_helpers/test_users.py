"""Pre-built role headers for every role in the PRD (§2.1).

All nine roles carry opaque identity: X-User-ID is an operator identifier never
compared to any entity id. It only matters for segregation-of-duties checks
(publish vs submit; edition approve vs submit; audit settle vs open), so tests
that exercise SoD build headers with an explicit operator id via the
make_*_headers builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "licensing_admin_headers": build_user_headers("test-admin-1", "LicensingAdmin"),
    "rights_officer_headers": build_user_headers("test-rights-1", "RightsOfficer"),
    "roster_operator_headers": build_user_headers("test-operator-1", "RosterOperator"),
    "roster_reviewer_headers": build_user_headers("test-reviewer-1", "RosterReviewer"),
    "liveops_manager_headers": build_user_headers("test-liveops-1", "LiveOpsManager"),
    "finance_controller_headers": build_user_headers("test-finance-1", "FinanceController"),
    "league_auditor_headers": build_user_headers("test-league-aud-1", "LeagueAuditor"),
    "union_auditor_headers": build_user_headers("test-union-aud-1", "UnionAuditor"),
    "compliance_reviewer_headers": build_user_headers("test-compliance-1", "ComplianceReviewer"),
}


def make_licensing_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LicensingAdmin")


def make_rights_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RightsOfficer")


def make_roster_operator_headers(user_id: str) -> dict:
    """For RosterOperator. Pass the batch's submitted_by value whenever the
    downstream publish is SoD-gated against this operator."""
    return build_user_headers(user_id, "RosterOperator")


def make_roster_reviewer_headers(user_id: str) -> dict:
    """For RosterReviewer. The publish step must use an id different from the
    batch's submitted_by (PRD §2.9)."""
    return build_user_headers(user_id, "RosterReviewer")


def make_liveops_manager_headers(user_id: str) -> dict:
    """For LiveOpsManager. The edition submit-review step records this id for
    the later approve SoD check."""
    return build_user_headers(user_id, "LiveOpsManager")


def make_finance_controller_headers(user_id: str) -> dict:
    """For FinanceController. Audit settle must use an id different from the
    auditor who opened the case (PRD §2.9)."""
    return build_user_headers(user_id, "FinanceController")


def make_league_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LeagueAuditor")


def make_union_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "UnionAuditor")


def make_compliance_reviewer_headers(user_id: str) -> dict:
    """For ComplianceReviewer. Edition approve must use an id different from
    the submit-review operator (PRD §2.9)."""
    return build_user_headers(user_id, "ComplianceReviewer")
