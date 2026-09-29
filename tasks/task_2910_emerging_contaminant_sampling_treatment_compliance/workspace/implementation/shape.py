"""Request-shape validation (ladder priority 6) and pagination (priority 7)."""

import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from flask import request

import constants as C
from errors import ApiError, invalid
from numeric import decimal_places, dec

INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?([Zz]|[+-]\d{2}:\d{2})$"
)
PERIOD_RE = re.compile(r"^\d{4}Q[1-4]$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value, field):
    if not isinstance(value, str):
        raise invalid("%s must be an ISO 8601 UTC instant" % field)
    match = INSTANT_RE.match(value)
    if not match:
        raise invalid("%s must be an ISO 8601 UTC instant" % field)
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    fraction = match.group(7)
    micro = 0
    if fraction:
        digits = (fraction[1:] + "000000")[:6]
        micro = int(digits)
    try:
        parsed = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        raise invalid("%s must be an ISO 8601 UTC instant" % field)
    offset = match.group(8)
    if offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6]))
        parsed = parsed - sign * delta
    return parsed


def parse_date(value, field):
    if not isinstance(value, str):
        raise invalid("%s must be a calendar date" % field)
    match = DATE_RE.match(value)
    if match:
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc
            )
        except ValueError:
            raise invalid("%s must be a calendar date" % field)
    return parse_instant(value, field)


def decode_period(label):
    return (int(label[:4]), int(label[5]))


def period_of(instant):
    return "%04dQ%d" % (instant.year, (instant.month - 1) // 3 + 1)


def read_json_body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except Exception:
        raise invalid("body is not well-formed JSON")
    if parsed is None:
        return {}
    return parsed


class Body(object):
    """Strict allow-list reader.  Any field name not declared for the endpoint —
    including a derived field or a misplaced concurrency token — is a shape
    failure (PRD 2.6 and 2.9)."""

    def __init__(self, allowed):
        payload = read_json_body()
        if not isinstance(payload, dict):
            raise invalid("body must be a JSON object")
        for key in payload:
            if key not in allowed:
                raise invalid("unrecognised field %s" % key)
        self.data = payload

    def has(self, name):
        return name in self.data

    def raw(self, name):
        return self.data.get(name)

    # ------------------------------------------------------------------ scalars
    def _present(self, name, required, default):
        if name not in self.data:
            if required:
                raise invalid("%s is required" % name)
            return False, default
        return True, None

    def string(self, name, required=True, default=None, min_len=None, max_len=None,
               pattern=None, nonblank=False):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        value = self.data[name]
        if not isinstance(value, str):
            raise invalid("%s must be a string" % name)
        if min_len is not None and len(value) < min_len:
            raise invalid("%s is shorter than %d characters" % (name, min_len))
        if max_len is not None and len(value) > max_len:
            raise invalid("%s is longer than %d characters" % (name, max_len))
        if nonblank and value.strip() == "":
            raise invalid("%s must not be blank" % name)
        if pattern is not None and not re.match(pattern, value):
            raise invalid("%s has an unacceptable shape" % name)
        return value

    def enum(self, name, choices, required=True, default=None):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        value = self.data[name]
        if not isinstance(value, str) or value not in choices:
            raise invalid("%s must be one of %s" % (name, ", ".join(choices)))
        return value

    def boolean(self, name, required=True, default=None):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        value = self.data[name]
        if not isinstance(value, bool):
            raise invalid("%s must be a boolean" % name)
        return value

    def integer(self, name, required=True, default=None, minimum=None, maximum=None,
                exclusive_minimum=None):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        value = self.data[name]
        if isinstance(value, bool):
            raise invalid("%s must be an integer" % name)
        if isinstance(value, Decimal):
            if value != value.to_integral_value():
                raise invalid("%s must be an integer" % name)
            value = int(value)
        if not isinstance(value, int):
            raise invalid("%s must be an integer" % name)
        if minimum is not None and value < minimum:
            raise invalid("%s must be at least %s" % (name, minimum))
        if exclusive_minimum is not None and value <= exclusive_minimum:
            raise invalid("%s must be greater than %s" % (name, exclusive_minimum))
        if maximum is not None and value > maximum:
            raise invalid("%s must be at most %s" % (name, maximum))
        return value

    def decimal(self, name, required=True, default=None, places=2, minimum=None,
                maximum=None, exclusive_minimum=None):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        value = self.data[name]
        if isinstance(value, bool) or isinstance(value, str):
            raise invalid("%s must be a number" % name)
        if not isinstance(value, (int, Decimal)):
            raise invalid("%s must be a number" % name)
        try:
            number = dec(value)
        except (InvalidOperation, ValueError):
            raise invalid("%s must be a number" % name)
        if not number.is_finite():
            raise invalid("%s must be a finite number" % name)
        if decimal_places(number) > places:
            raise invalid("%s carries more than %d decimal places" % (name, places))
        if minimum is not None and number < dec(minimum):
            raise invalid("%s must be at least %s" % (name, minimum))
        if exclusive_minimum is not None and number <= dec(exclusive_minimum):
            raise invalid("%s must be greater than %s" % (name, exclusive_minimum))
        if maximum is not None and number > dec(maximum):
            raise invalid("%s must be at most %s" % (name, maximum))
        return number.quantize(Decimal(1).scaleb(-places))

    def instant(self, name, required=True, default=None):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        return parse_instant(self.data[name], name)

    def date(self, name, required=True, default=None):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        return parse_date(self.data[name], name)

    def period(self, name, required=True, default=None):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        value = self.data[name]
        if not isinstance(value, str) or not PERIOD_RE.match(value):
            raise invalid("%s must be a YYYYQn monitoring-period label" % name)
        return value

    def string_list(self, name, required=True, default=None, choices=None,
                    non_empty=True, distinct=True):
        found, fallback = self._present(name, required, default)
        if not found:
            return fallback
        value = self.data[name]
        if not isinstance(value, list):
            raise invalid("%s must be an array" % name)
        for item in value:
            if not isinstance(item, str):
                raise invalid("%s must contain only strings" % name)
            if choices is not None and item not in choices:
                raise invalid("%s contains an unrecognised value" % name)
        if non_empty and len(value) == 0:
            raise invalid("%s must not be empty" % name)
        if distinct and len(set(value)) != len(value):
            raise invalid("%s must not contain duplicates" % name)
        return list(value)


def pagination():
    """Priority 7.  Never clamps."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = C.PAGE_LIMIT_DEFAULT
    offset = C.PAGE_OFFSET_DEFAULT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_OUT_OF_RANGE")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_OUT_OF_RANGE")
    if limit < C.PAGE_LIMIT_MIN or limit > C.PAGE_LIMIT_MAX:
        raise ApiError("ERR_PAGINATION_OUT_OF_RANGE")
    if offset < C.PAGE_OFFSET_MIN:
        raise ApiError("ERR_PAGINATION_OUT_OF_RANGE")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def boolean_filter(name):
    value = filter_value(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None
