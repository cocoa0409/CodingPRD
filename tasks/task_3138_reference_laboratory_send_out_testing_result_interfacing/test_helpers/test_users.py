"""Pre-built role headers for every role in the PRD.

Identity semantics (PRD 2.1): ``LabClientAdmin`` is entity-backed — its
``X-User-ID`` is the id of the acting ``ClientLaboratory``. Every other role is
an opaque operator identifier not tied to any persisted entity.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Safe for opaque roles, and for LabClientAdmin calls that do
# not exercise ownership scoping (e.g. creating a catalog entry, which takes no
# client in its path or body).
TEST_USERS = {
    "reference_lab_operations_headers": build_user_headers("test-ops-1", "ReferenceLabOperations"),
    "lab_client_admin_headers": build_user_headers("test-client-admin-1", "LabClientAdmin"),
    "courier_coordinator_headers": build_user_headers("test-courier-1", "CourierCoordinator"),
    "accessioning_technologist_headers": build_user_headers(
        "test-accessioning-1", "AccessioningTechnologist"),
    "medical_technologist_headers": build_user_headers("test-medtech-1", "MedicalTechnologist"),
    "interface_analyst_headers": build_user_headers("test-interface-1", "InterfaceAnalyst"),
    "pathologist_headers": build_user_headers("test-pathologist-1", "Pathologist"),
    "medical_director_headers": build_user_headers("test-director-1", "MedicalDirector"),
    "lab_billing_specialist_headers": build_user_headers(
        "test-billing-1", "LabBillingSpecialist"),
    "utilization_reviewer_headers": build_user_headers("test-utilization-1", "UtilizationReviewer"),
}


def make_lab_client_admin_headers(user_id: str) -> dict:
    """For LabClientAdmin (entity_backed:ClientLaboratory).

    Pass the actual ``ClientLaboratory.id`` as ``user_id`` whenever the call is
    ownership-gated (publish-requirements, submit order, cancel order,
    acknowledge/dismiss advisory, read one client). The shared constant above is
    a fallback for calls that do not compare the caller against a client id.
    """
    return build_user_headers(user_id, "LabClientAdmin")


# Distinct opaque operator identities, used where a rule compares two operator
# identifiers against one another (segregation of duties on result release).
def make_medical_technologist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MedicalTechnologist")


def make_pathologist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Pathologist")


def make_reference_lab_operations_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReferenceLabOperations")