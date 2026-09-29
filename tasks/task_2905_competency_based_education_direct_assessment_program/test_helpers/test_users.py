"""Pre-built identity headers for every role named by the PRD.

Three roles are entity-backed — a Student acts under its own student id, a
FacultyMentor under its mentor id and an Evaluator under its evaluator id — so
every ownership-gated call must use the matching ``make_*_headers`` builder with
the real row's id. The shared constants below are only for opaque roles and for
calls that exercise no ownership check.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is the canonical form.
    "registrar_headers": build_user_headers("registrar-1", "Registrar"),
    "integrity_officer_headers": build_user_headers("officer-1", "IntegrityOfficer"),
    "financial_aid_officer_headers": build_user_headers("aid-1", "FinancialAidOfficer"),
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Entity-backed roles — fallback for tests that exercise no ownership check.
    "student_headers": build_user_headers("student-1", "Student"),
    "faculty_mentor_headers": build_user_headers("mentor-1", "FacultyMentor"),
    "evaluator_headers": build_user_headers("evaluator-1", "Evaluator"),
}

# A second opaque integrity officer, because one officer may not both open and
# resolve the same case.
SECOND_INTEGRITY_OFFICER = build_user_headers("officer-2", "IntegrityOfficer")


def make_registrar_headers(user_id: str = "registrar-1") -> Dict[str, str]:
    """Registrar identities are opaque strings."""
    return build_user_headers(user_id, "Registrar")


def make_integrity_officer_headers(user_id: str) -> Dict[str, str]:
    """IntegrityOfficer identities are opaque strings; pass a distinct one per
    officer so the resolver can differ from the opener."""
    return build_user_headers(user_id, "IntegrityOfficer")


def make_financial_aid_officer_headers(user_id: str = "aid-1") -> Dict[str, str]:
    return build_user_headers(user_id, "FinancialAidOfficer")


def make_platform_admin_headers(user_id: str = "admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, "PlatformAdmin")


def make_student_headers(user_id: str) -> Dict[str, str]:
    """For the Student role. Pass the actual student's id whenever the call is
    ownership-gated."""
    return build_user_headers(user_id, "Student")


def make_mentor_headers(user_id: str) -> Dict[str, str]:
    """For the FacultyMentor role. Pass the actual mentor's id whenever the call
    is ownership-gated."""
    return build_user_headers(user_id, "FacultyMentor")


def make_evaluator_headers(user_id: str) -> Dict[str, str]:
    """For the Evaluator role. Pass the actual evaluator's id whenever the call
    is ownership-gated."""
    return build_user_headers(user_id, "Evaluator")


def blank_identity_headers(role: str = "Registrar") -> Dict[str, str]:
    """Headers whose X-User-ID is present but empty. The empty string — never a
    whitespace string, which the HTTP layer refuses to transmit."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def blank_role_headers(user_id: str = "registrar-1") -> Dict[str, str]:
    """Headers whose X-User-Role is present but empty."""
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def missing_role_headers(user_id: str = "registrar-1") -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def missing_identity_headers(role: str = "Registrar") -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


NO_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
