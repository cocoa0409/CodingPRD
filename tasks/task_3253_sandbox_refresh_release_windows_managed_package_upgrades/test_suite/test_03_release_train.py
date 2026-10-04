"""The seasonal release train: the cyclic posture, the preview window, the
reopen precondition and the release cascade."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    apply_release,
    complete_refresh_job,
    create_environment,
    create_ledger,
    get_environment,
    grant_permission,
    install_package,
    load_installation,
    publish_package_version,
    schedule_release,
    schedule_and_apply_release,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RELEASE = TEST_USERS["release_manager_headers"]
ENV_ADMIN = TEST_USERS["environment_admin_headers"]


# ─── The cyclic release posture ───────────────────────────────────────────────

def test_release_schedule_reopens_after_release(api):
    """PRD §3.3: "The result is that an environment cycles `CONFIG` →
    `SCHEDULED` → `RELEASED` → `SCHEDULED` → `RELEASED` → `CONFIG` for as long
    as the organization keeps riding the train."

    Design: Difficulty/non_linear_state_machine/environment_release_schedule_reopens_after_release
    """
    env = create_environment(type="DEVELOPER")
    released = schedule_and_apply_release(env["id"], "SU26")
    assert released["release_status"] == "RELEASED"
    assert released["applied_release_version"] == "SU26"

    rescheduled = validate_success(
        api.schedule_release(env["id"], {"target_release_version": "WI26"}, RELEASE), 200)
    assert rescheduled["release_status"] == "SCHEDULED"
    assert rescheduled["scheduled_release_version"] == "WI26"


def test_release_cycle_keeps_applied_version_across_rescheduling(api):
    """PRD §3.3: "The result is that an environment cycles `CONFIG` →
    `SCHEDULED` → `RELEASED` → `SCHEDULED` → `RELEASED` → `CONFIG` for as long
    as the organization keeps riding the train."

    Design: Difficulty/non_linear_state_machine/environment_release_schedule_reopens_after_release
    """
    env = create_environment(type="DEVELOPER")
    schedule_and_apply_release(env["id"], "SU26")
    api.schedule_release(env["id"], {"target_release_version": "WI26"}, RELEASE)

    env_after = get_environment(env["id"])
    assert env_after["release_status"] == "SCHEDULED"
    assert env_after["applied_release_version"] == "SU26"
    assert env_after["scheduled_release_version"] == "WI26"
    assert env_after["refresh_generation"] >= 1


# ─── Reopening the release window ─────────────────────────────────────────────

def test_reopen_before_aperture_use_is_refused(api):
    """PRD §3.3: "It is valid only when at least one refresh has already passed
    through the environment's aperture — that is, when `aperture_used` is at
    least 1 — because the reopen exists to let an environment that has already
    consumed its refresh allowance be re-scheduled onto a later release."
    PRD §2.12: "State preconditions produce `ERR_INVALID_STATE` with HTTP status
    409."

    Design: Difficulty/scheduled_actions/release_window_reopen_requires_prior_aperture_use
    """
    env = create_environment(type="DEVELOPER")
    schedule_release(env, "SP26")
    before = get_environment(env["id"])
    assert before["release_status"] == "SCHEDULED"
    assert before["aperture_used"] == 0

    res = api.open_release_window(env["id"], RELEASE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    after = get_environment(env["id"])
    assert after["release_status"] == "SCHEDULED"
    assert after["scheduled_release_version"] == "SP26"
    assert after["applied_release_version"] is None


def test_reopen_after_aperture_use_returns_environment_to_config(api):
    """PRD §3.3: "It clears `scheduled_release_version` to null and advances the
    environment's version."
    PRD §3.3: "Reopening the release window is the compensating move that
    returns an environment to `CONFIG` from either `SCHEDULED` or `RELEASED`."

    Design: Difficulty/scheduled_actions/release_window_reopen_requires_prior_aperture_use
    """
    env = create_environment(type="DEVELOPER", refresh_interval_days=1)
    complete_refresh_job(env["id"], masked_field_count=2)
    schedule_and_apply_release(env["id"], "SU26")
    released = get_environment(env["id"])
    assert released["aperture_used"] >= 1

    reopened = validate_success(api.open_release_window(env["id"], RELEASE), 200)
    assert reopened["release_status"] == "CONFIG"
    assert reopened["scheduled_release_version"] is None


# ─── Scheduling gate: the target version must advance ─────────────────────────

def test_scheduling_the_already_applied_version_is_refused(api):
    """PRD §3.3: "The requested version must differ from the environment's
    already-applied version; a schedule that names the version already running
    is refused with `ERR_INVALID_REQUEST` and HTTP status 400."

    Design: Difficulty/cross_entity_state_dependency/schedule_release_requires_target_version_advance
    """
    env = create_environment(type="DEVELOPER", refresh_interval_days=1)
    complete_refresh_job(env["id"], masked_field_count=2)
    schedule_and_apply_release(env["id"], "SU26")
    api.open_release_window(env["id"], RELEASE)
    before = get_environment(env["id"])
    assert before["scheduled_release_version"] is None
    assert before["applied_release_version"] == "SU26"

    res = api.schedule_release(env["id"], {"target_release_version": "SU26"}, RELEASE)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
    assert get_environment(env["id"])["applied_release_version"] == "SU26"


def test_distinct_applied_version_can_be_scheduled_again(api):
    """PRD §3.3: "The requested version must differ from the environment's
    already-applied version; a schedule that names the version already running
    is refused with `ERR_INVALID_REQUEST` and HTTP status 400."

    Design: Difficulty/cross_entity_state_dependency/schedule_release_requires_target_version_advance
    """
    env = create_environment(type="DEVELOPER", refresh_interval_days=1)
    complete_refresh_job(env["id"], masked_field_count=2)
    schedule_and_apply_release(env["id"], "SU26")
    api.open_release_window(env["id"], RELEASE)

    scheduled = validate_success(
        api.schedule_release(env["id"], {"target_release_version": "WI26"}, RELEASE), 200)
    assert scheduled["release_status"] == "SCHEDULED"
    assert scheduled["scheduled_release_version"] == "WI26"
    assert scheduled["applied_release_version"] == "SU26"


# ─── The preview window (release_window_index) ────────────────────────────────

def test_release_window_index_applied_and_scheduled_readings(api):
    """PRD §3.3: "An environment in `SCHEDULED` reports the ordinal of its
    `scheduled_release_version` — this is the scheduling preview that lets a
    client see the window it is about to enter, and it reads the scheduled
    version rather than the applied one. An environment in `RELEASED` reports
    the ordinal of its `applied_release_version` reduced by a launch-protection
    offset of two generations, floored at zero so it can never go negative"

    Design: Difficulty/dual_variant_calc/permission_layer_total_before_vs_after_snapshot_dispatch
    """
    env = create_environment(type="DEVELOPER")
    scheduled = schedule_release(env, "SU26")
    assert scheduled["release_window_index"] == 3

    applied = apply_release(env["id"])
    assert applied["release_window_index"] == 1

    rescheduled = validate_success(
        api.schedule_release(env["id"], {"target_release_version": "WI26"}, RELEASE), 200)
    assert rescheduled["release_status"] == "SCHEDULED"
    assert rescheduled["release_window_index"] == 4


def test_release_window_index_variants_disagree_by_three(api):
    """PRD §3.3: "The two readings are meant to disagree: an environment that
    applied `SU26`, ordinal 3, reports 1 through the released-posture branch,
    while the scheduling preview for a `WI26` schedule, ordinal 4, reports 4 — a
    difference of three positions for the same environment."

    Design: Corner/calculations/release_window_index_applied_and_scheduled_variants
    """
    env = create_environment(type="DEVELOPER")
    scheduled = schedule_release(env, "SU26")
    assert scheduled["release_window_index"] == 3

    applied = apply_release(env["id"])
    assert applied["release_window_index"] == 1

    rescheduled = validate_success(
        api.schedule_release(env["id"], {"target_release_version": "WI26"}, RELEASE), 200)
    assert rescheduled["release_window_index"] == 4
    assert rescheduled["applied_release_version"] == "SU26"
    assert rescheduled["scheduled_release_version"] == "WI26"


def test_release_window_index_threshold_ordinals(api):
    """PRD §2.9: "The seasonal train is ordered, and the orderings used
    throughout this API are: `WI25` at ordinal 1, `SP26` at ordinal 2, `SU26` at
    ordinal 3 and `WI26` at ordinal 4."

    Design: Corner/calculations/release_window_index_threshold_ordinals
    """
    env = create_environment(type="DEVELOPER")
    assert get_environment(env["id"])["release_window_index"] == 1

    scheduled = schedule_release(env, "WI26")
    assert scheduled["release_window_index"] == 4

    applied = apply_release(env["id"])
    assert applied["applied_release_version"] == "WI26"
    assert applied["release_status"] == "RELEASED"
    assert applied["release_window_index"] == 2


# ─── Posture gate and role separation ─────────────────────────────────────────

def test_apply_release_before_scheduling_is_refused(api):
    """PRD §2.12: "The first is the environment's release posture: applying a
    release requires the environment to be `SCHEDULED`; scheduling a release is
    valid from `CONFIG` or from `RELEASED`"

    Design: Corner/errors/apply_release_before_scheduling_returns_invalid_state
    """
    env = create_environment(type="DEVELOPER")
    before = get_environment(env["id"])
    assert before["release_status"] == "CONFIG"

    res = api.apply_release(env["id"], RELEASE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    after = get_environment(env["id"])
    assert after["release_status"] == "CONFIG"
    assert after["applied_release_version"] is None
    assert after["refresh_generation"] == 0


def test_environment_admin_cannot_apply_release(api):
    """PRD §2.1: "`ReleaseManager` owns the seasonal release train and the
    deployment pipeline."
    PRD §2.1: "A request whose role is recognized but is not listed among the
    authorized roles for the addressed operation is rejected with
    `ERR_UNAUTHORIZED` and HTTP status 403."

    Design: Corner/validations/environment_admin_cannot_apply_release
    """
    env = create_environment(type="DEVELOPER")
    schedule_release(env, "SP26")

    res = api.apply_release(env["id"], ENV_ADMIN)
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)

    after = get_environment(env["id"])
    assert after["release_status"] == "SCHEDULED"
    assert after["refresh_generation"] == 0
    assert after["applied_release_version"] is None


# ─── Forward half of the release cycle ────────────────────────────────────────

def test_release_schedule_forward_cycle(api):
    """PRD §3.3: "An environment sits in `CONFIG` until a `ReleaseManager`
    schedules it, in `SCHEDULED` until the release is applied, and in `RELEASED`
    thereafter"
    PRD §3.3: "On success `applied_release_version` takes the scheduled version,
    `refresh_generation` advances by one independently of the release status,
    and the environment's release cascade fires."

    Design: Corner/state_machines/environment_release_schedule_valid_transition_cycle
    """
    env = create_environment(type="DEVELOPER")
    scheduled = schedule_release(env, "SP26")
    assert scheduled["release_status"] == "SCHEDULED"
    assert scheduled["scheduled_release_version"] == "SP26"

    applied = apply_release(env["id"])
    assert applied["release_status"] == "RELEASED"
    assert applied["applied_release_version"] == "SP26"
    assert applied["refresh_generation"] == 1
    # RELEASED reports the applied ordinal (SP26 -> 2) less the launch-protection
    # offset of 2, floored at zero.
    assert applied["release_window_index"] == 0


# ─── The release cascade ──────────────────────────────────────────────────────

def test_apply_release_invalidates_installation(api):
    """PRD §3.3: "That cascade is the same three-hop shape described in §2.7:
    every non-`UNINSTALLED` installation of the environment has its `refreshed_at`
    stamped and re-enters `NEEDS_UPGRADE` wherever a newer non-deprecated
    candidate exists"

    Design: Difficulty/transitive_cascade/release_apply_three_hop_cascade
    """
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    pkg = install_package(env, v1["id"])
    publish_package_version("acme", 2, supersedes_version_id=v1["id"])
    schedule_release(env, "SU26")

    applied = apply_release(env["id"])
    assert applied["applied_release_version"] == "SU26"

    pkg_after = load_installation(env["id"], pkg["id"])
    assert pkg_after["status"] == "NEEDS_UPGRADE"
    assert pkg_after["stale"] is True


def test_apply_release_rederives_grant_sharing_scope(api):
    """PRD §3.3: "the installation write then drives
    `PermissionAssignment.sharing_rule_scope` to `ORG_WIDE` for every
    non-revoked grant of the environment"

    Design: Difficulty/transitive_cascade/release_apply_three_hop_cascade
    """
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    install_package(env, v1["id"])
    grant = grant_permission(env["id"], "PROFILE", "AcmeUser", "0050a000020001",
                             object_prefix="acme")
    schedule_release(env, "SU26")

    apply_release(env["id"])

    rows, _ = validate_paginated(
        api_client.list_permissions(env["id"], TEST_USERS["storage_archivist_headers"]))
    grant_after = next(row for row in rows if row["id"] == grant["id"])
    assert grant_after["sharing_rule_scope"] == "ORG_WIDE"


def test_apply_release_marks_file_ledger_archivable(api):
    """PRD §3.3: "and drives `StorageLedger.archivable` to true for every file
    ledger of the environment."

    Design: Difficulty/transitive_cascade/release_apply_three_hop_cascade
    """
    env = create_environment(type="PARTIAL")
    ledger = create_ledger(env["id"], "FILE", 1048576, 1)
    assert ledger["archivable"] is False

    schedule_and_apply_release(env["id"], "SU26")

    rows, _ = validate_paginated(api_client.list_storage_ledgers(env["id"], ADMIN))
    assert next(row for row in rows if row["id"] == ledger["id"])["archivable"] is True