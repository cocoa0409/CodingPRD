"""Pre-built role headers for every role in the PRD.

All roles in this system use opaque operator identifiers (PRD §2.1): the
X-User-ID value is not tied to any persisted entity id, so a shared constant
per role is the canonical form. Per-scenario user ids matter only where the
PRD compares user ids directly (segregation of duties on screening
clearance); for that, use make_recorder_headers / make_screener_headers with
a chosen id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-01", "PlatformAdmin"),
    "compliance_headers": build_user_headers("co-01", "ComplianceOfficer"),
    "recorder_headers": build_user_headers("rec-01", "Recorder"),
    "recorder2_headers": build_user_headers("rec-02", "Recorder"),
    "recorder3_headers": build_user_headers("rec-03", "Recorder"),
    "recorder4_headers": build_user_headers("rec-04", "Recorder"),
    "screener_headers": build_user_headers("ms-01", "MedicalScreener"),
    "phlebotomist_headers": build_user_headers("ph-01", "Phlebotomist"),
}


def make_recorder_headers(user_id: str) -> dict:
    """Recorder headers with a caller-chosen user id (for SoD scenarios)."""
    return build_user_headers(user_id, "Recorder")


def make_screener_headers(user_id: str) -> dict:
    """MedicalScreener headers with a caller-chosen user id (for SoD scenarios)."""
    return build_user_headers(user_id, "MedicalScreener")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_phlebotomist_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Phlebotomist")
