"""In-memory data store.

Plain Python dicts keyed by id.  There is no database, no file, no cache and no
external persistence of any kind: re-invoking start.sh wipes every byte of
state.  The store starts EMPTY on every boot — nothing is seeded, preloaded,
registered or hardcoded here.  Every entity a caller needs is built through the
declared API surface.
"""
import itertools
import uuid

import clock

KINDS = (
    "seasons",
    "membership_categories",
    "households",
    "waitlist_entries",
    "memberships",
    "guest_visits",
    "lifeguards",
    "certifications",
    "guard_shifts",
    "swim_team_registrations",
    "meets",
    "volunteer_assignments",
    "party_reservations",
    "inspection_findings",
    "conduct_cases",
    "capital_projects",
)

# Not-found error identifier per collection (PRD §2.9 band 9).
NOT_FOUND = {
    "seasons": "ERR_SEASON_NOT_FOUND",
    "membership_categories": "ERR_CATEGORY_NOT_FOUND",
    "households": "ERR_HOUSEHOLD_NOT_FOUND",
    "waitlist_entries": "ERR_WAITLIST_ENTRY_NOT_FOUND",
    "memberships": "ERR_MEMBERSHIP_NOT_FOUND",
    "guest_visits": "ERR_GUEST_VISIT_NOT_FOUND",
    "lifeguards": "ERR_LIFEGUARD_NOT_FOUND",
    "certifications": "ERR_CERTIFICATION_NOT_FOUND",
    "guard_shifts": "ERR_GUARD_SHIFT_NOT_FOUND",
    "swim_team_registrations": "ERR_REGISTRATION_NOT_FOUND",
    "meets": "ERR_MEET_NOT_FOUND",
    "volunteer_assignments": "ERR_VOLUNTEER_ASSIGNMENT_NOT_FOUND",
    "party_reservations": "ERR_PARTY_RESERVATION_NOT_FOUND",
    "inspection_findings": "ERR_INSPECTION_FINDING_NOT_FOUND",
    "conduct_cases": "ERR_CONDUCT_CASE_NOT_FOUND",
    "capital_projects": "ERR_CAPITAL_PROJECT_NOT_FOUND",
}


class Store(object):
    def __init__(self):
        self.tables = {}
        self._seq = None
        self._touched = set()
        self.reset()

    def reset(self):
        for kind in KINDS:
            self.tables[kind] = {}
        self._seq = itertools.count(1)
        self._touched = set()

    def begin_request(self):
        """A row's version advances by exactly 1 per request that changes it,
        however many hops of a cascade reach it (PRD §2.4)."""
        self._touched = set()

    # ------------------------------------------------------------------ basics
    def next_seq(self):
        return next(self._seq)

    def table(self, kind):
        return self.tables[kind]

    def get(self, kind, row_id):
        if not isinstance(row_id, str):
            return None
        return self.tables[kind].get(row_id)

    def all(self, kind):
        """Every row of a collection in created_at ascending order (§2.3)."""
        return sorted(self.tables[kind].values(), key=lambda r: (r["created_at"], r["_seq"]))

    def insert(self, kind, fields):
        row = dict(fields)
        stamp = clock.now_iso()
        row["id"] = str(uuid.uuid4())
        row["created_at"] = stamp
        row["updated_at"] = stamp
        row["version"] = 1
        row["_seq"] = self.next_seq()
        row["_kind"] = kind
        self.tables[kind][row["id"]] = row
        self._touched.add((kind, row["id"]))
        return row

    def touch(self, row):
        """Every row a request actually changes advances its own version and
        refreshes its own updated_at (PRD §2.4).  A row reached twice by one
        request advances once: the counter tracks mutating requests, not hops.
        """
        key = (row["_kind"], row["id"])
        row["updated_at"] = clock.now_iso()
        if key in self._touched:
            return row
        self._touched.add(key)
        row["version"] = row["version"] + 1
        return row


DB = Store()


def serialize(row):
    """Public projection of a stored row: internal keys are stripped."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_many(rows):
    return [serialize(r) for r in rows]


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
