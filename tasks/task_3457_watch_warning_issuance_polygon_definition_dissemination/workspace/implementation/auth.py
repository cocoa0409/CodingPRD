"""Validation-pipeline tiers 1-3: authentication, role authorization,
privilege (MIC override) and office scope (PRD §2.1, §2.8)."""
from flask import request

from constants import ENTITY_BACKED_ROLES, ROLES
from db import STORE
from errors import api_error


def authenticate():
    """Tier 1: headers present, role declared, entity-backed id resolves."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise api_error(
            "ERR_UNAUTHENTICATED",
            "Missing X-User-ID, missing/unknown X-User-Role, or unresolvable identity.",
        )
    forecaster = None
    if role in ENTITY_BACKED_ROLES:
        forecaster = STORE["forecasters"].get(uid)
        if forecaster is None:
            raise api_error(
                "ERR_UNAUTHENTICATED",
                "X-User-ID does not resolve to an existing Forecaster row.",
            )
    return role, uid, forecaster


def require_role(role, allowed):
    """Tier 2: role must be listed for the endpoint."""
    if role not in allowed:
        raise api_error("ERR_FORBIDDEN_ROLE", "Role %s is not authorized for this endpoint." % role)


def require_mic_for_override(role, forecaster, coordination_override):
    """Tier 3: coordination_override=true is MIC-only (MeteorologistInCharge
    role whose Forecaster row carries level == MIC)."""
    if not coordination_override:
        return
    if role != "MeteorologistInCharge" or forecaster is None or forecaster["level"] != "MIC":
        raise api_error(
            "ERR_MIC_REQUIRED",
            "coordination_override=true requires a MeteorologistInCharge whose level is MIC.",
        )


def check_office_scope(forecaster, owning_office_id):
    """Tier 3: forecaster-scoped callers act only within their own office."""
    if forecaster is not None and forecaster["office_id"] != owning_office_id:
        raise api_error(
            "ERR_OFFICE_SCOPE_VIOLATION",
            "Forecaster may only act on resources belonging to their own office.",
        )
