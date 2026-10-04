"""Role headers for every role named in PRD section 2.1.

Patient, Physician and QAAuditor are entity-backed roles: for any
ownership-gated call the headers MUST be built with the actual entity's id
via the ``make_*_headers`` builders.  The shared constants are only safe for
opaque roles (ComplianceOfficer, PlatformAdmin) and for tests whose outcome
never depends on ownership.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "compliance_headers": build_user_headers("compliance-1", "ComplianceOfficer"),
    # Entity-backed roles: shared constants for non-ownership tests only.
    "patient_headers": build_user_headers("test-patient-1", "Patient"),
    "physician_headers": build_user_headers("test-physician-1", "Physician"),
    "qa_auditor_headers": build_user_headers("test-auditor-1", "QAAuditor"),
}

ADMIN = TEST_USERS["admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


def make_patient_headers(user_id):
    """Patient (entity-backed): pass the actual Patient.id for ownership-gated calls."""
    return build_user_headers(user_id, "Patient")


def make_physician_headers(user_id):
    """Physician (entity-backed): pass the actual Physician.id for ownership-gated calls."""
    return build_user_headers(user_id, "Physician")


def make_qa_auditor_headers(user_id):
    """QAAuditor (entity-backed): pass the actual QAAuditor.id for ownership-gated calls."""
    return build_user_headers(user_id, "QAAuditor")


def make_compliance_headers(user_id="compliance-1"):
    """ComplianceOfficer is opaque; any identifier works."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_admin_headers(user_id="admin-1"):
    """PlatformAdmin is opaque; any identifier works."""
    return build_user_headers(user_id, "PlatformAdmin")
