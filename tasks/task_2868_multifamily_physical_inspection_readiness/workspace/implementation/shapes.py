"""Request-shape (priority 3) and enum-membership (priority 4) validation.

Shape validation runs to completion for every declared field before any enum
membership is inspected, so a badly typed body always reports
ERR_INVALID_REQUEST rather than ERR_INVALID_ENUM_VALUE.
"""

import re
from decimal import Decimal

from flask import request

import store
from errors import ApiError

# A numeric literal delivered as a JSON string is still a number; anything that
# is not a clean numeric literal remains a shape error.
_INTEGER_TEXT = re.compile(r"^[+-]?\d+$")
_NUMBER_TEXT = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)$")

# --- declared enumerations -------------------------------------------------
ADOPTION_STATUS = ["DRAFT", "ADOPTED", "SUPERSEDED"]
INSPECTABLE_AREA = ["UNIT", "INSIDE", "OUTSIDE"]
SEVERITY = ["LIFE_THREATENING", "SEVERE", "MODERATE", "LOW"]
OCCUPANCY_STATUS = ["OCCUPIED", "VACANT", "DOWN"]
READINESS_POSTURE = ["READY", "WATCH", "RESTRICTED", "FROZEN"]
INSPECTION_KIND = ["INITIAL", "FOLLOW_UP"]
INSPECTION_STATUS = [
    "SCHEDULED",
    "SAMPLED",
    "NOTIFIED",
    "IN_PROGRESS",
    "SCORED",
    "APPEALED",
    "CAP_REQUIRED",
    "CAP_APPROVED",
    "FOLLOW_UP_SCHEDULED",
    "CLOSED",
    "CANCELLED",
]
SELECTION_BASIS = ["SAMPLED", "REPLACEMENT"]
SELECTION_STATUS = ["ACTIVE", "REPLACED"]
ACCESS_STATUS = ["NOT_NOTIFIED", "NOTIFIED", "GRANTED", "REFUSED"]
NOTICE_METHOD = ["POSTED", "MAILED", "POSTED_AND_MAILED", "EMAIL"]
ACCESS_RESULT = ["GRANTED", "REFUSED"]
DEFICIENCY_SOURCE = ["INSPECTION", "SELF_ASSESSMENT"]
DEFICIENCY_STATUS = ["OPEN", "CORRECTED", "VERIFIED", "OVERDUE", "VOIDED"]
SWEEP_STATUS = ["PLANNED", "IN_PROGRESS", "CLOSED", "ABANDONED"]
PLANNED_AREA_SCOPE = ["UNIT_ONLY", "INSIDE_OUTSIDE", "ALL_AREAS"]
REPAIR_STATUS = ["OPEN", "REPAIRED", "VOID"]
VERIFICATION_STATUS = ["UNVERIFIED", "VERIFIED", "REJECTED"]
PRIORITY_TIER = ["ROUTINE", "URGENT"]
VERIFICATION_RESULT = ["PASSED", "FAILED"]
APPEAL_TYPE = ["TECHNICAL_ERROR", "SCORE_CORRECTION"]
APPEAL_STATUS = ["SUBMITTED", "RETURNED_FOR_INFO", "GRANTED", "DENIED"]
APPEAL_DECISION = ["GRANTED", "DENIED", "RETURNED_FOR_INFO"]
CAP_STATUS = ["SUBMITTED", "REJECTED", "APPROVED", "FOLLOW_UP_SCHEDULED", "COMPLETED"]
CAP_DECISION = ["APPROVED", "REJECTED"]
RECURRENCE_BASIS = ["INSPECTION_SCOPED", "CALENDAR_SCOPED"]
CAPITAL_ITEM_STATUS = ["ACTIVE", "SUPERSEDED"]


class Field(object):
    def __init__(self, name, kind, required=True, values=None, minimum=None,
                 maximum=None, min_len=None, max_len=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.values = values
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len


def F(name, kind, required=True, **kw):
    return Field(name, kind, required, **kw)


def _bad(name, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def _as_decimal(value):
    return Decimal(str(value))


def read_body():
    body = request.get_json(silent=True)
    if body is None:
        if request.data and request.data.strip():
            raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def validate(fields):
    """Two-pass validation. Returns a dict of the recognised values.

    Optional fields supplied as JSON null are treated as absent.
    """
    body = read_body()
    out = {}
    enum_checks = []

    for field in fields:
        present = field.name in body
        value = body.get(field.name)
        if not present or value is None:
            if field.required:
                _bad(field.name, "is required")
            out[field.name] = None
            continue

        kind = field.kind
        if kind == "string":
            if not isinstance(value, str):
                _bad(field.name, "must be a string")
            if field.min_len is not None and len(value) < field.min_len:
                _bad(field.name, "must be at least %d characters" % field.min_len)
            if field.max_len is not None and len(value) > field.max_len:
                _bad(field.name, "must be at most %d characters" % field.max_len)
            out[field.name] = value
        elif kind == "enum":
            if not isinstance(value, str):
                _bad(field.name, "must be a string")
            out[field.name] = value
            enum_checks.append((field, value))
        elif kind == "integer":
            if isinstance(value, bool):
                _bad(field.name, "must be an integer")
            if isinstance(value, str):
                text = value.strip()
                if not _INTEGER_TEXT.match(text):
                    _bad(field.name, "must be an integer")
                value = int(text)
            if not isinstance(value, int):
                _bad(field.name, "must be an integer")
            if field.minimum is not None and value < field.minimum:
                _bad(field.name, "must be at least %s" % field.minimum)
            if field.maximum is not None and value > field.maximum:
                _bad(field.name, "must be at most %s" % field.maximum)
            out[field.name] = value
        elif kind == "number":
            if isinstance(value, bool):
                _bad(field.name, "must be a number")
            if isinstance(value, str):
                if not _NUMBER_TEXT.match(value.strip()):
                    _bad(field.name, "must be a number")
                value = value.strip()
            elif not isinstance(value, (int, float)):
                _bad(field.name, "must be a number")
            dec = _as_decimal(value)
            if field.minimum is not None and dec < _as_decimal(field.minimum):
                _bad(field.name, "must be at least %s" % field.minimum)
            if field.maximum is not None and dec > _as_decimal(field.maximum):
                _bad(field.name, "must be at most %s" % field.maximum)
            out[field.name] = dec
        elif kind == "datetime":
            if not isinstance(value, str):
                _bad(field.name, "must be an ISO 8601 UTC instant string")
            parsed = store.parse_instant(value)
            if parsed is None:
                _bad(field.name, "must be an ISO 8601 UTC instant string")
            out[field.name] = value
        elif kind == "string_list":
            if not isinstance(value, list):
                _bad(field.name, "must be an array of strings")
            for entry in value:
                if not isinstance(entry, str):
                    _bad(field.name, "must be an array of strings")
            out[field.name] = list(value)
        elif kind == "boolean":
            if not isinstance(value, bool):
                _bad(field.name, "must be a boolean")
            out[field.name] = value
        else:  # pragma: no cover - defensive
            out[field.name] = value

    for field, value in enum_checks:
        if value not in field.values:
            raise ApiError(
                "ERR_INVALID_ENUM_VALUE",
                "Field '%s' must be one of %s." % (field.name, ", ".join(field.values)),
            )
    return out


def instant(values, name):
    """The parsed datetime of a validated instant field, or None."""
    raw = values.get(name)
    if raw is None:
        return None
    return store.parse_instant(raw)
