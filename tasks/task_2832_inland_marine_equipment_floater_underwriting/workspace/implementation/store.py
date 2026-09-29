"""In-memory store.  Starts empty on every boot; nothing is ever seeded."""
import datetime

from common import clock_now, fail, fmt_date, fmt_instant, new_id

policies = {}
coverage_parts = {}
rate_rules = {}
equipment_items = {}
jobsites = {}
installation_floaters = {}
vehicles = {}
transit_shipments = {}
value_reports = {}
claims = {}
ledger_entries = {}

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def reset():
    for table in (policies, coverage_parts, rate_rules, equipment_items, jobsites,
                  installation_floaters, vehicles, transit_shipments, value_reports,
                  claims, ledger_entries):
        table.clear()
    _seq["n"] = 0


def make(fields):
    """Build a row: id first, then the entity's declared fields, then the
    common system fields."""
    row = {"id": new_id()}
    row.update(fields)
    now = clock_now()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    row["updated_at"] = clock_now()


def bump(row):
    row["version"] = row["version"] + 1
    row["updated_at"] = clock_now()


def _scalar(value):
    if isinstance(value, datetime.datetime):
        return fmt_instant(value)
    if isinstance(value, datetime.date):
        return fmt_date(value)
    return value


def serialize(row):
    return {k: _scalar(v) for k, v in row.items() if not k.startswith("_")}


def order(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def all_of(table, **filters):
    out = []
    for row in table.values():
        keep = True
        for key, val in filters.items():
            if val is None:
                continue
            if row.get(key) != val:
                keep = False
                break
        if keep:
            out.append(row)
    return order(out)


def find(table, row_id, error_id):
    if row_id is None:
        fail(error_id)
    row = table.get(row_id)
    if row is None:
        fail(error_id, "%s not found" % row_id)
    return row


def maybe(table, row_id):
    if row_id is None:
        return None
    return table.get(row_id)


# --------------------------------------------------------------------------
# Convenience accessors
# --------------------------------------------------------------------------
def part_of(row):
    return coverage_parts.get(row["coverage_part_id"])


def policy_of_part(part):
    return policies.get(part["policy_id"])


def policy_of(row):
    return policy_of_part(coverage_parts[row["coverage_part_id"]])


def parts_of_policy(policy_id):
    return order([p for p in coverage_parts.values() if p["policy_id"] == policy_id])


def items_of_part(part_id):
    return order([i for i in equipment_items.values() if i["coverage_part_id"] == part_id])


def floaters_of_part(part_id):
    return order([f for f in installation_floaters.values()
                  if f["coverage_part_id"] == part_id])


def shipments_of_part(part_id):
    return order([s for s in transit_shipments.values()
                  if s["coverage_part_id"] == part_id])


def reports_of_part(part_id):
    return order([r for r in value_reports.values() if r["coverage_part_id"] == part_id])


def claims_of_part(part_id):
    return order([c for c in claims.values() if c["coverage_part_id"] == part_id])


def entries_of_policy(policy_id):
    return order([e for e in ledger_entries.values() if e["policy_id"] == policy_id])


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------
PREMIUM_ENTRY_TYPES = {
    "INITIAL_PREMIUM", "ENDORSEMENT_PREMIUM", "ENDORSEMENT_RETURN",
    "REPORTING_ADJUSTMENT", "LATE_REPORTING_PENALTY", "CANCELLATION_RETURN",
}
LOSS_ENTRY_TYPES = {"CLAIM_SETTLEMENT", "SALVAGE_RECOVERY"}


def ledger_of(entry_type):
    return "PREMIUM" if entry_type in PREMIUM_ENTRY_TYPES else "LOSS"


def append_entry(policy_id, entry_type, amount_cents, memo, claim_id=None,
                 effective_date=None):
    row = {
        "id": new_id(),
        "policy_id": policy_id,
        "claim_id": claim_id,
        "entry_type": entry_type,
        "ledger": ledger_of(entry_type),
        "amount_cents": amount_cents,
        "memo": memo,
        "effective_date": effective_date if effective_date is not None else clock_now().date(),
        "created_at": clock_now(),
        "_seq": next_seq(),
    }
    ledger_entries[row["id"]] = row
    return row
