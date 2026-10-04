"""Dues endpoints: periods (create/list/get/bill/reconcile) and invoices
(list/get/pay/waive) + flat reads."""

from flask import Blueprint, request

import calcs
import services
from auth import require_roles, require_member_actor
from db import store, now, _parse_iso
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
                    ERR_INVALID_STATE, ERR_TENDER_MISMATCH)
from helpers import (body, mint_common, touch, get_association, get_member,
                     get_dues_period, get_invoice, page)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("dues", __name__)


# ------------------------------ periods ------------------------------------

@bp.route("/mls/associations/<assoc_id>/dues-periods", methods=["POST"])
def create_period(assoc_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("year", "period_start_date", "due_date", "grace_end_date",
              "amount_cents"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    if isinstance(data["year"], bool) or not isinstance(data["year"], int):
        raise_err(ERR_INVALID_REQUEST, "year must be an integer")
    amount = data["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be an integer >= 0")
    for f in ("period_start_date", "due_date", "grace_end_date"):
        from helpers import parse_dt
        parse_dt(data[f], f)
    period = {
        "association_id": assoc_id,
        "year": data["year"],
        "period_start_date": data["period_start_date"],
        "due_date": data["due_date"],
        "grace_end_date": data["grace_end_date"],
        "amount_cents": amount,
        "status": "OPEN",
    }
    mint_common(period)
    store.dues_periods[period["id"]] = period
    return success_object(period, 201)


@bp.route("/mls/associations/<assoc_id>/dues-periods", methods=["GET"])
def list_periods(assoc_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    items = [p for p in store.dues_periods.values()
             if p["association_id"] == assoc_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    year = request.args.get("year")
    if year is not None:
        try:
            year_i = int(year)
        except ValueError:
            raise_err(ERR_INVALID_REQUEST, "year must be an integer")
        items = [p for p in items if p["year"] == year_i]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/dues-periods/<period_id>", methods=["GET"])
def get_period_route(assoc_id, period_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    return success_object(get_dues_period(period_id, assoc_id))


@bp.route("/mls/dues-periods/<period_id>", methods=["GET"])
def flat_get_period(period_id):
    require_roles("AssociationStaff", "Member")
    return success_object(get_dues_period(period_id))


@bp.route("/mls/associations/<assoc_id>/dues-periods/<period_id>/bill",
          methods=["POST"])
def bill_period(assoc_id, period_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    period = get_dues_period(period_id, assoc_id)
    check_not_merged(assoc)
    data = body()
    expected = data.get("expected_dues_period_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST,
                  "Missing or invalid 'expected_dues_period_version'")
    if expected != period["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_dues_period_version does not match current version")
    if period["status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "Only an OPEN period may be billed")

    issued_at = now()
    for member in list(store.members.values()):
        if member["association_id"] != assoc_id:
            continue
        if member["membership_state"] != "ACTIVE":
            continue
        # consolidated-member variant: skip members who already hold any
        # invoice for the same calendar year (from any association).
        has_year_invoice = any(
            (lambda p: p is not None and p["year"] == period["year"])(
                store.dues_periods.get(i["dues_period_id"]))
            for i in store.dues_invoices.values()
            if i["member_id"] == member["id"])
        if has_year_invoice:
            continue
        (base, days_overdue, late_fee, credit_applied,
         amount_due) = calcs.compute_invoice_amounts(assoc, period, member,
                                                     issued_at)
        member["sanction_credit_balance_cents"] -= credit_applied
        touch(member)
        invoice = {
            "dues_period_id": period["id"],
            "member_id": member["id"],
            "base_amount_cents": base,
            "days_overdue_at_issue": days_overdue,
            "late_fee_cents": late_fee,
            "credit_applied_cents": credit_applied,
            "amount_due_cents": amount_due,
            "status": "PENDING",
            "paid_at": None,
        }
        mint_common(invoice)
        store.dues_invoices[invoice["id"]] = invoice

    period["status"] = "BILLED"
    touch(period)
    return success_object(period)


@bp.route("/mls/associations/<assoc_id>/dues-periods/<period_id>/reconcile",
          methods=["POST"])
def reconcile_period(assoc_id, period_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    period = get_dues_period(period_id, assoc_id)
    check_not_merged(assoc)
    if period["status"] != "BILLED":
        raise_err(ERR_INVALID_STATE, "Only a BILLED period may be reconciled")
    grace_end = _parse_iso(period["grace_end_date"])
    # permitted only once the current logical date is later than grace_end_date
    # (suspension fires at 00:00:00 on grace_end_date + 1)
    from datetime import timedelta
    if now() < (grace_end + timedelta(days=1)).replace(hour=0, minute=0,
                                                       second=0, microsecond=0):
        raise_err(ERR_INVALID_STATE,
                  "Reconcile requires the current logical date to be later than grace_end_date")
    for invoice in list(store.dues_invoices.values()):
        if invoice["dues_period_id"] != period["id"]:
            continue
        if invoice["status"] != "PENDING":
            continue
        member = store.members.get(invoice["member_id"])
        if member is not None and member["membership_state"] == "ACTIVE":
            services.suspend_member(member, trigger_grace_end_date=grace_end)
    period["status"] = "RECONCILED"
    touch(period)
    return success_object(period)


# ------------------------------ invoices -----------------------------------

@bp.route("/mls/associations/<assoc_id>/dues-invoices", methods=["GET"])
def list_invoices(assoc_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    period_ids = {p["id"] for p in store.dues_periods.values()
                  if p["association_id"] == assoc_id}
    items = [i for i in store.dues_invoices.values()
             if i["dues_period_id"] in period_ids]
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [i for i in items if i["member_id"] == member_id]
    period_id = request.args.get("dues_period_id")
    if period_id is not None:
        items = [i for i in items if i["dues_period_id"] == period_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/associations/<assoc_id>/dues-invoices/<invoice_id>",
          methods=["GET"])
def get_invoice_route(assoc_id, invoice_id):
    require_roles("AssociationStaff", "Member")
    get_association(assoc_id)
    return success_object(get_invoice(invoice_id, assoc_id))


@bp.route("/mls/dues-invoices", methods=["GET"])
def flat_list_invoices():
    require_roles("AssociationStaff", "Member")
    items = list(store.dues_invoices.values())
    period_id = request.args.get("dues_period_id")
    if period_id is not None:
        items = [i for i in items if i["dues_period_id"] == period_id]
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [i for i in items if i["member_id"] == member_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


@bp.route("/mls/dues-invoices/<invoice_id>", methods=["GET"])
def flat_get_invoice(invoice_id):
    require_roles("AssociationStaff", "Member")
    return success_object(get_invoice(invoice_id))


@bp.route("/mls/associations/<assoc_id>/dues-invoices/<invoice_id>/pay",
          methods=["POST"])
def pay_invoice(assoc_id, invoice_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    invoice = get_invoice(invoice_id, assoc_id)
    check_not_merged(assoc)
    require_member_actor(user_id, invoice["member_id"])
    if invoice["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING invoice may be paid")
    data = body()
    tender = data.get("tender_cents")
    if tender is None or isinstance(tender, bool) or not isinstance(tender, int):
        raise_err(ERR_INVALID_REQUEST, "tender_cents must be an integer")
    if tender != invoice["amount_due_cents"]:
        raise_err(ERR_TENDER_MISMATCH,
                  "tender_cents must equal amount_due_cents")
    invoice["status"] = "PAID"
    from helpers import now_iso_str
    invoice["paid_at"] = now_iso_str()
    touch(invoice)
    member = store.members.get(invoice["member_id"])
    if member is not None:
        services.maybe_reinstate_after_settlement(member)
    return success_object(invoice)


@bp.route("/mls/associations/<assoc_id>/dues-invoices/<invoice_id>/waive",
          methods=["POST"])
def waive_invoice(assoc_id, invoice_id):
    require_roles("AssociationStaff")
    assoc = get_association(assoc_id)
    invoice = get_invoice(invoice_id, assoc_id)
    check_not_merged(assoc)
    if invoice["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING invoice may be waived")
    invoice["status"] = "WAIVED"
    touch(invoice)
    member = store.members.get(invoice["member_id"])
    if member is not None:
        services.maybe_reinstate_after_settlement(member)
    return success_object(invoice)
