"""Account endpoints (PRD 3.1, scaffold 1.5)."""

from flask import Blueprint, request

import auth
import constants as K
import lookup
import models
import recompute
from response import array_response, object_response, paginate, sort_by_created
from store import store
from util import (pagination, parse_instant, q_int, req_enum, req_num, req_str,
                  body_field)
from errors import (APIError, ERR_CLOSURE_DELETION_REQUIRED,
                    ERR_CLOSURE_SETS_REMAIN, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE)

bp = Blueprint("accounts", __name__, url_prefix="/backup-provider")


def _public(account):
    return models.public(account)


@bp.route("/accounts", methods=["POST"])
def create_account():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_ACCOUNT_CREATE)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise APIError(ERR_INVALID_REQUEST, "request body must be a JSON object")

    name = req_str(body, "name")
    account_type = req_enum(body, "account_type", K.ACCOUNT_TYPES)
    region = req_enum(body, "region", K.REGIONS)
    storage_tier = req_enum(body, "storage_tier", K.STORAGE_TIERS,
                            required=False, default="BASIC")
    encryption_key_id = req_str(body, "encryption_key_id")
    usage_gb = req_num(body, "usage_gb", required=False, default=0)

    account = models.account(store, name, account_type, region, encryption_key_id,
                             storage_tier=storage_tier, usage_gb=usage_gb)
    store.accounts[account["id"]] = account
    return object_response(_public(account), 201)


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_ACCOUNT_LIST)
    limit, offset = pagination(request.args)

    status = request.args.get("status")
    account_type = request.args.get("account_type")
    rows = list(store.accounts.values())
    if status:
        rows = [a for a in rows if a["status"] == status]
    if account_type:
        rows = [a for a in rows if a["account_type"] == account_type]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([_public(a) for a in page], limit, offset, total)


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    caller = auth.parse(request.headers)
    auth.require(caller, auth.R_ACCOUNT_GET)
    account = lookup.account(lookup.ensure_id(account_id, "id"))
    auth.require(caller, auth.R_ACCOUNT_GET, owned_account_id=account["id"])
    return object_response(_public(account))


@bp.route("/accounts/<account_id>/reinstate", methods=["POST"])
def reinstate_account(account_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "SystemOperator")
    account = lookup.account(lookup.ensure_id(account_id, "id"))

    # DELINQUENT -> ACTIVE (scaffold state machine 9)
    if account["status"] != "DELINQUENT":
        raise APIError(ERR_INVALID_STATE,
                       "account is not DELINQUENT and cannot be reinstated")
    account["status"] = "ACTIVE"
    for bset in store.sets_of_account(account["id"]):
        if bset["state"] == "SUSPENDED":
            bset["state"] = "ACTIVE"
            lookup.bump(bset)
    lookup.bump(account)
    return object_response(_public(account))


@bp.route("/accounts/<account_id>/close", methods=["POST"])
def close_account(account_id):
    caller = auth.parse(request.headers)
    auth.require_exact(caller, "ComplianceOfficer")
    account = lookup.account(lookup.ensure_id(account_id, "id"))

    # PRD 3.8: closure is gated by two preconditions that make erasure the
    # mandatory precursor.  They are consulted before the state check so a
    # premature closure names the missing precursor rather than a generic
    # state conflict; execution of an ACCOUNT_CLOSURE purge has already put the
    # account in CLOSED, so the explicit close remains available afterwards.
    deletions = [d for d in store.deletions.values() if d["account_id"] == account["id"]]
    satisfied = any(d["state"] == "COMPLETED" and d["deletion_scope"] == "ACCOUNT_CLOSURE"
                    for d in deletions)
    if not satisfied:
        raise APIError(ERR_CLOSURE_DELETION_REQUIRED,
                       "every data deletion request of the account must be COMPLETED "
                       "with scope ACCOUNT_CLOSURE")
    for bset in store.sets_of_account(account["id"]):
        if bset["state"] != "DELETED":
            raise APIError(ERR_CLOSURE_SETS_REMAIN,
                           "every backup set of the account must be DELETED")

    account["status"] = "CLOSED"
    for agent in store.agents_of_account(account["id"]):
        agent["status"] = "RETIRED"
        lookup.bump(agent)
    account["usage_gb"] = 0.0
    lookup.bump(account)
    return object_response(_public(account))