"""In-memory data store. Starts empty on every boot — no seeding."""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"


def parse_iso(s):
    if isinstance(s, datetime):
        dt = s
    else:
        txt = str(s).strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class Store:
    def __init__(self):
        self.model_versions = {}
        self.partners = {}
        self.credit_boxes = {}
        self.applicants = {}
        self.applications = {}
        self.verifications = {}
        self.fairness_reviews = {}
        self.attestations = {}
        self.loans = {}
        self.servicing_events = {}
        self.securitization_pools = {}
        self.allocation_decisions = {}
        self.clock = parse_iso(DEFAULT_CLOCK_ISO)


store = Store()
