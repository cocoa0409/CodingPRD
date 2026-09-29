"""In-memory data store.  Starts completely empty on every boot: no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

from util import utcnow

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.brands = {}
        self.market_requirements = {}
        self.styles = {}
        self.material_inputs = {}
        self.lab_tests = {}
        self.origin_determinations = {}
        self.label_specs = {}
        self.import_shipments = {}
        self.compliance_audits = {}
        self.audit_findings = {}
        self._seq = itertools.count(1)
        # PRD 2.4: the logical clock reads exactly 2026-08-01T00:00:00Z at
        # startup and never falls back to host wall-clock time.
        self.logical_clock = CLOCK_DEFAULT

    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        return self.logical_clock


db = Store()


def create_row(table, fields, versioned=True):
    """Insert a row with the system-minted identity / timestamp / version fields."""
    row = dict(fields)
    row["id"] = db.new_id()
    stamp = utcnow()
    row["created_at"] = stamp
    row["_seq"] = db.next_seq()
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    table[row["id"]] = row
    return row


def touch(row):
    """Mutation bookkeeping: refresh updated_at and increment version by one."""
    row["updated_at"] = utcnow()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """Default ordering: created_at ascending, insertion sequence as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
