"""Authentication / authorization rungs 1-6 of the PRD 2.8 rejection ladder.

PRD 2.1: "Every request to the API must carry two headers. X-User-ID identifies
the acting user and X-User-Role declares the capacity in which they are acting."
"""
from flask import request

from errors import ApiError

ROLES = ["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant", "ClientContact"]


def authenticate(allowed_roles):
    """Rung 1 (ERR_UNAUTHENTICATED) and rung 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not perform this operation." % role)
    return user_id, role


def check_project_manager(role, user_id, project):
    """Rung 3 -- PRD 2.1: "When X-User-Role is ProjectManager and the operation
    mutates a project's own records, the acting X-User-ID must equal that
    project's project_manager_user_id." When the project cannot be resolved the
    check is skipped so the later existence/reference rungs can report."""
    if role != "ProjectManager" or project is None:
        return
    if user_id != project.get("project_manager_user_id"):
        raise ApiError("ERR_NOT_PROJECT_MANAGER",
                       "This project is managed by a different user.")


def check_client_contact(role, user_id, project):
    """Rung 4 -- PRD 2.1: for any invoice a client contact reaches, the owning
    project's client_id must equal the acting X-User-ID."""
    if role != "ClientContact" or project is None:
        return
    if user_id != project.get("client_id"):
        raise ApiError("ERR_NOT_PROJECT_CLIENT",
                       "This invoice belongs to a different client.")


def check_segregation(user_id, creator_user_id):
    """Rung 5 -- PRD 2.1: the acting X-User-ID must differ from the X-User-ID of
    the user who created the record now under approval."""
    if creator_user_id is None:
        return
    if user_id == creator_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The approver may not be the preparer of the same record.")


def check_write_off_approval_level(role, write_off):
    """Rung 6 -- PRD 2.1: a write-off sitting in PENDING_CONTROLLER_APPROVAL may
    only be approved by an acting Controller."""
    if write_off is None:
        return
    if write_off["status"] == "PENDING_CONTROLLER_APPROVAL" and role != "Controller":
        raise ApiError("ERR_APPROVAL_LEVEL_INSUFFICIENT",
                       "This write-off requires Controller approval.")
