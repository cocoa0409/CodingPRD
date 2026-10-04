"""In-memory data store. Starts empty on every boot; no seeding."""

from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00+00:00"


class Store:
    def __init__(self):
        self.agencies = {}
        self.rate_schedules = {}
        self.discount_plans = {}
        self.accounts = {}
        self.transponders = {}
        self.toll_transactions = {}
        self.image_bills = {}
        self.violations = {}
        self.disputes = {}
        self.settlement_files = {}
        self.plate_data_agreements = {}
        # logical clock
        self.current_dt = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_origin = self.current_dt
        self.epoch_day = 0
        # monotonic sequence for stable created_at ordering
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def epoch_day_of(self, dt):
        """Epoch day index for an arbitrary datetime (floor of days since clock origin)."""
        if dt is None:
            return None
        return (dt - self.clock_origin).days

    # --- clock ---
    def set_clock(self, dt):
        self.current_dt = dt

    def advance_days(self, days):
        old_month = (self.current_dt.year, self.current_dt.month)
        self.current_dt = self.current_dt + timedelta(days=days)
        self.epoch_day += days
        new_month = (self.current_dt.year, self.current_dt.month)
        month_rolled = new_month != old_month
        return month_rolled

    def current_iso(self):
        return self.current_dt.strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{self.current_dt.microsecond // 1000:03d}Z"

    def current_dt_wall(self):
        """Wall-clock time for created_at/updated_at stamps."""
        return datetime.now(timezone.utc)


store = Store()
