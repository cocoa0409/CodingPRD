"""Account and AccountRestriction routes (PRD 3.4-3.6)."""

from datetime import timedelta

from flask import Blueprint, g

from core import (
    ApiError, READ_ROLES, ROLE_COMPLIANCE_OFFICER, ROLE_PLATFORM_ADMIN,
    ROLE_PORTFOLIO_MANAGER, ROLE_SPONSOR_OPERATOR, arg, body_json, clock, db,
    lookup, new_row, ok, paged, qfilter, require_roles, sequence_sort_key,
    serialize, sponsor_scope, touch, v_dt, v_enum, v_int, v_str, whole_days,
)
from calc import (
    account_lots, evaluate_drift, generate_trade_orders, market_value_cents,
)
from entities import (
    DRIFT_BASES, LOT_ORIGINS, RESTRICTION_TYPES, guard_not_suspended,
    guard_not_written_off, serialize_account,
)

bp = Blueprint("accounts", __name__)


# ----------------------------------------------------------------- Account --
@bp.post("/sma/accounts")
@require_roles(ROLE_SPONSOR_OPERATOR)
def create_account():
    body = body_json()

    # Rung 3: sponsor scope, evaluated on the body's own sponsor_id.
    raw_sponsor_id = body.get("sponsor_id")
    if isinstance(raw_sponsor_id, str) and raw_sponsor_id:
        sponsor_scope(raw_sponsor_id)

    # Rung 6: body reference existence, in declared input order.
    sponsor = None
    model = None
    if isinstance(raw_sponsor_id, str):
        sponsor = lookup(db.sponsors, raw_sponsor_id, "ERR_SPONSOR_NOT_FOUND")
    if isinstance(body.get("model_id"), str):
        model = lookup(db.models, body["model_id"], "ERR_MODEL_NOT_FOUND")

    # Rung 7: request shape.
    v_str(body, "sponsor_id")
    v_str(body, "model_id")
    account_number = v_str(body, "account_number", min_len=3, max_len=20)
    cash_reserve_bps = v_int(body, "cash_reserve_bps", required=False,
                             minimum=0, maximum=2000, default=100)
    drift_basis = v_enum(body, "drift_basis", DRIFT_BASES, required=False, default="SETTLED")
    tax_overlay_enabled = body.get("tax_overlay_enabled")
    if tax_overlay_enabled is None:
        tax_overlay_enabled = False
    elif not isinstance(tax_overlay_enabled, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'tax_overlay_enabled' must be a boolean.")
    harvest_budget_cents = v_int(body, "harvest_budget_cents", required=False,
                                 minimum=0, default=0)

    # Rung 11: from-state - the model must already have a published version.
    if not model.get("published_model_version_id"):
        raise ApiError("ERR_MODEL_NOT_PUBLISHED",
                       "The strategy has never published a model version.")

    # Rung 18: unique key.
    for existing in db.accounts.values():
        if existing["account_number"] == account_number:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "Account number '%s' is already taken." % account_number)

    row = new_row(
        sponsor_id=sponsor["id"],
        model_id=model["id"],
        account_number=account_number,
        current_model_version_id=model["published_model_version_id"],
        pending_model_version_id=None,
        implementation_status="SYNCED",
        billing_status="CURRENT",
        cash_cents=0,
        cash_reserve_bps=cash_reserve_bps,
        drift_basis=drift_basis,
        drift_bps=None,
        drift_basis_used=None,
        drift_evaluated_at=None,
        tax_overlay_enabled=tax_overlay_enabled,
        harvest_budget_cents=harvest_budget_cents,
        realized_loss_ytd_cents=0,
        fees_billed_ytd_cents=0,
        notified_at=None,
        implementation_deadline=None,
        last_implementation_lag_days=None,
        implemented_late=False,
        latest_return_bps=None,
        latest_return_period_end=None,
        latest_ending_value_cents=None,
        next_order_sequence=1,
    )
    db.accounts[row["id"]] = row
    sponsor["account_count"] += 1
    touch(sponsor)
    return ok(serialize_account(row), 201)


