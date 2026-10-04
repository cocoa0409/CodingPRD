"""In-memory data store for the Veteran Loan Eligibility API.

All storage is plain Python dicts keyed by id. The store starts empty on
every boot; no seeding of any kind happens here.
"""
import threading


class _Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.veterans = {}
        self.service_periods = {}
        self.coes = {}
        self.entitlement_accounts = {}
        self.loans = {}
        self.funding_fee_assessments = {}
        self.appraisers = {}
        self.appraisals = {}
        self.repair_requirements = {}
        self.occupancy_certificates = {}
        self.deployment_exceptions = {}
        self.underwriting_decisions = {}
        self.assumption_requests = {}
        self.refinance_requests = {}
        self.restoration_requests = {}
        self.audit_events = {}
        # Logical clock: starts at 2026-09-01T00:00:00Z, never wall clock.
        self.clock_iso = "2026-09-01T00:00:00Z"


STORE = _Store()
