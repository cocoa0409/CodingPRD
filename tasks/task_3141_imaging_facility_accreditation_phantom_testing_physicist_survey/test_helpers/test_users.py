"""Role headers for every role declared by the API.

`FacilityAdmin` acts as the Facility entity itself and `MedicalPhysicist`
acts as the PersonnelQualification row, so both are entity-backed and each
has a per-instance builder that must be used whenever the call is
ownership-gated. `AccreditationBody`, `Any` and `Anonymous` are opaque.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles in
# tests where ownership of the subject resource is not being exercised.
TEST_USERS = {
    # entity_backed:Facility — shared constant is a fallback for calls that
    # are not ownership-gated.
    "facility_admin_headers": build_user_headers("test-facility-admin-1", "FacilityAdmin"),
    # entity_backed:PersonnelQualification — shared constant is a fallback.
    "medical_physicist_headers": build_user_headers("test-physicist-1", "MedicalPhysicist"),
    # opaque roles — the shared constant is the canonical form.
    "accreditation_body_headers": build_user_headers("test-accreditation-body-1", "AccreditationBody"),
    "any_headers": build_user_headers("test-any-caller-1", "Any"),
}


def make_facility_admin_headers(user_id: str) -> dict:
    """For FacilityAdmin (entity_backed:Facility).

    Pass the actual Facility.id as `user_id` whenever the call is
    ownership-gated, so the principal matches the facility it represents.
    """
    return build_user_headers(user_id, "FacilityAdmin")


def make_medical_physicist_headers(user_id: str) -> dict:
    """For MedicalPhysicist (entity_backed:PersonnelQualification).

    Pass the actual PersonnelQualification.id as `user_id` whenever the call
    is ownership-gated, so the survey's signatory matches the principal.
    """
    return build_user_headers(user_id, "MedicalPhysicist")


def make_anonymous_headers() -> dict:
    """A request that carries no usable role header at all."""
    return {"Content-Type": "application/json"}