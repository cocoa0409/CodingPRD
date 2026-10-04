"""Pre-built role headers for every capacity the API recognizes.

Three capacities are entity-backed, so their `X-User-ID` must carry the `id` of a
real entity whenever the call is ownership-gated:

  * `Member`           — the acting member's own id
  * `CareAdvocate`     — the acting advocate's own id
  * `ClinicCoordinator` — the acting clinic's own id

The remaining capacities are opaque operators whose id is never matched against a
persisted row; the shared constants below are their canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # --- entity-backed roles: shared constants are fallbacks for calls that ---
    # --- do not exercise ownership. Prefer the per-instance builders below. ---
    "member_headers": build_user_headers("test-member-fallback", "Member"),
    "care_advocate_headers": build_user_headers("test-advocate-fallback", "CareAdvocate"),
    "clinic_coordinator_headers": build_user_headers("test-clinic-fallback", "ClinicCoordinator"),
    # --- opaque roles: the shared constant IS the canonical form ---
    "clinical_reviewer_headers": build_user_headers("test-reviewer-1", "ClinicalReviewer"),
    "specialty_pharmacist_headers": build_user_headers("test-pharmacist-1", "SpecialtyPharmacist"),
    "claims_processor_headers": build_user_headers("test-claims-processor-1", "ClaimsProcessor"),
    "claims_reviewer_headers": build_user_headers("test-claims-reviewer-1", "ClaimsReviewer"),
    "network_manager_headers": build_user_headers("test-network-manager-1", "NetworkManager"),
    "plan_administrator_headers": build_user_headers("test-plan-admin-1", "PlanAdministrator"),
}


# --- Per-instance builders (required for every entity-backed role) --------------

def make_member_headers(member_id: str) -> dict:
    """Headers for the Member role. Pass the acting Member's own `id` whenever the
    call is ownership-gated — a member may read only their own records."""
    return build_user_headers(member_id, "Member")


def make_care_advocate_headers(advocate_id: str) -> dict:
    """Headers for the CareAdvocate role. Pass the acting CareAdvocate's own `id`;
    plans, pathway requests, medication orders and surrender routes carry the
    guiding advocate in `care_advocate_id`, which is compared against `X-User-ID`."""
    return build_user_headers(advocate_id, "CareAdvocate")


def make_clinic_coordinator_headers(clinic_id: str) -> dict:
    """Headers for the ClinicCoordinator role. Pass the acting Clinic's own `id`;
    a coordinator acts for one clinic of record, and clinic-scoped operations are
    performed in that clinic's name."""
    return build_user_headers(clinic_id, "ClinicCoordinator")


def make_clinical_reviewer_headers(reviewer_id: str) -> dict:
    """Headers for the ClinicalReviewer role. The id is an opaque operator
    identifier; it is recorded as `decision_actor` and is also the value the
    segregation-of-duties rule compares against."""
    return build_user_headers(reviewer_id, "ClinicalReviewer")


def make_claims_processor_headers(operator_id: str) -> dict:
    """Headers for the ClaimsProcessor role, with an opaque operator identifier."""
    return build_user_headers(operator_id, "ClaimsProcessor")


def make_claims_reviewer_headers(reviewer_id: str) -> dict:
    """Headers for the ClaimsReviewer role. The id must differ from the
    `decision_actor` recorded on the claim's last adjudication."""
    return build_user_headers(reviewer_id, "ClaimsReviewer")


def make_network_manager_headers(operator_id: str) -> dict:
    """Headers for the NetworkManager role, with an opaque operator identifier."""
    return build_user_headers(operator_id, "NetworkManager")