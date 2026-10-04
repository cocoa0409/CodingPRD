"""Authentication (X-User-ID / X-User-Role), role authorization, segregation of duties."""
from flask import request

from errors import err

ROLES = {
    "FoundryManager",
    "MeltOperator",
    "QualityInspector",
    "SeasoningLead",
    "EnvironmentalOfficer",
    "RetailPlanner",
    "OutletManager",
}

ALL_ROLES = sorted(ROLES)


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing X-User-ID / X-User-Role or undeclared role")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED_ROLE", f"role {role} is not authorized for this endpoint")


def check_sod(uid, recorded_by):
    """Segregation of duties: caller must differ from the recorded provenance user."""
    if recorded_by is not None and uid == recorded_by:
        raise err(
            "ERR_SEGREGATION_OF_DUTIES",
            "caller X-User-ID matches the segregated provenance field",
        )
