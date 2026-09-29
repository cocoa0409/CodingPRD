"""In-memory data store. Starts EMPTY on every boot - nothing is ever seeded."""
import itertools
import uuid
import clock

KINDS = (
    "policy_cycle",
    "team",
    "employee",
    "eligibility_classification",
    "attendance_week",
    "compliance_signal",
    "exception_request",
    "remote_location_request",
    "neighborhood",
    "seat_allocation",
    "desk_assignment",
    "escalation_case",
    "recalibration_review",
)

tables = {kind: {} for kind in KINDS}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def insert(kind, fields, versioned=True):
    row = dict(fields)
    row["id"] = new_id()
    row["_seq"] = next_seq()
    stamp = clock.now_iso()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    tables[kind][row["id"]] = row
    return row


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return tables[kind].get(row_id)


def all_rows(kind):
    return list(tables[kind].values())


def find(kind, **criteria):
    out = []
    for row in tables[kind].values():
        if all(row.get(k) == v for k, v in criteria.items()):
            out.append(row)
    return out


def touch(row):
    """Force a mutation stamp: refresh updated_at and advance version by one."""
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 0) + 1
    return row


def apply_changes(row, changes):
    """Write changes; refresh updated_at + version only when something changed."""
    changed = False
    for key, value in changes.items():
        if key not in row or row[key] != value:
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def seq_key(row):
    """Stable (created_at, insertion-sequence) ordering key.

    The logical clock does not advance on its own, so many rows share a
    created_at value; the insertion sequence resolves those ties in creation
    order without ever consulting the surrogate id.
    """
    return (row["created_at"], row["_seq"])
