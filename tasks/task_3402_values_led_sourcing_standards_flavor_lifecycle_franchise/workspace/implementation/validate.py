"""Request-payload validation helpers and enum domains (PRD 2.4, section 3).

Missing required fields or malformed values -> ERR_INVALID_REQUEST (400).
Enum values outside the declared set -> ERR_INVALID_ENUM (400).
"""
import re
from datetime import date

from flask import request

from errors import fail
from timeutil import parse_iso

INGREDIENT_CATEGORIES = ("DAIRY", "COCOA", "SUGAR", "VANILLA", "NUTS",
                         "FRUIT", "CHUNK_INCLUSION")
CERT_SCHEMES = ("FAIR_TRADE", "ORGANIC", "NON_GMO", "B_CORP",
                "RAINFOREST_ALLIANCE")
CERT_SCOPES = INGREDIENT_CATEGORIES + ("PACKAGING", "WHOLE_COMPANY")
PAYMENT_PERIODS = ("Q1", "Q2", "Q3", "Q4")
BASE_TYPES = ("DAIRY", "NON_DAIRY")
PLANT_CODES = ("VT_WATERBURY", "VT_ST_ALBANS", "NL_HELLENDOORN")
SHIFTS = ("DAY", "NIGHT")
ISSUE_AREAS = ("CLIMATE", "RACIAL_JUSTICE", "FAIR_TRADE", "DEMOCRACY",
               "LGBTQ_RIGHTS")
RETAIL_IMPACTS = ("NONE", "LOW", "HIGH")
OPERATOR_TYPES = ("FRANCHISEE", "NONPROFIT_PARTNER")
CLAIM_TYPES = ("NONE", "FAIR_TRADE_SOURCING", "ORGANIC_INGREDIENTS",
               "NON_GMO", "CLIMATE_POSITIVE")
PROMOTE_TARGETS = ("TEST_BATCH", "LIMITED_RUN", "CORE_LINE")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def get_body():
    """Return the JSON request body as a dict; {} when no body was sent."""
    data = request.get_json(silent=True)
    if data is None:
        if request.data and request.data.strip():
            fail("ERR_INVALID_REQUEST", "Request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _missing(name):
    fail("ERR_INVALID_REQUEST", "Missing required field: %s" % name)


def _malformed(name, what):
    fail("ERR_INVALID_REQUEST", "Field %s must be %s" % (name, what))


def req_str(body, name):
    v = body.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, str) or v == "":
        _malformed(name, "a non-empty string")
    return v


def opt_str(body, name, default=None):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, str) or v == "":
        _malformed(name, "a non-empty string")
    return v


def req_bool(body, name):
    v = body.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, bool):
        _malformed(name, "a boolean")
    return v


def opt_bool(body, name, default=False):
    v = body.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        _malformed(name, "a boolean")
    return v


def req_int(body, name, minv=None, maxv=None):
    v = body.get(name)
    if v is None:
        _missing(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _malformed(name, "an integer")
    if minv is not None and v < minv:
        _malformed(name, ">= %d" % minv)
    if maxv is not None and v > maxv:
        _malformed(name, "<= %d" % maxv)
    return v


def opt_int(body, name, default=None, minv=None, maxv=None):
    v = body.get(name)
    if v is None:
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        _malformed(name, "an integer")
    if minv is not None and v < minv:
        _malformed(name, ">= %d" % minv)
    if maxv is not None and v > maxv:
        _malformed(name, "<= %d" % maxv)
    return v


def req_num(body, name, minv=None, maxv=None):
    v = body.get(name)
    if v is None:
        _missing(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _malformed(name, "a number")
    if minv is not None and v < minv:
        _malformed(name, ">= %s" % minv)
    if maxv is not None and v > maxv:
        _malformed(name, "<= %s" % maxv)
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, str):
        _malformed(name, "a string")
    if v not in allowed:
        fail("ERR_INVALID_ENUM",
             "Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def req_dt(body, name):
    """Required ISO 8601 datetime field; returns an aware UTC datetime."""
    v = req_str(body, name)
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        _malformed(name, "an ISO 8601 datetime")


def req_date(body, name):
    """Required ISO yyyy-mm-dd date field; returns the normalized string."""
    v = req_str(body, name)
    if not _DATE_RE.match(v):
        _malformed(name, "an ISO yyyy-mm-dd date")
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        _malformed(name, "a valid calendar date")


def req_str_list(body, name, allow_empty=False):
    v = body.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, list) or (not allow_empty and not v):
        _malformed(name, "a non-empty array of strings")
    for el in v:
        if not isinstance(el, str) or el == "":
            _malformed(name, "an array of non-empty strings")
    return list(v)
