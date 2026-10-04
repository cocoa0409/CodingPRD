"""In-memory data store. Starts empty on every boot; no seeding."""
from datetime import datetime, timezone


def _parse_startup(s):
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.shops = {}
        self.requirements = {}
        self.cycles = {}
        self.attestations = {}
        self.audits = {}
        self.corrective_actions = {}
        self.technicians = {}
        self.courses = {}
        self.completions = {}
        self.repair_orders = {}
        self.procedure_steps = {}
        self.part_lines = {}
        self.warranty_claims = {}
        self.insurer_relations = {}
        self.referrals = {}
        # logical clock: fixed startup default, never wall-clock
        self.clock = _parse_startup(None)
        # monotonic creation sequence, tie-break for equal created_at
        self._seq_counter = 0

    def next_seq(self):
        self._seq_counter += 1
        return self._seq_counter


def serialize(entity):
    """Public view of an entity: strip internal bookkeeping keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


db = Store()
