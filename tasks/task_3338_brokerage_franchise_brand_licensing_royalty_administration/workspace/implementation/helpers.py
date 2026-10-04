"""Request-body and field validation helpers plus serialization/pagination."""
import re

from flask import request

from envelope import ok_list, parse_pagination
from errors import ApiError

PERIOD_RE = re.compile(r'^\d{4}-(0[1-9]|1[0-2])$')


def body():
    """JSON object body; absent body treated as {} (action endpoints)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'request body must be a JSON object')
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(d, name):
    v = d.get(name)
    if not isinstance(v, str):
        raise ApiError('ERR_INVALID_REQUEST', 400, f'{name} is required and must be a string')
    return v


def req_nonempty_str(d, name):
    v = req_str(d, name)
    if v == '':
        raise ApiError('ERR_INVALID_REQUEST', 400, f'{name} must not be empty')
    return v


def req_int(d, name):
    v = d.get(name)
    if not is_int(v):
        raise ApiError('ERR_INVALID_REQUEST', 400, f'{name} is required and must be an integer')
    return v


def req_period_month(d, name='period_month'):
    v = d.get(name)
    if not isinstance(v, str) or not PERIOD_RE.match(v):
        raise ApiError('ERR_INVALID_REQUEST', 400, f'{name} must be a YYYY-MM month key')
    return v


def req_enum(d, name, allowed):
    v = d.get(name)
    if v not in allowed:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       f'{name} must be one of {sorted(allowed)}')
    return v


def serialize(e):
    return {k: v for k, v in e.items() if not k.startswith('_')}


def apply_filters(items, args, names):
    out = items
    for name in names:
        v = args.get(name)
        if v is not None:
            out = [e for e in out if e.get(name) == v]
    return out


def paginate(items, args, filter_names=()):
    """Sort by created_at ascending (insertion order tiebreak), filter, slice."""
    limit, offset = parse_pagination(args)
    out = apply_filters(list(items), args, filter_names)
    out = sorted(out, key=lambda e: (e['created_at'], e['_seq']))
    total = len(out)
    page = out[offset:offset + limit]
    return ok_list([serialize(e) for e in page], total, limit, offset)
