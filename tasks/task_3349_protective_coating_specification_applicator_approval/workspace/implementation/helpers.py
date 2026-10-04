"""Shared helpers: timestamps, body/field validation, entity lifecycle, pagination."""
import uuid
from datetime import datetime, timezone

from flask import request

from errors import ApiError
from storage import store


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime string to an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith('Z'):
        s = s[:-1] + '+00:00'
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def invalid(message):
    raise ApiError('ERR_INVALID_REQUEST', 400, message)


def body():
    """JSON request body as a dict; empty body -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid('request body must be a JSON object')
    return data


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _check(name, v, kind, enum):
    if kind == 'str':
        if not isinstance(v, str):
            invalid('%s must be a string' % name)
    elif kind == 'int':
        if not is_int(v):
            invalid('%s must be an integer' % name)
    elif kind == 'num':
        if not is_number(v):
            invalid('%s must be a number' % name)
    elif kind == 'bool':
        if not isinstance(v, bool):
            invalid('%s must be a boolean' % name)
    elif kind == 'dt':
        v = parse_dt(v)
        if v is None:
            invalid('%s must be an ISO8601 UTC datetime' % name)
    elif kind == 'list_num':
        if not isinstance(v, list) or not all(is_number(x) for x in v):
            invalid('%s must be a list of numbers' % name)
    if enum is not None and v not in enum:
        invalid('%s must be one of %s' % (name, sorted(enum)))
    return v


def req(payload, name, kind='any', enum=None):
    """Required field: missing or explicit null -> ERR_INVALID_REQUEST."""
    if name not in payload or payload[name] is None:
        invalid('missing required field: %s' % name)
    return _check(name, payload[name], kind, enum)


def opt(payload, name, default=None, kind='any', enum=None):
    """Optional field: absent or explicit null -> default."""
    if name not in payload or payload[name] is None:
        return default
    return _check(name, payload[name], kind, enum)


def new_entity():
    """Common system-managed fields per PRD §2.4. version starts at 1."""
    now = store.now()
    return {
        'id': str(uuid.uuid4()),
        'created_at': iso(now),
        'updated_at': iso(now),
        'version': 1,
        '_seq': store.next_seq(),
        '_created_dt': now,
    }


def touch(entity):
    """Every modification refreshes updated_at and increments version by one."""
    entity['version'] += 1
    entity['updated_at'] = iso(store.now())


def pub(entity):
    """Public view: strip internal underscore-prefixed bookkeeping fields."""
    return {k: v for k, v in entity.items() if not k.startswith('_')}


def get_or_404(collection, rid, error_id, message):
    entity = collection.get(rid)
    if entity is None:
        raise ApiError(error_id, 404, message)
    return entity


def page_args():
    limit = 10
    offset = 0
    raw_limit = request.args.get('limit')
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid('limit must be an integer')
        if limit < 1 or limit > 100:
            invalid('limit must be at least 1 and at most 100')
    raw_offset = request.args.get('offset')
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid('offset must be an integer')
        if offset < 0:
            invalid('offset must be at least 0')
    return limit, offset


def paginate(items, limit, offset):
    """Sort by creation ascending, apply offset/limit, return (page, total_count)."""
    ordered = sorted(items, key=lambda e: e['_seq'])
    total = len(ordered)
    page = [pub(e) for e in ordered[offset:offset + limit]]
    return page, total
