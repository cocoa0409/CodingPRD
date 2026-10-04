"""Environment lifecycle, storage roll-ups, the refresh-window projection and
the aperture gate (PRD §2.4, §2.8, §2.9, §3.2).

Three of the platform's nine calculations live here.  The clock-dependent ones
(``next_refresh_at`` and ``permission_layer_total``) are computed on read so
that a clock advance is reflected immediately, and cached on the row so that a
clock advance does not itself look like a mutation of the environment.
"""

import calculations
import clock
import db
from errors import ERR_INVALID_REQUEST, fail
from services import common

MANUAL_FIXED = "MANUAL_FIXED"


def refresh_window_next_at(env, generation=None):
    """Project when the next sandbox refresh may start (PRD §3.2).

    anchor = last_refresh_at when set, else the current logical instant;
    base   = anchor + refresh_interval_days;
    curve  = 2 * (refresh_generation mod 3), dropped entirely for an
    environment whose release_schedule_mode is MANUAL_FIXED.
    """
    anchor = env.get("last_refresh_at")
    if anchor is None:
        anchor = clock.now()
    base = clock.add_days(anchor, env["refresh_interval_days"])
    if env.get("release_schedule_mode") == MANUAL_FIXED:
        return base
    gen = env.get("refresh_generation", 0) if generation is None else generation
    curve = calculations.REFRESH_CURVE_STEP_DAYS * (gen % calculations.REFRESH_CURVE_MODULUS)
    return clock.add_days(base, curve)


def recompute_next_refresh_at(env):
    """Re-derive the projection.

    ``next_refresh_at`` is a projection of the environment's authored state
    (interval, anchor, generation) rather than authored state itself, so
    re-deriving it does not register as a mutation of the environment.  The
    endpoints whose own writes drive the projection bump the version
    themselves.
    """
    env["next_refresh_at"] = refresh_window_next_at(env)
    return env["next_refresh_at"]


def create_environment(actor, b):
    from validate import ENVIRONMENT_TYPES, optional_int, optional_string
    from validate import require_enum, require_string

    name = require_string(b, "name")
    env_type = require_enum(b, "type", ENVIRONMENT_TYPES)

    for existing in db.environments.values():
        if existing["name"] == name:
            fail(
                ERR_INVALID_REQUEST,
                "An environment named '%s' already exists." % name,
            )

    parent_id = optional_string(b, "parent_environment_id", default=None)
    parent = None
    if env_type == "PRODUCTION":
        if parent_id is not None:
            fail(ERR_INVALID_REQUEST, "A PRODUCTION environment cannot have a parent.")
        level = None
    else:
        if parent_id is None:
            fail(
                ERR_INVALID_REQUEST,
                "A %s environment must name its parent_environment_id." % env_type,
            )
        parent = common.get_environment(parent_id)
        # Clone depth is 1-based: a sandbox created directly from production
        # sits at level 1, and a sandbox cloned from that sandbox sits at
        # level 2 (PRD §2.4).
        parent_level = parent.get("level")
        level = 1 if parent_level is None else parent_level + 1

    refresh_interval_days = optional_int(
        b, "refresh_interval_days", min_value=1, max_value=365,
        default=calculations.DEFAULT_REFRESH_INTERVAL_DAYS,
    )
    masked_field_count = optional_int(b, "masked_field_count", min_value=0, default=0)
    storage_cap_bytes = optional_int(
        b, "storage_cap_bytes", min_value=1, default=calculations.DEFAULT_STORAGE_CAP_BYTES
    )
    release_schedule_mode = optional_string(
        b, "release_schedule_mode", default=calculations.DEFAULT_RELEASE_SCHEDULE_MODE
    )
    if release_schedule_mode not in calculations.RELEASE_SCHEDULE_MODES:
        fail(ERR_INVALID_REQUEST, "release_schedule_mode is outside its declared set.")
    aperture_limit = optional_int(
        b, "aperture_limit", min_value=0, max_value=10,
        default=calculations.DEFAULT_APERTURE_LIMIT,
    )

    env = db.create(
        db.environments,
        {
            "name": name,
            "type": env_type,
            "parent_environment_id": parent_id,
            "refresh_interval_days": refresh_interval_days,
            "last_refresh_at": None,
            "next_refresh_at": None,
            "masked_field_count": masked_field_count,
            "storage_cap_bytes": storage_cap_bytes,
            "storage_used_bytes": 0,
            "storage_archived_bytes": 0,
            "storage_total_bytes": 0,
            "storage_breach": False,
            "storage_headroom_bytes": 0,
            "last_archive_batch_id": None,
            "permission_layer_total": 0,
            "level": level,
            "release_status": "CONFIG",
            "scheduled_release_version": None,
            "applied_release_version": None,
            "release_schedule_mode": release_schedule_mode,
            "aperture_limit": aperture_limit,
            "aperture_used": 0,
            "aperture_consumed": True,
            "release_window_index": 1,
            "refresh_generation": 0,
            "installed_version_ids": [],
            "_layer_total_cache": None,
        },
    )
    # release_window_index is 1 while the environment is in CONFIG (§3.1).
    env["release_window_index"] = release_window_index(env)
    env["next_refresh_at"] = refresh_window_next_at(env)
    return env


