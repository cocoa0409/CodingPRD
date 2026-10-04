"""In-memory data store.

The store starts completely empty on every boot. Nothing is seeded: every
entity is constructed through the declared API surface by the caller.
"""
import clock


class Store:
    def __init__(self):
        self.organizations = {}
        self.competitions = {}
        self.applications = {}
        self.awards = {}
        self.slots = {}
        self.members = {}
        self.checks = {}
        self.enrollments = {}
        self.hour_entries = {}
        self.payments = {}
        self.education_awards = {}
        self.uses = {}
        self.visits = {}
        self.findings = {}
        self.grievances = {}
        self.measures = {}
        self.seq = 0  # global insertion counter; stable tiebreak for sorting

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def new_entity(fields, common=True):
    """Build a stored entity dict with system-managed common fields (PRD 2.5).

    common=True  -> id/created_at/updated_at/version (version starts at 1)
    common=False -> id/created_at only (LivingAllowancePayment)
    """
    now = clock.now_iso()
    entity = dict(fields)
    entity["_seq"] = store.next_seq()
    entity["created_at"] = now
    if common:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity
