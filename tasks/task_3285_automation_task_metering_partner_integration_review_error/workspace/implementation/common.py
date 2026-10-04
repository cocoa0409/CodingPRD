"""Shared lookups and reachability checks."""
from db import db
from errors import ApiError
from middleware import acting_id, acting_role


def account_or_404(account_id):
    rec = db.accounts.get(account_id)
    if rec is None:
        raise ApiError("ERR_ACCOUNT_NOT_FOUND")
    return rec


def workflow_or_404(workflow_id):
    rec = db.workflows.get(workflow_id)
    if rec is None:
        raise ApiError("ERR_WORKFLOW_NOT_FOUND")
    return rec


def action_or_404(action_id):
    rec = db.actions.get(action_id)
    if rec is None:
        raise ApiError("ERR_NO_RUNNABLE_ACTION", "The referenced action does not exist.", 404)
    return rec


def member_or_404(member_id):
    rec = db.members.get(member_id)
    if rec is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    return rec


def connection_or_404(connection_id):
    rec = db.connections.get(connection_id)
    if rec is None:
        raise ApiError("ERR_CONNECTION_NOT_FOUND")
    return rec


def integration_or_404(integration_id):
    rec = db.integrations.get(integration_id)
    if rec is None:
        raise ApiError("ERR_INTEGRATION_NOT_FOUND")
    return rec


def integration_version_or_404(version_id):
    rec = db.integration_versions.get(version_id)
    if rec is None:
        raise ApiError("ERR_INTEGRATION_VERSION_NOT_FOUND")
    return rec


def folder_or_404(folder_id):
    rec = db.folders.get(folder_id)
    if rec is None:
        raise ApiError("ERR_FOLDER_NOT_PERMITTED", "The referenced folder does not exist.", 403)
    return rec


def folder_visible(folder, member_id):
    """OWNER of the account, or a MANAGE grant on the folder (PRD §2.1)."""
    account = db.accounts.get(folder.get("account_id"))
    if account is not None:
        for member in db.members.values():
            if member["id"] == member_id and member["account_id"] == account["id"] \
                    and member["role"] == "OWNER":
                return True
    for grant in db.folder_grants.values():
        if grant["folder_id"] == folder["id"] and grant["member_id"] == member_id:
            if grant["grant_role"] == "MANAGE":
                return True
    return False


def require_folder_visibility(folder):
    role = acting_role()
    if role != "Member":
        return
    if not folder_visible(folder, acting_id()):
        raise ApiError("ERR_FOLDER_NOT_PERMITTED")


def require_action_folder_visibility(workflow):
    """Attaching an action is filed under the workflow's folder, so the acting
    member must still be able to reach it (PRD §2.13 puts the referential
    folder check ahead of the uniqueness constraints such as
    ERR_DUPLICATE_ACTION_POSITION)."""
    folder = db.folders.get(workflow.get("folder_id"))
    if folder is not None:
        require_folder_visibility(folder)


def require_owner(connection):
    """Owner comparison only applies to the entity-backed Member role (PRD §2.1)."""
    if acting_role() != "Member":
        return
    if connection.get("owner_member_id") != acting_id():
        raise ApiError("ERR_CONNECTION_INVALID_STATE",
                       "Only the connection's owner member may perform this operation.")


def actions_of(workflow_id):
    items = [a for a in db.actions.values() if a["workflow_id"] == workflow_id]
    items.sort(key=lambda a: a["position"])
    return items


def runs_of(workflow_id):
    return [r for r in db.runs.values() if r["workflow_id"] == workflow_id]


def make_join(folder_id, grant_id):
    from models import new_folder_folder_grant
    rec = new_folder_folder_grant(folder_id, grant_id)
    db.folder_folder_grants[rec["id"]] = rec
    return rec