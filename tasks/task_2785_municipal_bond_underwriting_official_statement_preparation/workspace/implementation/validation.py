"""Request-shape validation (PRD 2.5 tier 5) plus numeric and calendar helpers."""
import calendar
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import request

from errors import ApiError

MISSING = object()


class Body(dict):
    def __init__(self, *args, **kwargs):
        dict.__init__(self, *args, **kwargs)
        self.present = set()

    def has(self, name):
        return name in self.present


def spec(name, kind, required=True, default=None, **opts):
    entry = {"name": name, "kind": kind, "required": required, "default": default}
    entry.update(opts)
    return entry


def _bad():
    raise ApiError("ERR_INVALID_REQUEST")


def parse_datetime(value):
    if not isinstance(value, str):
        _bad()
    text = value.strip()
    if text == "":
        _bad()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        _bad()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def decimal_places(value):
    exponent = Decimal(str(value)).as_tuple().exponent
    if not isinstance(exponent, int):
        _bad()
    return -exponent if exponent < 0 else 0


def dec(value):
    return Decimal(str(value))


def _coerce(entry, value):
    kind = entry["kind"]
    if kind == "string":
        if not isinstance(value, str):
            _bad()
        if entry.get("non_blank", True) and value.strip() == "":
            _bad()
        length = len(value)
        if "min_len" in entry and length < entry["min_len"]:
            _bad()
        if "max_len" in entry and length > entry["max_len"]:
            _bad()
        if "pattern" in entry and not re.match(entry["pattern"], value):
            _bad()
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad()
        _check_range(entry, Decimal(value))
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad()
        as_dec = dec(value)
        if "max_decimals" in entry and decimal_places(value) > entry["max_decimals"]:
            _bad()
        _check_range(entry, as_dec)
        return as_dec
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad()
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in entry["values"]:
            _bad()
        return value
    if kind == "datetime":
        return parse_datetime(value)
    if kind == "string_array":
        if not isinstance(value, list):
            _bad()
        for item in value:
            if not isinstance(item, str) or item.strip() == "":
                _bad()
        if "max_items" in entry and len(value) > entry["max_items"]:
            _bad()
        if "min_items" in entry and len(value) < entry["min_items"]:
            _bad()
        return list(value)
    _bad()


def _check_range(entry, value):
    if "minimum" in entry and value < dec(entry["minimum"]):
        _bad()
    if "exclusive_minimum" in entry and value <= dec(entry["exclusive_minimum"]):
        _bad()
    if "maximum" in entry and value > dec(entry["maximum"]):
        _bad()
    if "multiple_of" in entry and value % dec(entry["multiple_of"]) != 0:
        _bad()


def parse_body(specs):
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        _bad()
    allowed = set(entry["name"] for entry in specs)
    for key in raw.keys():
        if key not in allowed:
            _bad()
    body = Body()
    for entry in specs:
        name = entry["name"]
        if name in raw and raw[name] is not None:
            body[name] = _coerce(entry, raw[name])
            body.present.add(name)
        else:
            if entry["required"] and name not in raw:
                _bad()
            if entry["required"] and name in raw:
                _bad()
            body[name] = entry["default"]
    return body


# --- numeric helpers -------------------------------------------------------

def quant(value, places):
    return dec(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def q2(value):
    return quant(value, 2)


def q3(value):
    return quant(value, 3)


def q4(value):
    return quant(value, 4)


def floor_to_multiple(value, multiple):
    step = dec(multiple)
    return (dec(value) / step).to_integral_value(rounding=ROUND_FLOOR) * step


# --- calendar helpers ------------------------------------------------------

def add_months(moment, months):
    total = moment.month - 1 + months
    year = moment.year + total // 12
    month = total % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def semiannual_periods(dated_date, target):
    """Number of semiannual periods from dated_date to target.

    Returns None when target is not strictly after dated_date or does not fall
    exactly on a semiannual anniversary of it.
    """
    months = (target.year - dated_date.year) * 12 + (target.month - dated_date.month)
    if months <= 0 or months % 6 != 0:
        return None
    if add_months(dated_date, months) != target:
        return None
    return months // 6


# --- query helpers ---------------------------------------------------------

def query_value(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def sorted_rows(rows, key=None):
    if key is None:
        return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))
    return sorted(rows, key=key)
