"""Rewards ledger routes."""

from flask import Blueprint

from db import DB
from errors import ERR_INVALID_STATE, ApiError
from middleware import auth
from response import ok_object
from routes.common import fetch, guard_member_view, list_response
from services import serialize, workflows

BP = Blueprint("rewards", __name__)


@BP.route("/benefits/rewards-ledger-entries", methods=["GET"])
def list_entries():
    auth(("PlatformAdmin", "BenefitsAdmin", "Member"))
    items = list(DB.ledger.values())
    filters = {
        "member_id": "member_id",
        "loan_account_id": "loan_account_id",
        "entry_type": "entry_type",
        "entry_status": "entry_status",
    }
    return list_response(items, serialize.ledger, filters)


@BP.route("/benefits/rewards-ledger-entries/<entry_id>", methods=["GET"])
def get_entry(entry_id):
    user_id, role = auth(("PlatformAdmin", "BenefitsAdmin", "Member"))
    entry = fetch("ledger", entry_id)
    guard_member_view(user_id, role, entry["member_id"])
    return ok_object(serialize.ledger(entry))


@BP.route("/benefits/rewards-ledger-entries/<entry_id>/reverse", methods=["POST"])
def reverse_entry(entry_id):
    auth(("BenefitsAdmin",))
    entry = fetch("ledger", entry_id)
    if entry["entry_status"] != "POSTED":
        raise ApiError(ERR_INVALID_STATE)
    if entry["entry_type"] not in workflows.SAFE_LEDGER_TYPES:
        raise ApiError(ERR_INVALID_STATE)
    workflows.reverse_ledger_entry(entry)
    return ok_object(serialize.ledger(entry))