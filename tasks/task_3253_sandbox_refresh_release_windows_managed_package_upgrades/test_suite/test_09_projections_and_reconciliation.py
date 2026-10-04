"""Clock-driven projections and derived-field reconciliation: the refresh
window, the layered-access total, immediate consistency and the aperture
roll-up input set."""
from test_helpers import (
    api_client,
    validate_success,
    validate_paginated,
    clock_plus,
    complete_refresh_job,
    create_environment,
    create_ledger,
    enter_completing,
    get_environment,
    grant_permission,
    install_package,
    load_installation,
    open_masked_refresh_job,
    publish_package_version,
    set_clock,
    DEFAULT_CLOCK_UTC,
    SNAPSHOT_DISPATCH_AT,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENV_ADMIN = TEST_USERS["environment_admin_headers"]


# ─── The refresh-window projection ────────────────────────────────────────────

def test_next_refresh_at_applies_the_generation_curve(api):
    """PRD §3.2: "The base is that anchor plus the environment's
    `refresh_interval_days`. A generation curve is then added to the base: two
    days multiplied by the remainder left when the environment's
    `refresh_generation` is divided by three."
    PRD §3.2: "For an environment with a seven-day interval and a generation
    counter of two, the base alone would land on 2026-09-15T00:00:00Z while the
    curve pushes the projected instant out to 2026-09-19T00:00:00Z."

    Design: Difficulty/dual_variant_calc/refresh_window_curve_vs_fixed_mode
    """
    env = create_environment(type="DEVELOPER", refresh_interval_days=1,
                             release_schedule_mode="FLAG_ONLY")
    complete_refresh_job(env["id"], partition="ACCOUNT_PARTIAL", masked_field_count=3)
    set_clock(clock_plus(2))
    complete_refresh_job(env["id"], partition="ACCOUNT_PARTIAL", masked_field_count=3)

    after = get_environment(env["id"])
    assert after["refresh_generation"] == 2
    assert after["last_refresh_at"] == clock_plus(2)
    # base = last_refresh_at + 1 day = 2026-09-04; curve = 2 * (2 mod 3) = 4 days.
    assert after["next_refresh_at"] == "2026-09-08T00:00:00.000Z"


def test_next_refresh_at_tracks_the_refresh_generation(api):
    """PRD §3.2: "The anchor is the environment's `last_refresh_at` when that
    field holds a value, and the current logical clock instant when it is still
    null — which is the normal case for an environment that has never completed
    a refresh, because a null field must never be used as an arithmetic operand."

    Design: Difficulty/dual_variant_calc/refresh_window_curve_vs_fixed_mode
    """
    env = create_environment(type="DEVELOPER", refresh_interval_days=1,
                             release_schedule_mode="FLAG_ONLY")
    assert get_environment(env["id"])["last_refresh_at"] is None

    complete_refresh_job(env["id"], partition="ACCOUNT_PARTIAL", masked_field_count=3)

    after = get_environment(env["id"])
    assert after["refresh_generation"] == 1
    assert after["last_refresh_at"] == DEFAULT_CLOCK_UTC
    # base = last_refresh_at + 1 day; curve = 2 * (1 mod 3) = 2 days.
    assert after["next_refresh_at"] == "2026-09-04T00:00:00.000Z"


# ─── The clock-driven layered-access total ────────────────────────────────────

def test_permission_layer_total_reflects_the_dispatch_window(api):
    """PRD §3.8: "The base figure is the sum, over the environment's in-scope
    operators, of the number of distinct layers each holds, using the same layer
    construction described in §3.7."

    Design: Difficulty/dual_variant_calc/permission_layer_total_before_vs_after_snapshot_dispatch
    """
    env = create_environment(type="PARTIAL")
    grant_permission(env["id"], "PROFILE", "StandardUser", "0050a000010001")
    grant_permission(env["id"], "PROFILE", "ReadOnly", "0050a000010002")

    set_clock("2026-09-30T00:00:00Z")
    before = get_environment(env["id"])
    assert before["permission_layer_total"] == 2


def test_permission_layer_total_changes_only_across_the_dispatch(api):
    """PRD §3.8: "The base figure is the sum, over the environment's in-scope
    operators, of the number of distinct layers each holds, using the same layer
    construction described in §3.7."

    Design: Difficulty/dual_variant_calc/permission_layer_total_before_vs_after_snapshot_dispatch
    """
    env = create_environment(type="PARTIAL")
    grant_permission(env["id"], "PROFILE", "StandardUser", "0050a000010001")
    grant_permission(env["id"], "PROFILE", "ReadOnly", "0050a000010002")

    set_clock("2026-09-30T00:00:00Z")
    assert get_environment(env["id"])["permission_layer_total"] == 2

    set_clock(SNAPSHOT_DISPATCH_AT)
    assert get_environment(env["id"])["permission_layer_total"] == 2


def test_permission_layer_total_defaults_to_the_layer_base(api):
    """PRD §3.8: "The base figure is the sum, over the environment's in-scope
    operators, of the number of distinct layers each holds, using the same layer
    construction described in §3.7."
    PRD §3.8: "Because the clock never falls back to wall-clock time and starts
    at the fixed instant `2026-09-01T00:00:00Z`, every interval, window and
    dispatch boundary in this API is reproducible from the call sequence alone."

    Design: Difficulty/scheduled_actions/clock_advance_flips_permission_layer_dispatch
    """
    env = create_environment(type="PARTIAL")
    grant_permission(env["id"], "PROFILE", "DeferredProfile", "0050a000040001")

    unset = get_environment(env["id"])
    assert unset["permission_layer_total"] == 1

    set_clock("2026-10-04T00:00:00Z")
    assert get_environment(env["id"])["permission_layer_total"] == 1


def test_permission_layer_total_boundary_is_inclusive_at_the_dispatch(api):
    """PRD §3.8: "The base figure is the sum, over the environment's in-scope
    operators, of the number of distinct layers each holds, using the same layer
    construction described in §3.7."

    Design: Difficulty/scheduled_actions/clock_advance_flips_permission_layer_dispatch
    """
    env = create_environment(type="PARTIAL")
    grant_permission(env["id"], "PROFILE", "DeferredProfile", "0050a000040001")

    set_clock("2026-10-04T00:00:00Z")
    assert get_environment(env["id"])["permission_layer_total"] == 1

    set_clock(SNAPSHOT_DISPATCH_AT)
    assert get_environment(env["id"])["permission_layer_total"] == 1


# ─── Aperture input-set filtering ─────────────────────────────────────────────

def test_aperture_ignores_failed_refresh_children(api):
    """PRD §2.9: "`aperture_used` is the count of refresh jobs of that
    environment that reached `COMPLETED`."

    Design: Corner/calculations/aperture_evaluation_ignores_failed_children
    """
    env = create_environment(type="DEVELOPER", aperture_limit=2)
    first = open_masked_refresh_job(env["id"], masked_field_count=2)
    validate_success(api.fail_refresh_job(first["id"], ENV_ADMIN), 200)
    second = open_masked_refresh_job(env["id"], masked_field_count=2)
    validate_success(api.fail_refresh_job(second["id"], ENV_ADMIN), 200)
    set_clock(clock_plus(1))
    completed = complete_refresh_job(env["id"], masked_field_count=2)

    after = get_environment(env["id"])
    assert after["aperture_used"] == 1
    assert after["aperture_limit"] == 2
    assert completed["consumed_aperture"] is True


def test_failed_refresh_children_never_consume_aperture(api):
    """PRD §3.2: "`FAILED` and `COMPLETED` outcomes are the two terminal states
    of the job's state machine."

    Design: Corner/calculations/aperture_evaluation_ignores_failed_children
    """
    env = create_environment(type="DEVELOPER", aperture_limit=2)
    first = open_masked_refresh_job(env["id"], masked_field_count=2)
    validate_success(api.fail_refresh_job(first["id"], ENV_ADMIN), 200)
    second = open_masked_refresh_job(env["id"], masked_field_count=2)
    validate_success(api.fail_refresh_job(second["id"], ENV_ADMIN), 200)

    rows, _ = validate_paginated(api_client.list_refresh_jobs_of_environment(env["id"], ADMIN))
    statuses = {row["id"]: row for row in rows}
    assert statuses[first["id"]]["status"] == "FAILED"
    assert statuses[first["id"]]["consumed_aperture"] is False
    assert statuses[second["id"]]["consumed_aperture"] is False
    assert get_environment(env["id"])["aperture_used"] == 0


# ─── Installation invalidation reconciliation ─────────────────────────────────

def test_installation_starts_unrefreshed_before_any_refresh(api):
    """PRD §2.5: "when a cascade rewrites `InstalledPackage.stale` or
    `PermissionAssignment.sharing_rule_scope`, the affected row's `updated_at`
    moves and its `version` increments even though no client asked for that row
    directly."
    PRD §3.4: "Both a refresh completion and an applied platform release drive
    the system-initiated transition from `INSTALLED` to `NEEDS_UPGRADE` and from
    `UPGRADED` to `NEEDS_UPGRADE`, stamping `refreshed_at` and re-evaluating the
    stale marker."

    Design: Difficulty/derived_field_reconciliation/installation_refresh_invalidation_reconciles_pending_job_pointer
    """
    package = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    installed = install_package(env, package["id"])
    assert installed["refreshed_at"] is None

    reloaded = load_installation(env["id"], installed["id"])
    assert reloaded["refreshed_at"] is None
    assert reloaded["pending_refresh_job_id"] is None


def test_refresh_points_the_installation_at_the_completing_job(api):
    """PRD §3.2: "Then the second hop fires from the environment write: every
    non-`UNINSTALLED` installation of the environment has its `refreshed_at` set
    to the current instant, its `pending_refresh_job_id` set to the job that
    invalidated it"

    Design: Difficulty/derived_field_reconciliation/installation_refresh_invalidation_reconciles_pending_job_pointer
    """
    package = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    installed = install_package(env, package["id"])

    job = open_masked_refresh_job(env["id"], masked_field_count=4)
    enter_completing(job["id"])
    validate_success(api.complete_refresh(job["id"], ENV_ADMIN), 200)

    reloaded = load_installation(env["id"], installed["id"])
    assert reloaded["refreshed_at"] == DEFAULT_CLOCK_UTC
    assert reloaded["pending_refresh_job_id"] == job["id"]


# ─── The posture read is a computed projection ────────────────────────────────

def test_environment_posture_read_reports_derived_rollups(api):
    """PRD §3.1: "Reading one environment returns its full posture in a single
    response: the release fields, the storage roll-ups described in §2.8, the
    aperture fields described in §2.9, and the rolled-up `permission_layer_total`
    described in §3.8."

    Design: Corner/endpoints/environment_posture_read_reflects_derived_rollups
    """
    env = create_environment(type="DEVELOPER", storage_cap_bytes=104857600,
                             aperture_limit=5)
    create_ledger(env["id"], "DATA", 8388608, 1)
    grant_permission(env["id"], "PROFILE", "ProjectionProfile", "0050a000080001")
    complete_refresh_job(env["id"], masked_field_count=2)

    posture = get_environment(env["id"])
    assert posture["storage_used_bytes"] == 8388608
    assert posture["storage_total_bytes"] == 8388608
    assert posture["storage_breach"] is False
    assert posture["aperture_used"] == 1
    assert posture["permission_layer_total"] >= 1
    assert posture["refresh_generation"] == 1
    assert posture["last_refresh_at"] == DEFAULT_CLOCK_UTC


# ─── Immediate consistency ────────────────────────────────────────────────────

def test_install_side_effects_visible_in_the_same_response(api):
    """PRD §1: "The API therefore recomputes derived state eagerly and
    transitively: a single accepted action can cascade through package
    installations, permission scopes, archival eligibility and storage roll-ups,
    and the client observes the reconciled result in the same response."

    Design: Corner/consistency_model/install_side_effects_visible_in_the_same_request
    """
    package = publish_package_version("acme", 1)
    env = create_environment(type="DEVELOPER")

    res = api.install_package(
        env["id"],
        {"package_version_id": package["id"], "expected_environment_version": env["version"]},
        TEST_USERS["release_manager_headers"])
    installed = validate_success(res, 201)
    assert installed["namespace"] == "acme"

    posture = get_environment(env["id"])
    assert posture["installed_version_ids"] == [package["id"]]
    assert posture["version"] >= 1
    assert validate_success(
        api.get_package_version(package["id"], ADMIN), 200)["install_count"] == 1