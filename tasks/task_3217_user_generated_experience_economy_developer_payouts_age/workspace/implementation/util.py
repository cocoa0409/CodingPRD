"""Shared helpers: timestamps, common fields, pagination, audit, body parsing."""
import math
import re
import uuid
from datetime import datetime, timezone

from flask import request

from db import DB
from errors import err, ERR_INVALID_REQUEST

SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso_ms(datetime.now(timezone.utc))


def stamp_new(obj, with_version=True):
    ts = now_iso()
    obj["created_at"] = ts
    if with_version:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1


def audit(actor_user_id, action, subject_type, subject_id, payload=None):
    entry = {
        "id": new_id(),
        "actor_user_id": actor_user_id,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "payload": payload or {},
        "at": now_iso(),
    }
    entry["created_at"] = entry["at"]
    DB.audit_logs[entry["id"]] = entry
    return entry


def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise err(ERR_INVALID_REQUEST, "Malformed JSON payload")
        data = {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Malformed JSON payload")
    return data


def req_str(data, field, min_len=None, max_len=None, pattern=None):
    v = data.get(field)
    if v is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a string")
    if min_len is not None and len(v) < min_len:
        raise err(ERR_INVALID_REQUEST, f"Field {field} too short")
    if max_len is not None and len(v) > max_len:
        raise err(ERR_INVALID_REQUEST, f"Field {field} too long")
    if pattern is not None and not re.fullmatch(pattern, v):
        raise err(ERR_INVALID_REQUEST, f"Field {field} malformed")
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} above maximum {maximum}")
    return v


def opt_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} below minimum {minimum}")
    if maximum is not None and v > maximum:
        raise err(ERR_INVALID_REQUEST, f"Field {field} above maximum {maximum}")
    return v


def opt_enum(data, field, values):
    v = data.get(field)
    if v is None:
        return None
    if v not in values:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(values)}")
    return v


def parse_iso_dt(value, field="timestamp"):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"Field {field} is not valid ISO 8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value, field="date"):
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be YYYY-MM-DD")
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"Field {field} is not a valid date")
    return d


def paginate(items):
    """Offset pagination per PRD §2.3. Returns (page, pagination_meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def list_view(table, filters):
    """filters: list of (query_param, record_field, transform) tuples."""
    items = list(table.values())
    for qp, field, transform in filters:
        raw = request.args.get(qp)
        if raw is None:
            continue
            # unreachable, kept for clarity
        if transform == "bool":
            val = raw.lower() in ("true", "1", "yes")
        elif transform == "int":
            try:
                val = int(raw)
            except ValueError:
                raise err(ERR_INVALID_REQUEST, f"{qp} must be an integer")
        else:
            val = raw
        items = [r for r in items if r.get(field) == val]
    items.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    return paginate(items)


# --- Lexical blocklist for STANDARD chat filter (PRD §3.10) ---
BLOCKLIST = {"damn", "hell", "stupid", "idiot", "hate", "sucks", "crap"}


def filter_standard(text):
    def repl(m):
        return "#" * len(m.group(0))

    pattern = re.compile(
        r"\b(" + "|".join(re.escape(w) for w in sorted(BLOCKLIST)) + r")\b",
        re.IGNORECASE,
    )
    return pattern.sub(repl, text)


def filter_safe(text):
    # Strip digits and most punctuation; keep letters, spaces, apostrophes, hyphens.
    return re.sub(r"[^A-Za-z '\-]", "", text)
