"""Auth, pagination and request-body validation (PRD sections 2.1, 2.3, 2.8)."""

from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError, invalid

# The fifty-one valid two-letter USPS codes (PRD section 3.1).
STATE_CODES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN",
    "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA",
    "WV", "WI", "WY",
]
STATE_SET = set(STATE_CODES)

ROLES = ("CarrierRep", "InsuranceFiler", "VettingAnalyst", "ComplianceOfficer", "RegistryAdmin")

APPLICATION_KINDS = ("NEW", "NAME_CHANGE", "REINSTATEMENT", "SUCCESSOR_IN_INTEREST")
TRANSPORTATION_TYPES = (
    "FOR_HIRE_PROPERTY", "HOUSEHOLD_GOODS", "PASSENGER", "PROPERTY_BROKER", "FREIGHT_FORWARDER",
)
FILING_TYPES = ("BIPD", "CARGO", "SURETY_BOND", "TRUST_FUND")
COMMODITY_CLASSES = (
    "GENERAL_FREIGHT", "HOUSEHOLD_GOODS", "HAZMAT_BULK", "HAZMAT_NONBULK", "PASSENGERS",
)
DISPOSITIONS = ("RETURN", "PUBLISH", "DENY")


# ------------------------------------------------------------------------ auth

def authenticate(allowed_roles):
    """Ladder rungs 1 and 2: headers present and non-empty, then role admitted."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# ------------------------------------------------------------------ pagination

def pagination():
    """limit defaults to 10, min 1, max 100; offset defaults to 0."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise invalid("limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            raise invalid("limit must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise invalid("offset must be a non-negative integer.")
        if offset < 0:
            raise invalid("offset must be a non-negative integer.")
    return limit, offset


def paginate(records):
    limit, offset = pagination()
    total = len(records)
    window = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, meta


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


# ---------------------------------------------------------------- request body

def body_or_empty():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid("The request body must be a JSON object.")
    return data


class Body:
    """Structural validation helper. Every failure is ERR_INVALID_REQUEST."""

    def __init__(self, required=True):
        data = request.get_json(silent=True)
        if data is None:
            if required:
                raise invalid("A JSON request body is required.")
            data = {}
        if not isinstance(data, dict):
            raise invalid("The request body must be a JSON object.")
        self.data = data

    def has(self, name):
        return name in self.data and self.data[name] is not None

    def raw(self, name, default=None):
        value = self.data.get(name, default)
        return default if value is None else value

    # ---- strings

    def req_str(self, name, min_len=1, max_len=None):
        if name not in self.data or self.data[name] is None:
            raise invalid("Field '%s' is required." % name)
        return self._check_str(name, self.data[name], min_len, max_len)

    def opt_str(self, name, min_len=1, max_len=None, default=None):
        if name not in self.data or self.data[name] is None:
            return default
        return self._check_str(name, self.data[name], min_len, max_len)

    def _check_str(self, name, value, min_len, max_len):
        if not isinstance(value, str):
            raise invalid("Field '%s' must be a string." % name)
        if min_len is not None:
            if len(value) < min_len or not value.strip():
                raise invalid("Field '%s' must be a non-blank string." % name)
        if max_len is not None and len(value) > max_len:
            raise invalid("Field '%s' must be at most %d characters." % (name, max_len))
        return value

    def req_text(self, name):
        """A narrative field: required and string-typed, no length constraint."""
        if name not in self.data or self.data[name] is None:
            raise invalid("Field '%s' is required." % name)
        if not isinstance(self.data[name], str):
            raise invalid("Field '%s' must be a string." % name)
        return self.data[name]

    # ---- enums

    def req_enum(self, name, allowed):
        value = self.req_str(name, min_len=None)
        if value not in allowed:
            raise invalid("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
        return value

    def req_state(self, name):
        value = self.req_str(name, min_len=None)
        if value not in STATE_SET:
            raise invalid("Field '%s' must be a valid two-letter state code." % name)
        return value

    def req_state_list(self, name, min_n=1, max_n=51):
        if name not in self.data or self.data[name] is None:
            raise invalid("Field '%s' is required." % name)
        value = self.data[name]
        if not isinstance(value, list):
            raise invalid("Field '%s' must be an array of state codes." % name)
        if len(value) < min_n or len(value) > max_n:
            raise invalid("Field '%s' must hold between %d and %d entries." % (name, min_n, max_n))
        seen = set()
        for item in value:
            if not isinstance(item, str) or item not in STATE_SET:
                raise invalid("Field '%s' contains an invalid state code." % name)
            if item in seen:
                raise invalid("Field '%s' contains duplicate state codes." % name)
            seen.add(item)
        return list(value)

    # ---- integers

    def req_int(self, name, min_v=None, max_v=None):
        if name not in self.data or self.data[name] is None:
            raise invalid("Field '%s' is required." % name)
        return self._check_int(name, self.data[name], min_v, max_v)

    def opt_int(self, name, min_v=None, max_v=None, default=None):
        if name not in self.data or self.data[name] is None:
            return default
        return self._check_int(name, self.data[name], min_v, max_v)

    def _check_int(self, name, value, min_v, max_v):
        if isinstance(value, bool) or not isinstance(value, int):
            raise invalid("Field '%s' must be an integer." % name)
        if min_v is not None and value < min_v:
            raise invalid("Field '%s' must be at least %d." % (name, min_v))
        if max_v is not None and value > max_v:
            raise invalid("Field '%s' must be at most %d." % (name, max_v))
        return value

    # ---- numbers

    def req_number(self, name, lo=None, hi=None, max_dp=None):
        if name not in self.data or self.data[name] is None:
            raise invalid("Field '%s' is required." % name)
        return self._check_number(name, self.data[name], lo, hi, max_dp)

    def _check_number(self, name, value, lo, hi, max_dp):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise invalid("Field '%s' must be a number." % name)
        try:
            dec = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise invalid("Field '%s' must be a number." % name)
        if not dec.is_finite():
            raise invalid("Field '%s' must be a finite number." % name)
        if lo is not None and dec < Decimal(str(lo)):
            raise invalid("Field '%s' must be at least %s." % (name, lo))
        if hi is not None and dec > Decimal(str(hi)):
            raise invalid("Field '%s' must be at most %s." % (name, hi))
        if max_dp is not None and -dec.as_tuple().exponent > max_dp:
            raise invalid("Field '%s' carries at most %d decimals." % (name, max_dp))
        return value

    # ---- booleans

    def opt_bool(self, name, default=False):
        if name not in self.data or self.data[name] is None:
            return default
        value = self.data[name]
        if not isinstance(value, bool):
            raise invalid("Field '%s' must be a boolean." % name)
        return value

    # ---- instants

    def req_instant(self, name):
        if name not in self.data or self.data[name] is None:
            raise invalid("Field '%s' is required." % name)
        parsed = clock.parse(self.data[name])
        if parsed is None:
            raise invalid("Field '%s' must be a parseable ISO 8601 instant." % name)
        return parsed

    def opt_instant(self, name, default=None):
        if name not in self.data or self.data[name] is None:
            return default
        parsed = clock.parse(self.data[name])
        if parsed is None:
            raise invalid("Field '%s' must be a parseable ISO 8601 instant." % name)
        return parsed

    # ---- references

    def req_ref(self, name):
        """A foreign key: must be present and string-typed."""
        value = self.data.get(name)
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        return value
