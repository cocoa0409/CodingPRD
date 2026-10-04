"""PRD 2.1 authentication/authorization helpers."""
from flask import request

from errors import api_error

ROLES = (
    "PlatformAdmin",
    "ProgramManager",
    "RetailDesigner",
    "DealerRep",
    "PlantScheduler",
    "LogisticsCoordinator",
    "ClaimsAdjuster",
    "FieldServiceRep",
)


def get_body():
    """JSON request body as a dict; absent/malformed JSON yields {}."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def caller():
    """Stage 1: X-User-ID and X-User-Role must be present and the role known."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise api_error("ERR_UNAUTHENTICATED",
                        "missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_roles(*roles):
    """Stage 1 + the endpoint's role list (stage 2)."""
    uid, role = caller()
    if role not in roles:
        raise api_error("ERR_FORBIDDEN",
                        "role {} is not authorized for this operation".format(role))
    return uid, role
