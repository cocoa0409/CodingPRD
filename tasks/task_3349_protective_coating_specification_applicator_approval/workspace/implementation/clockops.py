"""POST /coating/_clock/set_current_utc — logical clock + monthly decay sweep."""
from datetime import timedelta

from flask import Blueprint

from auth import require_roles
from helpers import body, iso, req
from response import ok
from scoring import monthly_decay
from storage import store

bp = Blueprint('clockops', __name__)


def _first_of_month(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(dt):
    m = _first_of_month(dt)
    if m.month == 12:
        return m.replace(year=m.year + 1, month=1)
    return m.replace(month=m.month + 1)


@bp.post('/coating/_clock/set_current_utc')
@require_roles('PlatformAdmin')
def set_current_utc():
    payload = body()
    new_dt = req(payload, 'current_utc', kind='dt')
    old = store.clock
    if new_dt > old:
        # Each crossed first-of-month boundary sweeps the calendar month just ended.
        boundary = _next_month(old)
        while boundary <= new_dt:
            month_start = _first_of_month(boundary - timedelta(seconds=1))
            monthly_decay(month_start, boundary)
            boundary = _next_month(boundary)
    store.clock = new_dt
    return ok({'current_utc': iso(new_dt)})
