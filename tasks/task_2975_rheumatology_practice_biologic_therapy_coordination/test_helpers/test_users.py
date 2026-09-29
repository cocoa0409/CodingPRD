"""Pre-built role headers for every role in the PRD (§2.1).

`X-User-ID` is interpreted per role:
  * `Rheumatologist` and `InfusionNurse` — the id of the acting `Clinician`.
  * `Patient` — the id of the acting `Patient`.
  * `PriorAuthCoordinator`, `PayerReviewer`, `BenefitsCounselor`, `RegistryAdmin`
    — an opaque operator identifier not tied to any persisted entity.

Tests whose success depends on ownership MUST use the per-instance builders
below with the real entity id; the shared constants are only safe for opaque
roles and for tests that never reach an ownership comparison.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator identities — the canonical form for these four roles.
    "registry_admin_headers": build_user_headers("ops-registry-admin-1", "RegistryAdmin"),
    "prior_auth_coordinator_headers": build_user_headers("ops-pa-coordinator-1", "PriorAuthCoordinator"),
    "payer_reviewer_headers": build_user_headers("ops-payer-reviewer-1", "PayerReviewer"),
    "benefits_counselor_headers": build_user_headers("ops-counselor-alpha", "BenefitsCounselor"),
    # A second, distinct counselor identity for the segregation-of-duties rule.
    "benefits_counselor_second_headers": build_user_headers("ops-counselor-beta", "BenefitsCounselor"),
    # Entity-backed roles: these shared constants are fallbacks for tests that
    # never reach an ownership comparison (bad payloads, missing resources,
    # role-only rejections). Ownership-gated calls must use the builders below.
    "rheumatologist_headers": build_user_headers("unbacked-rheumatologist-1", "Rheumatologist"),
    "infusion_nurse_headers": build_user_headers("unbacked-infusion-nurse-1", "InfusionNurse"),
    "patient_headers": build_user_headers("unbacked-patient-1", "Patient"),
}

# Opaque operator identifier strings, exposed so tests can assert the audit
# fields the server stamps from `X-User-ID`.
COUNSELOR_ALPHA_USER_ID = "ops-counselor-alpha"
COUNSELOR_BETA_USER_ID = "ops-counselor-beta"
REGISTRY_ADMIN_USER_ID = "ops-registry-admin-1"
PRIOR_AUTH_COORDINATOR_USER_ID = "ops-pa-coordinator-1"
PAYER_REVIEWER_USER_ID = "ops-payer-reviewer-1"


def make_rheumatologist_headers(clinician_id: str) -> dict:
    """`Rheumatologist` headers carrying a real `Clinician.id` as `X-User-ID`."""
    return build_user_headers(clinician_id, "Rheumatologist")


def make_infusion_nurse_headers(clinician_id: str) -> dict:
    """`InfusionNurse` headers carrying a real `Clinician.id` as `X-User-ID`."""
    return build_user_headers(clinician_id, "InfusionNurse")


def make_patient_headers(patient_id: str) -> dict:
    """`Patient` headers carrying a real `Patient.id` as `X-User-ID`."""
    return build_user_headers(patient_id, "Patient")


def make_benefits_counselor_headers(user_id: str) -> dict:
    """`BenefitsCounselor` headers carrying an arbitrary opaque operator id."""
    return build_user_headers(user_id, "BenefitsCounselor")


def make_registry_admin_headers(user_id: str = REGISTRY_ADMIN_USER_ID) -> dict:
    return build_user_headers(user_id, "RegistryAdmin")


def make_prior_auth_coordinator_headers(user_id: str = PRIOR_AUTH_COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "PriorAuthCoordinator")


def make_payer_reviewer_headers(user_id: str = PAYER_REVIEWER_USER_ID) -> dict:
    return build_user_headers(user_id, "PayerReviewer")


def make_headers(user_id: str, role: str) -> dict:
    """Free-form builder for RBAC matrices that iterate over role names."""
    return build_user_headers(user_id, role)


def headers_for_role(role: str, user_id: str = "probe-user-1") -> dict:
    """Headers for an arbitrary role string, used by role-rejection matrices."""
    return build_user_headers(user_id, role)
