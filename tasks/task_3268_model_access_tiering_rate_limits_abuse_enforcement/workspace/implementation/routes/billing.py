"""Invoice and invoice-line routes."""
from __future__ import annotations

import db
from errors import (invalid_request, invalid_state, not_found, period_overlap,
                    temporal_invalid)
from middleware import require_roles, pagination_params, paginate
from response import success
from services.domain import finalize_invoice
from services.util import (body, require_datetime, require_enum, require_int,
                           require_str, simple_view, sort_by_created, stamp_new,
                           touch)

from flask import Blueprint, request

bp = Blueprint("billing", __name__)

LINE_KINDS = {"INPUT_TOKENS", "OUTPUT_TOKENS", "CACHED_TOKENS"}


def _validate_lines(data) -> list:
    raw = data.get("lines")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise invalid_request("lines must be an array")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise invalid_request("each line must be an object")
        mv_id = item.get("model_version_id")
        if not isinstance(mv_id, str) or not mv_id:
            raise invalid_request("line.model_version_id is required")
        kind = item.get("kind")
        if kind not in LINE_KINDS:
            raise invalid_request("line.kind must be INPUT_TOKENS, OUTPUT_TOKENS, or CACHED_TOKENS")
        qty = item.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 0:
            raise invalid_request("line.quantity must be a non-negative integer")
        rate = item.get("rate_per_mtok_cents")
        if isinstance(rate, bool) or not isinstance(rate, int) or rate < 0:
            raise invalid_request("line.rate_per_mtok_cents must be a non-negative integer")
        batch = item.get("batch", False)
        if not isinstance(batch, bool):
            raise invalid_request("line.batch must be a boolean")
        out.append({
            "model_version_id": mv_id,
            "kind": kind,
            "quantity": qty,
            "rate_per_mtok_cents": rate,
            "batch": batch,
        })
    return out


@bp.post("/invoices")
def create_invoice():
    require_roles("BillingContact", "PlatformAdmin")
    data = body()
    org_id = require_str(data, "organization_id")
    period_start = require_datetime(data, "period_start")
    period_end = require_datetime(data, "period_end")
    lines = _validate_lines(data)

    org = db.organizations.get(org_id)
    if org is None:
        raise not_found("organization not found")

    if period_end <= period_start:
        raise temporal_invalid("period_end must be strictly after period_start")

    # closed-open interval overlap against every existing invoice for this org
    for inv in db.invoices.values():
        if inv["organization_id"] != org_id:
            continue
        ex_start = db.parse_iso(inv["period_start"])
        ex_end = db.parse_iso(inv["period_end"])
        if period_start < ex_end and ex_start < period_end:
            raise period_overlap()

    invoice = {
        "organization_id": org_id,
        "period_start": db.fmt_clock(period_start),
        "period_end": db.fmt_clock(period_end),
        "status": "DRAFT",
        "subtotal_cents": 0,
        "batch_discount_cents": 0,
        "total_cents": 0,
    }
    stamp_new(invoice, common=True)
    db.invoices[invoice["id"]] = invoice

    for line in lines:
        rec = {
            "invoice_id": invoice["id"],
            "model_version_id": line["model_version_id"],
            "kind": line["kind"],
            "quantity": line["quantity"],
            "rate_per_mtok_cents": line["rate_per_mtok_cents"],
            "batch": line["batch"],
            "amount_cents": None,
        }
        stamp_new(rec, common=False)
        db.invoice_lines[rec["id"]] = rec

    return success(simple_view(invoice), status=201)


@bp.get("/invoice-lines")
def list_invoice_lines():
    require_roles("BillingContact", "PlatformAdmin", "OrganizationAdmin")
    limit, offset = pagination_params()
    items = list(db.invoice_lines.values())
    inv_f = request.args.get("invoice_id")
    mv_f = request.args.get("model_version_id")
    if inv_f is not None:
        items = [l for l in items if l["invoice_id"] == inv_f]
    if mv_f is not None:
        items = [l for l in items if l["model_version_id"] == mv_f]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([simple_view(l) for l in page], response_type="array", pagination=meta)


@bp.get("/invoice-lines/<line_id>")
def get_invoice_line(line_id):
    require_roles("BillingContact", "PlatformAdmin", "OrganizationAdmin")
    line = db.invoice_lines.get(line_id)
    if line is None:
        raise not_found("invoice line not found")
    return success(simple_view(line))


@bp.post("/invoices/<invoice_id>/finalize")
def finalize(invoice_id):
    require_roles("BillingContact")
    invoice = db.invoices.get(invoice_id)
    if invoice is None:
        raise not_found("invoice not found")
    if invoice["status"] != "DRAFT":
        raise invalid_state("invoice is not DRAFT")
    org = db.organizations.get(invoice["organization_id"])
    if org is not None and org["status"] == "TERMINATED":
        raise invalid_state("cannot finalize invoice for TERMINATED organization")
    finalize_invoice(invoice, org)
    touch(invoice)
    return success(simple_view(invoice))
