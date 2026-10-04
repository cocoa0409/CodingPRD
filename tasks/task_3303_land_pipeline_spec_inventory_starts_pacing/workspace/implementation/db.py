"""In-memory data store and logical clock.

The store starts completely empty on every boot -- no seeding of any kind.
"""

from datetime import datetime, timezone


def _dt(s):
    """Parse an ISO-8601 string into an aware UTC datetime."""
    if isinstance(s, datetime):
        d = s
    else:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def iso3(d):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits + Z."""
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def now_wall():
    return datetime.now(timezone.utc)


class DB:
    def __init__(self):
        self.land_parcels = {}
        self.option_contracts = {}
        self.takedowns = {}
        self.communities = {}
        self.product_series = {}
        self.lots = {}
        self.homes = {}
        self.sales_contracts = {}
        self.incentives = {}
        self.trade_partners = {}
        self.capacity_commitments = {}
        self.pacing_plans = {}
        # Idempotency-Key -> {"fingerprint": ..., "status": int, "body": dict}
        self.idempotency = {}
        # Logical clock: boots at 2026-09-01T00:00:00Z, never wall time.
        self.clock = _dt("2026-09-01T00:00:00Z")


db = DB()