def storage_breach_evaluation(env):
    """Re-derive the four conserved storage figures (PRD §2.8)."""
    used = 0
    archived = 0
    for ledger in db.storage_ledgers.values():
        if ledger["environment_id"] != env["id"]:
            continue
        if ledger["status"] == "LIVE":
            used += ledger["bytes"]
        else:
            archived += ledger["bytes"]
    env["storage_used_bytes"] = used
    env["storage_archived_bytes"] = archived
    env["storage_total_bytes"] = used + archived
    env["storage_headroom_bytes"] = env["storage_total_bytes"] - env["storage_cap_bytes"]
    env["storage_breach"] = used >= env["storage_cap_bytes"]
    return env


def aperture_consumption_evaluation(env):
    """Count the completed refresh jobs and refresh the aperture admission flag."""
    after = sum(
        1
        for job in db.refresh_jobs.values()
        if job["environment_id"] == env["id"] and job["status"] == "COMPLETED"
    )
    env["aperture_used"] = after
    gate_applies = (env.get("level") or 0) >= calculations.REFRESH_APERTURE_BASE_LEVEL
    admitted = (not gate_applies) or (after <= env["aperture_limit"])
    env["aperture_consumed"] = admitted
    return env


def aperture_allows(env):
    """The aperture gate as a precondition (inclusive comparison, §3.2)."""
    if (env.get("level") or 0) < calculations.REFRESH_APERTURE_BASE_LEVEL:
        return True
    return env["aperture_used"] < env["aperture_limit"]


def aperture_post_completion_allows(env):
    after = env["aperture_used"] + 1
    if (env.get("level") or 0) < calculations.REFRESH_APERTURE_BASE_LEVEL:
        return True
    return after <= env["aperture_limit"]


def release_window_index(env):
    """Ordinal position inside the seasonal release train (PRD §2.9)."""
    status = env.get("release_status")
    if status == "RELEASED":
        ordinal = calculations.release_ordinal(env.get("applied_release_version"))
        if ordinal is None:
            return 1
        return max(0, ordinal - calculations.LAUNCH_PROTECT_GENERATIONS)
    if status == "SCHEDULED":
        ordinal = calculations.release_ordinal(env.get("scheduled_release_version"))
        if ordinal is None:
            return 1
        return ordinal
    return 1


def recompute_release_window_index(env):
    """Re-derive the index without registering a mutation (see above)."""
    env["release_window_index"] = release_window_index(env)
    return env["release_window_index"]


def payment_layer_total(env):
    """Project the rolled-up layered-access total (PRD §3.8).

    The base is the sum, over the environment's in-scope operators, of the
    number of distinct layers each holds; when the environment holds a
    SNAPSHOT_START backlog request and the logical clock has reached the
    dispatch instant, two backlogged layers are added.  The figure is always
    recomputed (the underlying grants may have changed); the cached copy is
    only used to detect a genuine change so that a pure re-derivation does not
    register as a mutation of the environment.
    """
    from services import permissions

    users = permissions.in_scope_users(env["id"])
    base = sum(permissions.layer_sum(env["id"], user) for user in users)

    backlog_open = any(
        request["environment_id"] == env["id"]
        and request.get("request_kind") == calculations.SNAPSHOT_START_KIND
        for request in db.governor_requests.values()
    )
    dispatch_at = clock.parse(clock.SNAPSHOT_DISPATCH_AT)
    if backlog_open and clock.now() >= dispatch_at:
        total = base + calculations.ASYNC_BACKLOG_LAYERS
    else:
        total = base

    if env.get("_layer_total_cache") != total:
        env["_layer_total_cache"] = total
        env["permission_layer_total"] = total
    return total


def recompute_all_clock_projections():
    """Re-derive every clock-dependent projection (PRD §3.8).

    Advancing the logical clock re-evaluates every environment's next_refresh_at
    and permission_layer_total, and re-evaluates the scheduled/deferred
    release-window comparisons.  These are projections of each environment's
    authored state rather than authored state itself, so the re-evaluation does
    not advance the environment's version — the caller's own clock write is the
    only mutation.
    """
    for env in db.environments.values():
        recompute_next_refresh_at(env)
        payment_layer_total(env)
        recompute_release_window_index(env)