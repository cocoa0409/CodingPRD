"""Acting users and their request headers.

Staff identifiers are opaque operator strings that resolve to no persisted row.
The patient role is different: its ``X-User-ID`` *is* the identifier of the
acting patient, so its headers can only be built once that patient exists.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_INTERPRETING_PHYSICIAN,
    ROLE_PATIENT_PORTAL_USER,
    ROLE_PROGRAM_ADMIN,
    ROLE_QUALITY_REVIEWER,
    ROLE_SCHEDULER,
    ROLE_TECHNOLOGIST,
)

# ── Opaque staff operator identifiers ───────────────────────────────────────
ADMIN_USER_ID = "admin-001"
SCHEDULER_USER_ID = "sched-001"
SCHEDULER_ALT_USER_ID = "sched-002"
TECHNOLOGIST_USER_ID = "tech-001"
TECHNOLOGIST_ALT_USER_ID = "tech-002"
REVIEWER_USER_ID = "qa-001"
REVIEWER_ALT_USER_ID = "qa-002"
PHYSICIAN_USER_ID = "phys-001"
PHYSICIAN_ALT_USER_ID = "phys-002"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"user_id": ADMIN_USER_ID, "role": ROLE_PROGRAM_ADMIN},
    "scheduler": {"user_id": SCHEDULER_USER_ID, "role": ROLE_SCHEDULER},
    "scheduler_alt": {"user_id": SCHEDULER_ALT_USER_ID, "role": ROLE_SCHEDULER},
    "technologist": {"user_id": TECHNOLOGIST_USER_ID, "role": ROLE_TECHNOLOGIST},
    "technologist_alt": {
        "user_id": TECHNOLOGIST_ALT_USER_ID,
        "role": ROLE_TECHNOLOGIST,
    },
    "reviewer": {"user_id": REVIEWER_USER_ID, "role": ROLE_QUALITY_REVIEWER},
    "reviewer_alt": {"user_id": REVIEWER_ALT_USER_ID, "role": ROLE_QUALITY_REVIEWER},
    "physician": {"user_id": PHYSICIAN_USER_ID, "role": ROLE_INTERPRETING_PHYSICIAN},
    "physician_alt": {
        "user_id": PHYSICIAN_ALT_USER_ID,
        "role": ROLE_INTERPRETING_PHYSICIAN,
    },
}

ADMIN_HEADERS = build_user_headers(ADMIN_USER_ID, ROLE_PROGRAM_ADMIN)
SCHEDULER_HEADERS = build_user_headers(SCHEDULER_USER_ID, ROLE_SCHEDULER)
SCHEDULER_ALT_HEADERS = build_user_headers(SCHEDULER_ALT_USER_ID, ROLE_SCHEDULER)
TECHNOLOGIST_HEADERS = build_user_headers(TECHNOLOGIST_USER_ID, ROLE_TECHNOLOGIST)
TECHNOLOGIST_ALT_HEADERS = build_user_headers(
    TECHNOLOGIST_ALT_USER_ID, ROLE_TECHNOLOGIST
)
REVIEWER_HEADERS = build_user_headers(REVIEWER_USER_ID, ROLE_QUALITY_REVIEWER)
REVIEWER_ALT_HEADERS = build_user_headers(REVIEWER_ALT_USER_ID, ROLE_QUALITY_REVIEWER)
PHYSICIAN_HEADERS = build_user_headers(PHYSICIAN_USER_ID, ROLE_INTERPRETING_PHYSICIAN)
PHYSICIAN_ALT_HEADERS = build_user_headers(
    PHYSICIAN_ALT_USER_ID, ROLE_INTERPRETING_PHYSICIAN
)

HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_ADMIN: ADMIN_HEADERS,
    ROLE_SCHEDULER: SCHEDULER_HEADERS,
    ROLE_TECHNOLOGIST: TECHNOLOGIST_HEADERS,
    ROLE_QUALITY_REVIEWER: REVIEWER_HEADERS,
    ROLE_INTERPRETING_PHYSICIAN: PHYSICIAN_HEADERS,
}


def make_patient_headers(patient_id: str) -> Dict[str, str]:
    """Headers for the patient role, whose user identifier is the patient row."""
    return build_user_headers(patient_id, ROLE_PATIENT_PORTAL_USER)


def make_admin_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_scheduler_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SCHEDULER)


def make_technologist_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_TECHNOLOGIST)


def make_reviewer_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_QUALITY_REVIEWER)


def make_physician_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INTERPRETING_PHYSICIAN)


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an arbitrary role/user pairing."""
    return build_user_headers(user_id, role)


def headers_without(header_name: str, role: str = ROLE_PROGRAM_ADMIN) -> Dict[str, str]:
    """A header set with one authentication header removed entirely."""
    headers = dict(build_user_headers(ADMIN_USER_ID, role))
    headers.pop(header_name, None)
    return headers


def headers_with_empty(header_name: str, role: str = ROLE_PROGRAM_ADMIN) -> Dict[str, str]:
    """A header set with one authentication header present but empty."""
    headers = dict(build_user_headers(ADMIN_USER_ID, role))
    headers[header_name] = ""
    return headers
