"""In-memory data store. Storage is Python dicts keyed by id only — no SQLite,
no files, no external persistence. A fresh process starts completely empty;
nothing is seeded at startup.

Every record carries the common fields (PRD 2.5): server-minted UUID `id`,
`created_at` / `updated_at` logical-clock timestamps, and an integer `version`
that increments by one on every mutation, including cascade-driven ones.
Records also carry internal `"_seq"` (monotonic insertion order, used as a
deterministic tie-break when two records share a logical-clock created_at)
and may carry other underscore-prefixed internal fields, none of which are
ever serialized.
"""
import uuid

from core import clock


class Store:
    def __init__(self):
        self.seq = 0
        self.trend_signals = {}
        self.concepts = {}
        self.products = {}
        self.manufacturers = {}
        self.formula_projects = {}
        self.cost_quotes = {}
        self.dossiers = {}
        self.retail_partners = {}
        self.line_reviews = {}
        self.planogram_slots = {}
        self.launch_plans = {}
        self.discontinuation_reviews = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def new_record(fields):
    """Create a record dict with common fields populated from the logical clock."""
    ts = clock.now()
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a record mutated: version += 1 and updated_at := logical now."""
    rec["version"] += 1
    rec["updated_at"] = clock.now()
