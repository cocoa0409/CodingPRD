"""The seasonal release train and its preview windows (PRD §2.9, §3.3).

The train is cyclic: CONFIG -> SCHEDULED -> RELEASED -> SCHEDULED -> RELEASED ->
CONFIG.  Applying a release emits the release cascade, whose first hop stamps
every non-UNINSTALLED installation of the environment and re-enters it into
NEEDS_UPGRADE wherever a newer non-deprecated candidate exists.
"""

import clock
import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REFRESH_APERTURE_EXCEEDED,
    ERR_STORAGE_BREACH,
    fail,
)
from services import common, environments, packages, permissions

SCHEDULE_VALID_FROM = ("CONFIG", "RELEASED")
OPEN_WINDOW_VALID_FROM = ("CONFIG", "SCHEDULED", "RELEASED")


def schedule_release(actor, env, b):
    from validate import require_string

    target = require_string(b, "target_release_version")

    # 1. release posture: valid from CONFIG or RELEASED.
    if env["release_status"] not in SCHEDULE_VALID_FROM:
        fail(ERR_INVALID_STATE, "The environment's release posture does not permit scheduling.")

    # 2. aperture rule (level 1 is exempt).
    if not environments.aperture_allows(env):
        fail(
            ERR_REFRESH_APERTURE_EXCEEDED,
            "The environment's refresh aperture is exhausted.",
        )

    # 3. must not be in storage breach.
    if env["storage_breach"]:
        fail(ERR_STORAGE_BREACH, "The environment is in storage breach.")

    # 4. the requested version must differ from the already-applied one.
    if target == env.get("applied_release_version"):
        fail(ERR_INVALID_REQUEST, "The target release version is already applied.")

    env["release_status"] = "SCHEDULED"
    env["scheduled_release_version"] = target
    env["release_window_index"] = environments.release_window_index(env)
    db.touch(env)
    return env


def apply_release(actor, env):
    if env["release_status"] != "SCHEDULED" or not env.get("scheduled_release_version"):
        fail(ERR_INVALID_STATE, "The environment is not SCHEDULED onto a release.")

    for change_set in db.change_sets.values():
        if (
            change_set["target_environment_id"] == env["id"]
            and change_set["status"] == "VALIDATED"
        ):
            fail(
                ERR_INVALID_STATE,
                "A validated change set is queued against this environment.",
            )

    # HOP 0: the environment-level write.
    env["applied_release_version"] = env["scheduled_release_version"]
    env["release_status"] = "RELEASED"
    env["release_window_index"] = environments.release_window_index(env)
    env["refresh_generation"] = env.get("refresh_generation", 0) + 1
    db.touch(env)

    # HOP 1: every non-UNINSTALLED installation is stamped and reconsidered.
    for row in db.installed_packages.values():
        if row["environment_id"] != env["id"] or row["status"] == "UNINSTALLED":
            continue
        row["refreshed_at"] = clock.default_iso()
        db.touch(row)

    # HOP 2 (from the InstalledPackage write): sharing scopes, derived ORG_WIDE.
    permissions.recompute_sharing_scopes(env, mode="ORG_WIDE")

    # HOP 2 (from the InstalledPackage write): archival eligibility.
    _recompute_archivable(env)

    # The installation write re-derives the stale marker: an installation can
    # legitimately end the cascade with stale == false (PRD §3.3).
    packages.upgrade_candidate_evaluation(env)
    for row in db.installed_packages.values():
        if row["environment_id"] != env["id"] or row["status"] == "UNINSTALLED":
            continue
        if row["stale"] and row["status"] != "NEEDS_UPGRADE":
            row["status"] = "NEEDS_UPGRADE"
            db.touch(row)
    packages.package_conflict_resolution(env)
    return env


def _is_archivable(env, ledger):
    """archivable is true once the applied release reaches the archival floor.

    The marker is derived for every ledger row; the batch-size cap is the rule
    that separates FILE rows from DATA rows (PRD §2.8, §3.6).
    """
    ordinal = common.release_ordinal(env)
    if ordinal is None:
        return False
    import calculations

    return ordinal >= calculations.STORAGE_ARCHIVE_MIN_RELEASE


def _recompute_archivable(env):
    for ledger in db.storage_ledgers.values():
        if ledger["environment_id"] != env["id"]:
            continue
        archivable = _is_archivable(env, ledger)
        if ledger.get("archivable") != archivable:
            ledger["archivable"] = archivable
            db.touch(ledger)


def open_release_window(actor, env):
    if env["release_status"] not in OPEN_WINDOW_VALID_FROM:
        fail(ERR_INVALID_STATE, "The environment's release posture does not permit reopening.")

    if env.get("aperture_used", 0) < 1:
        fail(
            ERR_INVALID_STATE,
            "No refresh has passed through the environment's aperture.",
        )

    env["release_status"] = "CONFIG"
    env["scheduled_release_version"] = None
    env["release_window_index"] = environments.release_window_index(env)
    db.touch(env)
    return env