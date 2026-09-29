"""Small shared helpers for the route modules."""
from flask import request


def arg(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def bool_arg(name):
    value = arg(name)
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1", "yes"):
        return True
    if low in ("false", "0", "no"):
        return False
    return None


def int_arg(name):
    value = arg(name)
    if value is None:
        return None
    text = value.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        return None
    return int(text)


def match_all(row, pairs):
    """Conjunctive filtering; a None filter value is simply not applied."""
    for field, wanted in pairs:
        if wanted is None:
            continue
        if row.get(field) != wanted:
            return False
    return True
