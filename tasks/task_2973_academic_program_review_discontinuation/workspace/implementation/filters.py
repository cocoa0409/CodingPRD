"""Additive list filters (PRD 2.3).

A filter naming a value no row carries yields an empty array rather than an
error, so no filter value is ever validated against an enum.
"""

from flask import request


def _get(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def apply_string(rows, param, key):
    value = _get(param)
    if value is None:
        return rows
    return [r for r in rows if r.get(key) == value]


def apply_int(rows, param, key):
    value = _get(param)
    if value is None:
        return rows
    stripped = value.strip()
    negative = stripped.startswith("-")
    digits = stripped[1:] if negative or stripped.startswith("+") else stripped
    if not digits.isdigit():
        return []
    number = int(stripped)
    return [r for r in rows if r.get(key) == number]


def apply_bool(rows, param, key, getter):
    value = _get(param)
    if value is None:
        return rows
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        wanted = True
    elif lowered in ("false", "0"):
        wanted = False
    else:
        return []
    return [r for r in rows if getter(r) == wanted]
