"""Routes: accounts, subscriber lines, subscriber-line lifecycle."""

from flask import Blueprint

import calculations
import clock
import errors
import lookups
import middleware
import models
import response
import storage

bp = Blueprint("lines", __name__, url_prefix="/portability")

ACCOUNT_READERS = ("PlatformAdmin", "CustomerService", "Customer")
LINE_READERS = ("PlatformAdmin", "CustomerService", "CreditAnalyst", "Customer")


# ---------------------------------------------------------------------------
@bp.post("/accounts")
@middleware.require_roles("PlatformAdmin")
def create_account(caller):
    data = middleware.body()
    account_type = middleware.required_str(data, "account_type")
    if account_type not in ("FAMILY", "BUSINESS"):
        errors.fail("ERR_INVALID_REQUEST", "account_type must be FAMILY or BUSINESS.")

    tax_id_last4 = middleware.required_str(data, "tax_id_last4")
    if len(tax_id_last4) != 4:
        errors.fail("ERR_INVALID_REQUEST", "tax_id_last4 must be exactly 4 characters.")

    score = middleware.optional_int(data, "payment_history_score", 500)
    if score < 0 or score > 1000:
        errors.fail("ERR_INVALID_REQUEST", "payment_history_score must be between 0 and 1000.")

    account = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "account_type": account_type,
        "account_status": "OPEN",
        "tax_id_last4": tax_id_last4,
        "payment_history_score": score,
        "active_line_count": 0,
        "reserved_mdn_count": 0,
        "deposit_required_cents": 0,
        "existing_deposit_cents": middleware.optional_int(data, "existing_deposit_cents", 0),
        "promo_credited_cents": 0,
        "promo_clawed_back_cents": 0,
        "net_promo_credit_cents": 0,
        "credit_class": "CLASS_C",
    }
    storage.db.add("accounts", account)
    # Derive credit class / deposit on creation (scaffold side effect).
    klass, deposit = calculations.credit_class_determination(score, 0, 0)
    account["credit_class"] = klass
    account["deposit_required_cents"] = deposit
    return response.ok(models.account_out(account), 201)


@bp.get("/accounts/<account_id>")
@middleware.require_roles(*ACCOUNT_READERS)
def get_account(caller, account_id):
    account = lookups.account(account_id)
    middleware.enforce_ownership(caller, account["id"])
    return response.ok(models.account_out(account))


# ---------------------------------------------------------------------------
@bp.post("/subscriber-lines")
@middleware.require_roles("PlatformAdmin")
def create_line(caller):
    data = middleware.body()
    account_id = middleware.required_str(data, "account_id")
    lookups.account(account_id)

    mdn = middleware.required_str(data, "mdn")
    billing_mode = middleware.optional_str(data, "billing_mode", "PREPAID")
    if billing_mode not in ("PREPAID", "POSTPAID"):
        errors.fail("ERR_INVALID_REQUEST", "billing_mode must be PREPAID or POSTPAID.")

    if models.mdn_conflicting(mdn) is not None:
        errors.fail("ERR_MDN_CONFLICT", "That directory number is already held by another line.")

    line = {
        "id": storage.new_id(),
        "created_at": clock.fmt_now(),
        "updated_at": clock.fmt_now(),
        "version": 1,
        "account_id": account_id,
        "mdn": mdn,
        "billing_mode": billing_mode,
        "service_status": "PROVISIONED",
        "number_status": "UNASSIGNED",
        "port_protection_status": "UNPROTECTED",
        "line_opened_at": None,
        "loyalty_tenure_months": 0,
        "retention_cycle_count": 0,
        "promo_eligibility_state": "INELIGIBLE",
        "cancellation_effective_at": None,
    }
    storage.db.add("subscriber_lines", line)
    models.recompute_account_counters(account_id)
    return response.ok(models.line_out(line), 201)


@bp.get("/subscriber-lines/<line_id>")
@middleware.require_roles(*LINE_READERS)
def get_line(caller, line_id):
    line = lookups.line(line_id)
    middleware.enforce_ownership(caller, line["account_id"])
    return response.ok(models.line_out(line))


@bp.get("/accounts/<account_id>/subscriber-lines")
@middleware.require_roles(*LINE_READERS)
def list_account_lines(caller, account_id):
    from flask import request

    lookups.account(account_id)
    middleware.enforce_ownership(caller, account_id)
    rows = [
        line
        for line in storage.db.all("subscriber_lines")
        if line["account_id"] == account_id
    ]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, limit, offset, total = response.paginate(rows, request.args)
    return response.ok_list([models.line_out(r) for r in page], limit, offset, total)


@bp.post("/subscriber-lines/<line_id>/activate")
@middleware.require_roles("PlatformAdmin")
def activate_line(caller, line_id):
    line = lookups.line(line_id)
    if line["service_status"] != "PROVISIONED":
        errors.fail("ERR_INVALID_STATE", "Only a PROVISIONED line can be activated.")

    line["service_status"] = "ACTIVE"
    if line["number_status"] == "UNASSIGNED":
        line["number_status"] = "ASSIGNED"
    if line["line_opened_at"] is None:
        line["line_opened_at"] = clock.fmt_now()
    models.recompute_line_tenure(line)
    models.touch(line)
    models.recompute_account_counters(line["account_id"])
    return response.ok(models.line_out(line))


@bp.post("/subscriber-lines/<line_id>/cancel")
@middleware.require_roles("PlatformAdmin", "CustomerService")
def cancel_line(caller, line_id):
    data = middleware.body()
    line = lookups.line(line_id)
    if line["service_status"] == "CANCELLED":
        errors.fail("ERR_INVALID_STATE", "The line is already cancelled.")

    reason_code = data.get("reason_code")
    if reason_code is None or not isinstance(reason_code, str):
        errors.fail("ERR_INVALID_REQUEST", "Field 'reason_code' is required.")

    line["service_status"] = "CANCELLED"
    line["cancellation_effective_at"] = clock.fmt_now()
    models.touch(line)

    cfg = storage.init_system_config()
    grace = cfg["line_cancellation_grace_hours"]
    cfg["last_line_cancellation_deadline"] = clock.fmt(
        clock.add_hours(clock.now(), grace)
    )
    models.touch(cfg)

    models.recompute_account_counters(line["account_id"])
    return response.ok(models.line_out(line))