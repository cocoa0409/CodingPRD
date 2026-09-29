"""Existence resolution (tier 4), pagination and collection filters."""
from flask import g, request

import db
from errors import ApiError
from services.validate import invalid

_NOT_FOUND = {
    "terminals": "ERR_TERMINAL_NOT_FOUND",
    "brands": "ERR_BRAND_NOT_FOUND",
    "products": "ERR_PRODUCT_NOT_FOUND",
    "grants": "ERR_GRANT_NOT_FOUND",
    "allowance_rules": "ERR_ALLOWANCE_RULE_NOT_FOUND",
    "stock_items": "ERR_STOCK_ITEM_NOT_FOUND",
    "movements": "ERR_MOVEMENT_NOT_FOUND",
    "itineraries": "ERR_ITINERARY_NOT_FOUND",
    "sales": "ERR_SALE_NOT_FOUND",
    "sale_lines": "ERR_SALE_LINE_NOT_FOUND",
    "sealed_bags": "ERR_SEALED_BAG_NOT_FOUND",
    "pre_orders": "ERR_PRE_ORDER_NOT_FOUND",
    "agreements": "ERR_AGREEMENT_NOT_FOUND",
    "audits": "ERR_AUDIT_NOT_FOUND",
}

_STORES = {
    "terminals": db.terminals,
    "brands": db.brands,
    "products": db.products,
    "grants": db.grants,
    "allowance_rules": db.allowance_rules,
    "stock_items": db.stock_items,
    "movements": db.movements,
    "itineraries": db.itineraries,
    "sales": db.sales,
    "sale_lines": db.sale_lines,
    "sealed_bags": db.sealed_bags,
    "pre_orders": db.pre_orders,
    "agreements": db.agreements,
    "audits": db.audits,
}


def fetch(kind, identifier):
    """Resolve an identifier or raise the entity's own 404."""
    store = _STORES[kind]
    if not isinstance(identifier, str) or identifier not in store:
        raise ApiError(_NOT_FOUND[kind])
    return store[identifier]


def fetch_body(kind, field, body):
    """Resolve an identifier carried in the request body (tier 4 before tier 5)."""
    return fetch(kind, body.get(field))


def page_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            invalid("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            invalid("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            invalid("Query parameter 'offset' must be an integer.")
        if offset < 0:
            invalid("Query parameter 'offset' must be >= 0.")
    return limit, offset


def apply_filters(rows, fields):
    """Equality filters taken from the query string (PRD section 2.3)."""
    for field in fields:
        value = request.args.get(field)
        if value is None:
            continue
        rows = [r for r in rows if str(r.get(field)) == value]
    return rows


def listing(store, filter_fields, predicate=None):
    limit, offset = page_params()
    rows = db.ordered(store, predicate)
    rows = apply_filters(rows, filter_fields)
    total = len(rows)
    page = rows[offset:offset + limit]
    return [db.public(r) for r in page], limit, offset, total
