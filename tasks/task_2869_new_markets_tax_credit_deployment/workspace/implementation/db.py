"""In-memory data store. Starts empty on every boot; nothing is ever seeded."""
import copy
import uuid

VERSIONED_TABLES = (
    "cdes", "awards", "qalicbs", "funds", "qeis", "qlicis",
    "obligations", "cbas", "unwinds",
)
APPEND_ONLY_TABLES = ("tracts", "eligibility_tests", "annual_tests", "job_reports")
TABLES = VERSIONED_TABLES + APPEND_ONLY_TABLES


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in TABLES:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def snapshot(self):
        return copy.deepcopy({name: getattr(self, name) for name in TABLES})

    def restore(self, snap):
        for name in TABLES:
            setattr(self, name, snap[name])


db = Store()


def new_id():
    return str(uuid.uuid4())


def _comparable(row):
    return {k: v for k, v in row.items() if k not in ("version", "updated_at")}


def commit(snapshot, forced_ids, stamp):
    """Bump version and updated_at on every pre-existing row whose content changed."""
    for name in VERSIONED_TABLES:
        current = getattr(db, name)
        previous = snapshot.get(name, {})
        for row_id, row in current.items():
            before = previous.get(row_id)
            if before is None:
                continue
            if row_id in forced_ids or _comparable(before) != _comparable(row):
                row["version"] = row["version"] + 1
                row["updated_at"] = stamp
