"""Affiliate invoices: issue, pay, dispute cycle with credit memos."""

from flask import Blueprint, request

import db
import domain
from errors import ApiError
from response import ok, listing
from validation import (
    require_roles, ALL_ROLES, body, check_allowed, req_string, opt_int,
    pagination,
)

bp = Blueprint("invoices", __name__, url_prefix="/library")

DISPUTE_OUTCOMES = ("OPEN", "RESOLVE_UPHELD", "RESOLVE_OVERRULED")


def get_invoice_or_404(iid):
    inv = db.invoices.get(iid)
    if inv is None:
        raise ApiError(404, "ERR_INVOICE_NOT_FOUND",
                       "Referenced invoice id does not exist")
    return inv


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require_roles(*ALL_ROLES)
    return ok(domain.ser_invoice(get_invoice_or_404(iid)))


@bp.get("/invoices")
def list_invoices():
    uid, role = require_roles(*ALL_ROLES)
    limit, offset = pagination()
    f_aff = request.args.get("affiliate_id")
    f_wave = request.args.get("wave_id")
    f_status = request.args.get("status")
    if role == "AffiliateCoordinator":
        if f_aff is not None and f_aff != uid:
            raise ApiError(403, "ERR_FORBIDDEN",
                           "Coordinator may only list their own affiliate's invoices")
        f_aff = uid
    rows = [i for i in db.invoices.values()
            if (f_aff is None or i["affiliate_id"] == f_aff)
            and (f_wave is None or i["wave_id"] == f_wave)
            and (f_status is None or i["status"] == f_status)]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return listing([domain.ser_invoice(i) for i in page], limit, offset, total)


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    require_roles("PlatformAdmin")
    data = body()
    check_allowed(data, set())
    inv = get_invoice_or_404(iid)
    if inv["status"] != "DRAFT":
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only a DRAFT invoice can be issued")
    inv["status"] = "ISSUED"
    db.touch(inv)
    return ok(domain.ser_invoice(inv))


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    uid, role = require_roles("AffiliateCoordinator")
    data = body()
    check_allowed(data, set())
    inv = get_invoice_or_404(iid)
    if uid != inv["affiliate_id"]:
        raise ApiError(403, "ERR_FORBIDDEN",
                       "Coordinator may only pay their own affiliate's invoices")
    if inv["status"] not in ("ISSUED", "ADJUSTED"):
        raise ApiError(409, "ERR_INVALID_STATE",
                       "Only an ISSUED or ADJUSTED invoice can be paid")
    inv["status"] = "PAID"
    db.touch(inv)
    return ok(domain.ser_invoice(inv))


@bp.post("/invoices/<iid>/dispute")
def dispute_invoice(iid):
    uid, role = require_roles("AffiliateCoordinator", "PlatformAdmin")
    inv = get_invoice_or_404(iid)
    data = body()
    check_allowed(data, {"outcome", "credit_amount_cents"})
    outcome = req_string(data, "outcome")
    if outcome not in DISPUTE_OUTCOMES:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "outcome must be OPEN, RESOLVE_UPHELD or RESOLVE_OVERRULED")
    credit = opt_int(data, "credit_amount_cents", None)
    # Role-split outcomes plus coordinator ownership.
    if role == "AffiliateCoordinator":
        if outcome != "OPEN":
            raise ApiError(403, "ERR_FORBIDDEN",
                           "RESOLVE_* outcomes are PlatformAdmin-only")
        if uid != inv["affiliate_id"]:
            raise ApiError(403, "ERR_FORBIDDEN",
                           "Coordinator may only dispute their own affiliate's invoices")
    else:
        if outcome == "OPEN":
            raise ApiError(403, "ERR_FORBIDDEN",
                           "The OPEN outcome is coordinator-only")
    if outcome == "OPEN":
        if inv["status"] != "ISSUED":
            raise ApiError(409, "ERR_INVALID_STATE",
                           "Only an ISSUED invoice can be disputed")
        inv["status"] = "DISPUTED"
    elif outcome == "RESOLVE_OVERRULED":
        if inv["status"] != "DISPUTED":
            raise ApiError(409, "ERR_INVALID_STATE",
                           "Only a DISPUTED invoice can be resolved")
        inv["status"] = "ISSUED"
    else:  # RESOLVE_UPHELD
        if inv["status"] != "DISPUTED":
            raise ApiError(409, "ERR_INVALID_STATE",
                           "Only a DISPUTED invoice can be resolved")
        if credit is None or credit <= 0 or credit > inv["gross_cents"]:
            raise ApiError(422, "ERR_CREDIT_EXCEEDS_GROSS",
                           "credit_amount_cents must be > 0 and <= gross_cents")
        inv["credit_memo_cents"] = credit
        inv["local_share_cents"] = (inv["gross_cents"] - inv["state_share_cents"]
                                    - credit)
        inv["status"] = "ADJUSTED"
    db.touch(inv)
    return ok(domain.ser_invoice(inv))
