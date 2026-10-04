"""Pre-built role headers for every role in the PRD (§2.1).

LeadStateAG, ParticipatingStateAG and StateLegislature are entity-backed by
StateOffice: their X-User-ID must be the id of the StateOffice being acted
through, so fixtures and tests that exercise ownership-gated calls MUST use
the per-instance builders below with the actual office id. The shared
constants in TEST_USERS are safe only for opaque roles and for tests whose
outcome does not depend on office identity matching (e.g. 400/404 probes).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are canonical.
    "committee_chair_headers": build_user_headers("test-chair-1", "CommitteeChair"),
    "defendant_counsel_headers": build_user_headers("test-counsel-1", "DefendantCounsel"),
    "fund_administrator_headers": build_user_headers("test-fundadmin-1", "FundAdministrator"),
    "compliance_monitor_headers": build_user_headers("test-monitor-1", "ComplianceMonitor"),
    # Entity-backed roles — fallback constants for non-ownership tests only.
    "lead_state_ag_headers": build_user_headers("test-leadag-1", "LeadStateAG"),
    "participating_state_ag_headers": build_user_headers("test-stateag-1", "ParticipatingStateAG"),
    "state_legislature_headers": build_user_headers("test-legislature-1", "StateLegislature"),
}


def make_lead_state_ag_headers(user_id: str) -> dict:
    """For LeadStateAG (entity-backed by StateOffice). Pass the actual
    StateOffice.id whenever the call is ownership- or lead-gated (settlement
    create/revise, response accept, own-office sign-on/demand/disbursement)."""
    return build_user_headers(user_id, "LeadStateAG")


def make_participating_state_ag_headers(user_id: str) -> dict:
    """For ParticipatingStateAG (entity-backed by StateOffice). Pass the
    actual StateOffice.id whenever the call is ownership-gated (execute-cia,
    withdraw, demand create, sign-on, disbursement create for that office)."""
    return build_user_headers(user_id, "ParticipatingStateAG")


def make_state_legislature_headers(user_id: str) -> dict:
    """For StateLegislature (entity-backed by StateOffice). Pass the actual
    StateOffice.id of the certifying state when certifying a disbursement —
    certification is lawful only for the legislature's own state."""
    return build_user_headers(user_id, "StateLegislature")
