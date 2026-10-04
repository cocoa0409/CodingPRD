"""CustomerAccount endpoints: register, list, get, migrate, consolidate, orphan."""
from flask import Blueprint, request

import db
from calculations import deposit_settlement
from errors import ApiError
from middleware import current_user, require_roles, require_fields, require_int, require_str
from models import new_customer_account, touch
from response import success_obj, success_list, json_body, parse_pagination, paginate
from routes_targets import get_target_or_404
from util import ALL_ROLES

bp = Blueprint("customer_accounts", __name__)


def get_customer_account_or_404(account_id):
    account = db.customer_accounts.get(account_id)
    if account is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CustomerAccount not found")
    return account


@bp.route("/acquisitions/targets/<target_id>/customer-accounts", methods=["POST"])
def create_customer_account(target_id):
    _, role = current_user()
    require_roles(role, ["TransitionManager"])
    target = get_target_or_404(target_id)
    body = json_body()
    require_fields(body, ["account_ref", "deposit_cents", "ar_balance_cents"])
    require_str(body, "account_ref")
    require_int(body, "deposit_cents", minimum=0)
    require_int(body, "ar_balance_cents", minimum=0)
    # Priority 16: account_ref unique within the target.
    if any(a["account_ref"] == body["account_ref"]
           for a in db.customer_accounts_of_target(target_id)):
        raise ApiError("ERR_DUPLICATE", 409,
                       "account_ref already exists within the target")
    account = new_customer_account(target["id"], body["account_ref"],
                                   body["deposit_cents"], body["ar_balance_cents"])
    return success_obj(account, status=201)


@bp.route("/acquisitions/targets/<target_id>/customer-accounts", methods=["GET"])
def list_customer_accounts(target_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    get_target_or_404(target_id)
    limit, offset = parse_pagination()
    records = db.customer_accounts_of_target(target_id)
    status = request.args.get("status")
    if status is not None:
        records = [a for a in records if a["status"] == status]
    records.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(records, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/acquisitions/customer-accounts/<account_id>", methods=["GET"])
def get_customer_account(account_id):
    _, role = current_user()
    require_roles(role, ALL_ROLES)
    return success_obj(get_customer_account_or_404(account_id))


@bp.route("/acquisitions/customer-accounts/<account_id>/migrate", methods=["POST"])
def migrate_customer_account(account_id):
    _, role = current_user()
    require_roles(role, ["TransitionManager"])
    account = get_customer_account_or_404(account_id)
    target = db.targets[account["target_id"]]
    if account["status"] != "LEGACY":
        raise ApiError("ERR_INVALID_STATE", 409, "Account is not in LEGACY")
    if target["status"] != "CLOSING":
        raise ApiError("ERR_INVALID_STATE", 409, "Target is not in CLOSING")
    billing = next((i for i in db.transition_items_of_target(target["id"])
                    if i["category"] == "BILLING_RECORDS"), None)
    if billing is None or billing["status"] != "DONE":
        raise ApiError("ERR_TRANSITION_PREREQ", 409,
                       "BILLING_RECORDS transition item is not DONE")
    offset, refund, new_ar = deposit_settlement(account)
    account["deposit_offset_cents"] = offset
    account["refund_cents"] = refund
    account["new_ar_balance_cents"] = new_ar
    account["status"] = "MIGRATED"
    touch(account)
    return success_obj(account)


@bp.route("/acquisitions/customer-accounts/<account_id>/consolidate", methods=["POST"])
def consolidate_customer_account(account_id):
    _, role = current_user()
    require_roles(role, ["TransitionManager"])
    account = get_customer_account_or_404(account_id)
    if account["status"] != "MIGRATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Account is not in MIGRATED")
    if not any(t["status"] == "ADOPTED"
               for t in db.tariff_cases_of_target(account["target_id"])):
        raise ApiError("ERR_TARIFF_NOT_ADOPTED", 409,
                       "No ADOPTED TariffCase exists for the target")
    account["status"] = "CONSOLIDATED"
    touch(account)
    return success_obj(account)


@bp.route("/acquisitions/customer-accounts/<account_id>/orphan", methods=["POST"])
def orphan_customer_account(account_id):
    _, role = current_user()
    require_roles(role, ["TransitionManager"])
    account = get_customer_account_or_404(account_id)
    target = db.targets[account["target_id"]]
    if account["status"] != "LEGACY":
        raise ApiError("ERR_INVALID_STATE", 409, "Account is not in LEGACY")
    if target["status"] != "CLOSING":
        raise ApiError("ERR_INVALID_STATE", 409, "Target is not in CLOSING")
    if account["ar_balance_cents"] != 0 or account["deposit_cents"] != 0:
        raise ApiError("ERR_ACCOUNT_NOT_SETTLED", 409,
                       "Account still carries a deposit or AR balance")
    account["status"] = "ORPHANED"
    touch(account)
    return success_obj(account)
