"""Shared route plumbing: existence lookups (PRD 2.6 rung 4) and list paging."""

import db
from errors import ApiError
from middleware import page_params, query, slice_rows
from response import ok_list


def need(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def store_or_404(row_id):
    return need(db.host_stores, row_id, "ERR_HOST_STORE_NOT_FOUND")


def agreement_or_404(row_id):
    return need(db.license_agreements, row_id, "ERR_LICENSE_AGREEMENT_NOT_FOUND")


def kiosk_or_404(row_id):
    return need(db.kiosks, row_id, "ERR_KIOSK_NOT_FOUND")


def chef_or_404(row_id):
    return need(db.chefs, row_id, "ERR_CHEF_RECORD_NOT_FOUND")


def certification_or_404(row_id):
    return need(db.certifications, row_id, "ERR_CHEF_RECORD_NOT_FOUND")


def plan_or_404(row_id):
    return need(db.production_plans, row_id, "ERR_PRODUCTION_RECORD_NOT_FOUND")


def batch_or_404(row_id):
    return need(db.rice_batches, row_id, "ERR_PRODUCTION_RECORD_NOT_FOUND")


def pack_lot_or_404(row_id):
    return need(db.pack_lots, row_id, "ERR_PRODUCTION_RECORD_NOT_FOUND")


def fish_lot_or_404(row_id):
    return need(db.fish_lots, row_id, "ERR_SOURCING_RECORD_NOT_FOUND")


def reading_or_404(row_id):
    return need(db.cold_chain_readings, row_id, "ERR_SOURCING_RECORD_NOT_FOUND")


def feed_or_404(row_id):
    return need(db.pos_sales_feeds, row_id, "ERR_SETTLEMENT_RECORD_NOT_FOUND")


def statement_or_404(row_id):
    return need(db.settlement_statements, row_id, "ERR_SETTLEMENT_RECORD_NOT_FOUND")


def audit_or_404(row_id):
    return need(db.food_safety_audits, row_id, "ERR_AUDIT_RECORD_NOT_FOUND")


def finding_or_404(row_id):
    return need(db.audit_findings, row_id, "ERR_AUDIT_RECORD_NOT_FOUND")


def state_or_fail(row, allowed, error_id):
    """PRD 2.6 rung 6."""
    if row["status"] not in allowed:
        raise ApiError(error_id)


def filters(rows, spec):
    """spec: {query_param_name: row_field_name}. Filters are additive (PRD 2.3)."""
    for param, field in spec.items():
        wanted = query(param)
        if wanted is None:
            continue
        rows = [r for r in rows if r.get(field) == wanted]
    return rows


def paginate(rows, presorted=False):
    limit, offset = page_params()
    if not presorted:
        rows = db.ordered(rows)
    page, total = slice_rows(rows, limit, offset)
    return ok_list([db.public(r) for r in page], limit, offset, total)


def fk_lookup(payload, field, resolver):
    """PRD 2.6 rung 4: body foreign keys resolve before rung 5 schema checks.

    A value that is not even a non-blank string cannot be resolved; it is left to
    the schema rung to reject.
    """
    value = payload.get(field)
    if isinstance(value, str) and not isinstance(value, bool) and value.strip():
        return resolver(value)
    return None
