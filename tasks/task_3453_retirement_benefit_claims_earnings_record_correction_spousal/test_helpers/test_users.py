"""Pre-built role headers for every role in the PRD (§2.1).

Claimant is entity-backed by Worker: X-User-ID must equal the acting worker's
id on any ownership-gated call. The shared `claimant_headers` constant is a
fallback only for tests that never touch ownership (its X-User-ID matches no
real worker). Every ownership-gated call MUST use make_claimant_headers with
the actual worker id.

The opaque roles (Employer, ClaimsSpecialist, SeniorAdjudicator,
ProgramAdministrator) carry operator identifiers that are never compared to
entity ids; named builders exist so segregation-of-duties tests can pin exact
X-User-ID strings (e.g. "spec-1" vs "sen-9").
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed:Worker — fallback for non-ownership tests only.
    "claimant_headers": build_user_headers("test-claimant-1", "Claimant"),
    # opaque roles — canonical shared form.
    "employer_headers": build_user_headers("test-employer-1", "Employer"),
    "claims_specialist_headers": build_user_headers("test-specialist-1", "ClaimsSpecialist"),
    "senior_adjudicator_headers": build_user_headers("test-adjudicator-1", "SeniorAdjudicator"),
    "program_administrator_headers": build_user_headers("test-admin-1", "ProgramAdministrator"),
}


def make_claimant_headers(worker_id: str) -> dict:
    """For Claimant (entity-backed by Worker): X-User-ID must equal the acting
    worker's id whenever the call is ownership-gated (filing claims and
    corrections for self, submitting evidence, withdraw, suspend/resume,
    waiver requests, reading own records)."""
    return build_user_headers(worker_id, "Claimant")


def make_claims_specialist_headers(user_id: str) -> dict:
    """ClaimsSpecialist with an explicit operator id — required wherever
    decided_by / created_by is asserted or segregation of duties is exercised."""
    return build_user_headers(user_id, "ClaimsSpecialist")


def make_senior_adjudicator_headers(user_id: str) -> dict:
    """SeniorAdjudicator with an explicit operator id — required wherever
    waiver_decided_by is asserted or segregation of duties is exercised."""
    return build_user_headers(user_id, "SeniorAdjudicator")


def make_program_administrator_headers(user_id: str) -> dict:
    """ProgramAdministrator with an explicit operator id."""
    return build_user_headers(user_id, "ProgramAdministrator")
