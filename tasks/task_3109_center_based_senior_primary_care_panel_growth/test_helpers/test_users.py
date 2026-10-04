"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for opaque roles, and for tests that do not exercise
ownership. CareTeamLead is entity-backed by CareTeam: any ownership-gated call
(e.g., completing an appointment) must use make_care_team_lead_headers with the
acting team's id as X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "network_operator_headers": build_user_headers("test-network-operator-1", "NetworkOperator"),
    "enrollment_coordinator_headers": build_user_headers(
        "test-enrollment-coordinator-1", "EnrollmentCoordinator"
    ),
    "care_team_lead_headers": build_user_headers("test-care-team-lead-1", "CareTeamLead"),
    "front_desk_headers": build_user_headers("test-front-desk-1", "FrontDesk"),
    "transport_dispatcher_headers": build_user_headers(
        "test-transport-dispatcher-1", "TransportDispatcher"
    ),
    "triage_nurse_headers": build_user_headers("test-triage-nurse-1", "TriageNurse"),
    "claims_adjudicator_headers": build_user_headers(
        "test-claims-adjudicator-1", "ClaimsAdjudicator"
    ),
    "finance_analyst_headers": build_user_headers("test-finance-analyst-1", "FinanceAnalyst"),
    "finance_controller_headers": build_user_headers(
        "test-finance-controller-1", "FinanceController"
    ),
}


def make_care_team_lead_headers(care_team_id: str) -> dict:
    """For CareTeamLead (entity-backed by CareTeam): X-User-ID must equal the
    acting care team's id whenever the call is ownership-gated (appointment
    completion)."""
    return build_user_headers(care_team_id, "CareTeamLead")
