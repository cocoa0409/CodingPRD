"""Reference resolution of PRD 2.9 and the shared list-endpoint helper.

Path identifiers resolve before anything in the body is examined, strictly left to
right; body foreign keys resolve afterwards in the order the fields are declared on
the owning resource. Each identifier has its own dedicated 404.
"""
from flask import request

from envelope import collection
from errors import ApiError
from shape import pagination
from store import db, ordered, ordered_desc


def _find(coll, identifier, error_id):
    row = coll.get(identifier) if isinstance(identifier, str) else None
    if row is None:
        raise ApiError(error_id, "No such resource: %s." % identifier)
    return row


def account(identifier):
    return _find(db.accounts, identifier, "ERR_ACCOUNT_NOT_FOUND")


def site(identifier):
    return _find(db.sites, identifier, "ERR_SITE_NOT_FOUND")


def route(identifier):
    return _find(db.routes, identifier, "ERR_ROUTE_NOT_FOUND")


def equipment_model(identifier):
    return _find(db.equipment_models, identifier, "ERR_MODEL_NOT_FOUND")


def equipment_asset(identifier):
    return _find(db.equipment_assets, identifier, "ERR_ASSET_NOT_FOUND")


def placement(identifier):
    return _find(db.equipment_placements, identifier, "ERR_PLACEMENT_NOT_FOUND")


def product_item(identifier):
    return _find(db.product_items, identifier, "ERR_PRODUCT_NOT_FOUND")


def par_level(identifier):
    return _find(db.par_levels, identifier, "ERR_PAR_LEVEL_NOT_FOUND")


def service_visit(identifier):
    return _find(db.service_visits, identifier, "ERR_VISIT_NOT_FOUND")


def work_order(identifier):
    return _find(db.work_orders, identifier, "ERR_WORK_ORDER_NOT_FOUND")


def invoice(identifier):
    return _find(db.invoices, identifier, "ERR_INVOICE_NOT_FOUND")


def invoice_line(identifier):
    return _find(db.invoice_lines, identifier, "ERR_INVOICE_LINE_NOT_FOUND")


def price_adjustment(identifier):
    return _find(db.price_adjustments, identifier, "ERR_ADJUSTMENT_NOT_FOUND")


def listing(rows, serializer, newest_first=False, predicate=None):
    """Pagination and the default created_at-ascending ordering of PRD 2.3."""
    limit, offset = pagination()
    if predicate is not None:
        rows = [r for r in rows if predicate(r)]
    rows = ordered_desc(rows) if newest_first else ordered(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return collection([serializer(r) for r in page], limit, offset, total)


def eq_filter(rows, field, param=None, coerce=None):
    """Query filters match on exact equality (PRD 4)."""
    param = param or field
    raw = request.args.get(param)
    if raw is None:
        return rows
    if coerce is not None:
        wanted = coerce(raw)
    else:
        wanted = raw
    return [r for r in rows if r.get(field) == wanted]


def bool_param(raw):
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return object()
