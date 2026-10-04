"""In-memory data store. Starts empty on every boot — no seeding."""

import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.municipalities = {}
        self.host_agreements = {}
        self.agreements = {}
        self.deliveries = {}
        self.boilers = {}
        self.outages = {}
        self.diversion_plans = {}
        self.diversion_legs = {}
        self.throughput_reports = {}
        self.ppas = {}
        self.energy_deliveries = {}
        self.metals_contracts = {}
        self.metals_batches = {}
        self.landfills = {}
        self.ash_shipments = {}
        self.ash_tests = {}
        self.emissions_permits = {}
        self.emissions_readings = {}
        self.put_or_pay_settlements = {}  # id -> record
        # Logical clock: starts at exactly 2026-09-01T00:00:00Z
        from datetime import datetime, timezone
        self.logical_now = datetime(2026, 9, 1, tzinfo=timezone.utc)


store = Store()
