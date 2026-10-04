"""In-memory data store.

Hard contract: nothing is persisted.  No file, no database, no cache.  The store
is created empty on every process start and no entity is ever seeded, preloaded
or hardcoded here -- every record is produced by a test calling a declared
endpoint.
"""
import uuid
from datetime import datetime, timezone

# Collections keyed by entity name.  Each holds dicts keyed by ``id``.
COLLECTIONS = [
    "product_configurations",
    "jurisdiction_programs",
    "allocation_batches",
    "allocation_windows",
    "allocation_entitlements",
    "site_orders",
    "storage_sites",
    "site_equipment_verifications",
    "dispatch_orders",
    "cold_chain_shippers",
    "logger_readings",
    "cartons",
    "dose_ledger_entries",
    "site_transfers",
    "temperature_excursions",
    "excursion_adjudications",
    "doses_affected_slices",
    "wastage_reports",
    "order_rejections",
    "entitlement_releases",
    "reporting_periods",
    "program_standings",
    "shipping_window_lapses",
    "adjudication_appeals",
    "carton_storage_reservations",
    "carton_families",
]


class Store:
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        # The logical clock starts at 2026-09-01T00:00:00Z (PRD §2.4).
        self.current_utc = "2026-09-01T00:00:00Z"
        # Standing-status changes queued under AFTER_CYCLE propagation.
        self.deferred_standings = []

    def all(self, name):
        return list(getattr(self, name).values())

    def get(self, name, key):
        if key is None:
            return None
        return getattr(self, name).get(key)

    def put(self, name, record):
        getattr(self, name)[record["id"]] = record
        return record

    def find(self, name, **criteria):
        out = []
        for rec in getattr(self, name).values():
            if all(rec.get(k) == v for k, v in criteria.items()):
                out.append(rec)
        return out


STORE = Store()


def new_id():
    """System-minted resource id: a bare UUID with no type prefix (PRD §2.5)."""
    return str(uuid.uuid4())


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (datetime.now(timezone.utc).microsecond // 1000)


def stamp(record):
    """Refresh updated_at on a mutation and bump version."""
    if "updated_at" in record:
        record["updated_at"] = now_iso()
    if "version" in record:
        record["version"] = record.get("version", 0) + 1
    return record


def create(name, fields):
    """Create a record with id/created_at/updated_at/version where applicable."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    if name == "logger_readings" or name == "dose_ledger_entries":
        # TemperatureLoggerReading and DoseLedgerEntry are immutable/append-only:
        # only id and created_at (PRD §2.5).
        pass
    else:
        rec["updated_at"] = rec["created_at"]
        rec.setdefault("version", 1)
    STORE.put(name, rec)
    return rec