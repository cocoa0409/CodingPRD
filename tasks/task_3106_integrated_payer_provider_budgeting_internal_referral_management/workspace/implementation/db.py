"""In-memory data store.

Storage is pure in-process Python dicts keyed by id. Nothing is persisted to
disk, nothing is seeded or preloaded: the store starts empty on every boot and
every entity is created through the declared API surface.
"""


class Store:
    def __init__(self):
        self.regions = {}
        self.members = {}
        self.care_sites = {}
        self.departments = {}
        self.providers = {}
        self.network_services = {}
        self.appointments = {}
        self.referrals = {}
        self.claims = {}
        self.budgets = {}
        self.capacity_plans = {}
        self.transfers = {}
        self.quality_metrics = {}
        self.integrations = {}
        self.alerts = {}
        # Test-driving bookkeeping: records compensation plans drafted through
        # POST /provider-compensation-plans and claim lines carried on claims.
        self.compensation_plans = {}
        self.claim_lines = {}
        # Escalated deductible pool remaining, keyed by region id (PRD 3.7).
        self.escalated_pool = {}
        # Referential-integration bookkeeping keyed by region id: the posted
        # portion that entered premium revenue and the unposted remainder
        # reported as outside-services spending (PRD 3.11).
        self.integration_premium = {}
        self.integration_outside = {}

    def all(self, table):
        return list(getattr(self, table).values())


STORE = Store()