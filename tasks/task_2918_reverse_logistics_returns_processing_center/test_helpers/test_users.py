"""Operator identities and their request headers (PRD §2.1).

Six of the seven roles carry an opaque identifier that the server never
resolves against a stored row, so those header dicts are module-level
constants. `ClientRep` is the one entity-backed role — its `X-User-ID` is the
`id` of the acting `Client` — so its headers must be built per client with
`client_rep_headers(client_id)`.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CENTER_ADMIN,
    ROLE_CLIENT_REP,
    ROLE_DISPOSITION_SUPERVISOR,
    ROLE_GRADING_INSPECTOR,
    ROLE_RECEIVING_CLERK,
    ROLE_REFUND_ANALYST,
    ROLE_REFURB_TECHNICIAN,
    USER_ADMIN,
    USER_ANALYST,
    USER_CLERK,
    USER_DUAL,
    USER_GRADER,
    USER_QA,
    USER_SUPERVISOR,
    USER_SUPERVISOR_2,
    USER_TECH,
)

# ─── Opaque-identity roles ──────────────────────────────────────────────

ADMIN = build_user_headers(USER_ADMIN, ROLE_CENTER_ADMIN)
CLERK = build_user_headers(USER_CLERK, ROLE_RECEIVING_CLERK)
GRADER = build_user_headers(USER_GRADER, ROLE_GRADING_INSPECTOR)
TECHNICIAN = build_user_headers(USER_TECH, ROLE_REFURB_TECHNICIAN)
SUPERVISOR = build_user_headers(USER_SUPERVISOR, ROLE_DISPOSITION_SUPERVISOR)
SUPERVISOR_2 = build_user_headers(USER_SUPERVISOR_2, ROLE_DISPOSITION_SUPERVISOR)
ANALYST = build_user_headers(USER_ANALYST, ROLE_REFUND_ANALYST)

# The QA signer is a distinct person from the assigned technician, and holds
# GradingInspector so it may record a refurbishment test result.
QA_INSPECTOR = build_user_headers(USER_QA, ROLE_GRADING_INSPECTOR)

# One human wearing two hats: grades a line as GradingInspector and later
# attempts the refund release as RefundAnalyst under the same X-User-ID.
DUAL_GRADER = build_user_headers(USER_DUAL, ROLE_GRADING_INSPECTOR)
DUAL_ANALYST = build_user_headers(USER_DUAL, ROLE_REFUND_ANALYST)

# A second technician identity, for opening a work order that someone else
# must then sign off.
TECHNICIAN_2 = build_user_headers(USER_QA, ROLE_REFURB_TECHNICIAN)


def client_rep_headers(client_id: str) -> Dict[str, str]:
    """Headers for a ClientRep acting on behalf of the client with this id."""
    return build_user_headers(client_id, ROLE_CLIENT_REP)


def headers_for(user_id: str, role: str) -> Dict[str, str]:
    """Arbitrary user/role pairing, for identity-separation probes."""
    return build_user_headers(user_id, role)


def headers_missing_user_id(role: str) -> Dict[str, str]:
    """Headers carrying a role but no X-User-ID at all."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> Dict[str, str]:
    """Headers carrying an operator id but no X-User-Role at all."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_blank_user_id(role: str) -> Dict[str, str]:
    """Headers whose X-User-ID is present but empty.

    The value is the empty string, never whitespace: a whitespace-only header
    value is rejected by the HTTP client before the request is ever sent.
    """
    return {"X-User-ID": "", "X-User-Role": role, "Content-Type": "application/json"}


def headers_blank_role(user_id: str) -> Dict[str, str]:
    """Headers whose X-User-Role is present but empty."""
    return {
        "X-User-ID": user_id,
        "X-User-Role": "",
        "Content-Type": "application/json",
    }
