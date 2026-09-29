"""Rungs 10, 20 and 30 of the validation precedence ladder (PRD 2.6).

Authentication is checked before authorization, and both are checked before the
request body is examined at all (PRD 2.1).
"""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_ts

ROLES = (
    "QCAnalyst",
    "ProductionOperator",
    "QAReleaser",
    "RegulatoryAffairs",
    "DistributionPlanner",
    "PlatformAdmin",
)
ALL_ROLES = list(ROLES)

MATERIAL_TYPES = ("ANTIBODY", "ENZYME", "CALIBRATOR_MATERIAL", "BUFFER")
ACCEPTANCE_MODES = ("ALL_PASS", "WEIGHTED_SCORE")
MATERIAL_TEST_CODES = ("POTENCY", "PURITY", "ENDOTOXIN", "IDENTITY")
MATERIAL_LOT_STATUSES = (
    "RECEIVED", "UNDER_TEST", "OOS_INVESTIGATION", "QUALIFIED", "REJECTED",
    "QUARANTINED",
)
RELEASE_TEST_CODES = ("ACTIVITY", "CALIBRATION_SLOPE", "PRECISION", "LINEARITY")
STORAGE_CONDITIONS = ("TWO_TO_EIGHT_C", "MINUS_TWENTY_C")
CLEARANCE_STATUSES = ("DESIGN", "CLEARED", "WITHDRAWN")
RECORD_TYPES = ("DESIGN_INPUT", "DESIGN_OUTPUT", "VERIFICATION", "VALIDATION")
RECORD_STATUSES = ("DRAFT", "APPROVED", "SUPERSEDED")
DISPOSITION_STATUSES = (
    "PLANNED", "IN_PROCESS", "FILLED", "UNDER_RELEASE_TEST", "RELEASED",
    "REJECTED", "RECALLED",
)
DISTRIBUTION_STATUSES = ("WITHHELD", "AVAILABLE", "BLOCKED")
SHELF_LIFE_BASES = ("REAL_TIME", "ACCELERATED", "CLAIM")
COMPONENT_STATUSES = ("CONSUMED", "RETURNED")
FILL_RUN_STATUSES = ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED")
ENVIRONMENTAL_STATES = ("CONFORMING", "EXCURSION", "DISQUALIFIED")
SAMPLE_TYPES = ("VIABLE_AIR", "SURFACE", "NONVIABLE_PARTICLE", "BIOBURDEN_BULK")
SUBJECT_TYPES = ("MATERIAL_LOT", "REAGENT_LOT", "STABILITY_TIMEPOINT")
STUDY_TYPES = ("REAL_TIME", "ACCELERATED")
STUDY_STATUSES = ("PROTOCOL_DRAFT", "APPROVED", "IN_PROGRESS", "COMPLETE", "ABORTED")
SHELF_LIFE_METHODS = ("REAL_TIME_LAST_CONFORMING", "ACCELERATED_Q10")
BRIDGING_STATUSES = ("DRAFT", "APPROVED", "FAILED")
EQUIVALENCE_VERDICTS = ("PENDING", "EQUIVALENT", "NOT_EQUIVALENT")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
FIELD_ACTIONS = ("NONE", "ADVISORY", "CORRECTION", "REMOVAL")
COMPLAINT_STATUSES = (
    "RECEIVED", "TRIAGED", "MALFUNCTION_REPORTED", "FIELD_ACTION_DECIDED",
    "CLOSED",
)
ALLOCATION_POLICIES = ("FEFO_STRICT", "FEFO_WITH_SHORTFALL")
ORDER_STATUSES = (
    "DRAFT", "ALLOCATED", "PARTIALLY_ALLOCATED", "SHIPPED", "CLOSED", "CANCELLED",
)
ALLOCATION_STATUSES = (
    "RESERVED", "SHIPPED", "DELIVERED", "CANCELLED", "QUARANTINED",
)
COLD_CHAIN_STATUSES = ("INTACT", "EXCURSION_ACCEPTABLE", "EXCURSION_REJECTED")
MATERIAL_DECISIONS = ("QUALIFY", "REJECT", "INVESTIGATE")
REAGENT_DECISIONS = ("RELEASE", "REJECT")
BRIDGING_DECISIONS = ("APPROVE", "REJECT")


def bad_request(message="The request is malformed."):
    return ApiError("ERR_INVALID_REQUEST", message)


def authenticate_and_authorize(allowed_roles):
    """Rung 10 then rung 20.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role


def json_body():
    """Rung 30: the body parses as JSON."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad_request("The request body must be a JSON object.")
    return parsed


def _present(body, name):
    """A required field that is present but null counts as missing."""
    return name in body and body[name] is not None


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def to_decimal(value, name):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise bad_request("Field '%s' is not a valid number." % name)


