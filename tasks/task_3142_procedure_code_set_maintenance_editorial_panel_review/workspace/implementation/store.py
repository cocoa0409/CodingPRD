"""In-memory data store.

Nothing is persisted to disk and nothing is seeded at boot: every table starts
empty on each fresh process, which is exactly what the per-test-server
isolation contract (start.sh re-invoked per test) requires.  Every entity any
request touches is created through a declared endpoint.
"""

import uuid

from clock import logical_now

# Entity tables, keyed by the server-minted UUID id.
societies = {}
applicants = {}
code_changes = {}
committee_reviews = {}
meetings = {}
public_comments = {}
editorial_votes = {}
valuations = {}
code_values = {}
errata_notices = {}
release_cycles = {}
licenses = {}
territories = {}
deliveries = {}
education_activities = {}
interpretation_requests = {}
errata_reviews = {}

ALL_TABLES = (
    societies, applicants, code_changes, committee_reviews, meetings,
    public_comments, editorial_votes, valuations, code_values, errata_notices,
    release_cycles, licenses, territories, deliveries, education_activities,
    interpretation_requests, errata_reviews,
)

_seq = [0]


def new_id():
    """A UUID string carrying no type prefix (PRD.md 2.5)."""
    return str(uuid.uuid4())


def _next_seq():
    _seq[0] += 1
    return _seq[0]


def reset():
    """Wipe every table.  Only used by tests that drive the process directly;
    normal isolation comes from restarting the process."""
    for table in ALL_TABLES:
        table.clear()
    _seq[0] = 0


def create(table, fields, common=True):
    """Insert a record and stamp the common field set (PRD.md 2.5).

    `id` is a UUID string without a type prefix; `created_at`, `updated_at` and
    `version` accompany it on every entity because every entity declares the
    common field set.
    """
    record = dict(fields)
    if common:
        now = logical_now()
        record["id"] = new_id()
        record["created_at"] = now
        record["updated_at"] = now
        record["version"] = 1
        record["_seq"] = _next_seq()
    table[record["id"]] = record
    return record


def bump(record):
    """Refresh `updated_at` and increment `version` by exactly one.

    PRD.md 2.5 / 2.12: every mutation, including server-initiated mutations and
    every hop of a cascade, refreshes the timestamp and advances the version.
    """
    if record is None:
        return None
    record["updated_at"] = logical_now()
    record["version"] = int(record.get("version", 0)) + 1
    return record


def sorted_rows(table, key=None):
    """Oldest-first ordering by creation timestamp, stable across ties."""
    rows = list(table.values())
    rows.sort(key=lambda r: (r.get("created_at"), r.get("_seq", 0)))
    if key is not None:
        rows.sort(key=key)
    return rows


def rows_where(table, predicate):
    return [r for r in sorted_rows(table) if predicate(r)]


def find(table, row_id):
    return table.get(row_id)