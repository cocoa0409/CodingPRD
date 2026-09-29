"""Admission ladder rungs 1-4: authentication, authorization, path existence,
resource ownership  (PRD s2.1 + s2.5)."""

from flask import request

from errors import ApiError
from store import ROLES, db


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


# --- rung 1 ----------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID", None)
    role = request.headers.get("X-User-Role", None)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not user_id.strip() or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(user_id, role)


# --- rung 2 ----------------------------------------------------------------
def authorize(actor, allowed_roles):
    if actor.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return actor


def admit(allowed_roles):
    """Run rungs 1 and 2 and return the acting principal."""
    actor = authenticate()
    authorize(actor, allowed_roles)
    return actor


# --- rung 3 ----------------------------------------------------------------
def get_property(property_id):
    row = db.properties.get(property_id)
    if row is None:
        raise ApiError("ERR_PROPERTY_NOT_FOUND")
    return row


def get_contract(contract_id):
    row = db.contracts.get(contract_id)
    if row is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    return row


def get_resident(resident_id, error_id="ERR_RESIDENT_NOT_FOUND"):
    row = db.residents.get(resident_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_contractor(contractor_id, error_id="ERR_CONTRACTOR_NOT_FOUND"):
    row = db.contractors.get(contractor_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_night(night_id):
    row = db.nights.get(night_id)
    if row is None:
        raise ApiError("ERR_SERVICE_NIGHT_NOT_FOUND")
    return row


def get_route(route_id):
    row = db.routes.get(route_id)
    if row is None:
        raise ApiError("ERR_ROUTE_NOT_FOUND")
    return row


def get_scan(scan_id):
    row = db.scans.get(scan_id)
    if row is None:
        raise ApiError("ERR_SCAN_NOT_FOUND")
    return row


def get_fine(fine_id):
    row = db.fines.get(fine_id)
    if row is None:
        raise ApiError("ERR_FINE_NOT_FOUND")
    return row


def get_incident(incident_id):
    row = db.incidents.get(incident_id)
    if row is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND")
    return row


def get_statement(statement_id):
    row = db.statements.get(statement_id)
    if row is None:
        raise ApiError("ERR_STATEMENT_NOT_FOUND")
    return row


# --- rung 4 ----------------------------------------------------------------
def own(condition):
    if not condition:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_property_owner(actor, property_id):
    """PropertyManager acts as the Property whose id is X-User-ID."""
    if actor.role == "PropertyManager":
        own(actor.user_id == property_id)


def require_valet_owner(actor, contractor_id):
    if actor.role == "Valet":
        own(actor.user_id == contractor_id)


def require_resident_owner(actor, resident_id):
    if actor.role == "Resident":
        own(actor.user_id == resident_id)


# --- structural navigation helpers -----------------------------------------
def property_of_contract(contract):
    return db.properties.get(contract["property_id"])


def contract_of_night(night):
    return db.contracts.get(night["contract_id"])


def property_of_night(night):
    contract = contract_of_night(night)
    if contract is None:
        return None
    return db.properties.get(contract["property_id"])


def night_of_route(route):
    return db.nights.get(route["service_night_id"])


def property_of_route(route):
    night = night_of_route(route)
    if night is None:
        return None
    return property_of_night(night)


def property_of_resident(resident):
    return db.properties.get(resident["property_id"])


def property_id_of_scan(scan):
    resident = db.residents.get(scan["resident_id"])
    if resident is None:
        return None
    return resident["property_id"]


def property_id_of_fine(fine):
    resident = db.residents.get(fine["resident_id"])
    if resident is None:
        return None
    return resident["property_id"]
