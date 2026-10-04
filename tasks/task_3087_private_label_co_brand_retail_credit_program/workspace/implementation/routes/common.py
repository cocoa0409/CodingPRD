"""Shared response helpers for route modules."""
from flask import jsonify

from core.auth import apply_filters, page, pagination
from core.envelope import success_array, success_object
from core.serialize import clean, clean_all


def listing(rows, filters=None):
    """Paginated list envelope, sorted by created_at ascending (PRD §2.3)."""
    limit, offset = pagination()
    if filters:
        rows = apply_filters(rows, filters)
    rows = sorted(rows, key=lambda r: r.get("created_at", ""))
    total = len(rows)
    return jsonify(success_array(clean_all(page(rows, limit, offset)), limit, offset, total))


def single(entity, status=200):
    return jsonify(success_object(clean(entity))), status