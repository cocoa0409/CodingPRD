"""Pre-built role headers for every role in the PRD (§2.1).

Two of the six roles are person-backed: when X-User-Role is Instructor or
Student, X-User-ID is the id of the acting Person and ownership is enforced on
it. The other four are opaque operator identifiers not tied to any persisted
entity, so a shared constant is the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Safe for the four opaque roles, and for Instructor/Student
# tests that do not exercise ownership (a 401/403/404 probe, for instance).
TEST_USERS = {
    "registrar_headers": build_user_headers("op-registrar-1", "Registrar"),
    "registrar_alt_headers": build_user_headers("op-registrar-2", "Registrar"),
    "lms_admin_headers": build_user_headers("op-lmsadmin-1", "LmsAdmin"),
    "lms_admin_alt_headers": build_user_headers("op-lmsadmin-2", "LmsAdmin"),
    "privacy_reviewer_headers": build_user_headers("priv-rev-1", "PrivacyReviewer"),
    "privacy_reviewer_alt_headers": build_user_headers("priv-rev-2", "PrivacyReviewer"),
    "accessibility_reviewer_headers": build_user_headers("acc-rev-1", "AccessibilityReviewer"),
    "accessibility_reviewer_alt_headers": build_user_headers("acc-rev-2", "AccessibilityReviewer"),
    # Person-backed roles: fallback only, never for ownership-gated calls.
    "instructor_headers": build_user_headers("unbound-instructor", "Instructor"),
    "student_headers": build_user_headers("unbound-student", "Student"),
}

# Stable operator identifiers, exposed so segregation-of-duties tests can name
# the exact X-User-ID they expect the server to have recorded.
REGISTRAR_USER_ID = "op-registrar-1"
REGISTRAR_ALT_USER_ID = "op-registrar-2"
LMS_ADMIN_USER_ID = "op-lmsadmin-1"
LMS_ADMIN_ALT_USER_ID = "op-lmsadmin-2"
PRIVACY_REVIEWER_USER_ID = "priv-rev-1"
PRIVACY_REVIEWER_ALT_USER_ID = "priv-rev-2"
ACCESSIBILITY_REVIEWER_USER_ID = "acc-rev-1"
ACCESSIBILITY_REVIEWER_ALT_USER_ID = "acc-rev-2"


# ─── Per-instance builders ────────────────────────────────────────────────

def make_instructor_headers(person_id: str) -> dict:
    """Instructor headers bound to a real Person.id.

    Ownership checks compare the shell's owner_person_id to X-User-ID, so every
    ownership-gated instructor call must pass the owning Person's id here.
    """
    return build_user_headers(person_id, "Instructor")


def make_student_headers(person_id: str) -> dict:
    """Student headers bound to a real Person.id.

    Ownership checks compare the relevant Enrollment's person_id to X-User-ID.
    """
    return build_user_headers(person_id, "Student")


def make_registrar_headers(user_id: str) -> dict:
    """Registrar headers with a caller-chosen opaque operator id."""
    return build_user_headers(user_id, "Registrar")


def make_lms_admin_headers(user_id: str) -> dict:
    """LmsAdmin headers with a caller-chosen opaque operator id."""
    return build_user_headers(user_id, "LmsAdmin")


def make_privacy_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrivacyReviewer")


def make_accessibility_reviewer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AccessibilityReviewer")
