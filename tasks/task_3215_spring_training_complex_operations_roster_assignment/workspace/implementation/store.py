"""In-memory data store.

Everything lives in this module's dictionaries. Nothing is written to disk,
nothing is seeded at boot: the store is empty until a declared endpoint
creates a record. Because the process is relaunched by `start.sh` before every
test, a fresh boot always means a fresh, empty store plus a logical clock reset
to its documented startup instant.
"""

import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "complexes",
    "community_agreements",
    "players",
    "roster_records",
    "host_community_records",
    "sponsorships",
    "workout_groups",
    "group_assignments",
    "throw_programs",
    "workout_group_sessions",
    "throw_program_sessions",
    "spring_trails",
    "minor_league_assignments",
    "program_profiles",
    "camp_invitations",
    "travel_arrangements",
    "physicals",
    "games",
    "game_participations",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.ops_run_index = 0

    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_id(self):
        return str(uuid.uuid4())

    def insert(self, collection, record):
        record["__seq"] = self.next_seq()
        getattr(self, collection)[record["id"]] = record
        return record

    def get(self, collection, rid):
        return getattr(self, collection).get(rid)

    def all(self, collection):
        items = list(getattr(self, collection).values())
        items.sort(key=lambda r: (r["created_at"], r["__seq"]))
        return items

    def find(self, collection, **filters):
        out = []
        for record in self.all(collection):
            ok = True
            for key, value in filters.items():
                if value is None:
                    continue
                if record.get(key) != value:
                    ok = False
                    break
            if ok:
                out.append(record)
        return out

    def remove(self, collection, rid):
        getattr(self, collection).pop(rid, None)


db = Store()