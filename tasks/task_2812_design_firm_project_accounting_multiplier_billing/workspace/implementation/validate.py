"""Request/query shape validation -- ladder rung 7, ERR_INVALID_REQUEST (PRD 2.5, 2.8)."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

ROLE_CODES = ["PRINCIPAL", "PROJECT_ARCHITECT", "DESIGNER", "ADMIN"]
EXPENSE_CATEGORIES = ["TRAVEL", "MILEAGE", "PRINTING", "MEALS", "ENTERTAINMENT", "PERMIT_FEE"]
CONTRACT_TYPES = ["FIXED_FEE", "TIME_AND_MATERIALS", "COST_PLUS_FIXED_FEE"]
PERCENT_COMPLETE_METHODS = ["EFFORT_BASED", "ASSESSED"]
FEE_BASES = ["PERCENT_OF_CONTRACT", "LUMP_SUM"]
PROJECT_STATUSES = ["SETUP", "ACTIVE", "CLOSED"]
PHASE_STATUSES = ["PLANNED", "IN_PROGRESS", "COMPLETE"]
MULTIPLIER_STATUSES = ["ACTIVE", "SUPERSEDED"]
TIME_ENTRY_STATUSES = ["SUBMITTED", "APPROVED", "BILLED", "WRITTEN_OFF"]
ALLOWABILITY_STATUSES = ["PENDING_REVIEW", "ALLOWED", "DISALLOWED"]
EXPENSE_BILLING_STATUSES = ["UNBILLED", "BILLED"]
SUBCONTRACT_STATUSES = ["DRAFT", "EXECUTED", "CLOSED"]
CI_APPROVAL_STATUSES = ["RECEIVED", "APPROVED", "REJECTED"]
CI_PAYMENT_STATUSES = ["WITHHELD", "RELEASED"]
CI_BILLING_STATUSES = ["UNBILLED", "BILLED_TO_CLIENT"]
INVOICE_STATUSES = ["DRAFT", "PENDING_CLIENT_REVIEW", "REVISION_REQUESTED", "APPROVED",
                    "PAID", "WRITTEN_OFF", "VOID"]
WRITE_OFF_STATUSES = ["PENDING_PM_APPROVAL", "PENDING_CONTROLLER_APPROVAL", "APPROVED"]
WRITE_OFF_TARGET_TYPES = ["UNBILLED_LABOR_WIP", "INVOICE_RECEIVABLE"]
CERTIFICATION_STATUSES = ["SUBMITTED", "CERTIFIED", "REJECTED"]


def bad(msg):
    return ApiError("ERR_INVALID_REQUEST", msg)


def peek_body():
    """Best-effort body parse used by the authorization rungs (3-6), which run
    ahead of the shape rung (7) and must not raise a shape error themselves."""
    try:
        return _parse_body()
    except ApiError:
        return {}


def body_json():
    return _parse_body()


def _parse_body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        raise bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def _present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, allow_empty=False):
    if not _present(body, name):
        raise bad("Field '%s' is required." % name)
    v = body[name]
    if not isinstance(v, str):
        raise bad("Field '%s' must be a string." % name)
    if not allow_empty and v.strip() == "":
        raise bad("Field '%s' may not be empty." % name)
    return v


def opt_string(body, name, allow_empty=True):
    if not _present(body, name):
        return None
    return req_string(body, name, allow_empty=allow_empty)


def req_bool(body, name):
    if not _present(body, name):
        raise bad("Field '%s' is required." % name)
    v = body[name]
    if not isinstance(v, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return v


def req_enum(body, name, members):
    v = req_string(body, name)
    if v not in members:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return v


def _numeric(body, name):
    v = body[name]
    if isinstance(v, bool):
        raise bad("Field '%s' must be a number." % name)
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, Decimal):
        return v
    if isinstance(v, float):
        return Decimal(str(v))
    raise bad("Field '%s' must be a number." % name)


def _scale_of(v):
    exp = v.as_tuple().exponent
    if not isinstance(exp, int):
        raise bad("Malformed number.")
    return -exp if exp < 0 else 0


def req_money(body, name, minimum=None, min_exclusive=None, maximum=None):
    if not _present(body, name):
        raise bad("Field '%s' is required." % name)
    v = _numeric(body, name)
    _check_money_range(name, v, minimum, min_exclusive, maximum)
    return v


def opt_money(body, name, minimum=None, min_exclusive=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return req_money(body, name, minimum, min_exclusive, maximum)


def _check_money_range(name, v, minimum, min_exclusive, maximum):
    if _scale_of(v) > 2:
        raise bad("Field '%s' may carry at most 2 decimal places." % name)
    if minimum is not None and v < minimum:
        raise bad("Field '%s' must be at least %s." % (name, minimum))
    if min_exclusive is not None and v <= min_exclusive:
        raise bad("Field '%s' must be greater than %s." % (name, min_exclusive))
    if maximum is not None and v > maximum:
        raise bad("Field '%s' may not exceed %s." % (name, maximum))


def req_ratio(body, name, minimum=None, maximum=None, min_exclusive=None):
    if not _present(body, name):
        raise bad("Field '%s' is required." % name)
    v = _numeric(body, name)
    if _scale_of(v) > 4:
        raise bad("Field '%s' may carry at most 4 decimal places." % name)
    if minimum is not None and v < minimum:
        raise bad("Field '%s' must be at least %s." % (name, minimum))
    if min_exclusive is not None and v <= min_exclusive:
        raise bad("Field '%s' must be greater than %s." % (name, min_exclusive))
    if maximum is not None and v > maximum:
        raise bad("Field '%s' may not exceed %s." % (name, maximum))
    return v


def opt_ratio(body, name, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        return default
    return req_ratio(body, name, minimum, maximum)


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        raise bad("Field '%s' is required." % name)
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad("Field '%s' must be an integer." % name)
    if minimum is not None and v < minimum:
        raise bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and v > maximum:
        raise bad("Field '%s' may not exceed %d." % (name, maximum))
    return v


def parse_date_str(name, v):
    if not isinstance(v, str):
        raise bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
    try:
        parsed = datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
    return parsed


def req_date(body, name):
    if not _present(body, name):
        raise bad("Field '%s' is required." % name)
    return parse_date_str(name, body[name])


def opt_date(body, name):
    if not _present(body, name):
        return None
    return parse_date_str(name, body[name])


def req_string_list(body, name, members):
    if not _present(body, name):
        raise bad("Field '%s' is required." % name)
    v = body[name]
    if not isinstance(v, list):
        raise bad("Field '%s' must be an array." % name)
    for item in v:
        if not isinstance(item, str) or item not in members:
            raise bad("Field '%s' must be a subset of %s." % (name, ", ".join(members)))
    return list(v)


def parse_instant(name, v):
    if not isinstance(v, str) or v.strip() == "":
        raise bad("Field '%s' must be an ISO 8601 instant." % name)
    text = v.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad("Field '%s' must be an ISO 8601 instant." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def query_enum(name, members):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in members:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return v


def query_bool(name):
    v = request.args.get(name)
    if v is None:
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    raise bad("Query parameter '%s' must be true or false." % name)


def query_int(name):
    v = request.args.get(name)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise bad("Query parameter '%s' must be an integer." % name)


def query_str(name):
    return request.args.get(name)


def forbid(body, name, reason):
    if name in body and body[name] is not None:
        raise bad(reason)
