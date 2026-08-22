"""Security, Sponsor and Model routes (PRD 3.1)."""

from flask import Blueprint, g

from core import (
    ApiError, READ_ROLES, ROLE_PLATFORM_ADMIN, ROLE_PORTFOLIO_MANAGER,
    body_json, db, lookup, new_row, ok, require_roles, serialize, touch,
    v_bool, v_int, v_str,
)
from entities import ASSET_CLASSES

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------- Security --
@bp.post("/sma/securities")
@require_roles(ROLE_PLATFORM_ADMIN)
def create_security():
    body = body_json()
    ticker = v_str(body, "ticker", min_len=1, max_len=8, pattern=r"[A-Z]+")
    name = v_str(body, "name")
    asset_class = v_str(body, "asset_class")
    if asset_class not in ASSET_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'asset_class' is not a member of the enum.")
    last_price_cents = v_int(body, "last_price_cents", minimum=1)
    restricted_globally = v_bool(body, "restricted_globally", required=False, default=False)

    for existing in db.securities.values():
        if existing["ticker"] == ticker:
            raise ApiError("ERR_DUPLICATE_KEY", "Ticker '%s' is already registered." % ticker)

    row = new_row(ticker=ticker, name=name, asset_class=asset_class,
                  last_price_cents=last_price_cents,
                  restricted_globally=restricted_globally)
    db.securities[row["id"]] = row
    return ok(serialize(row), 201)


@bp.get("/sma/securities/<security_id>")
@require_roles(*READ_ROLES)
def get_security(security_id):
    row = lookup(db.securities, security_id, "ERR_SECURITY_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/sma/securities/<security_id>/price")
@require_roles(ROLE_PLATFORM_ADMIN)
def reprice_security(security_id):
    row = lookup(db.securities, security_id, "ERR_SECURITY_NOT_FOUND")
    body = body_json()
    row["last_price_cents"] = v_int(body, "last_price_cents", minimum=1)
    touch(row)
    return ok(serialize(row))


# ----------------------------------------------------------------- Sponsor --
@bp.post("/sma/sponsors")
@require_roles(ROLE_PLATFORM_ADMIN)
def create_sponsor():
    body = body_json()
    name = v_str(body, "name")
    platform_code = v_str(body, "platform_code", min_len=2, max_len=12)
    revenue_share_bps = v_int(body, "revenue_share_bps", minimum=0, maximum=9000)
    implementation_lag_days = v_int(body, "implementation_lag_days", required=False,
                                    minimum=0, maximum=10, default=2)
    min_account_value_cents = v_int(body, "min_account_value_cents", required=False,
                                    minimum=0, default=0)

    for existing in db.sponsors.values():
        if existing["platform_code"] == platform_code:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "Platform code '%s' is already registered." % platform_code)

    row = new_row(name=name, platform_code=platform_code,
                  revenue_share_bps=revenue_share_bps,
                  implementation_lag_days=implementation_lag_days,
                  min_account_value_cents=min_account_value_cents,
                  account_count=0)
    db.sponsors[row["id"]] = row
    return ok(serialize(row), 201)


@bp.get("/sma/sponsors/<sponsor_id>")
@require_roles(*READ_ROLES)
def get_sponsor(sponsor_id):
    row = lookup(db.sponsors, sponsor_id, "ERR_SPONSOR_NOT_FOUND")
    return ok(serialize(row))


# ------------------------------------------------------------------- Model --
@bp.post("/sma/models")
@require_roles(ROLE_PORTFOLIO_MANAGER)
def create_model():
    body = body_json()
    manager_name = v_str(body, "manager_name")
    name = v_str(body, "name")
    strategy_code = v_str(body, "strategy_code", min_len=2, max_len=12)
    asset_class = v_str(body, "asset_class")
    if asset_class not in ASSET_CLASSES:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'asset_class' is not a member of the enum.")
    base_fee_bps = v_int(body, "base_fee_bps", minimum=1, maximum=500)
    drift_threshold_bps = v_int(body, "drift_threshold_bps", required=False,
                                minimum=1, maximum=10000, default=300)

    for existing in db.models.values():
        if existing["strategy_code"] == strategy_code:
            raise ApiError("ERR_DUPLICATE_KEY",
                           "Strategy code '%s' is already registered." % strategy_code)

    row = new_row(manager_name=manager_name, name=name, strategy_code=strategy_code,
                  asset_class=asset_class, base_fee_bps=base_fee_bps,
                  drift_threshold_bps=drift_threshold_bps,
                  published_model_version_id=None, version_count=0)
    db.models[row["id"]] = row
    return ok(serialize(row), 201)


@bp.get("/sma/models/<model_id>")
@require_roles(*READ_ROLES)
def get_model(model_id):
    row = lookup(db.models, model_id, "ERR_MODEL_NOT_FOUND")
    return ok(serialize(row))
