"""Shared list-filter helpers for the route modules."""
from flask import request


def arg(name):
    value = request.args.get(name)
    return value if value not in (None, "") else None


def eq(records, field, value):
    if value is None:
        return records
    return [r for r in records if r.get(field) == value]


def contains(records, field, value):
    if value is None:
        return records
    return [r for r in records if value in (r.get(field) or [])]


def boolean(records, field, raw):
    if raw is None:
        return records
    wanted = raw.strip().lower()
    if wanted in ("true", "1"):
        flag = True
    elif wanted in ("false", "0"):
        flag = False
    else:
        return []
    return [r for r in records if bool(r.get(field)) is flag]
