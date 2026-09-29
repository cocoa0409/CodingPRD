"""In-memory data store.

Every collection starts EMPTY on every boot: no seeding, preloading or
hardcoded records anywhere in this module or in app startup.  Tests build all
their preconditions through the declared API surface.
"""

import uuid

import clock


class Store:
    def __init__(self):
        self.platform_specs = {}
        self.mix_stages = {}
        self.mixers = {}
        self.voice_talents = {}
        self.library_assets = {}
        self.projects = {}
        self.stem_packages = {}
        self.music_cues = {}
        self.asset_usages = {}
        self.adr_sessions = {}
        self.mix_bookings = {}
        self.deliverables = {}
        self.qc_reports = {}
        self.archive_packages = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    """PRD §2.5: 'a string id holding a UUID, with no prefix'."""
    return str(uuid.uuid4())


def new_record(versioned=True):
    """PRD §2.5 common system fields.

    Versioned resources get created_at, updated_at and version = 1.  Immutable
    resources (PlatformSpec, QcReport, ArchivePackage) get only created_at.
    """
    stamp = clock.now()
    rec = {"id": new_id(), "created_at": stamp, "_seq": db.next_seq()}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """PRD §2.5/§2.10: every mutation refreshes updated_at and bumps version by 1."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec["version"] + 1


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def newest_first(records):
    return sorted(records, key=sort_key, reverse=True)


def oldest_first(records):
    return sorted(records, key=sort_key)
