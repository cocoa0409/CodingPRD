"""In-memory data store and logical clock for the Classroom Book Club API.

All state lives in module-level dicts keyed by id. Nothing is persisted to
disk and nothing is seeded at startup: every boot begins with empty stores
and the logical clock pinned at 2026-09-01T00:00:00Z.
"""

import datetime

CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# Entity stores (dicts keyed by resource id).
schools = {}
teachers = {}
titles = {}
promotions = {}
flyer_cycles = {}
offerings = {}
class_orders = {}
order_lines = {}
book_fairs = {}
fair_titles = {}
donation_requests = {}
redemptions = {}
enrollments = {}
ledger = {}


def _parse_clock(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc
    )


class _Clock:
    def __init__(self):
        self.iso = CLOCK_DEFAULT_ISO

    def set(self, iso):
        self.iso = iso

    @property
    def dt(self):
        return _parse_clock(self.iso)

    @property
    def date(self):
        return self.dt.date()


clock = _Clock()


def now_iso_ms():
    """Wall-clock UTC timestamp with three fractional digits for meta fields."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
