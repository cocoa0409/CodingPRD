"""Enforcement actions: retrieval, the expiry sweep and the periodic review round."""

from flask import Blueprint, request

from db import STORE, add_days, now
from errors import ApiError, ERR_IN_FLIGHT_APPEAL, ERR_INVALID_STATE, ERR_RESOURCE_NOT_FOUND
from middleware import (assert_version_matches, body, require_version, route, touch)
from response import read_pagination, success, success_list
from serializers import account as serialize_account
from serializers import enforcement_action as serialize_action
from calculations import expiry_projection
from services import common

bp = Blueprint("enforcement", __name__)

_READ_ROLES = ("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead",
               "SafetyAppealReviewer", "RegulatorLiaison")


def get_action(action_id):
    action = STORE.enforcement_actions.get(action_id)
    if action is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such enforcement action: %s" % action_id)
    return action


@bp.route("/safety/enforcement-actions", methods=["GET"])
@route(*_READ_ROLES)
def list_actions(ident):
    limit, offset = read_pagination(request.args)
    items = list(STORE.enforcement_actions.values())

    def keep(action):
        for field in ("account_id", "incident_id", "enforcement_status"):
            wanted = request.args.get(field)
            if wanted is not None and action.get(field) != wanted:
                return False
        return True

    items = [a for a in items if keep(a)]
    items.sort(key=lambda a: (a.get("created_at"), a.get("id") or ""))
    return success_list([serialize_action(a) for a in items], limit, offset)


@bp.route("/safety/enforcement-actions/<action_id>", methods=["GET"])
@route("PlatformAdmin", "SafetyInvestigator", "SafetyOperationsLead", "SafetyAppealReviewer")
def get_one_action(ident, action_id):
    return success(serialize_action(get_action(action_id)))


@bp.route("/safety/enforcement-actions/expiry-sweep", methods=["POST"])
@route("SafetyOperationsLead")
def expiry_sweep(ident):
    payload = body()
    account_id = payload.get("account_id")
    account = STORE.accounts.get(account_id)
    if account is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such account: %s" % account_id)

    require_version(payload, "expected_account_version")
    assert_version_matches(payload, "expected_account_version", account, "Account")

    instant = now()
    candidates = [a for a in STORE.account_actions(account_id)
                  if a.get("enforcement_status") == "ACTIVE"
                  and a.get("expires_at") is not None
                  and instant >= a.get("expires_at")]
    candidates.sort(key=lambda a: (a.get("effective_at"), a.get("created_at"), a.get("id") or ""))

    if not candidates:
        raise ApiError(*ERR_INVALID_STATE,
                       message="The account has no enforcement action at its expiry "
                               "instant.")

    if account.get("status") != "RESTRICTED":
        raise ApiError(*ERR_INVALID_STATE,
                       message="The expiry sweep is not declared from account status %s."
                               % account.get("status"))

    action = candidates[0]

    # The in-flight-appeal guard reads the *other* standing actions. The action
    # being expired is itself standing right now, so it is excluded from the
    # reading: the sweep would otherwise refuse every legitimate call.
    if common.standing_actions(account_id, exclude_action_id=action.get("id"),
                               outcome="DEACTIVATED"):
        raise ApiError(*ERR_IN_FLIGHT_APPEAL,
                       message="The account carries an in-flight appeal.")

    regression, projected, projected_tier = expiry_projection(account, action)
    action["enforcement_status"] = "EXPIRED"
    touch(action)

    if regression:
        # A tier regression deactivates the account instead of restoring it. The
        # action being expired is itself the deactivation action, so it is marked
        # EXPIRED rather than a second stand-alone DEACTIVATED action being minted
        # alongside it.
        account["status"] = "DEACTIVATED"
    else:
        account["status"] = "ACTIVE"

    common.refresh_account(account)
    return success(serialize_account(account))


@bp.route("/safety/enforcement-actions/review-tick", methods=["POST"])
@route("SafetyOperationsLead")
def review_tick(ident):
    payload = body()
    account_id = payload.get("account_id")
    account = STORE.accounts.get(account_id)
    if account is None:
        raise ApiError(*ERR_RESOURCE_NOT_FOUND,
                       message="No such account: %s" % account_id)

    instant = now()
    actions = STORE.account_actions(account_id)
    due = [a for a in actions
           if a.get("review_due_at") is not None and instant >= a.get("review_due_at")]
    due.sort(key=lambda a: (a.get("effective_at"), a.get("created_at"), a.get("id") or ""))

    ticked = []
    for action in due:
        action["review_due_at"] = add_days(action.get("review_due_at"), 180)
        touch(action)
        ticked.append(action)
        # The peer action with a strictly earlier effective_at is re-checked too.
        peers = [a for a in actions
                 if a.get("effective_at") is not None
                 and action.get("effective_at") is not None
                 and a.get("effective_at") < action.get("effective_at")
                 and a.get("id") != action.get("id")]
        peers.sort(key=lambda a: (a.get("effective_at"), a.get("created_at"), a.get("id") or ""))
        if peers:
            peer = peers[-1]
            if peer.get("review_due_at") is not None:
                peer["review_due_at"] = add_days(peer.get("review_due_at"), 180)
                touch(peer)
                if peer not in ticked:
                    ticked.append(peer)

    common.drop_ineligible_from_report_queue(account_id)
    ticked.sort(key=lambda a: (a.get("created_at"), a.get("id") or ""))
    return success_list([serialize_action(a) for a in ticked], 100, 0)