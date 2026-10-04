"""Wholesale retail accounts (PRD §3.3)."""
from flask import Blueprint

from constants import ACCOUNT_STATUSES
from db import store
from errors import err
from middleware import auth, require_role
from services import calc
from util import get_body, new_record, ok_object, req_enum, req_int, req_str, serialize, touch

bp = Blueprint("retail_accounts", __name__)

_ACCOUNT_EDGES = {
    ("ACTIVE", "HOLD"),
    ("HOLD", "ACTIVE"),
    ("ACTIVE", "CLOSED"),
    ("HOLD", "CLOSED"),
}


def get_account(aid):
    a = store.retail_accounts.get(aid)
    if a is None:
        err("ERR_RETAIL_ACCOUNT_NOT_FOUND", "unknown retail account id")
    return a


@bp.route("/api/retail-accounts", methods=["POST"])
def create_account():
    _uid, role = auth()
    data = get_body()
    business_name = req_str(data, "business_name")
    credit_limit = req_int(data, "credit_limit_cents", minimum=1)
    require_role(role, ["PlatformAdmin"])
    rec = new_record()
    rec.update({
        "business_name": business_name,
        "credit_limit_cents": credit_limit,
        "credit_used_cents": 0,
        "status": "ACTIVE",
    })
    store.retail_accounts[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/api/retail-accounts/<aid>", methods=["GET"])
def fetch_account(aid):
    auth()
    return ok_object(serialize(get_account(aid)), 200)


@bp.route("/api/retail-accounts/<aid>/transition", methods=["POST"])
def transition_account(aid):
    _uid, role = auth()
    data = get_body()
    to_state = req_enum(data, "to_state", ACCOUNT_STATUSES)
    require_role(role, ["PlatformAdmin"])
    acct = get_account(aid)
    if (acct["status"], to_state) not in _ACCOUNT_EDGES:
        err("ERR_INVALID_TRANSITION", "account cannot move %s -> %s" % (acct["status"], to_state))
    if to_state == "CLOSED":
        calc.recompute_credit(acct)
        if acct["credit_used_cents"] != 0:
            err("ERR_ACCOUNT_HAS_OPEN_EXPOSURE", "account close requires zero open exposure")
    bumped = set()
    acct["status"] = to_state
    touch(acct, bumped)
    return ok_object(serialize(acct), 200)
