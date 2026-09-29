"""Caller identity and RBAC (PRD 2.1, precedence steps 1 and 2 of PRD 2.9)."""

import functools

from flask import request

import errors
from errors import fail

# PRD 2.1: "The eight roles are ..."
ROLE_DIRECTOR = "OfficiatingDirector"
ROLE_SCHEDULER = "CrewScheduler"
ROLE_GRADING_SUPERVISOR = "GradingSupervisor"
ROLE_OFFICIAL = "Official"
ROLE_FIELD_EVALUATOR = "FieldEvaluator"
ROLE_REPLAY_OFFICIAL = "ReplayOfficial"
ROLE_TRAINING_COORDINATOR = "TrainingCoordinator"
ROLE_COMMUNICATIONS = "CommunicationsOfficer"

ALL_ROLES = [
    ROLE_DIRECTOR,
    ROLE_SCHEDULER,
    ROLE_GRADING_SUPERVISOR,
    ROLE_OFFICIAL,
    ROLE_FIELD_EVALUATOR,
    ROLE_REPLAY_OFFICIAL,
    ROLE_TRAINING_COORDINATOR,
    ROLE_COMMUNICATIONS,
]


def caller_id():
    return request.headers.get("X-User-ID")


def caller_role():
    return request.headers.get("X-User-Role")


def authorize(allowed_roles):
    """Steps 1-2 of the rejection precedence in PRD 2.9.

    1. Both X-User-ID and X-User-Role are present and non-empty, else
       ERR_UNAUTHENTICATED (401).
    2. X-User-Role names one of the eight declared roles and that role is
       authorized for the target endpoint, else ERR_UNAUTHORIZED (403).
    """
    user_id = caller_id()
    role = caller_role()
    if user_id is None or user_id == "" or role is None or role == "":
        fail(errors.ERR_UNAUTHENTICATED)
    if role not in ALL_ROLES:
        fail(errors.ERR_UNAUTHORIZED, "Unknown role '%s'." % role)
    if role not in allowed_roles:
        fail(errors.ERR_UNAUTHORIZED,
             "Role '%s' is not authorized for this endpoint." % role)
    return user_id, role


def endpoint(roles):
    """Decorator running authentication and authorization before anything else."""
    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authorize(roles)
            return view(*args, **kwargs)
        return wrapper
    return decorator


ANY_ROLE = list(ALL_ROLES)
