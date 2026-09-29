"""Structural validation -- precedence rule 6, ERR_INVALID_REQUEST (400).

PRD 2.10: "Structural validation at position 6 covers a missing required field,
an unknown enum value, a value of the wrong JSON type, an integer outside its
declared range, a string failing its declared length or pattern, an array longer
than its declared maximum, and a malformed ISO 8601 instant or date."

"Conversely, fields the server computes or manages itself are silently ignored
if a client sends them" -- so unknown / server-owned keys are never an error.
"""

import json
import re
from decimal import Decimal
from fractions import Fraction

from errors import ApiError
from money import frac
from store import parse_date, parse_instant

_MISSING = object()


def bad(detail):
    raise ApiError("ERR_INVALID_REQUEST", detail)


class Field:
    def __init__(self, name, kind, required=False, default=None, **opts):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.opts = opts


def parse_json_body(raw):
    """Parse the request body. JSON floats become Decimal so that a client
    sending a decimal where cents are expected is detectable (PRD 2.5)."""
    if raw is None:
        return {}
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8", "replace")
    else:
        text = raw
    if text.strip() == "":
        return {}
    try:
        parsed = json.loads(text, parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _check_string(field, value):
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field.name)
    opts = field.opts
    if opts.get("non_blank") and value.strip() == "":
        bad("Field '%s' must not be blank." % field.name)
    if "min_len" in opts and len(value) < opts["min_len"]:
        bad("Field '%s' is shorter than %d characters." % (field.name, opts["min_len"]))
    if "max_len" in opts and len(value) > opts["max_len"]:
        bad("Field '%s' is longer than %d characters." % (field.name, opts["max_len"]))
    if "pattern" in opts and not re.match(opts["pattern"], value):
        bad("Field '%s' does not match its required pattern." % field.name)
    return value


def _check_int(field, value):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % field.name)
    opts = field.opts
    if "min" in opts and value < opts["min"]:
        bad("Field '%s' is below its minimum of %s." % (field.name, opts["min"]))
    if "max" in opts and value > opts["max"]:
        bad("Field '%s' is above its maximum of %s." % (field.name, opts["max"]))
    return value


def _check_number(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("Field '%s' must be a number." % field.name)
    quantity = frac(value)
    opts = field.opts
    if "min" in opts and quantity < frac(opts["min"]):
        bad("Field '%s' is below its minimum of %s." % (field.name, opts["min"]))
    if "max" in opts and quantity > frac(opts["max"]):
        bad("Field '%s' is above its maximum of %s." % (field.name, opts["max"]))
    return quantity


def _check_enum(field, value):
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field.name)
    if value not in field.opts["values"]:
        bad("Field '%s' carries an unknown value." % field.name)
    return value


def _check_array(field, value):
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field.name)
    opts = field.opts
    if "min_items" in opts and len(value) < opts["min_items"]:
        bad("Field '%s' needs at least %d entries." % (field.name, opts["min_items"]))
    if "max_items" in opts and len(value) > opts["max_items"]:
        bad("Field '%s' carries more than %d entries." % (field.name, opts["max_items"]))
    item = opts.get("item")
    if item == "nonblank_string":
        for entry in value:
            if not isinstance(entry, str) or entry.strip() == "":
                bad("Every entry of '%s' must be a non-blank string." % field.name)
    elif item == "int":
        for entry in value:
            if isinstance(entry, bool) or not isinstance(entry, int):
                bad("Every entry of '%s' must be an integer." % field.name)
    return value


def _check_instant(field, value):
    parsed = parse_instant(value)
    if parsed is None:
        bad("Field '%s' is not a valid ISO 8601 instant." % field.name)
    return parsed


def _check_date(field, value):
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' is not a valid ISO 8601 date." % field.name)
    return parsed


_CHECKERS = {
    "string": _check_string,
    "int": _check_int,
    "number": _check_number,
    "enum": _check_enum,
    "array": _check_array,
    "instant": _check_instant,
    "date": _check_date,
}


def validate(body, fields):
    """Validate a parsed body against an ordered field list."""
    result = {}
    for field in fields:
        raw = body.get(field.name, _MISSING)
        if raw is _MISSING or raw is None:
            if field.required:
                bad("Field '%s' is required." % field.name)
            result[field.name] = field.default
            continue
        result[field.name] = _CHECKERS[field.kind](field, raw)
    return result


EMAIL_MAX = 160


def validate_email(value, name="contact_email"):
    """PRD 3.1: "a contact_email of one to 160 characters containing exactly one
    at-sign with a non-empty local part before it and a non-empty domain part
    after it"."""
    if value.count("@") != 1:
        bad("Field '%s' must contain exactly one at-sign." % name)
    local, _, domain = value.partition("@")
    if local == "" or domain == "":
        bad("Field '%s' needs a non-empty local and domain part." % name)
    return value


def paging(args):
    """PRD 2.3 pagination parameters; an out-of-range value is a structural error."""
    from envelope import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT

    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        if not re.match(r"^-?\d+$", raw_limit.strip()):
            bad("Query parameter 'limit' must be an integer.")
        limit = int(raw_limit)
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad("Query parameter 'limit' must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX))
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        if not re.match(r"^-?\d+$", raw_offset.strip()):
            bad("Query parameter 'offset' must be an integer.")
        offset = int(raw_offset)
        if offset < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit, offset