class Body(object):
    """Typed accessors that raise ERR_INVALID_REQUEST (rung 30) on any breach."""

    def __init__(self, data):
        self.data = data

    def has(self, name):
        return _present(self.data, name)

    def raw(self, name):
        return self.data.get(name)

    # -- strings ---------------------------------------------------------
    def req_str(self, name, min_len=1, max_len=None):
        if not _present(self.data, name):
            raise bad_request("Field '%s' is required." % name)
        value = self.data[name]
        if not isinstance(value, str):
            raise bad_request("Field '%s' must be a string." % name)
        if len(value) < min_len:
            raise bad_request("Field '%s' is too short." % name)
        if max_len is not None and len(value) > max_len:
            raise bad_request("Field '%s' is too long." % name)
        return value

    def opt_str(self, name, default=None):
        if not _present(self.data, name):
            return default
        value = self.data[name]
        if not isinstance(value, str):
            raise bad_request("Field '%s' must be a string." % name)
        return value

    # -- numbers ---------------------------------------------------------
    def req_number(self, name, gt=None, ge=None):
        if not _present(self.data, name):
            raise bad_request("Field '%s' is required." % name)
        return self._number(name, self.data[name], gt, ge)

    def opt_number(self, name, default=None, gt=None, ge=None):
        if not _present(self.data, name):
            return default
        return self._number(name, self.data[name], gt, ge)

    def _number(self, name, value, gt, ge):
        if not _is_number(value):
            raise bad_request("Field '%s' must be a number." % name)
        as_dec = to_decimal(value, name)
        if gt is not None and not as_dec > Decimal(str(gt)):
            raise bad_request("Field '%s' must be greater than %s." % (name, gt))
        if ge is not None and not as_dec >= Decimal(str(ge)):
            raise bad_request("Field '%s' must be at least %s." % (name, ge))
        return as_dec

    def req_int(self, name, gt=None, ge=None):
        if not _present(self.data, name):
            raise bad_request("Field '%s' is required." % name)
        return self._int(name, self.data[name], gt, ge)

    def opt_int(self, name, default=None, gt=None, ge=None):
        if not _present(self.data, name):
            return default
        return self._int(name, self.data[name], gt, ge)

    def _int(self, name, value, gt, ge):
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad_request("Field '%s' must be an integer." % name)
        if gt is not None and not value > gt:
            raise bad_request("Field '%s' must be greater than %s." % (name, gt))
        if ge is not None and not value >= ge:
            raise bad_request("Field '%s' must be at least %s." % (name, ge))
        return value

    # -- booleans --------------------------------------------------------
    def req_bool(self, name):
        if not _present(self.data, name):
            raise bad_request("Field '%s' is required." % name)
        value = self.data[name]
        if not isinstance(value, bool):
            raise bad_request("Field '%s' must be a boolean." % name)
        return value

    def opt_bool(self, name, default=None):
        if not _present(self.data, name):
            return default
        value = self.data[name]
        if not isinstance(value, bool):
            raise bad_request("Field '%s' must be a boolean." % name)
        return value

    # -- enums -----------------------------------------------------------
    def req_enum(self, name, members):
        value = self.req_str(name)
        if value not in members:
            raise bad_request("Field '%s' is not a declared member of its enumeration." % name)
        return value

    def opt_enum(self, name, members, default=None):
        if not _present(self.data, name):
            return default
        value = self.data[name]
        if not isinstance(value, str) or value not in members:
            raise bad_request("Field '%s' is not a declared member of its enumeration." % name)
        return value

    # -- arrays ----------------------------------------------------------
    def req_code_array(self, name, members=None):
        if not _present(self.data, name):
            raise bad_request("Field '%s' is required." % name)
        value = self.data[name]
        if not isinstance(value, list) or len(value) == 0:
            raise bad_request("Field '%s' must be a non-empty array." % name)
        for item in value:
            if not isinstance(item, str) or item == "":
                raise bad_request("Field '%s' must contain non-empty strings." % name)
            if members is not None and item not in members:
                raise bad_request(
                    "Field '%s' contains a value outside its enumeration." % name)
        return list(value)

    def req_month_array(self, name):
        if not _present(self.data, name):
            raise bad_request("Field '%s' is required." % name)
        value = self.data[name]
        if not isinstance(value, list) or len(value) == 0:
            raise bad_request("Field '%s' must be a non-empty array." % name)
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int):
                raise bad_request("Field '%s' must contain integers." % name)
        if value[0] != 0:
            raise bad_request("Field '%s' must begin at 0." % name)
        for index in range(1, len(value)):
            if value[index] <= value[index - 1]:
                raise bad_request("Field '%s' must be strictly increasing." % name)
        return list(value)

    # -- instants --------------------------------------------------------
    def req_ts(self, name):
        if not _present(self.data, name):
            raise bad_request("Field '%s' is required." % name)
        value = self.data[name]
        parsed = parse_ts(value) if isinstance(value, str) else None
        if parsed is None:
            raise bad_request("Field '%s' must be an ISO 8601 instant." % name)
        return parsed

    def opt_ts(self, name, default=None):
        if not _present(self.data, name):
            return default
        value = self.data[name]
        parsed = parse_ts(value) if isinstance(value, str) else None
        if parsed is None:
            raise bad_request("Field '%s' must be an ISO 8601 instant." % name)
        return parsed


def pagination():
    """PRD 2.3.  Out-of-range values are rejected, never clamped."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be at least 0.")
    return limit, offset


def enum_filter(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        raise bad_request("Query parameter '%s' is not a declared enumeration member." % name)
    return value


def str_filter(name):
    return request.args.get(name)


def bool_filter(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    raise bad_request("Query parameter '%s' must be true or false." % name)


def paginate(items, limit, offset):
    return items[offset:offset + limit]
