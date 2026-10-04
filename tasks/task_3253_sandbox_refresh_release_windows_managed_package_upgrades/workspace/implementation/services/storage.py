"""Storage ledgers, the archived window and restoration (PRD §2.8, §3.6).

The archive/restore pair is compensating: archiving moves bytes from the used
bucket to the archived bucket without changing Environment.storage_total_bytes,
and restoring moves them back.  Only FILE ledgers are in scope for the batch
cap of three.
"""

import calculations
import clock
import db
from errors import (
    ERR_ARCHIVE_BATCH_EXCEEDED,
    ERR_ARCHIVE_WINDOW_CLOSED,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_STORAGE_BREACH,
    fail,
)
from services import common, environments


def create_ledger(actor, env, b):
    from validate import require_enum, require_int

    kind = require_enum(b, "kind", ("DATA", "FILE"))
    size = require_int(b, "bytes", min_value=1)
    rank_index = require_int(b, "rank_index", min_value=1)

    # PRD §2.8: rank_index is a 1-based ordinal unique within its environment,
    # so a duplicate is a structural error (ERR_INVALID_REQUEST, PRD §2.4).
    for existing in db.storage_ledgers.values():
        if existing["environment_id"] == env["id"] and existing["rank_index"] == rank_index:
            fail(
                ERR_INVALID_REQUEST,
                "rank_index %d is already assigned within this environment." % rank_index,
            )

    # Registration is refused once the environment is in breach (general rule
    # from §2.8: a breaching environment may not commit further storage).
    if env["storage_breach"]:
        fail(ERR_STORAGE_BREACH, "The environment is in storage breach.")

    ledger = db.create(
        db.storage_ledgers,
        {
            "environment_id": env["id"],
            "kind": kind,
            "bytes": size,
            "rank_index": rank_index,
            "status": "LIVE",
            "archived_at": None,
            # archivable is true once the owning environment's applied release
            # ordinal is at or past the archival floor (PRD §2.8).
            "archivable": _archivable(env),
            "archive_batch_id": None,
            "benchmark_outcome": None,
        },
    )

    environments.storage_breach_evaluation(env)
    db.touch(env)
    return ledger


def _archivable(env):
    ordinal = common.release_ordinal(env)
    if ordinal is None:
        return False
    return ordinal >= calculations.STORAGE_ARCHIVE_MIN_RELEASE


def _window(env, from_rank, to_rank):
    lo, hi = (from_rank, to_rank) if from_rank <= to_rank else (to_rank, from_rank)
    return [
        ledger
        for ledger in db.storage_ledgers.values()
        if ledger["environment_id"] == env["id"] and lo <= ledger["rank_index"] <= hi
    ]


def archive_window(actor, env, b):
    from validate import require_int

    from_rank = require_int(b, "from_rank", min_value=1)
    to_rank = require_int(b, "to_rank", min_value=1)
    rows = _window(env, from_rank, to_rank)

    # 1. every row inside the window must be LIVE.
    for ledger in rows:
        if ledger["status"] != "LIVE":
            fail(ERR_INVALID_STATE, "A ledger inside the window is not LIVE.")

    # 2. at most three FILE ledgers, and every row archivable.
    if sum(1 for ledger in rows if ledger["kind"] == "FILE") > calculations.ARCHIVE_BATCH_FILE_CAP:
        fail(
            ERR_ARCHIVE_BATCH_EXCEEDED,
            "The closed archive window contains more than %d FILE ledgers."
            % calculations.ARCHIVE_BATCH_FILE_CAP,
        )
    for ledger in rows:
        if not ledger.get("archivable"):
            fail(
                ERR_ARCHIVE_BATCH_EXCEEDED,
                "A ledger inside the window is not marked archivable.",
            )

    # 3. the archival floor.
    if not _archivable(env):
        fail(ERR_ARCHIVE_WINDOW_CLOSED, "The archival window is not open.")

    # 4. storage breach.
    if env["storage_breach"]:
        fail(ERR_STORAGE_BREACH, "The environment is in storage breach.")

    batch_id = db.new_id()
    for ledger in rows:
        ledger["status"] = "ARCHIVED"
        ledger["archived_at"] = clock.default_iso()
        ledger["archive_batch_id"] = batch_id
        db.touch(ledger)

    env["last_archive_batch_id"] = batch_id
    # HOP 1: used / archived sums re-derived.
    environments.storage_breach_evaluation(env)
    # HOP 2 (from the Environment write): total, headroom, breach, next_refresh_at.
    environments.refresh_window_next_at(env)
    env["next_refresh_at"] = environments.refresh_window_next_at(env)
    db.touch(env)
    return env


def restore_ledger(actor, ledger):
    env = common.get_environment(ledger["environment_id"])

    if ledger["status"] != "ARCHIVED":
        fail(ERR_INVALID_STATE, "The storage ledger is not ARCHIVED.")

    # Restoring releases bytes back into the live contract, so a breaching
    # environment may not take on more.
    if env["storage_breach"]:
        fail(ERR_STORAGE_BREACH, "The environment is in storage breach.")

    ledger["status"] = "LIVE"
    ledger["archived_at"] = None
    ledger["archive_batch_id"] = None
    db.touch(ledger)

    environments.storage_breach_evaluation(env)
    environments.refresh_window_next_at(env)
    db.touch(env)
    return env