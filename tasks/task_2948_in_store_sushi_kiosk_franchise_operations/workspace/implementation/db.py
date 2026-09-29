"""In-memory data store.

Every collection starts empty on every boot. Nothing is seeded, preloaded or
hardcoded: every entity a caller needs is built through the declared endpoints.
"""

from core import logical_now_iso, new_id

# --- collections (id -> row dict) -----------------------------------------
host_stores = {}
license_agreements = {}
chefs = {}
certifications = {}
kiosks = {}
production_plans = {}
rice_batches = {}
fish_lots = {}
cold_chain_readings = {}
pack_lots = {}
discard_events = {}
pos_sales_feeds = {}
settlement_statements = {}
food_safety_audits = {}
audit_findings = {}

ALL_COLLECTIONS = (
    host_stores,
    license_agreements,
    chefs,
    certifications,
    kiosks,
    production_plans,
    rice_batches,
    fish_lots,
    cold_chain_readings,
    pack_lots,
    discard_events,
    pos_sales_feeds,
    settlement_statements,
    food_safety_audits,
    audit_findings,
)


# --- row helpers -----------------------------------------------------------


def new_row(collection, fields, versioned=True):
    """Create a row with PRD 2.4 common fields and insert it."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = logical_now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    collection[row["id"]] = row
    return row


def touch(row):
    """Mutation bookkeeping: refresh updated_at, increment version by exactly 1."""
    if "version" in row:
        row["updated_at"] = logical_now_iso()
        row["version"] = row["version"] + 1
    return row


def apply_changes(row, changes):
    """Apply a derived/cascade update, bumping version only when something moved."""
    dirty = False
    for key, value in changes.items():
        if row.get(key) != value:
            dirty = True
            break
    if dirty:
        row.update(changes)
        touch(row)
    return dirty


def public(row):
    """Serialize a row, hiding private bookkeeping keys (prefixed with '_')."""
    return dict((k, v) for k, v in row.items() if not k.startswith("_"))


def ordered(rows):
    """PRD 2.3: created_at ascending, id ascending as the tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["id"]))
