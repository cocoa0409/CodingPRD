"""Identity headers, release-epoch derivation and time helpers."""

import re
from datetime import timedelta

from clock import CLOCK, parse_iso

DECLARED_ROLES = (
    "Anonymous",
    "Patron",
    "OpsManager",
    "AllocationsCoordinator",
    "CustomerService",
    "FinancialOps",
    "ConciergeDeskStaff",
    "ProducerAnalyst",
    "DemandAnalyst",
    "PlatformAdmin",
)

RELEASE_EPOCH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOCAL_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def coerce_discount(raw, default=None):
    """Discounts are a fraction between zero and one; whole percents are folded."""
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value > 1:
        value = value / 100.0
    return value


def identity(request):
    """Returns (user_id, role). Both headers are required and the role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        return None, None
    if role not in DECLARED_ROLES:
        return None, None
    return user_id, role


def release_at_for(epoch_date, release_time_local):
    """The epoch's release instant, from the epoch date and the local HH:MM."""
    hour, minute = 0, 0
    if release_time_local:
        match = LOCAL_TIME_RE.match(str(release_time_local).strip())
        if match:
            hour, minute = int(match.group(1)), int(match.group(2))
    day = parse_iso("%sT00:00:00.000+00:00" % epoch_date)
    return day + timedelta(hours=hour, minutes=minute)


def epoch_of(dt):
    return dt.strftime("%Y-%m-%d")


def current_epoch_date():
    return epoch_of(CLOCK.now)


def next_epoch_date(settled_epochs):
    """The allocation's next unsettled release epoch date."""
    today = CLOCK.now.date()
    last = None
    for raw in settled_epochs or []:
        try:
            candidate = parse_iso("%sT00:00:00.000+00:00" % raw).date()
        except ValueError:
            continue
        if last is None or candidate > last:
            last = candidate
    if last is None:
        return today.strftime("%Y-%m-%d")
    return (last + timedelta(days=1)).strftime("%Y-%m-%d")


def money(value):
    """Payments are integer cents; Decimal values are rounded half-up to int."""
    return int(value)


def hours_between(later_iso, earlier_iso):
    later = parse_iso(later_iso)
    earlier = parse_iso(earlier_iso)
    return (later - earlier).total_seconds() / 3600.0