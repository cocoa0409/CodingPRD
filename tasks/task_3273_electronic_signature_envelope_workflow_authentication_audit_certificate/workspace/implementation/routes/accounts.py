"""Account, credit and retention-policy routes."""

from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_ACCOUNT_NOT_FOUND, ERR_RETENTION_POLICY_NOT_FOUND
from middleware import authenticate, owned_by_account, ROLE_ACCOUNT, ROLE_PLATFORM_ADMIN
from response import ok, ok_array, paginate, read_pagination
from services import account as account_svc
from services.account import (
    adjust_credit,
    create_account,
    create_policy,
    set_account_status,
    update_policy,
)

bp = Blueprint("accounts", __name__)


def _load_account(account_id):
    account = db.account(account_id)
    if account is None:
        raise ApiError(
            ERR_ACCOUNT_NOT_FOUND[0],
            "no account matches id %s" % account_id,
            ERR_ACCOUNT_NOT_FOUND[1],
        )
    return account


def _load_policy(policy_id):
    policy = db.policy(policy_id)
    if policy is None:
        raise ApiError(
            ERR_RETENTION_POLICY_NOT_FOUND[0],
            "no retention policy matches id %s" % policy_id,
            ERR_RETENTION_POLICY_NOT_FOUND[1],
        )
    return policy


@bp.route("/esign/accounts", methods=["POST"])
def post_account():
    authenticate([ROLE_PLATFORM_ADMIN])
    body = request.get_json(silent=True) or {}
    account = create_account(body)
    return ok(account, 201)


@bp.route("/esign/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    actor = authenticate([ROLE_PLATFORM_ADMIN, ROLE_ACCOUNT])
    account = _load_account(account_id)
    owned_by_account(actor, account["id"])
    return ok(account, 200)


@bp.route("/esign/accounts/<account_id>/credit-adjustments", methods=["POST"])
def post_credit_adjustment(account_id):
    authenticate([ROLE_PLATFORM_ADMIN])
    account = _load_account(account_id)
    body = request.get_json(silent=True) or {}
    account = adjust_credit(account, body)
    return ok(account, 200)


@bp.route("/esign/accounts/<account_id>/status", methods=["POST"])
def post_account_status(account_id):
    authenticate([ROLE_PLATFORM_ADMIN])
    account = _load_account(account_id)
    body = request.get_json(silent=True) or {}
    account = set_account_status(account, body)
    return ok(account, 200)


@bp.route("/esign/retention-policies", methods=["POST"])
def post_policy():
    authenticate([ROLE_PLATFORM_ADMIN])
    body = request.get_json(silent=True) or {}
    policy = create_policy(body)
    return ok(policy, 201)


@bp.route("/esign/retention-policies", methods=["GET"])
def list_policies():
    authenticate([ROLE_PLATFORM_ADMIN, ROLE_ACCOUNT])
    limit, offset = read_pagination(request.args)
    scope = request.args.get("scope")
    policies = list(db.retention_policies.values())
    if scope:
        policies = [p for p in policies if p["scope"] == scope]
    policies.sort(key=lambda p: p.get("_ord", 0))
    window, limit, offset, total = paginate(policies, limit, offset)
    return ok_array(window, limit, offset, total, 200)


@bp.route("/esign/retention-policies/<policy_id>", methods=["PATCH"])
def patch_policy(policy_id):
    authenticate([ROLE_PLATFORM_ADMIN])
    policy = _load_policy(policy_id)
    body = request.get_json(silent=True) or {}
    policy = update_policy(policy, body)
    return ok(policy, 200)