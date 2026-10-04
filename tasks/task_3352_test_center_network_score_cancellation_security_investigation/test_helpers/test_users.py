"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (ProgramAdmin, Auditor, ScoreAnalyst) may use the shared
constants below. Entity-backed roles (CenterManager/Proctor -> Staff id,
Examinee -> Examinee id) MUST use the per-instance builders with the actual
entity id whenever the call is ownership- or identity-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import ADMIN_1_ID, ADMIN_2_ID, ANALYST_1_ID
from .types import UserRole

# Shared constants — safe for opaque roles and for calls that are not
# ownership-gated (e.g. 400/404 probes and RBAC denials).
TEST_USERS = {
    "program_admin_headers": build_user_headers(ADMIN_1_ID, UserRole.PROGRAM_ADMIN.value),
    "program_admin_2_headers": build_user_headers(ADMIN_2_ID, UserRole.PROGRAM_ADMIN.value),
    "auditor_headers": build_user_headers("auditor-1", UserRole.AUDITOR.value),
    "score_analyst_headers": build_user_headers(ANALYST_1_ID, UserRole.SCORE_ANALYST.value),
}


def make_program_admin_headers(user_id: str) -> dict:
    """ProgramAdmin is opaque: any operator id is accepted (PRD §2.1)."""
    return build_user_headers(user_id, UserRole.PROGRAM_ADMIN.value)


def make_auditor_headers(user_id: str) -> dict:
    """Auditor is opaque: any operator id is accepted (PRD §2.1)."""
    return build_user_headers(user_id, UserRole.AUDITOR.value)


def make_score_analyst_headers(user_id: str) -> dict:
    """ScoreAnalyst is opaque; the id is recorded as flagged_by_analyst_id (PRD §2.1)."""
    return build_user_headers(user_id, UserRole.SCORE_ANALYST.value)


def make_center_manager_headers(staff_id: str) -> dict:
    """CenterManager is entity-backed: pass the acting Staff row's id (PRD §2.1)."""
    return build_user_headers(staff_id, UserRole.CENTER_MANAGER.value)


def make_proctor_headers(staff_id: str) -> dict:
    """Proctor is entity-backed: pass the acting Staff row's id (PRD §2.1)."""
    return build_user_headers(staff_id, UserRole.PROCTOR.value)


def make_examinee_headers(examinee_id: str) -> dict:
    """Examinee is entity-backed: pass the acting Examinee row's id (PRD §2.1)."""
    return build_user_headers(examinee_id, UserRole.EXAMINEE.value)
