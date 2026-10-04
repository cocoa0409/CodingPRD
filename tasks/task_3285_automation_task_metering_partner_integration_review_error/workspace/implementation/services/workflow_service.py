"""Workflow lifecycle: activate, pause, resume, disable (PRD §3.2)."""
from common import actions_of
from db import db
from errors import ApiError
from models import touch

ACTIVATABLE_ACTION_STATES = {"PENDING", "SKIPPED"}
ACTIVATION_CONNECTION_STATES = {"CONNECTED", "TOKEN_EXPIRED", "REAUTH_REQUIRED"}


def activate(workflow):
    if workflow["status"] != "DRAFT":
        raise ApiError("ERR_WORKFLOW_INVALID_STATE")
    actions = actions_of(workflow["id"])
    if len(actions) < 1 or workflow["action_count"] < 1:
        raise ApiError("ERR_WORKFLOW_INVALID_STATE",
                       "A workflow needs at least one action before it can be activated.")
    for action in actions:
        if action["status"] not in ACTIVATABLE_ACTION_STATES:
            raise ApiError("ERR_WORKFLOW_INVALID_STATE",
                           "Every action must rest in PENDING or SKIPPED before activation.")
    for action in actions:
        conn = db.connections.get(action["connection_id"])
        if conn is None or conn["status"] not in ACTIVATION_CONNECTION_STATES:
            raise ApiError("ERR_WORKFLOW_INVALID_STATE",
                           "Every referenced connection must be resolvable and not disconnected.")
    workflow["status"] = "ACTIVE"
    workflow["attempt_epoch"] = 1
    touch(workflow)
    account = db.accounts.get(workflow["account_id"])
    if account is not None:
        touch(account)
    return workflow


def pause(workflow):
    if workflow["status"] != "ACTIVE":
        raise ApiError("ERR_WORKFLOW_INVALID_STATE")
    workflow["status"] = "PAUSED"
    workflow["pause_reason"] = "USER_PAUSED"
    touch(workflow)
    return workflow


def resume(workflow):
    if workflow["status"] != "PAUSED":
        # The lifecycle state gate is priority 10 and is decided before the
        # credential-health gate (priority 17) attached to dispatch, which is
        # why reviving a workflow that is not PAUSED reports the state error
        # rather than the connection error (PRD §2.13).
        raise ApiError("ERR_WORKFLOW_INVALID_STATE")
    if workflow["pause_reason"] == "TOKEN_EXPIRED":
        for action in actions_of(workflow["id"]):
            conn = db.connections.get(action["connection_id"])
            if conn is None or conn["status"] != "CONNECTED":
                raise ApiError("ERR_CONNECTION_INVALID_STATE",
                               "Every referenced connection must be CONNECTED before resuming.")
    account = db.accounts.get(workflow["account_id"])
    if account is not None:
        if (account["tasks_used_current"] >= account["task_allowance"]
                and not account["overage_enabled"]):
            raise ApiError("ERR_WORKFLOW_INVALID_STATE",
                           "The account is over its allowance and does not permit overage.")
    workflow["status"] = "ACTIVE"
    workflow["pause_reason"] = None
    touch(workflow)
    return workflow


def disable(workflow):
    if workflow["status"] not in ("DRAFT", "PAUSED"):
        raise ApiError("ERR_WORKFLOW_INVALID_STATE")
    workflow["status"] = "DISABLED"
    touch(workflow)
    return workflow