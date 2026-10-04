"""Request parsing, body shape validation (validation priority 3), and
pagination (PRD 2.3). All shape failures -> ERR_INVALID_REQUEST (400)."""
from datetime import date, datetime, timezone
from flask import request
from envelope import fail, ok_list


def parse_d(s):
    """Parse a canonical YYYY-MM-DD string to a date. Caller guarantees shape."""
    return date.fromisoformat(s)


def is_date_str(v):
    if not isinstance(v, str):
        return False
    try:
        date.fromisoformat(v)
        return True
    except ValueError:
        return False


def parse_iso_dt(s):
    if not isinstance(s, str):
        return None
    t = s
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail('ERR_INVALID_REQUEST', 'request body must be a JSON object')
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str):
        fail('ERR_INVALID_REQUEST', f'field {name} is required and must be a string')
    return v


def opt_str(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        fail('ERR_INVALID_REQUEST', f'field {name} must be a string')
    return v


def req_int(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if not is_int(v):
        fail('ERR_INVALID_REQUEST', f'field {name} is required and must be an integer')
    if minimum is not None and v < minimum:
        fail('ERR_INVALID_REQUEST', f'field {name} must be >= {minimum}')
    if maximum is not None and v > maximum:
        fail('ERR_INVALID_REQUEST', f'field {name} must be <= {maximum}')
    return v


def opt_int(body, name, minimum=None):
    v = body.get(name)
    if v is None:
        return None
    if not is_int(v):
        fail('ERR_INVALID_REQUEST', f'field {name} must be an integer')
    if minimum is not None and v < minimum:
        fail('ERR_INVALID_REQUEST', f'field {name} must be >= {minimum}')
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        fail('ERR_INVALID_REQUEST', f'field {name} must be one of {sorted(allowed)}')
    return v


def req_date(body, name):
    """Required calendar-date field; returns canonical YYYY-MM-DD string."""
    v = body.get(name)
    if not is_date_str(v):
        fail('ERR_INVALID_REQUEST', f'field {name} is required and must be a YYYY-MM-DD date')
    return date.fromisoformat(v).isoformat()


def opt_date(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not is_date_str(v):
        fail('ERR_INVALID_REQUEST', f'field {name} must be a YYYY-MM-DD date')
    return date.fromisoformat(v).isoformat()


def pagination():
    """limit default 10 (min 1, max 100); offset default 0 (min 0)."""
    args = request.args
    raw_limit = args.get('limit')
    raw_offset = args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail('ERR_INVALID_REQUEST', 'limit must be an integer')
        if limit < 1 or limit > 100:
            fail('ERR_INVALID_REQUEST', 'limit must be between 1 and 100')
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail('ERR_INVALID_REQUEST', 'offset must be an integer')
        if offset < 0:
            fail('ERR_INVALID_REQUEST', 'offset must be >= 0')
    return limit, offset


def paged(records, pub_fn):
    """Sort by created_at ascending (insertion sequence breaks ties, since the
    logical clock makes created_at ties common), then paginate."""
    limit, offset = pagination()
    items = sorted(records, key=lambda r: r['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([pub_fn(r) for r in page], total, limit, offset)
