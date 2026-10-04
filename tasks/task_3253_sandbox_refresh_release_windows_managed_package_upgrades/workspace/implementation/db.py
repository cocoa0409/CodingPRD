"""In-memory data store.

Storage is entirely in-memory and starts EMPTY on every boot: nothing is
seeded, preloaded or hardcoded here (or anywhere else).  A ``start.sh``
re-invocation therefore wipes all state and guarantees a fresh boot for the
per-test-server isolation model.
"""

from collections import OrderedDict

import clock


_SEQ = [0]


def next_seq():
    """A process-local minting sequence.

    Used only as a stable tie-break when several rows are created within the
    same (deterministic) logical clock instant, so "oldest first" ordering stays
    reproducible.
    """
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    import uuid

    return str(uuid.uuid4())


def _row():
    ts = clock.default_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def make_row(fields=None, internal=None):
    row = _row()
    if fields:
        row.update(fields)
    if internal:
        row.update(internal)
    return row


def touch(row):
    """Refresh a row's update timestamp and advance its concurrency version."""
    row["updated_at"] = clock.default_iso()
    row["version"] = row.get("version", 1) + 1


# --- tables (all empty at boot) --------------------------------------------
environments = OrderedDict()
refresh_jobs = OrderedDict()
package_versions = OrderedDict()
installed_packages = OrderedDict()
permission_assignments = OrderedDict()
change_sets = OrderedDict()
deployment_jobs = OrderedDict()
governor_requests = OrderedDict()
storage_ledgers = OrderedDict()
access_audits = OrderedDict()


def create(table, fields=None, internal=None):
    row = make_row(fields, internal)
    table[row["id"]] = row
    return row


def find(table, row_id):
    if row_id is None:
        return None
    return table.get(row_id)