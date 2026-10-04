import uuid
from datetime import datetime, timezone

from flask import jsonify, request


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


NOT_FOUND = {
    'markets': 'ERR_MARKET_NOT_FOUND',
    'brokerages': 'ERR_BROKERAGE_NOT_FOUND',
    'agents': 'ERR_AGENT_NOT_FOUND',
    'teams': 'ERR_TEAM_NOT_FOUND',
    'memberships': 'ERR_TEAM_MEMBERSHIP_NOT_FOUND',
    'orders': 'ERR_SHARE_ORDER_NOT_FOUND',
    'leads': 'ERR_LEAD_NOT_FOUND',
    'assignments': 'ERR_ASSIGNMENT_NOT_FOUND',
    'connections': 'ERR_LIVE_CONNECTION_NOT_FOUND',
    'claims': 'ERR_CREDIT_CLAIM_NOT_FOUND',
    'listings': 'ERR_LISTING_NOT_FOUND',
    'disputes': 'ERR_DISPUTE_NOT_FOUND',
}

STORE = {
    'markets': {}, 'brokerages': {}, 'agents': {}, 'teams': {}, 'memberships': {},
    'orders': {}, 'payments': {}, 'leads': {}, 'assignments': {}, 'connections': {},
    'recordings': {}, 'ratings': {}, 'claims': {}, 'listings': {}, 'disputes': {},
    'snapshots': {}, 'ops_runs': {},
}

# Internal audit trail of scoring events (never serialized): one entry per
# scoring-relevant mutation, used to compute the official (windowed) score
# variant at ops-run time per PRD §3.7.
EVENTS = []

CLOCK = {'now': datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}
OPS = {'seq': 0, 'last_run_at': None}

ROLES = {'Agent', 'BrokerageUser', 'MarketplaceOps', 'PlatformAdmin'}


def now():
    return CLOCK['now']


def fmt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError('not a string')
    txt = s.strip()
    if txt.endswith('Z'):
        txt = txt[:-1] + '+00:00'
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _meta():
    return {
        'api_request_id': 'req_' + uuid.uuid4().hex[:24],
        'api_request_timestamp': fmt(now()),
    }


def respond(data, status=200):
    return jsonify({'meta': _meta(), 'response_type': 'object', 'data': data}), status


def respond_list(items):
    limit, offset = page_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta.update({
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + limit < total,
    })
    return jsonify({'meta': meta, 'response_type': 'array', 'data': page}), 200


def page_params():
    raw_limit = request.args.get('limit', '10')
    raw_offset = request.args.get('offset', '0')
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError('ERR_VALIDATION', 400, 'invalid pagination parameters')
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def vstr(b, key, required=True):
    v = b.get(key)
    if v is None:
        if required:
            raise ApiError('ERR_VALIDATION', 400, 'missing required field: %s' % key)
        return None
    if not isinstance(v, str) or v == '':
        raise ApiError('ERR_VALIDATION', 400, 'field %s must be a non-empty string' % key)
    return v


def vint(b, key, required=True):
    v = b.get(key)
    if v is None:
        if required:
            raise ApiError('ERR_VALIDATION', 400, 'missing required field: %s' % key)
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError('ERR_VALIDATION', 400, 'field %s must be an integer' % key)
    return v


def venum(b, key, allowed, required=True, default=None):
    v = b.get(key)
    if v is None:
        if required:
            raise ApiError('ERR_VALIDATION', 400, 'missing required field: %s' % key)
        return default
    if v not in allowed:
        raise ApiError('ERR_VALIDATION', 400, 'field %s must be one of %s' % (key, sorted(allowed)))
    return v


def vbool(b, key, required=True):
    v = b.get(key)
    if v is None:
        if required:
            raise ApiError('ERR_VALIDATION', 400, 'missing required field: %s' % key)
        return None
    if not isinstance(v, bool):
        raise ApiError('ERR_VALIDATION', 400, 'field %s must be a boolean' % key)
    return v


def authenticate():
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLES:
        raise ApiError('ERR_UNAUTHENTICATED', 401, 'missing or malformed X-User-ID / X-User-Role headers')
    return uid, role


def authorize(allowed):
    uid, role = authenticate()
    if role != 'PlatformAdmin' and role not in allowed:
        raise ApiError('ERR_UNAUTHORIZED', 403, 'role %s not permitted for this endpoint' % role)
    return uid, role


def check_agent_active(uid):
    a = STORE['agents'].get(uid)
    if a is not None and a['agent_status'] in ('SUSPENDED', 'DEACTIVATED'):
        raise ApiError('ERR_AGENT_SUSPENDED', 409, 'agent is %s and cannot perform this action' % a['agent_status'])


def new_entity():
    ts = fmt(now())
    return {'id': str(uuid.uuid4()), 'created_at': ts, 'updated_at': ts, 'version': 1, '_created_dt': now()}


def new_record():
    return {'id': str(uuid.uuid4()), 'created_at': fmt(now()), '_created_dt': now()}


def touch(e):
    e['updated_at'] = fmt(now())
    e['version'] = e.get('version', 1) + 1


def pub(e):
    return {k: v for k, v in e.items() if not k.startswith('_')}


def sorted_items(coll):
    if isinstance(coll, dict):
        vals = coll.values()
    else:
        vals = coll
    return sorted(vals, key=lambda e: (e['created_at'], e['id']))


def get_or_404(coll, key):
    e = STORE[coll].get(key)
    if e is None:
        raise ApiError(NOT_FOUND[coll], 404, '%s not found: %s' % (coll, key))
    return e


def filter_items(coll, filters):
    out = []
    for e in sorted_items(STORE[coll]):
        ok = True
        for field, val in filters.items():
            if val is not None and e.get(field) != val:
                ok = False
                break
        if ok:
            out.append(e)
    return out
