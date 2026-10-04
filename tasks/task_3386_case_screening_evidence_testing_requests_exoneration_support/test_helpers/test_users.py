"""Pre-built role headers for every role in the PRD.

Per PRD section 2.1: the seven staff roles carry an opaque X-User-ID that is
never compared to any entity's id, so fixed identifiers are always safe for
them. The Client role is entity-backed: X-User-ID IS the acting Client
record's id, and ownership checks compare it against client_id chains - every
ownership-gated Client call MUST use make_client_headers(client_id) with the
real Client id. The shared "client_headers" constant is only a fallback for
tests that do not exercise ownership (for example role-admission probes).

The fixed opaque ids double as the attributable actor ids the server records
(recommended_by_user_id / decided_by_user_id / created_by_user_id /
assigned_attorney_id). The segregation-of-duties rule on decide compares the
deciding ManagingAttorney's X-User-ID against recommended_by_user_id, so the
recommender and the decider must never share an id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical opaque operator identifiers (used by the composite fixtures; tests
# asserting recommended_by_user_id / decided_by_user_id should reference these).
PLATFORM_ADMIN_ID = "pa_1"
INTAKE_SPECIALIST_ID = "spec_1"
SECOND_SPECIALIST_ID = "spec_2"
THIRD_SPECIALIST_ID = "spec_3"
MANAGING_ATTORNEY_ID = "ma_1"
SECOND_MANAGING_ATTORNEY_ID = "ma_2"
STAFF_ATTORNEY_ID = "atty_1"
EVIDENCE_ANALYST_ID = "ea_1"
CLIENT_SERVICES_ADVOCATE_ID = "csa_1"
POLICY_DIRECTOR_ID = "pd_1"

TEST_USERS = {
    # Opaque staff roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "intake_specialist_headers": build_user_headers(INTAKE_SPECIALIST_ID, "IntakeSpecialist"),
    "managing_attorney_headers": build_user_headers(MANAGING_ATTORNEY_ID, "ManagingAttorney"),
    "staff_attorney_headers": build_user_headers(STAFF_ATTORNEY_ID, "StaffAttorney"),
    "evidence_analyst_headers": build_user_headers(EVIDENCE_ANALYST_ID, "EvidenceAnalyst"),
    "client_services_advocate_headers": build_user_headers(
        CLIENT_SERVICES_ADVOCATE_ID, "ClientServicesAdvocate"
    ),
    "policy_director_headers": build_user_headers(POLICY_DIRECTOR_ID, "PolicyDirector"),
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only; it matches no real Client id, so any ownership-gated call
    # made with it would be rejected with ERR_OWNERSHIP_MISMATCH.
    "client_headers": build_user_headers("client-unowned-1", "Client"),
}


# =============================================================================
# Per-instance builders
# =============================================================================

def make_client_headers(client_id: str) -> dict:
    """Headers for the Client role. Pass the actual Client.id whenever the
    call is ownership-gated (self-submission, submit-supplement, own reads)."""
    return build_user_headers(client_id, "Client")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_intake_specialist_headers(user_id: str) -> dict:
    """Headers for a named IntakeSpecialist (the RECOMMEND actor id)."""
    return build_user_headers(user_id, "IntakeSpecialist")


def make_managing_attorney_headers(user_id: str) -> dict:
    """Headers for a named ManagingAttorney (the decide actor id). Pass the
    recommender's id here to probe ERR_DECISION_SELF_APPROVAL."""
    return build_user_headers(user_id, "ManagingAttorney")


def make_staff_attorney_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StaffAttorney")


def make_evidence_analyst_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "EvidenceAnalyst")


def make_client_services_advocate_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClientServicesAdvocate")


def make_policy_director_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PolicyDirector")


# =============================================================================
# Malformed credentials, for the header-presence / role-vocabulary probes
# =============================================================================

def headers_without_user_id(role: str = "StaffAttorney") -> dict:
    """Headers that omit X-User-ID entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str = "probe_1") -> dict:
    """Headers that omit X-User-Role entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_empty_user_id(role: str = "StaffAttorney") -> dict:
    """Headers whose X-User-ID is present but empty."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_with_empty_role(user_id: str = "probe_1") -> dict:
    """Headers whose X-User-Role is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


# A syntactically valid header value that names no declared role.
UNDECLARED_ROLE = "ForensicIntern"


def headers_with_undeclared_role(user_id: str = "probe_1") -> dict:
    """Headers naming a role the PRD does not declare."""
    return build_user_headers(user_id, UNDECLARED_ROLE)
