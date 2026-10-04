"""In-memory data store. Starts empty on every boot."""
from datetime import datetime, timezone


def _initial_clock():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.tiers = {}
        self.orgs = {}
        self.revenue_declarations = {}
        self.seat_subscriptions = {}
        self.editor_versions = {}
        self.projects = {}
        self.install_reports = {}
        self.invoices = {}
        self.policy_changes = {}
        self.grandfather_commitments = {}
        self.asset_listings = {}
        self.asset_purchases = {}
        self.export_agreements = {}
        self.export_builds = {}
        self.audit_cases = {}
        self.migration_assessments = {}
        self.clock = _initial_clock()
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
