"""Lease agreements: security, the memorandum, and the rent-invoice parent
(PRD sections 3.7 and 3.9).

The two lease dimensions are genuinely independent: rent_status may reach
CURRENT while recording_status is still UNRECORDED, and vice versa.
"""

from flask import Blueprint

import access
import calc
import cascades
import serializers as ser
import validation as v
from auth import (
    ALL_ROLES,
    PAYMENT_ADMINISTRATOR,
    PORTFOLIO_MANAGER,
    require,
)
from envelope import ok, ok_list
from errors import (
    ERR_ALREADY_RECORDED,
    ERR_DUPLICATE_INVOICE_PERIOD,
    ERR_INVALID_STATE,
    ERR_SECURITY_NOT_POSTED,
    ERR_SECURITY_OVERPOSTED,
    ERR_STALE_LEASE_VERSION,
    ERR_TITLE_CURATIVE_BLOCKING,
    ERR_W9_MISSING,
    fail,
)
from store import db, insert, now, ordered, touch
from util import D, num

bp = Blueprint("leases", __name__, url_prefix="/land-origination")

OCCUPIED_PERIOD_STATUSES = ("DRAFT", "ISSUED", "PAID")


# ------------------------------------------------------------------- reads
@bp.get("/leases/<lease_id>")
@require(*ALL_ROLES)
def get_lease(lease_id):
    row = access.lease(lease_id)
    access.own(row["landowner_id"])
    return ok(ser.lease(row))


