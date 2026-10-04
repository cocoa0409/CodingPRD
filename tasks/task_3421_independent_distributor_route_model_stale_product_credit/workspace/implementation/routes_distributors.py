"""Distributor routes: CRUD, settlement statement, retail accounts, audits."""
from flask import Blueprint, request

import auth
import calc
import clock
import domain
import store
import validators as V
from constants import (
    ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR,
    WEEKDAYS, STRIKE_SUSPEND_THRESHOLD,
)
from errors import (
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_AUDIT_SCORE_RANGE,
    ERR_AGREEMENT_NOT_ACTIVE, raise_err,
)
from response import ok, ok_object, ok_list, pagination_params, body

bp = Blueprint("distributors", __name__)

ALL = (ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR)
ACCOUNT_CREATORS = (ROLE_DISTRIBUTOR, ROLE_ROUTE_OPS)


def load_distributor(rid, user_id, role):
    """Stage 3 ownership (path scope) then stage 4 existence."""
    auth.require_path_distributor(user_id, role, rid)
    distributor = store.get("distributors", rid)
    if distributor is None:
        raise_err(ERR_NOT_FOUND, "Distributor not found")
    return distributor


@bp.route("/distributors", methods=["POST"])
def create_distributor():
    user_id, role = auth.caller()
    auth.require_role(role, (ROLE_COMPANY_ADMIN,))
    data = body()
    legal_name = V.get_str(data, "legal_name")
    credit_limit = V.get_int(data, "credit_limit_cents", minimum=1)
    distributor = store.insert("distributors", {
        "legal_name": legal_name,
        "credit_limit_cents": credit_limit,
        "status": "PROSPECT",
        "classification_status": "INDEPENDENT_CONTRACTOR",
        "account_standing": "GOOD",
        "trade_balance_cents": 0,
    })
    return ok_object(distributor, 201)


@bp.route("/distributors/<rid>", methods=["GET"])
def get_distributor(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ALL)
    return ok_object(load_distributor(rid, user_id, role))


@bp.route("/distributors/<rid>/settlement", methods=["GET"])
def settlement(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ALL)
    distributor = load_distributor(rid, user_id, role)
    if request.args.get("week") is not None:
        week_t = domain.parse_week(request.args.get("week"))
        if week_t is None:
            raise_err(ERR_INVALID_REQUEST, "week must be an ISO week (YYYY-Www)")
    else:
        week_t = domain.week_tuple_of(clock.today())
    gross = 0
    document_view = 0
    for order in domain.orders_of(rid):
        if order["status"] in ("DELIVERED", "RECONCILED"):
            document_view += order["total_charge_cents"] or 0
            if order.get("_delivered_date") and domain.date_in_week(order["_delivered_date"], week_t):
                gross += order["total_charge_cents"] or 0
        if order["status"] == "RECONCILED":
            document_view -= order["shortage_credit_cents"] or 0
    issued_week = 0
    for claim in domain.claims_of(rid):
        if claim["status"] == "CREDIT_ISSUED":
            document_view -= claim["issued_credit_cents"] or 0
            if claim.get("_submitted_date") and domain.date_in_week(claim["_submitted_date"], week_t):
                issued_week += claim["issued_credit_cents"] or 0
    cap = calc.stale_cap_cents(gross)
    ledger_view = distributor["trade_balance_cents"]
    return ok({
        "week": domain.week_str(week_t),
        "gross_charges_cents": gross,
        "stale_credits_issued_cents": issued_week,
        "net_trade_cents": gross - issued_week,
        "stale_cap_cents": cap,
        "stale_cap_used_cents": issued_week,
        "trade_balance_cents": distributor["trade_balance_cents"],
        "ledger_view_cents": ledger_view,
        "document_view_cents": document_view,
        "reconciles": ledger_view == document_view,
    }, "object", 200)


@bp.route("/distributors/<rid>/retail-accounts", methods=["POST"])
def create_retail_account(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ACCOUNT_CREATORS)
    load_distributor(rid, user_id, role)
    data = body()
    store_name = V.get_str(data, "store_name")
    weekdays = V.get_list(data, "delivery_weekdays", non_empty=True)
    for day in weekdays:
        if day not in WEEKDAYS:
            raise_err(ERR_INVALID_REQUEST,
                      f"delivery_weekdays entries must be one of {list(WEEKDAYS)}")
    agreement = domain.resolve_agreement(rid, active_only=True)
    if agreement is None:
        raise_err(ERR_AGREEMENT_NOT_ACTIVE,
                  "Retail account creation requires the distributor's ACTIVE agreement")
    account = store.insert("retail_accounts", {
        "distributor_id": rid,
        "store_name": store_name,
        "delivery_weekdays": weekdays,
        "compliance_score": None,
        "last_audit_on": None,
        "audit_log": [],
    })
    return ok_object(account, 201)


@bp.route("/distributors/<rid>/retail-accounts", methods=["GET"])
def list_retail_accounts(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ALL)
    load_distributor(rid, user_id, role)
    accounts = [a for a in store.all_of("retail_accounts") if a["distributor_id"] == rid]
    page = pagination_params()
    total = len(accounts)
    window = accounts[page["offset"]:page["offset"] + page["limit"]]
    return ok_list(window, total, page)


@bp.route("/retail-accounts/<rid>/audits", methods=["POST"])
def post_audit(rid):
    user_id, role = auth.caller()
    auth.require_role(role, (ROLE_ROUTE_OPS,))
    account = store.get("retail_accounts", rid)
    if account is None:
        raise_err(ERR_NOT_FOUND, "Retail account not found")
    data = body()
    audit_date_str, audit_date = V.get_date(data, "audit_date")
    scores = {}
    for field in ("shelf_stock_score", "rotation_score", "display_score"):
        if field not in data or data[field] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, int):
            raise_err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
        if value < 0 or value > 100:
            raise_err(ERR_AUDIT_SCORE_RANGE,
                      f"Field {field} must be within 0..100 inclusive")
        scores[field] = value
    composite = calc.composite_score(scores["shelf_stock_score"],
                                     scores["rotation_score"],
                                     scores["display_score"])
    violation = calc.is_violation(scores["shelf_stock_score"],
                                  scores["rotation_score"],
                                  scores["display_score"])
    entry = {
        "audit_date": audit_date_str,
        "shelf_stock_score": scores["shelf_stock_score"],
        "rotation_score": scores["rotation_score"],
        "display_score": scores["display_score"],
        "composite_score": composite,
        "is_violation": violation,
        "_audit_date": audit_date,
        "_seq": store.next_seq(),
    }
    account["audit_log"].append(entry)
    latest = max(account["audit_log"], key=lambda e: (e["_audit_date"], e["_seq"]))
    account["compliance_score"] = latest["composite_score"]
    account["last_audit_on"] = latest["audit_date"]
    store.touch(account)
    agreement = domain.resolve_agreement(account["distributor_id"], active_only=True)
    if agreement is not None:
        strikes = domain.recompute_strikes(agreement, audit_date)
        if (violation and strikes >= STRIKE_SUSPEND_THRESHOLD
                and agreement["status"] == "ACTIVE"):
            domain.suspend_agreement(agreement, "SERVICE_DEFAULT")
    return ok_object(account, 201)
