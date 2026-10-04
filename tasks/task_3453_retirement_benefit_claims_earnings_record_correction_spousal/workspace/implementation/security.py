"""Authentication, role authorization, and Claimant ownership (PRD §2.1,
§2.9 layers 1-3).

Every request carries X-User-ID and X-User-Role. The five recognized roles
are Claimant, Employer, ClaimsSpecialist, SeniorAdjudicator,
ProgramAdministrator. Only Claimant is entity-backed: its X-User-ID is the
Worker.id it acts as, and every resource it touches must trace back to that
worker id. All other roles carry opaque operator identifiers.
"""

from flask import request

from errors import (
    ApiError,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
)

ROLE_CLAIMANT = "Claimant"
ROLE_EMPLOYER = "Employer"
ROLE_CLAIMS_SPECIALIST = "ClaimsSpecialist"
ROLE_SENIOR_ADJUDICATOR = "SeniorAdjudicator"
ROLE_PROGRAM_ADMINISTRATOR = "ProgramAdministrator"

ROLES = {
    ROLE_CLAIMANT,
    ROLE_EMPLOYER,
    ROLE_CLAIMS_SPECIALIST,
    ROLE_SENIOR_ADJUDICATOR,
    ROLE_PROGRAM_ADMINISTRATOR,
}


def authenticate():
    """Layer 1: headers present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header.")
    if not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing, malformed, or unrecognized X-User-Role header.")
    return {"user_id": user_id, "role": role}


def require_role(ctx, allowed):
    """Layer 2: the recognized role is permitted on this endpoint."""
    if ctx["role"] not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            f"Role {ctx['role']} is not permitted on this endpoint.",
        )


def is_claimant(ctx):
    return ctx["role"] == ROLE_CLAIMANT


def claimant_owns(ctx, worker_id):
    """Layer 3: a Claimant's X-User-ID must equal the target's worker_id."""
    if is_claimant(ctx) and ctx["user_id"] != worker_id:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP,
            "Claimant may only access resources owned by their own worker record.",
        )


def claimant_involved(ctx, *worker_ids):
    """Layer 3 variant for relationship assertion: the Claimant must be one
    of the relationship's endpoints."""
    if is_claimant(ctx) and ctx["user_id"] not in worker_ids:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP,
            "Claimant may only assert relationships involving themself.",
        )