@bp.get("/leases")
@require(*ALL_ROLES)
def list_leases():
    limit, offset = v.pagination()
    rows = ordered(db.leases.values())
    rows = access.scope_rows(rows, lambda r: r["landowner_id"])
    rows = v.apply_filters(rows, [
        ("option_agreement_id", v.query_str("option_agreement_id")),
        ("parcel_id", v.query_str("parcel_id")),
        ("landowner_id", v.query_str("landowner_id")),
        ("rent_status", v.query_str("rent_status")),
        ("recording_status", v.query_str("recording_status")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.lease, page), limit, offset, total)


@bp.get("/leases/<lease_id>/rent-projection")
@require(PORTFOLIO_MANAGER, PAYMENT_ADMINISTRATOR)
def rent_projection(lease_id):
    row = access.lease(lease_id)
    period_year = v.query_req_int("period_year", lo=1)
    production_mwh = v.query_num("production_mwh", D("0"), lo=0)

    option = db.options.get(row["option_agreement_id"])
    parcel = db.parcels.get(row["parcel_id"])
    provisional_basis = D(parcel["gross_acres"]) if parcel else D("0.00")
    final_basis = D(parcel["buildable_acres"]) if parcel else D("0.00")

    _, _, provisional_gross = calc.rent_amounts(
        option, provisional_basis, period_year, production_mwh, "PROVISIONAL")
    final_per_acre, final_royalty, final_gross = calc.rent_amounts(
        option, final_basis, period_year, production_mwh, "FINAL_AS_BUILT")

    return ok({
        "lease_agreement_id": row["id"],
        "period_year": int(period_year),
        "provisional_acre_basis": num(provisional_basis),
        "provisional_gross_rent_cents": int(provisional_gross),
        "final_acre_basis": num(final_basis),
        "final_per_acre_component_cents": int(final_per_acre),
        "final_royalty_component_cents": int(final_royalty),
        "final_gross_rent_cents": int(final_gross),
        "variant_delta_cents": int(final_gross) - int(provisional_gross),
    })


# --------------------------------------------------------------- security
@bp.post("/leases/<lease_id>/post-security")
@require(PAYMENT_ADMINISTRATOR)
def post_security(lease_id):
    row = access.lease(lease_id)
    body = v.json_body()
    amount = v.req_int(body, "amount_cents", lo=0)

    # Over-posting is impossible, so "fully posted" and "exactly posted"
    # coincide (PRD section 3.7).
    if int(row["security_posted_cents"]) + amount > \
            int(row["total_security_required_cents"]):
        fail(ERR_SECURITY_OVERPOSTED)

    row["security_posted_cents"] = int(row["security_posted_cents"]) + amount
    touch(row)
    return ok(ser.lease(row))


# ------------------------------------------------------- the memorandum
@bp.post("/leases/<lease_id>/submit-memo")
@require(PORTFOLIO_MANAGER)
def submit_memo(lease_id):
    row = access.lease(lease_id)
    parcel = db.parcels.get(row["parcel_id"])

    if row["recording_status"] == "RECORDED":
        fail(ERR_ALREADY_RECORDED)
    if row["recording_status"] != "UNRECORDED":
        fail(ERR_INVALID_STATE)
    # Title compliance outranks security, which outranks money (section 2.9).
    if parcel is not None and int(parcel["blocking_curative_open_count"]) > 0:
        fail(ERR_TITLE_CURATIVE_BLOCKING)
    if int(row["security_posted_cents"]) < \
            int(row["total_security_required_cents"]):
        fail(ERR_SECURITY_NOT_POSTED)

    row["recording_status"] = "MEMO_SUBMITTED"
    row["memo_submitted_at"] = now()
    touch(row)
    return ok(ser.lease(row))


@bp.post("/leases/<lease_id>/record-memo")
@require(PORTFOLIO_MANAGER)
def record_memo(lease_id):
    row = access.lease(lease_id)
    body = v.json_body()
    instrument_no = v.req_str(body, "recording_instrument_no", min_len=1,
                              max_len=60)
    parcel = db.parcels.get(row["parcel_id"])
    owner = db.landowners.get(row["landowner_id"])

    if row["recording_status"] == "RECORDED":
        fail(ERR_ALREADY_RECORDED)
    if row["recording_status"] != "MEMO_SUBMITTED":
        fail(ERR_INVALID_STATE)
    if owner is None or not owner["w9_on_file"]:
        fail(ERR_W9_MISSING)

    row["recording_status"] = "RECORDED"
    row["recorded_at"] = now()
    row["recording_instrument_no"] = instrument_no
    touch(row)

    # The parcel reaches its own terminal status only now.
    if parcel is not None and parcel["status"] == "OPTIONED":
        parcel["status"] = "LEASED"
        touch(parcel)
    cascades.sync_landowner_posture(owner)
    return ok(ser.lease(row))


# ------------------------------------------------------ raising a rent invoice
@bp.post("/leases/<lease_id>/rent-invoices")
@require(PAYMENT_ADMINISTRATOR)
def create_rent_invoice(lease_id):
    row = access.lease(lease_id)
    body = v.json_body()
    expected_version = v.req_int(body, "expected_lease_agreement_version")
    # Rung 16 catches period_year < 1 as a 400; a period beyond the 35-year
    # term falls through to rung 37 instead.
    period_year = v.req_int(body, "period_year", lo=1)
    production_mwh = v.opt_num(body, "production_mwh", D("0"), lo=0)

    if int(expected_version) != int(row["version"]):
        fail(ERR_STALE_LEASE_VERSION)
    if period_year > calc.LEASE_TERM_YEARS:
        fail(ERR_DUPLICATE_INVOICE_PERIOD)
    for other in cascades.lease_invoices(row["id"]):
        if int(other["period_year"]) == period_year \
                and other["status"] in OCCUPIED_PERIOD_STATUSES:
            fail(ERR_DUPLICATE_INVOICE_PERIOD)

    option = db.options.get(row["option_agreement_id"])
    parcel = db.parcels.get(row["parcel_id"])
    # The variant is decided once, here, from the lease's recording dimension.
    variant = "FINAL_AS_BUILT" if row["recording_status"] == "RECORDED" \
        else "PROVISIONAL"
    if variant == "PROVISIONAL":
        acre_basis = D(parcel["gross_acres"]) if parcel else D("0.00")
    else:
        acre_basis = D(parcel["buildable_acres"]) if parcel else D("0.00")

    per_acre, royalty, gross = calc.rent_amounts(
        option, acre_basis, period_year, production_mwh, variant)

    invoice = insert("invoices", {
        "lease_agreement_id": row["id"],
        "period_year": period_year,
        "production_mwh": production_mwh,
        "rent_variant": variant,
        "acre_basis": acre_basis,
        "per_acre_component_cents": per_acre,
        "royalty_component_cents": royalty,
        "gross_rent_cents": gross,
        "issued_at": None,
        "due_at": None,
        "paid_at": None,
        "paid_amount_cents": None,
        "void_reason": None,
        "status": "DRAFT",
    })
    # The lease is the concurrency parent (PRD section 2.7).
    touch(row)
    return ok(ser.invoice(invoice), 201)
