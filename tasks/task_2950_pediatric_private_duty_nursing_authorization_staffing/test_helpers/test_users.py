"""Pre-built auth headers for every role in PRD section 2.1.

Four of the six roles are *opaque*: the platform never resolves `X-User-ID`
to a row, so a stable operator identifier is enough. Two roles are
*entity-backed* and their identity must be threaded from a created row:

- `PayerReviewer`: `X-User-ID` is the `id` of the acting `Payer`.
- `Nurse`: `X-User-ID` is the `id` of the acting `Nurse` row.

For those two, use `make_payer_reviewer_headers(payer_id)` and
`make_nurse_headers(nurse_id)`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# --- Opaque operator identifiers -----------------------------------------
AGENCY_ADMIN_USER_ID = "admin-001"
CASE_MANAGER_USER_ID = "cm-001"
SCHEDULER_USER_ID = "sch-001"
SUPERVISOR_USER_ID = "sup-001"
SUPERVISOR_2_USER_ID = "sup-002"
SUPERVISOR_3_USER_ID = "sup-003"

CASE_MANAGER_2_USER_ID = "cm-002"
SCHEDULER_2_USER_ID = "sch-002"

# --- Ready-made header dicts for the opaque roles ------------------------
AGENCY_ADMIN = build_user_headers(AGENCY_ADMIN_USER_ID, UserRole.AGENCY_ADMIN.value)
CASE_MANAGER = build_user_headers(CASE_MANAGER_USER_ID, UserRole.CASE_MANAGER.value)
CASE_MANAGER_2 = build_user_headers(CASE_MANAGER_2_USER_ID, UserRole.CASE_MANAGER.value)
SCHEDULER = build_user_headers(SCHEDULER_USER_ID, UserRole.SCHEDULER.value)
SCHEDULER_2 = build_user_headers(SCHEDULER_2_USER_ID, UserRole.SCHEDULER.value)
CLINICAL_SUPERVISOR = build_user_headers(
    SUPERVISOR_USER_ID, UserRole.CLINICAL_SUPERVISOR.value
)
CLINICAL_SUPERVISOR_2 = build_user_headers(
    SUPERVISOR_2_USER_ID, UserRole.CLINICAL_SUPERVISOR.value
)
CLINICAL_SUPERVISOR_3 = build_user_headers(
    SUPERVISOR_3_USER_ID, UserRole.CLINICAL_SUPERVISOR.value
)


def make_agency_admin_headers(user_id: str = AGENCY_ADMIN_USER_ID) -> Dict[str, str]:
    """Headers for an `AgencyAdmin`; the identifier is opaque to the platform."""
    return build_user_headers(user_id, UserRole.AGENCY_ADMIN.value)


def make_case_manager_headers(user_id: str = CASE_MANAGER_USER_ID) -> Dict[str, str]:
    """Headers for a `CaseManager`; the identifier is opaque to the platform."""
    return build_user_headers(user_id, UserRole.CASE_MANAGER.value)


def make_scheduler_headers(user_id: str = SCHEDULER_USER_ID) -> Dict[str, str]:
    """Headers for a `Scheduler`; the identifier is opaque to the platform."""
    return build_user_headers(user_id, UserRole.SCHEDULER.value)


def make_clinical_supervisor_headers(
    user_id: str = SUPERVISOR_USER_ID,
) -> Dict[str, str]:
    """Headers for a `ClinicalSupervisor`; the identifier is opaque, but it is
    compared against an incident report's `reported_by_user_id` for the
    segregation-of-duties rule, so callers vary it deliberately."""
    return build_user_headers(user_id, UserRole.CLINICAL_SUPERVISOR.value)


def make_payer_reviewer_headers(payer_id: str) -> Dict[str, str]:
    """Headers for a `PayerReviewer` acting as the payer identified by `payer_id`."""
    return build_user_headers(payer_id, UserRole.PAYER_REVIEWER.value)


def make_nurse_headers(nurse_id: str) -> Dict[str, str]:
    """Headers for a `Nurse` acting as the nurse row identified by `nurse_id`."""
    return build_user_headers(nurse_id, UserRole.NURSE.value)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for negative tests that need an arbitrary id/role pair."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers whose `X-User-ID` is present but empty (never whitespace)."""
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """Headers whose `X-User-Role` is present but empty (never whitespace)."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }


def headers_without_user_id(role: str) -> Dict[str, str]:
    """Headers that omit `X-User-ID` entirely."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_without_role(user_id: str) -> Dict[str, str]:
    """Headers that omit `X-User-Role` entirely."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}
