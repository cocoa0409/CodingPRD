"""Request body shape validation (PRD 2.6 step 3) and pagination parsing
(PRD 2.3: limit default 10, min 1, max 100; offset default 0)."""

import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
TIME_RE = re.compile(r'^\d{2}:\d{2}$')
INSTITUTION_CODE_RE = re.compile(r'^[A-Z0-9]{4,8}$')


def _bad(msg):
    raise ApiError('ERR_INVALID_REQUEST', 400, msg)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        _bad('Request body must be a JSON object')
    return data


def req_str(data, field, allow_empty=False):
    v = data.get(field)
    if not isinstance(v, str) or (not allow_empty and v == ''):
        _bad('{} is required and must be a string'.format(field))
    return v


def req_int(data, field, min_v=None, max_v=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad('{} is required and must be an integer'.format(field))
    if min_v is not None and v < min_v:
        _bad('{} must be >= {}'.format(field, min_v))
    if max_v is not None and v > max_v:
        _bad('{} must be <= {}'.format(field, max_v))
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        _bad('{} is required and must be a boolean'.format(field))
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if v not in values:
        _bad('{} must be one of {}'.format(field, sorted(values)))
    return v


def parse_date_str(v):
    """Strict YYYY-MM-DD -> datetime.date, or None."""
    if not isinstance(v, str) or not DATE_RE.match(v):
        return None
    try:
        return datetime.strptime(v, '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_time_str(v):
    """Strict HH:MM -> (hour, minute), or None."""
    if not isinstance(v, str) or not TIME_RE.match(v):
        return None
    h = int(v[0:2])
    m = int(v[3:5])
    if h > 23 or m > 59:
        return None
    return (h, m)


def req_date(data, field):
    v = data.get(field)
    if parse_date_str(v) is None:
        _bad('{} must be a valid YYYY-MM-DD date'.format(field))
    return v


def req_time(data, field):
    v = data.get(field)
    if parse_time_str(v) is None:
        _bad('{} must be a valid HH:MM time'.format(field))
    return v


def req_section_raws(data):
    v = data.get('section_raws')
    if not isinstance(v, list) or len(v) != 3:
        _bad('section_raws must be exactly 3 integers')
    for x in v:
        if isinstance(x, bool) or not isinstance(x, int) or x < 0 or x > 50:
            _bad('each section_raws entry must be an integer between 0 and 50')
    return v


def req_institution_code(data):
    v = data.get('institution_code')
    if not isinstance(v, str) or not INSTITUTION_CODE_RE.match(v):
        _bad('institution_code must match ^[A-Z0-9]{4,8}$')
    return v


def req_iso8601(data, field):
    v = data.get(field)
    dt = parse_iso8601(v)
    if dt is None:
        _bad('{} must be a valid ISO 8601 timestamp'.format(field))
    return dt


def parse_iso8601(v):
    if not isinstance(v, str):
        return None
    s = v.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pagination():
    """Parse limit/offset query params per PRD 2.3."""
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad('limit must be an integer')
        if limit < 1 or limit > 100:
            _bad('limit must be between 1 and 100')
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad('offset must be an integer')
        if offset < 0:
            _bad('offset must be >= 0')
    return limit, offset
