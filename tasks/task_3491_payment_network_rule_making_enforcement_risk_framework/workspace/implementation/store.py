"""In-memory data store (PRD: in-memory only; start.sh re-invocation wipes all
state). Plain dicts keyed by id; a monotonically increasing sequence number
keeps created_at ties in a stable order. No seeding of any kind."""
import uuid

from clock import CLOCK


class Store:
    def __init__(self):
        self.participants = {}
        self.originators = {}
        self.transaction_codes = {}
        self.settlement_windows = {}
        self.rule_proposals = {}
        self.ballots = {}
        self.guidance_documents = {}
        self.payment_entries = {}
        self.return_records = {}
        self.account_validations = {}
        self.return_rate_snapshots = {}
        self.inquiry_cases = {}
        self.enforcement_actions = {}
        self.compliance_attestations = {}
        self.audit_reports = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def new_id():
    """UUID-shaped resource id in dashed form (never uuid4().hex)."""
    return str(uuid.uuid4())


def add_record(table, fields, common=True):
    """Insert a record. `common` resources carry created_at/updated_at/version;
    immutable record types (SettlementWindow, ReturnRecord, AccountValidation)
    carry only id + created_at."""
    rec = dict(fields)
    rec["id"] = new_id()
    now = CLOCK.now()
    rec["created_at"] = now
    if common:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_seq"] = DB.next_seq()
    getattr(DB, table)[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and advance version by one (every mutation, including
    cascade- and side-effect-driven ones)."""
    rec["updated_at"] = CLOCK.now()
    rec["version"] += 1
