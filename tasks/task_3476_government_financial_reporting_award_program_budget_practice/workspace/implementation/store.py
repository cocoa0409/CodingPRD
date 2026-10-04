"""In-memory storage only (PRD benchmark contract).

Plain dicts keyed by id. The store boots EMPTY on every process start: no
seeding, no preloading, no fixtures. A global monotonically increasing
sequence number (_seq) is kept on each record purely as a deterministic
insertion-order tie-break for `created_at ASC` sorts (many records share the
same logical-clock instant); it is never serialized.
"""

import itertools
import uuid


class Store:
    def __init__(self):
        self.governments = {}
        self.members = {}
        self.reviewer_profiles = {}
        self.checklist_versions = {}
        self.standards_references = {}
        self.award_cycles = {}
        self.report_submissions = {}
        self.review_assignments = {}
        self.review_findings = {}
        self.publications = {}
        self.member_comments = {}
        self.scholarship_funds = {}
        self.scholarship_applications = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_id():
    return str(uuid.uuid4())


def touch(record, now_iso_str):
    """PRD 2.5: version increments by exactly one on every mutation (including
    cascade-driven ones) and updated_at refreshes."""
    record["version"] += 1
    record["updated_at"] = now_iso_str
