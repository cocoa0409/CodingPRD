"""Header builders for the eight roles declared in PRD 2.1.

PRD 2.1 requires ``X-User-ID`` and ``X-User-Role`` on every request. The role
values are opaque strings, so a role's identity comes from the header alone; the
user identifier is what distinguishes operators, which matters for the
underwriter binding and for the segregation-of-duties rule.

Distinct operators therefore get distinct ``X-User-ID`` values here: an
exception requester, its first signer and its second signer are three different
identifiers, never one shared constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_APPRAISAL_REVIEWER,
    ROLE_CHIEF_CREDIT_OFFICER,
    ROLE_CREDIT_COMMITTEE,
    ROLE_LOAN_OFFICER,
    ROLE_POST_CLOSE_AUDITOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SECURITIZATION_ANALYST,
    ROLE_UNDERWRITER,
)

# --- Canonical per-role operators -----------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_ADMIN: build_user_headers("admin-1", ROLE_PROGRAM_ADMIN),
    ROLE_LOAN_OFFICER: build_user_headers("lo-1", ROLE_LOAN_OFFICER),
    ROLE_UNDERWRITER: build_user_headers("uw-1", ROLE_UNDERWRITER),
    ROLE_CREDIT_COMMITTEE: build_user_headers("cc-1", ROLE_CREDIT_COMMITTEE),
    ROLE_CHIEF_CREDIT_OFFICER: build_user_headers("cco-1", ROLE_CHIEF_CREDIT_OFFICER),
    ROLE_APPRAISAL_REVIEWER: build_user_headers("ar-1", ROLE_APPRAISAL_REVIEWER),
    ROLE_POST_CLOSE_AUDITOR: build_user_headers("pca-1", ROLE_POST_CLOSE_AUDITOR),
    ROLE_SECURITIZATION_ANALYST: build_user_headers("sa-1", ROLE_SECURITIZATION_ANALYST),
}

ADMIN = TEST_USERS[ROLE_PROGRAM_ADMIN]
LOAN_OFFICER = TEST_USERS[ROLE_LOAN_OFFICER]
UNDERWRITER = TEST_USERS[ROLE_UNDERWRITER]
CREDIT_COMMITTEE = TEST_USERS[ROLE_CREDIT_COMMITTEE]
CHIEF_CREDIT_OFFICER = TEST_USERS[ROLE_CHIEF_CREDIT_OFFICER]
APPRAISAL_REVIEWER = TEST_USERS[ROLE_APPRAISAL_REVIEWER]
POST_CLOSE_AUDITOR = TEST_USERS[ROLE_POST_CLOSE_AUDITOR]
SECURITIZATION_ANALYST = TEST_USERS[ROLE_SECURITIZATION_ANALYST]


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Headers for an explicit operator identifier acting in ``role``."""
    return build_user_headers(user_id, role)


def underwriter(user_id: str) -> Dict[str, str]:
    """An `Underwriter` acting under a specific ``X-User-ID``."""
    return build_user_headers(user_id, ROLE_UNDERWRITER)


def loan_officer(user_id: str = "lo-1") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_LOAN_OFFICER)


def credit_committee(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CREDIT_COMMITTEE)


def chief_credit_officer(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_CHIEF_CREDIT_OFFICER)


def appraisal_reviewer(user_id: str = "ar-1") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_APPRAISAL_REVIEWER)


def post_close_auditor(user_id: str = "pca-1") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_POST_CLOSE_AUDITOR)


def securitization_analyst(user_id: str = "sa-1") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_SECURITIZATION_ANALYST)


def program_admin(user_id: str = "admin-1") -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


# --- Malformed authentication headers (PRD 2.1) ---------------------------
# A "blank" header must carry the empty string: a whitespace-only value is
# rejected by the HTTP client itself and would never reach the server.
def headers_without_role(user_id: str = "lo-1") -> Dict[str, str]:
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_with_blank_role(user_id: str = "lo-1") -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": "", "Content-Type": "application/json"}


def headers_with_unknown_role(user_id: str = "lo-1",
                              role: str = "NotARole") -> Dict[str, str]:
    return {"X-User-ID": user_id, "X-User-Role": role,
            "Content-Type": "application/json"}


def headers_without_user(role: str = ROLE_LOAN_OFFICER) -> Dict[str, str]:
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_with_blank_user(role: str = ROLE_LOAN_OFFICER) -> Dict[str, str]:
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}
