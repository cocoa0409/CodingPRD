"""Filtering and sorting for list endpoints (PRD section 2.3)."""

from flask import request

from store import by_created


def apply_filters(rows, pairs):
    """Filters are additive and case-sensitive against the stored strings."""
    for param, field in pairs:
        value = request.args.get(param)
        if value is None:
            continue
        rows = [r for r in rows if r[field] == value]
    return rows


def filter_membership(rows, param, field):
    value = request.args.get(param)
    if value is None:
        return rows
    return [r for r in rows if value in r[field]]


def sort_default(rows):
    """created_at ascending with id ascending as the stable tie-breaker."""
    return by_created(rows)


def sort_created_desc(rows):
    rows = sorted(rows, key=lambda r: r["id"])
    return sorted(rows, key=lambda r: r["created_at"], reverse=True)


def sort_by(rows, keys):
    rows = by_created(rows)
    return sorted(rows, key=lambda r: tuple(r[k] for k in keys))
