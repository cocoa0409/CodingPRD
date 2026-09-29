"""Request-shape validation (validation band 4) and pagination parsing."""
from flask import request

from common import canonical_instant, parse_date
from errors import fail
import store

BAD = "ERR_INVALID_REQUEST"


def json_body():
    """Return the request body as a dict. Absent body is treated as empty."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail(BAD, "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail(BAD, "Request body must be a JSON object.")
    return payload


def _present(body, name):
    return name in body and body[name] is not None


def forbid(body, name):
    if _present(body, name):
        fail(BAD, "Field '%s' is not permitted here." % name)


def require_present(body, name):
    if not _present(body, name):
        fail(BAD, "Field '%s' is required." % name)


def string_field(body, name, required=True, default=None, enum=None,
                 allow_blank=False):
    if not _present(body, name):
        if required:
            fail(BAD, "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        fail(BAD, "Field '%s' must be a string." % name)
    if not allow_blank and value.strip() == "":
        fail(BAD, "Field '%s' must not be blank." % name)
    if enum is not None and value not in enum:
        fail(BAD, "Field '%s' must be one of %s." % (name, ", ".join(enum)))
    return value


def int_field(body, name, required=True, default=None, minimum=None,
              maximum=None, allowed=None):
    if not _present(body, name):
        if required:
            fail(BAD, "Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail(BAD, "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail(BAD, "Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail(BAD, "Field '%s' must be at most %s." % (name, maximum))
    if allowed is not None and value not in allowed:
        fail(BAD, "Field '%s' must be one of %s." % (name, allowed))
    return value


def number_field(body, name, required=True, default=None, minimum=None,
                 exclusive_minimum=None, allowed=None):
    if not _present(body, name):
        if required:
            fail(BAD, "Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(BAD, "Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        fail(BAD, "Field '%s' must be at least %s." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        fail(BAD, "Field '%s' must be greater than %s." % (name, exclusive_minimum))
    if allowed is not None and value not in allowed:
        fail(BAD, "Field '%s' must be one of %s." % (name, allowed))
    return value


def bool_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            fail(BAD, "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        fail(BAD, "Field '%s' must be a boolean." % name)
    return value


def instant_field(body, name, required=True, default=None):
    text = string_field(body, name, required=required, default=None)
    if text is None:
        return default
    canonical = canonical_instant(text)
    if canonical is None:
        fail(BAD, "Field '%s' must be an ISO-8601 UTC instant." % name)
    return canonical


def date_field(body, name, required=True, default=None):
    text = string_field(body, name, required=required, default=None)
    if text is None:
        return default
    if parse_date(text) is None:
        fail(BAD, "Field '%s' must be a YYYY-MM-DD date." % name)
    return text


def str_list_field(body, name, required=True, default=None, enum=None):
    if not _present(body, name):
        if required:
            fail(BAD, "Field '%s' is required." % name)
        return list(default) if default is not None else None
    value = body[name]
    if not isinstance(value, list):
        fail(BAD, "Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            fail(BAD, "Field '%s' must contain only strings." % name)
        if enum is not None and item not in enum:
            fail(BAD, "Field '%s' contains an undeclared member." % name)
    return list(value)


# -------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail(BAD, "Query parameter 'limit' must be an integer.")
        if str(raw).strip() != str(limit):
            fail(BAD, "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail(BAD, "Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail(BAD, "Query parameter 'offset' must be an integer.")
        if str(raw).strip() != str(offset):
            fail(BAD, "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail(BAD, "Query parameter 'offset' must not be negative.")
    return limit, offset


def apply_filters(records, spec):
    """spec maps query-parameter name -> record field name."""
    args = request.args
    out = records
    for param, field in spec.items():
        if param not in args:
            continue
        wanted = args.get(param)
        filtered = []
        for rec in out:
            value = rec.get(field)
            if isinstance(value, bool):
                if str(wanted).strip().lower() == ("true" if value else "false"):
                    filtered.append(rec)
            elif value is None:
                continue
            elif str(value) == wanted:
                filtered.append(rec)
        out = filtered
    return out


def paginate(records, limit, offset):
    total = len(records)
    page = records[offset:offset + limit]
    return [store.serialize(r) for r in page], total