@bp.get("/sma/accounts/<account_id>")
@require_roles(*READ_ROLES)
def get_account(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    return ok(serialize_account(account))


@bp.get("/sma/accounts")
@require_roles(*READ_ROLES)
def list_accounts():
    rows = qfilter(db.accounts.values(),
                   sponsor_id=arg("sponsor_id"),
                   model_id=arg("model_id"),
                   current_model_version_id=arg("current_model_version_id"),
                   pending_model_version_id=arg("pending_model_version_id"),
                   implementation_status=arg("implementation_status"),
                   billing_status=arg("billing_status"))
    return paged(rows, serializer=serialize_account)


@bp.post("/sma/accounts/<account_id>/deposits")
@require_roles(ROLE_SPONSOR_OPERATOR)
def deposit(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    sponsor_scope(account["sponsor_id"])
    body = body_json()
    amount_cents = v_int(body, "amount_cents", minimum=1)
    guard_not_suspended(account)
    guard_not_written_off(account)
    account["cash_cents"] += amount_cents
    touch(account)
    return ok(serialize_account(account))


@bp.post("/sma/accounts/<account_id>/transfers-in")
@require_roles(ROLE_SPONSOR_OPERATOR)
def transfer_in(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    sponsor_scope(account["sponsor_id"])
    body = body_json()

    security = None
    if isinstance(body.get("security_id"), str):
        security = lookup(db.securities, body["security_id"], "ERR_SECURITY_NOT_FOUND")

    v_str(body, "security_id")
    shares = v_int(body, "shares", minimum=1)
    cost_basis_cents = v_int(body, "cost_basis_cents", minimum=0)
    origin = v_enum(body, "origin", LOT_ORIGINS, required=False, default="TRANSFER_IN")

    guard_not_suspended(account)
    guard_not_written_off(account)

    lot = new_row(
        account_id=account["id"],
        security_id=security["id"],
        parent_tax_lot_id=None,
        opening_trade_order_id=None,
        closing_trade_order_id=None,
        sequence_number=account["next_order_sequence"],
        origin=origin,
        open_date=clock(),
        shares_open=shares,
        shares_closed=0,
        cost_basis_cents=cost_basis_cents,
        status="OPEN",
        realized_gain_cents=None,
        close_date=None,
        wash_window_start=None,
        wash_window_end=None,
    )
    db.tax_lots[lot["id"]] = lot
    account["next_order_sequence"] += 1
    touch(account)
    return ok(serialize(lot), 201)


@bp.post("/sma/accounts/<account_id>/suspend")
@require_roles(ROLE_COMPLIANCE_OFFICER)
def suspend_account(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    if account["implementation_status"] not in ("SYNCED", "DRIFTED", "PENDING_IMPLEMENTATION"):
        raise ApiError("ERR_INVALID_STATE", "The account cannot be suspended from its current state.")
    account["implementation_status"] = "SUSPENDED"
    touch(account)
    return ok(serialize_account(account))


@bp.post("/sma/accounts/<account_id>/reinstate")
@require_roles(ROLE_COMPLIANCE_OFFICER)
def reinstate_account(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    guard_not_written_off(account)
    if account["implementation_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED account may be reinstated.")
    if account.get("pending_model_version_id"):
        account["implementation_status"] = "PENDING_IMPLEMENTATION"
    else:
        account["implementation_status"] = "SYNCED"
    touch(account)
    return ok(serialize_account(account))


@bp.post("/sma/accounts/<account_id>/implementations")
@require_roles(ROLE_SPONSOR_OPERATOR)
def implement_account(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    sponsor_scope(account["sponsor_id"])
    guard_not_suspended(account)
    guard_not_written_off(account)

    if account["implementation_status"] != "PENDING_IMPLEMENTATION":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an account in PENDING_IMPLEMENTATION may be implemented.")

    pending_id = account.get("pending_model_version_id")
    now = clock()

    # Rung 12: an ACTIVE distribution covering the clock must link sponsor -> version.
    covered = False
    for dist in db.sponsor_distributions.values():
        if dist["sponsor_id"] != account["sponsor_id"]:
            continue
        if dist["model_version_id"] != pending_id:
            continue
        if dist["status"] != "ACTIVE":
            continue
        if dist["effective_from"] > now:
            continue
        if dist["effective_until"] is not None and now >= dist["effective_until"]:
            continue
        covered = True
        break
    if not covered:
        raise ApiError("ERR_DISTRIBUTION_NOT_ACTIVE",
                       "No ACTIVE distribution covers the current instant for this account.")

    # Rung 24: sponsor minimum.
    sponsor = db.sponsors.get(account["sponsor_id"])
    if market_value_cents(account) < (sponsor["min_account_value_cents"] if sponsor else 0):
        raise ApiError("ERR_BELOW_SPONSOR_MINIMUM",
                       "The account's market value is below the sponsor's minimum.")

    version = db.model_versions.get(pending_id)
    orders = generate_trade_orders(account, version, "IMPLEMENTATION")

    account["current_model_version_id"] = pending_id
    account["pending_model_version_id"] = None
    notified_at = account.get("notified_at")
    account["last_implementation_lag_days"] = (
        whole_days(notified_at, now) if notified_at is not None else 0)
    deadline = account.get("implementation_deadline")
    account["implemented_late"] = bool(deadline is not None and now > deadline)
    account["implementation_status"] = "SYNCED"
    touch(account)

    return ok({
        "account_id": account["id"],
        "current_model_version_id": account["current_model_version_id"],
        "generated_order_count": len(orders),
        "trade_order_ids": [o["id"] for o in orders],
        "last_implementation_lag_days": account["last_implementation_lag_days"],
        "implemented_late": account["implemented_late"],
    })


@bp.post("/sma/accounts/<account_id>/drift-evaluations")
@require_roles(ROLE_SPONSOR_OPERATOR, ROLE_PORTFOLIO_MANAGER)
def evaluate_account_drift(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    sponsor_scope(account["sponsor_id"])
    body = body_json()
    basis = v_enum(body, "basis", DRIFT_BASES, required=False, default=None)
    guard_not_suspended(account)
    guard_not_written_off(account)

    if basis is None:
        basis = account["drift_basis"]

    drift_bps = evaluate_drift(account, basis)
    account["drift_bps"] = drift_bps
    account["drift_basis_used"] = basis
    account["drift_evaluated_at"] = clock()

    model = db.models.get(account["model_id"])
    threshold = model["drift_threshold_bps"] if model else 0
    if account["implementation_status"] == "SYNCED" and drift_bps >= threshold:
        account["implementation_status"] = "DRIFTED"
    elif account["implementation_status"] == "DRIFTED" and drift_bps < threshold:
        account["implementation_status"] = "SYNCED"
    touch(account)
    return ok(serialize_account(account))


@bp.post("/sma/accounts/<account_id>/rebalances")
@require_roles(ROLE_SPONSOR_OPERATOR)
def rebalance_account(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    sponsor_scope(account["sponsor_id"])
    guard_not_suspended(account)
    guard_not_written_off(account)

    if account["implementation_status"] != "DRIFTED":
        raise ApiError("ERR_ACCOUNT_NOT_DRIFTED", "Only a DRIFTED account may be rebalanced.")
    current_id = account.get("current_model_version_id")
    if not current_id:
        raise ApiError("ERR_INVALID_STATE", "The account has no current model version.")

    version = db.model_versions.get(current_id)
    orders = generate_trade_orders(account, version, "REBALANCE")
    touch(account)

    return ok({
        "account_id": account["id"],
        "model_version_id": current_id,
        "generated_order_count": len(orders),
        "trade_order_ids": [o["id"] for o in orders],
    })


@bp.post("/sma/accounts/<account_id>/performance-observations")
@require_roles(ROLE_SPONSOR_OPERATOR, ROLE_PLATFORM_ADMIN)
def record_performance(account_id):
    account = lookup(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    sponsor_scope(account["sponsor_id"])
    body = body_json()
    period_end = v_dt(body, "period_end")
    gross_return_bps = v_int(body, "gross_return_bps")
    ending_value_cents = v_int(body, "ending_value_cents", minimum=0)

    account["latest_return_bps"] = gross_return_bps
    account["latest_return_period_end"] = period_end
    account["latest_ending_value_cents"] = ending_value_cents
    touch(account)
    return ok(serialize_account(account))


# ------------------------------------------------------- AccountRestriction --
@bp.post("/sma/account-restrictions")
@require_roles(ROLE_COMPLIANCE_OFFICER)
def create_restriction():
    body = body_json()

    account = None
    security = None
    if isinstance(body.get("account_id"), str):
        account = lookup(db.accounts, body["account_id"], "ERR_ACCOUNT_NOT_FOUND")
    if isinstance(body.get("security_id"), str):
        security = lookup(db.securities, body["security_id"], "ERR_SECURITY_NOT_FOUND")

    v_str(body, "account_id")
    v_str(body, "security_id")
    restriction_type = v_enum(body, "restriction_type", RESTRICTION_TYPES)
    max_position_bps = v_int(body, "max_position_bps", required=False,
                             minimum=1, maximum=10000, default=None)
    if restriction_type == "MAX_POSITION":
        if max_position_bps is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "'max_position_bps' is required for a MAX_POSITION restriction.")
    elif max_position_bps is not None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "'max_position_bps' is only valid for a MAX_POSITION restriction.")

    row = new_row(account_id=account["id"], security_id=security["id"],
                  restriction_type=restriction_type,
                  max_position_bps=max_position_bps,
                  status="ACTIVE", lifted_at=None)
    db.account_restrictions[row["id"]] = row
    touch(account)
    return ok(serialize(row), 201)


@bp.get("/sma/account-restrictions/<account_restriction_id>")
@require_roles(*READ_ROLES)
def get_restriction(account_restriction_id):
    row = lookup(db.account_restrictions, account_restriction_id, "ERR_RESTRICTION_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/sma/account-restrictions")
@require_roles(*READ_ROLES)
def list_restrictions():
    rows = qfilter(db.account_restrictions.values(),
                   account_id=arg("account_id"),
                   security_id=arg("security_id"),
                   status=arg("status"))
    return paged(rows)


@bp.post("/sma/account-restrictions/<account_restriction_id>/lift")
@require_roles(ROLE_COMPLIANCE_OFFICER)
def lift_restriction(account_restriction_id):
    row = lookup(db.account_restrictions, account_restriction_id, "ERR_RESTRICTION_NOT_FOUND")
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE restriction may be lifted.")
    row["status"] = "LIFTED"
    row["lifted_at"] = clock()
    touch(row)
    account = db.accounts.get(row["account_id"])
    if account is not None:
        touch(account)
    return ok(serialize(row))
