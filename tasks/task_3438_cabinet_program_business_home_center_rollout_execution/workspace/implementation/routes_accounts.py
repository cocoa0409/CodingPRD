"""Account endpoints (PRD 3.1)."""
from flask import Blueprint

from auth import get_body, require_roles
from db import bump, new_entity, store
from envelope import ok
from errors import api_error
from services import OPEN_ORDER_STATUSES, recompute_credit

bp = Blueprint("accounts", __name__)

CHANNELS = ("RETAIL", "DEALER", "BUILDER")
PRICING_CLASSES = ("STANDARD", "VOLUME", "NATIONAL")
LEAD_TIME_CLASSES = ("STANDARD", "EXTENDED")
ALL_ROLES = ("PlatformAdmin", "ProgramManager", "RetailDesigner", "DealerRep",
             "PlantScheduler", "LogisticsCoordinator", "ClaimsAdjuster", "FieldServiceRep")


def serialize(account):
    return dict(account)


@bp.route("/cabinet/accounts", methods=["POST"])
def create_account():
    require_roles("PlatformAdmin")
    body = get_body()
    name = body.get("name")
    channel = body.get("channel")
    pricing_class = body.get("pricing_class")
    lead_time_class = body.get("lead_time_class")
    credit_limit = body.get("credit_limit_cents")
    if not isinstance(name, str) or not name:
        raise api_error("ERR_INVALID_REQUEST", "name is required")
    if channel not in CHANNELS:
        raise api_error("ERR_INVALID_REQUEST", "channel must be RETAIL, DEALER or BUILDER")
    if pricing_class not in PRICING_CLASSES:
        raise api_error("ERR_INVALID_REQUEST", "pricing_class must be STANDARD, VOLUME or NATIONAL")
    if lead_time_class not in LEAD_TIME_CLASSES:
        raise api_error("ERR_INVALID_REQUEST", "lead_time_class must be STANDARD or EXTENDED")
    if isinstance(credit_limit, bool) or not isinstance(credit_limit, int) or credit_limit < 0:
        raise api_error("ERR_INVALID_REQUEST", "credit_limit_cents must be a non-negative integer")
    store_codes = body.get("store_codes", [])
    if not isinstance(store_codes, list) or not all(isinstance(s, str) for s in store_codes):
        raise api_error("ERR_INVALID_REQUEST", "store_codes must be an array of strings")
    if channel != "RETAIL":
        store_codes = []
    account = new_entity()
    account.update({
        "name": name,
        "channel": channel,
        "pricing_class": pricing_class,
        "lead_time_class": lead_time_class,
        "credit_limit_cents": credit_limit,
        "store_codes": list(store_codes),
        "status": "ACTIVE",
        "open_exposure_cents": 0,
    })
    store.accounts[account["id"]] = account
    return ok(serialize(account), 201)


@bp.route("/cabinet/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    require_roles(*ALL_ROLES)
    account = store.accounts.get(account_id)
    if account is None:
        raise api_error("ERR_NOT_FOUND", "account not found")
    return ok(serialize(account))


@bp.route("/cabinet/accounts/<account_id>/status", methods=["POST"])
def set_account_status(account_id):
    require_roles("PlatformAdmin")
    account = store.accounts.get(account_id)
    if account is None:
        raise api_error("ERR_NOT_FOUND", "account not found")
    body = get_body()
    to_status = body.get("to_status")
    if to_status is None:
        raise api_error("ERR_INVALID_REQUEST", "to_status is required")
    current = account["status"]
    legal = {
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
        ("ACTIVE", "CLOSED"),
        ("SUSPENDED", "CLOSED"),
    }
    if (current, to_status) not in legal:
        raise api_error("ERR_INVALID_STATE",
                        "cannot move account from {} to {}".format(current, to_status))
    if to_status == "CLOSED":
        for order in store.orders.values():
            if order["account_id"] == account_id and order["status"] in OPEN_ORDER_STATUSES:
                raise api_error("ERR_ACCOUNT_HAS_OPEN_ORDERS",
                                "account has orders in open fulfillment states")
    account["status"] = to_status
    bump(account)
    if to_status == "ACTIVE":
        # PRD 3.1: returning a suspended account to ACTIVE recomputes exposure
        # and re-evaluates the release of held orders.
        recompute_credit(account_id)
    return ok(serialize(account))
