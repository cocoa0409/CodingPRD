"""Routes: leases, payment records, underwriting reports."""
from flask import Blueprint

import errors
import middleware as mw
import response as resp
import services as svc
from db import store, _parse_iso, wall_now_iso
from helpers import (body, new_id, stamp_new, touch, pagination_args, paginate,
                     req_str, req_int, opt_bool)

bp = Blueprint("leases", __name__)


# ---------------- Leases ----------------

@bp.post("/listings/<lid>/leases")
def create_lease(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Seller")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    data = body()
    rent = req_int(data, "monthly_rent_cents")
    if rent <= 0:
        raise errors.validation("monthly_rent_cents must be > 0")
    lease_start = req_str(data, "lease_start")
    lease_end = req_str(data, "lease_end")
    try:
        start_dt = _parse_iso(lease_start)
        end_dt = _parse_iso(lease_end)
    except (ValueError, TypeError):
        raise errors.validation("lease_start/lease_end must be valid ISO 8601 timestamps")
    if end_dt <= start_dt:
        raise errors.validation("lease_end must be strictly after lease_start")
    deposit = req_int(data, "deposit_cents")
    if deposit < 0:
        raise errors.validation("deposit_cents must be >= 0")
    # half-open interval overlap against existing ACTIVE leases
    for ex in store.leases.values():
        if ex["listing_id"] == lid and ex["status"] == "ACTIVE":
            exs = _parse_iso(ex["lease_start"])
            exe = _parse_iso(ex["lease_end"])
            if start_dt < exe and exs < end_dt:
                raise errors.lease_overlap()
    lease = stamp_new({
        "id": new_id(),
        "listing_id": lid,
        "tenant_alias": req_str(data, "tenant_alias"),
        "monthly_rent_cents": rent,
        "lease_start": lease_start,
        "lease_end": lease_end,
        "deposit_cents": deposit,
        "disclosure_status": "PENDING",
        "status": "ACTIVE",
    })
    store.leases[lease["id"]] = lease
    return resp.created(lease)


@bp.get("/listings/<lid>/leases")
def list_leases(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer")
    if lid not in store.listings:
        raise errors.not_found("Listing not found")
    limit, offset = pagination_args()
    items = [l for l in store.leases.values() if l["listing_id"] == lid]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


@bp.get("/leases/<lease_id>")
def get_lease(lease_id):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "PropertyManager")
    lease = store.leases.get(lease_id)
    if not lease:
        raise errors.not_found("Lease not found")
    return resp.ok(lease)


@bp.post("/leases/<lease_id>/transition")
def lease_transition(lease_id):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Seller")
    data = body()
    action = data.get("action")
    lease = store.leases.get(lease_id)
    if not lease:
        raise errors.not_found("Lease not found")
    listing = store.listings[lease["listing_id"]]

    if action == "DISCLOSE":
        if lease["disclosure_status"] not in ("PENDING", "REDACTED"):
            raise errors.invalid_state(f"DISCLOSE not defined from disclosure_status={lease['disclosure_status']}")
        if lease["status"] != "ACTIVE":
            raise errors.precondition("Lease must be ACTIVE to disclose")
        lease["disclosure_status"] = "DISCLOSED"
        touch(lease)
    elif action == "REDACT":
        if lease["disclosure_status"] != "PENDING":
            raise errors.invalid_state(f"REDACT not defined from disclosure_status={lease['disclosure_status']}")
        if not listing.get("seller_asks_confidential"):
            raise errors.precondition("Listing seller_asks_confidential must be true to redact")
        lease["disclosure_status"] = "REDACTED"
        touch(lease)
    elif action == "TERMINATE":
        if lease["status"] != "ACTIVE":
            raise errors.invalid_state(f"TERMINATE not defined from status={lease['status']}")
        if listing["status"] not in ("DRAFT", "SUBMITTED", "IN_REVIEW"):
            raise errors.precondition("Lease termination is pre-sale only")
        lease["status"] = "TERMINATED"
        touch(lease)
    else:
        raise errors.invalid_state(f"Unknown or inapplicable action {action!r}")
    return resp.ok(lease)


# ---------------- Payment records ----------------

@bp.post("/leases/<lease_id>/payment-records")
def create_payment(lease_id):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Seller", "PropertyManager")
    lease = store.leases.get(lease_id)
    if not lease:
        raise errors.not_found("Lease not found")
    data = body()
    due = req_str(data, "due_date")
    try:
        due_dt = _parse_iso(due)
    except (ValueError, TypeError):
        raise errors.validation("due_date must be a valid ISO 8601 timestamp")
    amount = req_int(data, "amount_cents")
    if amount < 0:
        raise errors.validation("amount_cents must be >= 0")
    paid = data.get("paid_date")
    if paid is not None:
        if not isinstance(paid, str):
            raise errors.validation("paid_date must be an ISO 8601 timestamp or null")
        try:
            _parse_iso(paid)
        except (ValueError, TypeError):
            raise errors.validation("paid_date must be a valid ISO 8601 timestamp")
    # due-month bucket: same UTC calendar month on the same lease
    ym = (due_dt.year, due_dt.month)
    for p in store.payments.values():
        if p["lease_id"] == lease_id:
            d = _parse_iso(p["due_date"])
            if (d.year, d.month) == ym:
                raise errors.duplicate_due_month()
    rec = {
        "id": new_id(),
        "lease_id": lease_id,
        "due_date": due,
        "paid_date": paid,
        "amount_cents": amount,
        "late": svc.compute_late(due, paid),
    }
    rec["created_at"] = wall_now_iso()
    store.payments[rec["id"]] = rec
    return resp.created(rec)


@bp.get("/leases/<lease_id>/payment-records")
def list_payments(lease_id):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Seller", "Buyer", "PropertyManager")
    if lease_id not in store.leases:
        raise errors.not_found("Lease not found")
    limit, offset = pagination_args()
    items = [p for p in store.payments.values() if p["lease_id"] == lease_id]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


# ---------------- Underwriting reports ----------------

@bp.post("/listings/<lid>/underwriting-reports")
def create_uw(lid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "Buyer")
    listing = store.listings.get(lid)
    if not listing:
        raise errors.not_found("Listing not found")
    data = body()
    buyer_id = req_str(data, "buyer_id")
    if ctx.user_id != buyer_id:
        raise errors.forbidden("buyer_id must be the acting buyer's own id")
    if buyer_id not in store.buyers:
        raise errors.not_found("Buyer not found")
    rent = req_int(data, "rent_estimate_cents")
    if rent <= 0:
        raise errors.validation("rent_estimate_cents must be > 0")
    vac = req_int(data, "vacancy_rate_bps")
    if vac < 0 or vac > 5000:
        raise errors.validation("vacancy_rate_bps must be 0-5000")
    opex = req_int(data, "opex_rate_bps")
    if opex < 0 or opex > 9000:
        raise errors.validation("opex_rate_bps must be 0-9000")
    disclosure_limited, noi, yld = svc.compute_underwriting(listing, rent, vac, opex)
    report = stamp_new({
        "id": new_id(),
        "listing_id": lid,
        "buyer_id": buyer_id,
        "rent_estimate_cents": rent,
        "vacancy_rate_bps": vac,
        "opex_rate_bps": opex,
        "projected_noi_cents": noi,
        "projected_yield_bps": yld,
        "disclosure_limited": disclosure_limited,
    })
    store.uw_reports[report["id"]] = report
    return resp.created(report)


@bp.get("/underwriting-reports")
def list_uw():
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Buyer")
    limit, offset = pagination_args()
    items = list(store.uw_reports.values())
    from flask import request
    for key in ("listing_id", "buyer_id"):
        v = request.args.get(key)
        if v is not None:
            items = [r for r in items if r.get(key) == v]
    page, total = paginate(items, limit, offset)
    return resp.listing_ok(page, limit, offset, total)


@bp.get("/underwriting-reports/<rid>")
def get_uw(rid):
    ctx = mw.get_ctx()
    mw.require_role(ctx, "PlatformAdmin", "Buyer")
    report = store.uw_reports.get(rid)
    if not report:
        raise errors.not_found("Underwriting report not found")
    return resp.ok(report)
