"""Pre-built acting-identity headers for the six roles of PRD §2.1.

Three roles are entity-backed (`FacultyReporter`, `PanelChair`, `Student`): for
those, `X-User-ID` must be the id of a real stored row, so the per-instance
builders below are mandatory whenever the call is ownership-gated.  The other
three roles (`IntegrityOfficer`, `AppealsDean`, `RegistrarOfficer`) are opaque
and their shared constants are the canonical form.
"""
from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Shared constants.
#
# Safe for the three opaque roles.  For the three entity-backed roles these are
# only usable in tests that never reach an ownership check (an unknown-role
# probe, a 401/403 probe, or a 404-on-missing-parent probe) — an ownership-gated
# call MUST use the matching make_*_headers(<real row id>) builder instead.
# ---------------------------------------------------------------------------

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is the canonical form.
    "officer_headers": build_user_headers("officer-001", "IntegrityOfficer"),
    "dean_headers": build_user_headers("dean-001", "AppealsDean"),
    "registrar_headers": build_user_headers("registrar-001", "RegistrarOfficer"),
    # Entity-backed roles — fallbacks for non-ownership tests only.
    "reporter_headers": build_user_headers("unbacked-reporter-001", "FacultyReporter"),
    "chair_headers": build_user_headers("unbacked-chair-001", "PanelChair"),
    "student_headers": build_user_headers("unbacked-student-001", "Student"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — required for every entity-backed role.
# ---------------------------------------------------------------------------


def make_officer_headers(user_id: str = "officer-001") -> Dict[str, str]:
    """IntegrityOfficer is opaque: any office-staff identifier is acceptable."""
    return build_user_headers(user_id, "IntegrityOfficer")


def make_dean_headers(user_id: str = "dean-001") -> Dict[str, str]:
    """AppealsDean is opaque: any dean identifier is acceptable."""
    return build_user_headers(user_id, "AppealsDean")


def make_registrar_headers(user_id: str = "registrar-001") -> Dict[str, str]:
    """RegistrarOfficer is opaque: any registrar identifier is acceptable."""
    return build_user_headers(user_id, "RegistrarOfficer")


def make_reporter_headers(faculty_member_id: str) -> Dict[str, str]:
    """FacultyReporter is entity-backed: pass the acting FacultyMember's id."""
    return build_user_headers(faculty_member_id, "FacultyReporter")


def make_chair_headers(faculty_member_id: str) -> Dict[str, str]:
    """PanelChair is entity-backed: pass the acting FacultyMember's id."""
    return build_user_headers(faculty_member_id, "PanelChair")


def make_student_headers(student_id: str) -> Dict[str, str]:
    """Student is entity-backed: pass the acting Student row's id."""
    return build_user_headers(student_id, "Student")


ROLE_HEADER_BUILDERS = {
    "IntegrityOfficer": make_officer_headers,
    "AppealsDean": make_dean_headers,
    "RegistrarOfficer": make_registrar_headers,
    "FacultyReporter": make_reporter_headers,
    "PanelChair": make_chair_headers,
    "Student": make_student_headers,
}


def headers_for(role: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Build headers for `role`, using `user_id` when the role is entity-backed."""
    if role in ("IntegrityOfficer", "AppealsDean", "RegistrarOfficer"):
        builder = ROLE_HEADER_BUILDERS[role]
        return builder(user_id) if user_id else builder()
    if user_id is None:
        raise ValueError(f"role {role} is entity-backed and requires a user_id")
    return ROLE_HEADER_BUILDERS[role](user_id)


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers carrying `X-User-Role` but no `X-User-ID` at all."""
    h = build_user_headers("placeholder", role)
    h.pop("X-User-ID", None)
    return h


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers carrying `X-User-ID` but no `X-User-Role` at all."""
    h = build_user_headers(user_id, "placeholder")
    h.pop("X-User-Role", None)
    return h


def headers_with_empty_role(user_id: str) -> Dict[str, str]:
    """`X-User-Role` present but carrying the empty string."""
    return build_user_headers(user_id, "")


def headers_with_whitespace_role(user_id: str) -> Dict[str, str]:
    """`X-User-Role` present but consisting only of spaces."""
    return build_user_headers(user_id, "   ")


def headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """`X-User-ID` present but carrying the empty string."""
    return build_user_headers("", role)


def headers_with_whitespace_user_id(role: str) -> Dict[str, str]:
    """`X-User-ID` present but consisting only of spaces."""
    return build_user_headers("   ", role)
