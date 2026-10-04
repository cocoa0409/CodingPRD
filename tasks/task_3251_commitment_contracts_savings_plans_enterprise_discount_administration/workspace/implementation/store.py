import uuid
import random
import string
from datetime import datetime, timezone


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


class Clock:
    def __init__(self):
        self._current = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def now(self):
        return self._current

    def set(self, dt):
        self._current = dt


CLOCK = Clock()


def new_id():
    return uuid.uuid4().hex


def new_request_id():
    suffix = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))
    return 'req_' + suffix


def iso_now():
    dt = datetime.now(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def iso_fmt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'


def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError('ERR_INVALID_REQUEST', 400, 'expected ISO8601 datetime string')
    s = value.strip()
    try:
        if s.endswith('Z'):
            s = s[:-1] + '+00:00'
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ApiError('ERR_INVALID_REQUEST', 400, 'malformed timestamp: ' + str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.orgs = {}
        self.linked_accounts = {}
        self.agreements = {}
        self.tiers = {}
        self.amendments = {}
        self.plans = {}
        self.usage = {}
        self.grants = {}
        self.invoices = {}
        self.lines = {}
        self.trueups = {}
        self.forecasts = {}


STORE = Store()
