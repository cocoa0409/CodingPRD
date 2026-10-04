"""Auth middleware — PRD §2.1 / SCAFFOLD §1.4 priorities 1-3.

Headers: X-User-Role, X-User-ID. Seven roles. Entity-backed roles
(RegistrarSubmitter/RegistrarCertifier -> InstitutionUser, Requester ->
Requester, Learner -> StudentRecord) must resolve to an existing entity;
ClearinghouseOps, Servicer, ResearchAnalyst carry opaque identifiers.
"""
from flask import request

import db
from core import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLE_CLEARINGHOUSE_OPS = "ClearinghouseOps"
ROLE_SUBMITTER = "RegistrarSubmitter"
ROLE_CERTIFIER = "RegistrarCertifier"
ROLE_REQUESTER = "Requester"
ROLE_LEARNER = "Learner"
ROLE_SERVICER = "Servicer"
ROLE_ANALYST = "ResearchAnalyst"

ALL_ROLES = (
    ROLE_CLEARINGHOUSE_OPS,
    ROLE_SUBMITTER,
    ROLE_CERTIFIER,
    ROLE_REQUESTER,
    ROLE_LEARNER,
    ROLE_SERVICER,
    ROLE_ANALYST,
)

REGISTRAR_ROLES = (ROLE_SUBMITTER, ROLE_CERTIFIER)


class Caller:
    def __init__(self, role, user_id, entity=None):
        self.role = role
        self.user_id = user_id
        self.entity = entity
        # Registrar tenancy anchor (InstitutionUser.institution_id)
        self.institution_id = entity["institution_id"] if entity and "institution_id" in entity else None


def authenticate():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid:
        raise ApiError(ERR_UNAUTHENTICATED, "X-User-Role and X-User-ID headers are required")

    if role == ROLE_SUBMITTER:
        user = db.store.users.get(uid)
        if user is None or user["role"] != "SUBMITTER" or user["status"] != "ACTIVE":
            raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID does not resolve to an active SUBMITTER user")
        return Caller(role, uid, user)
    if role == ROLE_CERTIFIER:
        user = db.store.users.get(uid)
        if user is None or user["role"] != "CERTIFIER" or user["status"] != "ACTIVE":
            raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID does not resolve to an active CERTIFIER user")
        return Caller(role, uid, user)
    if role == ROLE_REQUESTER:
        requester = db.store.requesters.get(uid)
        if requester is None:
            raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID does not resolve to a Requester")
        return Caller(role, uid, requester)
    if role == ROLE_LEARNER:
        student = db.store.students.get(uid)
        if student is None:
            raise ApiError(ERR_UNAUTHENTICATED, "X-User-ID does not resolve to a StudentRecord")
        return Caller(role, uid, student)
    # Opaque identities: ClearinghouseOps, Servicer, ResearchAnalyst, and
    # unrecognized role strings (the latter fail the role check with 403).
    return Caller(role, uid, None)


def require_role(caller, *roles):
    if caller.role not in roles:
        raise ApiError(ERR_UNAUTHORIZED, "role '%s' is not authorized for this endpoint" % caller.role)


def require_registrar_tenancy(caller, institution_id):
    """Registrar reads/writes are scoped to the acting user's institution."""
    if caller.role in REGISTRAR_ROLES and caller.institution_id != institution_id:
        raise ApiError(ERR_UNAUTHORIZED, "registrar user may only access own institution's resources")
