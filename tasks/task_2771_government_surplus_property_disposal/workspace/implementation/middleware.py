"""Authentication, authorisation and request-shape validation (PRD 2.1, 2.12)."""
import json
from decimal import Decimal
from functools import wraps

from flask import request, g

import db as store
from db import db, parse_date, parse_instant
from errors import ApiError
from response import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT

ROLES = (
    "ProgramAdmin",
    "DisposalOfficer",
    "SurplusAssessor",
    "ClearanceTechnician",
    "FinanceController",
    "AgencyOfficer",
    "Bidder",
)

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"


class Ctx(object):
    __slots__ = ("user_id", "role", "agency", "bidder", "touched", "body")

    def __init__(self):
        self.user_id = None
        self.role = None
        self.agency = None
        self.bidder = None
        self.touched = store.Touched()
        self.body = {}

    def touch(self, row):
        self.touched.touch(row)


def authenticate(allowed_roles):
    """Precedence steps 1-3 of PRD 2.12."""
    ctx = Ctx()
    role = request.headers.get(ROLE_HEADER)
    if role is None or role.strip() == "" or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-Role is missing or names an unknown role")
    ctx.role = role
    user_id = request.headers.get(USER_HEADER)
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID is missing")
    ctx.user_id = user_id
    if role == "AgencyOfficer":
        agency = db.agencies.get(user_id)
        if agency is None:
            raise ApiError("ERR_UNAUTHENTICATED",
                           "X-User-ID does not resolve to an Agency row")
        ctx.agency = agency
    elif role == "Bidder":
        bidder = db.bidders.get(user_id)
        if bidder is None:
            raise ApiError("ERR_UNAUTHENTICATED",
                           "X-User-ID does not resolve to a Bidder row")
        ctx.bidder = bidder
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role " + role + " may not perform this operation")
    return ctx


def agency_scope(ctx, agency_id):
    """Precedence step 4."""
    if ctx.role != "AgencyOfficer":
        return
    if agency_id is None:
        return
    if agency_id != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_AGENCY_SCOPE",
                       "An AgencyOfficer may only act for its own agency")


def bidder_scope(ctx, bidder_id):
    """Precedence step 5."""
    if ctx.role != "Bidder":
        return
    if bidder_id is None:
        return
    if bidder_id != ctx.user_id:
        raise ApiError("ERR_FORBIDDEN_BIDDER_SCOPE",
                       "A Bidder may only act on its own record")


def endpoint(roles):
    """Wraps a view: performs steps 1-3 and hands a Ctx to the handler."""
    def deco(fn):
        @wraps(fn)
        def inner(**kwargs):
            with store.lock:
                ctx = authenticate(roles)
                g.ctx = ctx
                return fn(ctx, **kwargs)
        return inner
    return deco


def read_body():
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return parsed


class Fields(object):
    """Step 6 (shape) checks run eagerly; step 7 (enum) checks are deferred until
    done() so that every shape problem outranks every enum problem."""

    def __init__(self, body):
        self.body = body
        self.v = {}
        self._enums = []

    def _bad(self, key, why):
        raise ApiError("ERR_INVALID_REQUEST", "'" + key + "' " + why)

    def _present(self, key, required):
        if key not in self.body or self.body[key] is None:
            if required:
                self._bad(key, "is required")
            return False
        return True

    def string(self, key, required=False, minlen=None, maxlen=None, default=None):
        if not self._present(key, required):
            self.v[key] = default
            return default
        val = self.body[key]
        if not isinstance(val, str):
            self._bad(key, "must be a string")
        if minlen is not None and len(val) < minlen:
            self._bad(key, "must be at least %d characters" % minlen)
        if maxlen is not None and len(val) > maxlen:
            self._bad(key, "must be at most %d characters" % maxlen)
        self.v[key] = val
        return val

    def integer(self, key, required=False, minv=None, maxv=None, default=None):
        if not self._present(key, required):
            self.v[key] = default
            return default
        val = self.body[key]
        if isinstance(val, bool) or not isinstance(val, int):
            self._bad(key, "must be an integer")
        if minv is not None and val < minv:
            self._bad(key, "must be >= %d" % minv)
        if maxv is not None and val > maxv:
            self._bad(key, "must be <= %d" % maxv)
        self.v[key] = val
        return val

    def boolean(self, key, required=False, default=None):
        if not self._present(key, required):
            self.v[key] = default
            return default
        val = self.body[key]
        if not isinstance(val, bool):
            self._bad(key, "must be a boolean")
        self.v[key] = val
        return val

    def rate(self, key, required=False, minv=None, maxv=None, default=None):
        if not self._present(key, required):
            self.v[key] = default
            return default
        val = self.body[key]
        if isinstance(val, bool) or not isinstance(val, (int, Decimal)):
            self._bad(key, "must be a number")
        dec = Decimal(val) if not isinstance(val, Decimal) else val
        if minv is not None and dec < minv:
            self._bad(key, "is below the permitted minimum")
        if maxv is not None and dec > maxv:
            self._bad(key, "is above the permitted maximum")
        self.v[key] = dec
        return dec

    def date(self, key, required=False, default=None):
        if not self._present(key, required):
            self.v[key] = default
            return default
        try:
            val = parse_date(self.body[key])
        except Exception:
            self._bad(key, "must be a YYYY-MM-DD date")
        self.v[key] = val
        return val

    def instant(self, key, required=False, default=None):
        if not self._present(key, required):
            self.v[key] = default
            return default
        try:
            val = parse_instant(self.body[key])
        except Exception:
            self._bad(key, "must be an ISO 8601 instant")
        self.v[key] = val
        return val

    def enum(self, key, allowed, required=False, default=None):
        if not self._present(key, required):
            self.v[key] = default
            return default
        val = self.body[key]
        if not isinstance(val, str):
            self._bad(key, "must be a string")
        self._enums.append((key, allowed))
        self.v[key] = val
        return val

    def done(self):
        for key, allowed in self._enums:
            if self.v[key] not in allowed:
                raise ApiError("ERR_INVALID_ENUM_VALUE",
                               "'" + key + "' must be one of " + ", ".join(sorted(allowed)))
        return self

    def __getitem__(self, key):
        return self.v.get(key)

    def has(self, key):
        return key in self.body and self.body[key] is not None


def future_date(value, label):
    """Step 10."""
    if value is not None and value > store.today():
        raise ApiError("ERR_FUTURE_DATE",
                       label + " may not lie in the future relative to the logical clock")


def list_params(enum_filters=None):
    """Steps 7 (enum-typed query filters) and 8 (pagination)."""
    args = request.args
    filters = {}
    if enum_filters:
        for key, allowed in enum_filters.items():
            raw = args.get(key)
            if raw is None or raw == "":
                continue
            if raw not in allowed:
                raise ApiError("ERR_INVALID_ENUM_VALUE",
                               "'" + key + "' must be one of " + ", ".join(sorted(allowed)))
            filters[key] = raw
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw = args.get("limit")
    if raw is not None and raw != "":
        try:
            limit = int(raw)
        except Exception:
            raise ApiError("ERR_INVALID_PAGINATION", "'limit' must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION",
                           "'limit' must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    raw = args.get("offset")
    if raw is not None and raw != "":
        try:
            offset = int(raw)
        except Exception:
            raise ApiError("ERR_INVALID_PAGINATION", "'offset' must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "'offset' must be >= 0")
    return filters, limit, offset


def plain_filters(keys):
    out = {}
    for key in keys:
        raw = request.args.get(key)
        if raw is not None and raw != "":
            out[key] = raw
    return out
