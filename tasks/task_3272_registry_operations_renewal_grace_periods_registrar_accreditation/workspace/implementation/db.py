import uuid

from util import fmt_iso

# In-memory stores: id -> record dict. Start empty on every boot.
registrars = {}
price_schedules = {}
domains = {}
nameservers = {}
links = {}          # DomainNameserverLink
transfers = {}
invoices = {}
ledger_entries = {}
abuse_reports = {}
court_orders = {}
notices = {}        # RegistrarAccreditationNotice


def new_id():
    return str(uuid.uuid4())


def new_common(clock_now):
    ts = fmt_iso(clock_now)
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(rec, clock_now):
    rec["updated_at"] = fmt_iso(clock_now)
    rec["version"] = rec.get("version", 1) + 1
