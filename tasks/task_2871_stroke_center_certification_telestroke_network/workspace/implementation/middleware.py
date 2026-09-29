"""Auth headers (PRD 2.1), request-shape validation (rule 5), enum
membership (rule 7), pagination bounds (rule 6) and path/body existence.
"""
import re

from flask import request

import db
from constants import ROLES
from errors import ApiError, NOT_FOUND_BY_COLLECTION, fail

_INT_RE = re.compile(r"^[+-]?\d+$")
_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


# --- rules 1-3 --------------------------------------------------------------

def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unrecognised X-User-Role '%s'." % role)
    if allowed_roles != "any" and role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return user_id, role


# --- rule 6 -----------------------------------------------------------------

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer.")
        limit = int(raw_limit.strip())
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100.")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset.strip()):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer.")
        offset = int(raw_offset.strip())
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be 0 or greater.")
    return limit, offset


# --- rule 5 / rule 7 --------------------------------------------------------

class Field(object):
    def __init__(self, name, kind, required=True, enum=None, minimum=None,
                 maximum=None, min_len=None, max_len=None, pattern=None,
                 default=None, item_kind=None, item_pattern=None,
                 non_empty_list=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len
        self.pattern = pattern
        self.default = default
        self.item_kind = item_kind
        self.item_pattern = item_pattern
        self.non_empty_list = non_empty_list


def _type_ok(kind, value):
    if kind == "str":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "num":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "dt":
        return isinstance(value, str) and db.parse_iso(value) is not None
    if kind == "list":
        return isinstance(value, list)
    return True


def read_body(spec):
    """Validate the JSON body against ``spec`` following PRD 2.11 rules 5/7."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")

    declared = dict((f.name, f) for f in spec)
    for key in body:
        if key not in declared:
            fail("ERR_INVALID_REQUEST", "Unknown field '%s'." % key)

    values = {}
    # pass 1: presence and declared JSON type
    for field in spec:
        if field.name not in body or body[field.name] is None:
            if field.required:
                fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field.name)
            values[field.name] = field.default
            continue
        value = body[field.name]
        if not _type_ok(field.kind, value):
            if field.kind == "dt":
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must be an ISO 8601 UTC instant." % field.name)
            fail("ERR_INVALID_REQUEST",
                 "Field '%s' must be of type %s." % (field.name, field.kind))
        if field.kind == "list":
            for item in value:
                if not _type_ok(field.item_kind or "str", item):
                    fail("ERR_INVALID_REQUEST",
                         "Field '%s' carries an element of the wrong type." % field.name)
        values[field.name] = value

    # pass 2: declared constraints
    for field in spec:
        value = values.get(field.name)
        if value is None:
            continue
        if field.kind == "str":
            if field.min_len is not None and len(value) < field.min_len:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must not be empty." % field.name)
            if field.max_len is not None and len(value) > field.max_len:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' exceeds %d characters." % (field.name, field.max_len))
            if field.pattern is not None and not field.pattern.match(value):
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' is malformed." % field.name)
        elif field.kind in ("int", "num"):
            if field.minimum is not None and value < field.minimum:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must be %s or greater." % (field.name, field.minimum))
            if field.maximum is not None and value > field.maximum:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must be %s or less." % (field.name, field.maximum))
        elif field.kind == "list":
            if field.non_empty_list and len(value) == 0:
                fail("ERR_INVALID_REQUEST",
                     "Field '%s' must not be empty." % field.name)
            if field.item_pattern is not None:
                for item in value:
                    if not field.item_pattern.match(item):
                        fail("ERR_INVALID_REQUEST",
                             "Field '%s' carries a malformed element." % field.name)

    # pass 3: enum membership
    for field in spec:
        value = values.get(field.name)
        if value is None or field.enum is None:
            continue
        if field.kind == "list":
            for item in value:
                if item not in field.enum:
                    fail("ERR_INVALID_ENUM_VALUE",
                         "'%s' is not a declared value of %s." % (item, field.name))
        elif value not in field.enum:
            fail("ERR_INVALID_ENUM_VALUE",
                 "'%s' is not a declared value of %s." % (value, field.name))
    return values


STATE_CODE_PATTERN = _STATE_CODE_RE


# --- rules 8 / 9 ------------------------------------------------------------

def load_path(collection, record_id):
    record = db.get(collection, record_id)
    if record is None:
        fail(NOT_FOUND_BY_COLLECTION[collection])
    return record


def load_ref(collection, record_id):
    record = db.get(collection, record_id)
    if record is None:
        fail(NOT_FOUND_BY_COLLECTION[collection])
    return record


# --- list filtering ---------------------------------------------------------

def apply_filters(records, mapping):
    """mapping: query-parameter name -> record field name."""
    out = records
    for param, field in mapping.items():
        raw = request.args.get(param)
        if raw is None:
            continue
        if field in ("board_certified", "denominator_included"):
            lowered = raw.strip().lower()
            if lowered in ("true", "1"):
                wanted = True
            elif lowered in ("false", "0"):
                wanted = False
            else:
                return []
            out = [r for r in out if r.get(field) is wanted]
        else:
            out = [r for r in out if r.get(field) == raw]
    return out
