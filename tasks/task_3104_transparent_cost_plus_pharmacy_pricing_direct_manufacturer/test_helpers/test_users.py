"""Pre-built role headers for every role in the API.

`Patient` identifies the acting principal by the id of the acting Patient
entity, so the patient header must always be built with the real entity id
(see make_patient_headers). `Pharmacist` and `PharmacyOps` carry opaque
operator identifiers that are never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles and for Patient calls that do
# not exercise ownership.
TEST_USERS = {
    "pharmacy_ops_headers": build_user_headers("ops-operator-1", "PharmacyOps"),
    "pharmacist_headers": build_user_headers("pharmacist-1", "Pharmacist"),
    "anonymous_headers": build_user_headers("anonymous-caller", "Anonymous"),
}


def make_patient_headers(patient_id: str) -> dict:
    """Headers for a Patient caller acting as the Patient entity `patient_id`.

    Patient ownership is enforced by comparing the addressed resource's
    patient foreign key to X-User-ID, so this builder must be called with an
    actual Patient.id.
    """
    return build_user_headers(patient_id, "Patient")


def make_pharmacist_headers(user_id: str = "pharmacist-1") -> dict:
    """Headers for a Pharmacist caller (opaque identity)."""
    return build_user_headers(user_id, "Pharmacist")


def make_pharmacy_ops_headers(user_id: str = "ops-operator-1") -> dict:
    """Headers for a PharmacyOps caller (opaque identity)."""
    return build_user_headers(user_id, "PharmacyOps")