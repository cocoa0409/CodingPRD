"""The sandbox refresh lifecycle (PRD §3.2).

PENDING -> MASKING -> COMPLETING -> COMPLETED is the happy branch; the
MASKING -> FAILED branch terminates without consuming aperture.  COMPLETING is
the join point that emits the refresh cascade.
"""

import clock
import db
from errors import (
    ERR_BUSINESS_RULE_VIOLATION,
    ERR_INVALID_STATE,
    ERR_MASKING_INSUFFICIENT,
    ERR_REFRESH_APERTURE_EXCEEDED,
    ERR_RELEASE_MISMATCH,
    ERR_STORAGE_BREACH,
    fail,
)
from services import common, environments, packages

FULL_COPY_MASKING_FLOOR = 20


def create_refresh_job(actor, b):
    from validate import optional_int, require_enum, require_string

    environment_id = require_string(b, "environment_id")
    env = common.get_environment(environment_id)
    partition = require_enum(b, "partition", ("FULL", "ACCOUNT_PARTIAL"))
    masked_field_count = optional_int(b, "masked_field_count", min_value=0, default=0)

    return db.create(
        db.refresh_jobs,
        {
            "environment_id": env["id"],
            "partition": partition,
            "status": "PENDING",
            "masked_field_count": masked_field_count,
            "consumed_aperture": False,
            "supersedes_job_id": None,
        },
    )


def complete_masking(actor, job):
    env = common.get_environment(job["environment_id"])

    if job["status"] != "PENDING":
        fail(ERR_INVALID_STATE, "The refresh job is not in PENDING.")

    if job["masked_field_count"] < 1:
        fail(
            ERR_MASKING_INSUFFICIENT,
            "The declared masking coverage must cover at least one field.",
        )

    if env["type"] == "FULL_COPY" and job["masked_field_count"] < FULL_COPY_MASKING_FLOOR:
        fail(
            ERR_MASKING_INSUFFICIENT,
            "A FULL_COPY refresh requires masked_field_count of at least %d."
            % FULL_COPY_MASKING_FLOOR,
        )

    job["status"] = "MASKING"
    db.touch(job)
    return job


def complete_refresh(actor, job):
    env = common.get_environment(job["environment_id"])

    if job["status"] == "MASKING":
        # First call of the join: no side effects beyond the state change.
        job["status"] = "COMPLETING"
        db.touch(job)
        return job

    if job["status"] != "COMPLETING":
        fail(ERR_INVALID_STATE, "The refresh job is not in COMPLETING.")

    # --- gates, in the order §2.12 fixes -----------------------------------
    parent_id = env.get("parent_environment_id")
    if parent_id:
        parent = db.environments.get(parent_id)
        if parent is not None and parent.get("applied_release_version") != env.get(
            "applied_release_version"
        ):
            fail(
                ERR_RELEASE_MISMATCH,
                "The refresh would cross a release boundary from its parent environment.",
            )

    if not environments.aperture_post_completion_allows(env):
        env["aperture_consumed"] = False
        db.touch(env)
        fail(
            ERR_REFRESH_APERTURE_EXCEEDED,
            "The environment's refresh aperture is exhausted.",
        )

    if env["storage_breach"]:
        fail(ERR_STORAGE_BREACH, "The environment is in storage breach.")

    # Independently of the gates, the refresh interval itself is enforced.
    last = env.get("last_refresh_at")
    if last is not None:
        elapsed = clock.day_delta(clock.now(), last)
        if elapsed < env["refresh_interval_days"] + 1:
            fail(
                ERR_BUSINESS_RULE_VIOLATION,
                "The sandbox refresh interval has not yet elapsed.",
            )

    # --- admitted completion: HOP 1 ----------------------------------------
    job["status"] = "COMPLETED"
    job["consumed_aperture"] = True
    db.touch(job)

    env["last_refresh_at"] = clock.now()
    env["refresh_generation"] = env.get("refresh_generation", 0) + 1
    # aperture_used is recomputed as the count of COMPLETED jobs, so the job's
    # terminal status must already be in place.
    environments.aperture_consumption_evaluation(env)
    environments.storage_breach_evaluation(env)
    db.touch(env)

    # --- HOP 2: the refresh invalidates every non-UNINSTALLED installation --
    invalidated = []
    for row in db.installed_packages.values():
        if row["environment_id"] != env["id"] or row["status"] == "UNINSTALLED":
            continue
        row["refreshed_at"] = clock.default_iso()
        row["pending_refresh_job_id"] = job["id"]
        row["stale"] = True
        db.touch(row)
        invalidated.append(row)

    # HOP 2 (from the Environment write): the refresh-window projection.
    env["next_refresh_at"] = environments.refresh_window_next_at(env)

    # --- HOP 3: installed_version_ids and the conflict set -----------------
    # The stale marker is re-derived here, so an installation can legitimately
    # end the cascade with stale == false and re-enters NEEDS_UPGRADE only
    # where a newer non-deprecated candidate actually exists (PRD §3.3).
    packages.upgrade_candidate_evaluation(env)
    for row in invalidated:
        if row["stale"] and row["status"] != "NEEDS_UPGRADE":
            row["status"] = "NEEDS_UPGRADE"
            db.touch(row)
    packages.package_conflict_resolution(env)
    db.touch(env)

    return job


def fail_refresh_job(actor, job):
    if job["status"] != "MASKING":
        fail(ERR_INVALID_STATE, "The refresh job is not in MASKING.")

    job["status"] = "FAILED"
    job["consumed_aperture"] = False
    db.touch(job)
    return job