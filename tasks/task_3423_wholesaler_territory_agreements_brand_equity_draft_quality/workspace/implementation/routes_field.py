"""Retail accounts, draft-quality audits, and point-of-sale grants
(§3.6, §3.7)."""

from flask import Blueprint, request

import calc
import cascades
import clock
import db
from auth import (ALL_ROLES, ROLE_BREWER_ADMIN, ROLE_DRAFT_AUDITOR,
                  require_roles)
from db import touch
from envelope import created, ok, paginate
from errors import (ApiError, ERR_ACCOUNT_NOT_ACTIVE, ERR_AUDIT_TOO_SOON,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE_TRANSITION,
                    ERR_NOT_FOUND, ERR_POS_VALUE_CAP_EXCEEDED)
from validate import field, get_body, validate_body

bp = Blueprint("field", __name__)


@bp.route("/retail-accounts", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def create_account(user_id, caller_role):
    data, _ = validate_body(get_body(), {
        "name": field("string", required=True),
        "state_code": field("string", required=True),
        "serving_wholesaler_id": field("string", required=True),
        "line_cleaning_frequency_days": field("integer", default=14),
    })
    if data["serving_wholesaler_id"] not in db.wholesalers:
        raise ApiError(ERR_NOT_FOUND, "Serving wholesaler not found", 404)
    account = db.stamped()
    account.update({
        "name": data["name"],
        "state_code": data["state_code"],
        "serving_wholesaler_id": data["serving_wholesaler_id"],
        "line_cleaning_frequency_days": data["line_cleaning_frequency_days"],
        "status": "ACTIVE",
        "last_audit_at": None,
    })
    db.accounts[account["id"]] = account
    return created(account)


@bp.route("/retail-accounts/<aid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_account(aid, user_id, caller_role):
    account = db.accounts.get(aid)
    if account is None:
        raise ApiError(ERR_NOT_FOUND, "Retail account not found", 404)
    return ok(account)


@bp.route("/retail-accounts/<aid>/draft-audits", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_account_audits(aid, user_id, caller_role):
    if aid not in db.accounts:
        raise ApiError(ERR_NOT_FOUND, "Retail account not found", 404)
    rows = [a for a in db.audits.values() if a["account_id"] == aid]
    return paginate(rows)


def _validate_kegs(kegs):
    cleaned = []
    for entry in kegs:
        if not isinstance(entry, dict):
            raise ApiError(ERR_INVALID_REQUEST, "kegs entries must be objects", 400)
        brand = entry.get("brand_code")
        filled = entry.get("filled_at")
        volume = entry.get("volume_bbl")
        if not isinstance(brand, str):
            raise ApiError(ERR_INVALID_REQUEST,
                           "kegs entries require a brand_code string", 400)
        if not isinstance(filled, str):
            raise ApiError(ERR_INVALID_REQUEST,
                           "kegs entries require a filled_at timestamp", 400)
        try:
            filled_dt = clock.parse_iso(filled)
        except Exception:
            raise ApiError(ERR_INVALID_REQUEST,
                           "kegs filled_at must be an ISO-8601 timestamp", 400)
        if (not isinstance(volume, (int, float))) or isinstance(volume, bool):
            raise ApiError(ERR_INVALID_REQUEST,
                           "kegs entries require a numeric volume_bbl", 400)
        cleaned.append({
            "brand_code": brand,
            "filled_at": clock.format_iso(filled_dt),
            "volume_bbl": volume,
        })
    return cleaned


@bp.route("/draft-audits", methods=["POST"])
@require_roles(ROLE_DRAFT_AUDITOR)
def create_audit(user_id, caller_role):
    data, _ = validate_body(get_body(), {
        "account_id": field("string", required=True),
        "conducted_at": field("datetime", required=True),
        "line_cleaning_last_at": field("datetime", required=True),
        "kegs": field("array", required=True),
    })
    kegs = _validate_kegs(data["kegs"])
    account = db.accounts.get(data["account_id"])
    if account is None:
        raise ApiError(ERR_NOT_FOUND, "Retail account not found", 404)
    conducted_at = clock.parse_iso(data["conducted_at"])
    line_cleaning_last_at = clock.parse_iso(data["line_cleaning_last_at"])
    if account["last_audit_at"] is not None:
        anchor = clock.parse_iso(account["last_audit_at"])
        gap_seconds = (conducted_at - anchor).total_seconds()
        if gap_seconds < calc.MIN_AUDIT_GAP_SECONDS:
            raise ApiError(ERR_AUDIT_TOO_SOON,
                           "Accepted audits on one account must be at least "
                           "7 days apart", 409)
    stale_keg_count = 0
    critical_keg_flag = False
    for keg in kegs:
        age_days = calc.whole_days(clock.parse_iso(keg["filled_at"]),
                                   conducted_at)
        if age_days >= calc.STALE_AGE_DAYS:
            stale_keg_count += 1
        if age_days >= calc.CRITICAL_AGE_DAYS:
            critical_keg_flag = True
    gap_days = calc.whole_days(line_cleaning_last_at, conducted_at)
    frequency = account["line_cleaning_frequency_days"]
    line_cleaning_overdue = gap_days > frequency
    critically_overdue = gap_days > 2 * frequency
    if critical_keg_flag or critically_overdue:
        result = "CRITICAL_FAIL"
    elif stale_keg_count >= 1 or line_cleaning_overdue:
        result = "FAIL"
    else:
        result = "PASS"
    audit = {
        "id": db.new_id(),
        "created_at": clock.now_iso(),
        "account_id": account["id"],
        "conducted_at": clock.format_iso(conducted_at),
        "line_cleaning_last_at": clock.format_iso(line_cleaning_last_at),
        "kegs": kegs,
        "stale_keg_count": stale_keg_count,
        "critical_keg_flag": critical_keg_flag,
        "line_cleaning_overdue": line_cleaning_overdue,
        "result": result,
    }
    db.audits[audit["id"]] = audit
    wholesaler = db.wholesalers.get(account["serving_wholesaler_id"])
    if result == "CRITICAL_FAIL" and account["status"] == "ACTIVE":
        account["status"] = "SERVICE_SUSPENDED"
        touch(account)
        if wholesaler is not None:
            wholesaler["suspended_account_count"] += 1
            cascades.maybe_suspend_wholesaler(wholesaler)
            touch(wholesaler)
    elif result == "PASS":
        if account["status"] == "SERVICE_SUSPENDED":
            account["status"] = "ACTIVE"
            if wholesaler is not None:
                wholesaler["suspended_account_count"] -= 1
                touch(wholesaler)
        # Only a passing audit advances the last_audit_at anchor (§3.6).
        account["last_audit_at"] = audit["conducted_at"]
        touch(account)
    return created(audit)


@bp.route("/retail-accounts/<aid>/pos-grants", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_account_grants(aid, user_id, caller_role):
    if aid not in db.accounts:
        raise ApiError(ERR_NOT_FOUND, "Retail account not found", 404)
    rows = [g for g in db.pos_grants.values() if g["account_id"] == aid]
    return paginate(rows, status_filter=request.args.get("status"))


@bp.route("/pos-grants", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def create_pos_grant(user_id, caller_role):
    data, _ = validate_body(get_body(), {
        "account_id": field("string", required=True),
        "item_description": field("string", required=True),
        "value_cents": field("integer", required=True),
    })
    account = db.accounts.get(data["account_id"])
    if account is None:
        raise ApiError(ERR_NOT_FOUND, "Retail account not found", 404)
    if account["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE,
                       "POS grants require an ACTIVE account", 409)
    current_year = clock.now().year
    ytd = sum(g["value_cents"] for g in db.pos_grants.values()
              if g["account_id"] == account["id"]
              and g["status"] == "ISSUED"
              and g["granted_year"] == current_year)
    cap = calc.pos_cap_cents(account["state_code"])
    if ytd + data["value_cents"] > cap:
        raise ApiError(ERR_POS_VALUE_CAP_EXCEEDED,
                       "Grant would exceed the account's annual POS value cap",
                       422)
    grant = db.stamped()
    grant.update({
        "account_id": account["id"],
        "item_description": data["item_description"],
        "value_cents": data["value_cents"],
        "status": "ISSUED",
        "granted_year": current_year,
        "voided_at": None,
    })
    db.pos_grants[grant["id"]] = grant
    return created(grant)


@bp.route("/pos-grants/<gid>/void", methods=["POST"])
@require_roles(ROLE_BREWER_ADMIN)
def void_pos_grant(gid, user_id, caller_role):
    grant = db.pos_grants.get(gid)
    if grant is None:
        raise ApiError(ERR_NOT_FOUND, "POS grant not found", 404)
    if grant["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION,
                       "Voiding requires an ISSUED grant", 409)
    grant["status"] = "VOIDED"
    grant["voided_at"] = clock.now_iso()
    touch(grant)
    return ok(grant)
