"""Authentication and role authorisation (PRD 2.1, first two bands of 2.11)."""

from flask import request

from errors import fail
from store import db

ROLES = (
    "DesignEngineer",
    "DesignReviewer",
    "ProductionPlanner",
    "BuildTechnician",
    "TestEngineer",
    "QualityCertifier",
    "ComplianceOfficer",
    "Distributor",
    "PlantAdmin",
)


def caller():
    """PRD 2.1 — both headers must be present and non-empty and X-User-Role must
    name one of the nine roles, or the request is rejected before any other
    processing occurs."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(*allowed):
    user_id, role = caller()
    if role not in allowed:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


def own_distributor_id(user_id, role, candidate):
    """For a Distributor caller X-User-ID is the id of the acting Distributor
    row; any attempt to reach another distributor's data, including supplying a
    foreign distributor_id in a creation payload, is ERR_NOT_OWNER."""
    if role != "Distributor":
        return
    if candidate is not None and candidate != user_id:
        fail("ERR_NOT_OWNER")


def resolve_distributor_row(user_id, role):
    if role != "Distributor":
        return None
    return db.distributors.get(user_id)
