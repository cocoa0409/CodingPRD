"""In-memory data store. Fresh on every process boot — never seeded."""

from collections import defaultdict


class Store:
    def __init__(self):
        self.enterprises = {}
        self.sites = {}
        self.surveys = {}
        self.designs = {}
        self.cells = {}
        self.leases = {}
        self.crs = {}            # SpectrumCoordinationRequest
        self.assignments = {}
        self.devices = {}
        self.sims = {}
        self.slices = {}
        self.bindings = {}
        self.contracts = {}
        self.alerts = {}
        self.remediations = {}
        # global uniqueness indexes
        self.erp_codes = set()
        self.serials = set()
        self.imeis = set()
        self.iccids = set()
        self.imsis = set()
        self.contract_codes = set()
        # imsi generation counter
        self.imsi_seq = 0
        self.sas_seq = 0
        # logical clock (datetime, tz-aware UTC)
        from datetime import datetime, timezone
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        # outage minutes per (enterprise_id, year, month) for CRITICAL outage alerts
        self.outage_minutes = defaultdict(int)
        # snapshot of sites that were OPERATIONAL before enterprise suspension
        self.pre_suspend_operational = set()


DB = Store()
