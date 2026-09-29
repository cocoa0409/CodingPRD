"""Query-string helpers for list endpoints."""

from flask import request


def arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value != "" else None


def arg_bool(name):
    value = arg(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    return None


def eq(rows, key, value):
    if value is None:
        return rows
    return [row for row in rows if row.get(key) == value]
