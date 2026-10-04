"""Pre-built role headers for every role in the PRD (§2.1).

Identity model:
- Staff roles (RefugeManager, Biologist, PermitOfficer, VolunteerCoordinator,
  LawEnforcementOfficer, StateAgencyPartner) are opaque — X-User-ID is never
  compared to any entity field. Shared constants are canonical.
- PermitApplicant and Cooperator are opaque BUT carry ownership anchors:
  X-User-ID must equal the application's applicant_ref / the bid's or
  agreement's cooperator_ref. Use the per-instance builders
  make_permit_applicant_headers(ref) / make_cooperator_headers(ref) for any
  ownership-gated call; the shared constants are safe only for tests whose
  outcome does not depend on ownership (e.g. 400-on-bad-payload probes).
- Volunteer is entity-backed: X-User-ID IS the acting Volunteer's id. Always
  use make_volunteer_headers(volunteer["id"]). There is deliberately no
  shared Volunteer constant — every Volunteer-role call in the API is
  self-scoped, so a placeholder id would fail every ownership check.
- Anonymous calls WITHOUT an identity header (only X-User-Role).
"""
from prd_bench_local_runner.testing import build_user_headers

__all__ = [
    "TEST_USERS", "ANONYMOUS_HEADERS",
    "make_permit_applicant_headers", "make_cooperator_headers",
    "make_volunteer_headers",
]

# Anonymous is the one role that calls without an identity header (PRD §2.1).
ANONYMOUS_HEADERS = {
    "X-User-Role": "Anonymous",
    "Content-Type": "application/json",
}

TEST_USERS = {
    # Opaque staff roles — shared constants are canonical.
    "refuge_manager_headers": build_user_headers("test-refuge-manager-1", "RefugeManager"),
    "biologist_headers": build_user_headers("test-biologist-1", "Biologist"),
    "permit_officer_headers": build_user_headers("test-permit-officer-1", "PermitOfficer"),
    "volunteer_coordinator_headers": build_user_headers(
        "test-volunteer-coordinator-1", "VolunteerCoordinator"),
    "law_enforcement_officer_headers": build_user_headers(
        "test-law-enforcement-officer-1", "LawEnforcementOfficer"),
    "state_agency_partner_headers": build_user_headers(
        "test-state-agency-partner-1", "StateAgencyPartner"),
    # Ownership-anchored opaque roles — shared constants are a fallback for
    # non-ownership tests ONLY (bad-payload, not-found, role-denied probes).
    "permit_applicant_headers": build_user_headers("test-applicant-1", "PermitApplicant"),
    "cooperator_headers": build_user_headers("test-cooperator-1", "Cooperator"),
    # Public, no identity header.
    "anonymous_headers": ANONYMOUS_HEADERS,
}


def make_permit_applicant_headers(applicant_ref: str) -> dict:
    """PermitApplicant ownership anchor: X-User-ID must equal the
    application payload's applicant_ref (create) and the stored
    applicant_ref (resubmit / pay / own reads)."""
    return build_user_headers(applicant_ref, "PermitApplicant")


def make_cooperator_headers(cooperator_ref: str) -> dict:
    """Cooperator ownership anchor: X-User-ID must equal the bid payload's
    cooperator_ref (bid create) and the agreement's cooperator_ref
    (PAYMENT ledger entries, own reads)."""
    return build_user_headers(cooperator_ref, "Cooperator")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """Volunteer is entity-backed: pass the actual Volunteer.id. Required for
    the self-scoped assignment reads (list and by-id)."""
    return build_user_headers(volunteer_id, "Volunteer")
