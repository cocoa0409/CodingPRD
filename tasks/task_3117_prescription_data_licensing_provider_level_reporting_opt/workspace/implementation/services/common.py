"""Shared helpers: JSON body validation, entity minting, timestamps."""

import re
import uuid
from datetime import datetime, timezone

from flask import request

from errors import err_invalid_request


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def body_json():
    """Return the request JSON body as a dict; empty body becomes {}.

    Raises ERR_INVALID_REQUEST for malformed JSON or a non-object body.
    """
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid_request("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")


def check_str(data, field):
    v = data[field]
    if not isinstance(v, str) or v == "":
        raise err_invalid_request(f"Field {field} must be a non-empty string")
    return v


def check_str_opt(data, field):
    if field not in data or data[field] is None:
        return None
    return check_str(data, field)


def check_int(data, field, min_v=None, max_v=None):
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"Field {field} must be an integer")
    if min_v is not None and v < min_v:
        raise err_invalid_request(f"Field {field} must be >= {min_v}")
    if max_v is not None and v > max_v:
        raise err_invalid_request(f"Field {field} must be <= {max_v}")
    return v


def check_int_opt(data, field, min_v=None, max_v=None):
    if field not in data or data[field] is None:
        return None
    return check_int(data, field, min_v, max_v)


def check_num(data, field, gt=None, min_v=None, max_v=None):
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"Field {field} must be a number")
    if gt is not None and not v > gt:
        raise err_invalid_request(f"Field {field} must be > {gt}")
    if min_v is not None and not v >= min_v:
        raise err_invalid_request(f"Field {field} must be >= {min_v}")
    if max_v is not None and not v <= max_v:
        raise err_invalid_request(f"Field {field} must be <= {max_v}")
    return v


def check_num_opt(data, field, gt=None, min_v=None, max_v=None):
    if field not in data or data[field] is None:
        return None
    return check_num(data, field, gt, min_v, max_v)


def check_enum(data, field, allowed):
    v = data[field]
    if not isinstance(v, str) or v not in allowed:
        raise err_invalid_request(f"Field {field} must be one of {sorted(allowed)}")
    return v


def check_bool(data, field):
    v = data[field]
    if not isinstance(v, bool):
        raise err_invalid_request(f"Field {field} must be a boolean")
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def check_date(data, field):
    v = data[field]
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise err_invalid_request(f"Field {field} must be an ISO date (YYYY-MM-DD)")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        raise err_invalid_request(f"Field {field} must be a valid ISO date")
    return v


def check_date_opt(data, field):
    if field not in data or data[field] is None:
        return None
    return check_date(data, field)


_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def check_period(data, field):
    v = data[field]
    if not isinstance(v, str) or not _PERIOD_RE.match(v):
        raise err_invalid_request(f"Field {field} must be a period code (YYYY-MM)")
    month = int(v[5:7])
    if month < 1 or month > 12:
        raise err_invalid_request(f"Field {field} must be a valid period code")
    return v


def check_str_list(data, field):
    v = data[field]
    if not isinstance(v, list):
        raise err_invalid_request(f"Field {field} must be an array")
    for item in v:
        if not isinstance(item, str):
            raise err_invalid_request(f"Field {field} must be an array of strings")
    return v


def mint(store, entity, common=True):
    """Assign system fields and insert into the store."""
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    if common:
        entity["updated_at"] = ts
        entity["version"] = 1
    store[entity["id"]] = entity
    return entity


def touch(entity):
    """Mutation bookkeeping: bump version and refresh updated_at."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
