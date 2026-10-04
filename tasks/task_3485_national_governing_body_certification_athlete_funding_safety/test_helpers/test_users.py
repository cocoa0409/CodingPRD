"""Pre-built role headers for every role in the PRD.

Identity model (PRD user/role section):
- NGBAdmin is entity-backed: X-User-ID must equal the acting GoverningBody.id.
- Athlete is entity-backed: X-User-ID must equal the acting Athlete.id.
- The other five roles are opaque: X-User-ID is an operator identifier not
  tied to any persisted entity.

Segregation-of-duties pairs must be DISTINCT opaque ids: the certification
cycle issuer differs from the closer, the complaint triager differs from the
resolver, and the result submitter (an Athlete id) differs from the verifier
(a ResultsOfficial id). The constants below never reuse one opaque id across
the two halves of a segregated pair.
"""
from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Opaque operator ids (stable literals; recorded by the server as
# issued_by_user_id / closed_by_user_id / triaged_by_user_id /
# resolved_by_user_id / verified_by_user_id / submitted_by_user_id /
# interim_manager_id).
# ---------------------------------------------------------------------------

COMMITTEE_ADMIN_ID = "committee-admin-1"
COMMITTEE_ADMIN_ALT_ID = "committee-admin-2"
INTERIM_MANAGER_ID = "interim-manager-1"

# Two distinct auditors: issuer/triager vs closer/resolver (segregation).
AUDITOR_ISSUER_ID = "auditor-issuer-1"
AUDITOR_CLOSER_ID = "auditor-closer-2"
AUDITOR_THIRD_ID = "auditor-third-3"

SAFE_SPORT_OFFICER_ID = "safe-sport-officer-1"
SAFE_SPORT_OFFICER_ALT_ID = "safe-sport-officer-2"
ARBITRATOR_ID = "arbitrator-1"
ARBITRATOR_ALT_ID = "arbitrator-2"
RESULTS_OFFICIAL_ID = "results-official-1"
RESULTS_OFFICIAL_ALT_ID = "results-official-2"

# Fallback placeholder ids for the entity-backed roles. Safe ONLY for tests
# whose outcome does not depend on ownership (400/404/role-denied paths).
# Ownership-gated calls MUST use make_ngb_admin_headers(body_id) /
# make_athlete_headers(athlete_id) with the real entity id.
PLACEHOLDER_BODY_ID = "00000000-0000-0000-0000-000000000000"
PLACEHOLDER_ATHLETE_ID = "00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------------------
# Shared header constants
# ---------------------------------------------------------------------------

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "committee_admin_headers": build_user_headers(COMMITTEE_ADMIN_ID, "CommitteeAdmin"),
    "committee_admin_alt_headers": build_user_headers(COMMITTEE_ADMIN_ALT_ID, "CommitteeAdmin"),
    "interim_manager_headers": build_user_headers(INTERIM_MANAGER_ID, "CommitteeAdmin"),
    "auditor_issuer_headers": build_user_headers(AUDITOR_ISSUER_ID, "CertificationAuditor"),
    "auditor_closer_headers": build_user_headers(AUDITOR_CLOSER_ID, "CertificationAuditor"),
    "auditor_third_headers": build_user_headers(AUDITOR_THIRD_ID, "CertificationAuditor"),
    "safe_sport_officer_headers": build_user_headers(SAFE_SPORT_OFFICER_ID, "SafeSportOfficer"),
    "safe_sport_officer_alt_headers": build_user_headers(SAFE_SPORT_OFFICER_ALT_ID, "SafeSportOfficer"),
    "arbitrator_headers": build_user_headers(ARBITRATOR_ID, "Arbitrator"),
    "arbitrator_alt_headers": build_user_headers(ARBITRATOR_ALT_ID, "Arbitrator"),
    "results_official_headers": build_user_headers(RESULTS_OFFICIAL_ID, "ResultsOfficial"),
    "results_official_alt_headers": build_user_headers(RESULTS_OFFICIAL_ALT_ID, "ResultsOfficial"),
    # Entity-backed roles — fallback only for non-ownership tests.
    "ngb_admin_headers": build_user_headers(PLACEHOLDER_BODY_ID, "NGBAdmin"),
    "athlete_headers": build_user_headers(PLACEHOLDER_ATHLETE_ID, "Athlete"),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------

def make_ngb_admin_headers(governing_body_id: str) -> dict:
    """NGBAdmin is entity-backed: pass the owning GoverningBody.id whenever
    the call is ownership-gated (procedure/roster/entry writes, own-body
    athlete registration, own-athlete deal proposals)."""
    return build_user_headers(governing_body_id, "NGBAdmin")


def make_athlete_headers(athlete_id: str) -> dict:
    """Athlete is entity-backed: pass the acting Athlete.id whenever the call
    is ownership-gated (own results, own appeals, deal consent, own slot
    decisions, self-retirement)."""
    return build_user_headers(athlete_id, "Athlete")


def make_committee_admin_headers(user_id: str = COMMITTEE_ADMIN_ID) -> dict:
    return build_user_headers(user_id, "CommitteeAdmin")


def make_auditor_headers(user_id: str) -> dict:
    """CertificationAuditor with a caller-chosen opaque id — use distinct ids
    for the two halves of a segregated pair (issue/close, triage/resolve)."""
    return build_user_headers(user_id, "CertificationAuditor")


def make_safe_sport_officer_headers(user_id: str = SAFE_SPORT_OFFICER_ID) -> dict:
    return build_user_headers(user_id, "SafeSportOfficer")


def make_arbitrator_headers(user_id: str = ARBITRATOR_ID) -> dict:
    return build_user_headers(user_id, "Arbitrator")


def make_results_official_headers(user_id: str = RESULTS_OFFICIAL_ID) -> dict:
    return build_user_headers(user_id, "ResultsOfficial")
