"""In-memory data store. Starts empty on every boot — no seeding."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.licensees = {}
        self.rate_schedules = {}
        self.rate_proceedings = {}
        self.usage_reports = {}
        self.play_lines = {}
        self.recordings = {}
        self.royalty_liabilities = {}
        self.distribution_batches = {}
        self.distribution_lines = {}
        self.artists = {}
        self.rights_owners = {}
        self.ownership_claims = {}
        self.unclaimed_pools = {}
        self.audit_cases = {}
        # licensee_id -> { calendar_year(int) -> cents }
        self.min_fee_paid_ytd = {}
        # logical clock; startup default per PRD 2.5
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()
