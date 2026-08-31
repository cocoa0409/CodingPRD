"""Ticket accounts, rep assignment, touchpoints and the renewal quote."""
from flask import Blueprint, request

import calc
from core import (ROLE_ADMIN, ROLE_SALES, READ_ROLES, apply_filters, bad_request, body, bump,
                  base_fields, db, endpoint, err, find_account, find_plan, new_id, now, ok,
                  ok_page, opt_str, pagination, paginate, req_enum, req_int, req_str, sort_created)

bp = Blueprint("accounts", __name__)

ACCOUNT_TYPES = ("INDIVIDUAL", "GROUP", "CORPORATE")


# ---------------------------------------------------------------------------
# Shared ownership / account-status gates (ladder rungs 6, 7 and 14)
# ---------------------------------------------------------------------------
def gate_rep_ownership(caller, account):
    if caller.is_sales and caller.user_id != account.get("assigned_rep_id"):
        err("ERR_NOT_ACCOUNT_REP", 403, "Caller is not the assigned rep for this account.")


def gate_holder_ownership(caller, account_id):
    if caller.is_holder and caller.user_id != account_id:
        err("ERR_NOT_ORDER_OWNER", 403, "Caller does not own this resource.")


def gate_account_written_off(account):
    if account["billing_status"] == "WRITTEN_OFF":
        err("ERR_ACCOUNT_WRITTEN_OFF", 409, "The account has been written off.")


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
@bp.route("/ticketing/accounts", methods=["POST"])
@endpoint(ROLE_ADMIN, ROLE_SALES)
def create_account(caller):
    data = body()
    account_name = req_str(data, "account_name")
    account_type = req_enum(data, "account_type", ACCOUNT_TYPES)
    territory_code = req_str(data, "territory_code")
    tenure_years = req_int(data, "tenure_years", minimum=0)
    row = {"id": new_id(), "account_name": account_name, "account_type": account_type,
           "territory_code": territory_code, "tenure_years": tenure_years,
           "assigned_rep_id": None, "billing_status": "CURRENT", "service_status": "PROSPECT",
           "past_due_since_utc": None, "at_risk_since_utc": None, "last_touchpoint_at_utc": None,
           "renewal_priority_active": False, "loyalty_credit_cents": 0, "no_show_count": 0,
           "season_no_show_count": 0, "attended_count": 0, "transfer_count_season": 0,
           "churn_risk_rolling": 0, "churn_risk_campaign": 0, "lifetime_value_cents": 0}
    row.update(base_fields())
    db.accounts[row["id"]] = row
    return ok(row, 201)


@bp.route("/ticketing/accounts/<account_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_account(caller, account_id):
    return ok(find_account(account_id))


@bp.route("/ticketing/accounts", methods=["GET"])
@endpoint(*READ_ROLES)
def list_accounts(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.accounts.values()), [
        ("assigned_rep_id", "assigned_rep_id"), ("billing_status", "billing_status"),
        ("service_status", "service_status")])
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)


@bp.route("/ticketing/accounts/<account_id>/assign-rep", methods=["POST"])
@endpoint(ROLE_ADMIN)
def assign_rep(caller, account_id):
    account = find_account(account_id)
    gate_account_written_off(account)
    if account.get("assigned_rep_id") is not None:
        err("ERR_ACCOUNT_STATE_INVALID", 409, "The account already has an assigned rep.")
    rep = calc.select_rep(account)
    if rep is None:
        err("ERR_NO_ELIGIBLE_REP", 422, "No eligible service rep is available for this territory.")
    account["assigned_rep_id"] = rep["id"]
    rep["assigned_account_count"] += 1
    bump(rep)
    bump(account)
    return ok(account)


@bp.route("/ticketing/accounts/<account_id>/touchpoints", methods=["POST"])
@endpoint(ROLE_SALES)
def log_touchpoint(caller, account_id):
    data = body()
    req_str(data, "touchpoint_type")
    outcome = req_str(data, "outcome")
    opt_str(data, "note")

    account = find_account(account_id)
    gate_rep_ownership(caller, account)
    gate_account_written_off(account)
    if outcome == "WIN_BACK_ACCEPTED" and account["service_status"] != "CHURNED":
        err("ERR_ACCOUNT_STATE_INVALID", 409, "A win-back touchpoint requires a CHURNED account.")

    account["last_touchpoint_at_utc"] = now()
    if outcome == "COMMITTED" and account["service_status"] == "AT_RISK":
        account["service_status"] = "ACTIVE"
        account["at_risk_since_utc"] = None
    elif outcome == "WIN_BACK_ACCEPTED" and account["service_status"] == "CHURNED":
        account["service_status"] = "WON_BACK"
        account["at_risk_since_utc"] = None

    rep = db.reps.get(caller.user_id)
    if rep is not None:
        rep["touchpoints_logged_count"] += 1
        bump(rep)
    calc.recompute_rolling(account)
    bump(account)
    return ok(account)


@bp.route("/ticketing/accounts/<account_id>/renewal-quote", methods=["GET"])
@endpoint(*READ_ROLES)
def renewal_quote(caller, account_id):
    plan_id = request.args.get("plan_id")
    if not plan_id:
        bad_request("Query parameter 'plan_id' is required.")
    account = find_account(account_id)
    plan = find_plan(plan_id)
    season = db.seasons.get(plan["season_id"])
    mode = season["dynamic_pricing_mode"] if season else "AGGRESSIVE"
    seat_ids = [s["id"] for s in sorted(
        [x for x in db.seats.values() if x.get("assigned_account_id") == account_id],
        key=lambda r: (r["section_code"], r["row_label"], r["seat_number"]))]
    total = calc.plan_order_total(plan, seat_ids, account, 0, mode, "QUOTED")
    return ok({
        "account_id": account_id,
        "plan_id": plan_id,
        "seat_count": len(seat_ids),
        "included_game_count": plan["included_game_count"],
        "quoted_total_cents": total,
        "pricing_variant": "QUOTED",
        "campaign_risk_score": account["churn_risk_campaign"],
    })
