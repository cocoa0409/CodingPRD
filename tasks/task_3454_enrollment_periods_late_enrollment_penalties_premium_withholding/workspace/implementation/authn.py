"""Authentication, role authorization, and resource-ownership checks.

Headers: X-User-Role and X-User-ID. Five declared roles. When the role is
Beneficiary, X-User-ID is the acting Beneficiary's id and every touched
resource's beneficiary_id must equal it.
"""
from __future__ import annotations

from flask import request

from errors import fail

ROLE_BENEFICIARY = "Beneficiary"
ROLE_FIELD_OFFICER = "FieldOfficer"
ROLE_APPEALS_OFFICER = "AppealsOfficer"
ROLE_IRS_DATA_AGENT = "IrsDataAgent"
ROLE_BENEFIT_ADMINISTRATOR = "BenefitAdministrator"

DECLARED_ROLES = (
    ROLE_BENEFICIARY,
    ROLE_FIELD_OFFICER,
    ROLE_APPEALS_OFFICER,
    ROLE_IRS_DATA_AGENT,
    ROLE_BENEFIT_ADMINISTRATOR,
)


def authenticate():
    """Priority 1: headers present and role declared."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in DECLARED_ROLES:
        fail("ERR_UNAUTHENTICATED",
             "Missing or invalid X-User-Role / X-User-ID headers")
    return role, uid


def authorize(role: str, allowed):
    """Priority 2: role permitted on this endpoint."""
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE",
             f"Role {role} is not permitted on this endpoint")


def check_ownership(role: str, uid: str, beneficiary_id) -> None:
    """Priority 3: a Beneficiary may only touch their own resources."""
    if role == ROLE_BENEFICIARY and beneficiary_id != uid:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Beneficiary may only act on resources they own")


def body_beneficiary_ownership(role: str, uid: str, body: dict) -> None:
    """Priority-3 ownership on a body-supplied beneficiary_id.

    Runs before full body validation: when the field is present and a
    string, a mismatch is ERR_NOT_RESOURCE_OWNER; when absent or mistyped,
    ownership is deferred to the well-formedness check (priority 4).
    """
    if role != ROLE_BENEFICIARY:
        return
    bid = body.get("beneficiary_id")
    if isinstance(bid, str) and bid != uid:
        fail("ERR_NOT_RESOURCE_OWNER",
             "Beneficiary may only act on resources they own")
