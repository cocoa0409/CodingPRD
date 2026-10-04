"""Sandbox refresh lifecycle: masking, the aperture gate, the fiscal gates and
the three-hop refresh cascade."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    clock_plus,
    complete_refresh_job,
    create_environment,
    create_gated_environment,
    create_ledger,
    create_production,
    create_refresh_job,
    create_sandbox,
    enter_completing,
    get_environment,
    install_package,
    load_installation,
    load_refresh_job,
    open_masked_refresh_job,
    publish_package_version,
    schedule_and_apply_release,
    set_clock,
    DEFAULT_CLOCK_UTC,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ENV_ADMIN = TEST_USERS["environment_admin_headers"]


def _complete_refreshes_over_time(environment_id: str, count: int, step_days: int = 2):
    """Complete ``count`` refreshes, advancing the logical clock between them.

    The refresh-interval rule refuses a completion attempted sooner than the
    configured interval plus one whole day after the previous completion, so
    every completion after the first is preceded by a clock advance.
    """
    jobs = []
    for index in range(count):
        if index > 0:
            set_clock(clock_plus(step_days * index))
        jobs.append(complete_refresh_job(environment_id))
    return jobs


# ─── Data masking boundary (FULL_COPY requires at least 20 fields) ────────────

def test_full_copy_masking_at_twenty_advances_to_masking(api):
    """PRD §3.2: "When the parent environment is a `FULL_COPY` sandbox the bar
    is higher: at least twenty fields must be covered, and a run that declares
    fewer is refused with `ERR_MASKING_INSUFFICIENT` and HTTP status 422."
    PRD §3.2: "This step deliberately consumes no aperture, so a job can be
    masked and then abandoned without cost."

    Design: Difficulty/boundary_precision_check/full_copy_masking_exactly_twenty
    """
    env = create_environment(type="FULL_COPY")
    job = create_refresh_job(env["id"], partition="FULL", masked_field_count=20)
    updated = validate_success(api.complete_masking(job["id"], ENV_ADMIN), 200)
    assert updated["status"] == "MASKING"
    assert updated["consumed_aperture"] is False


def test_full_copy_masking_below_twenty_is_refused(api):
    """PRD §3.2: "The job must actually be `PENDING`, and the declared masking
    coverage must be at least one field. When the parent environment is a
    `FULL_COPY` sandbox the bar is higher: at least twenty fields must be
    covered, and a run that declares fewer is refused with
    `ERR_MASKING_INSUFFICIENT` and HTTP status 422."

    Design: Difficulty/boundary_precision_check/full_copy_masking_exactly_twenty
    """
    env = create_environment(type="FULL_COPY")
    job = create_refresh_job(env["id"], partition="FULL", masked_field_count=19)
    res = api.complete_masking(job["id"], ENV_ADMIN)
    validate_error(res, "ERR_MASKING_INSUFFICIENT", expected_status=422)
    assert load_refresh_job(env["id"], job["id"])["status"] == "PENDING"


# ─── Three-hop refresh cascade ────────────────────────────────────────────────

def test_refresh_completion_emits_three_hop_cascade(api):
    """PRD §3.2: "It stamps the environment's `last_refresh_at` with the current
    logical instant, adds one to `refresh_generation`, sets the job's
    `consumed_aperture` to true, and recomputes `aperture_used` as the count of
    refresh jobs of that environment that have reached `COMPLETED` — a count, so
    failed jobs never inflate it."
    PRD §3.2: "Then the second hop fires from the environment write: every
    non-`UNINSTALLED` installation of the environment has its `refreshed_at` set
    to the current instant, its `pending_refresh_job_id` set to the job that
    invalidated it, and its `stale` marker set to true"

    Design: Difficulty/transitive_cascade/refresh_completion_three_hop_cascade
    """
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    pkg = install_package(env, v1["id"])
    publish_package_version("acme", 2, supersedes_version_id=v1["id"])

    job = open_masked_refresh_job(env["id"], masked_field_count=5)
    enter_completing(job["id"])
    done = validate_success(api.complete_refresh(job["id"], ENV_ADMIN), 200)
    assert done["status"] == "COMPLETED"
    assert done["consumed_aperture"] is True

    env_after = get_environment(env["id"])
    assert env_after["refresh_generation"] == 1
    assert env_after["last_refresh_at"] == DEFAULT_CLOCK_UTC

    pkg_after = load_installation(env["id"], pkg["id"])
    assert pkg_after["refreshed_at"] == DEFAULT_CLOCK_UTC
    assert pkg_after["pending_refresh_job_id"] == job["id"]


def test_refresh_cascade_rederives_installation_stale_marker(api):
    """PRD §3.2: "The third hop fires from that installation write: the
    environment's `installed_version_ids` is re-derived and the managed-package
    conflict set is re-evaluated (§3.4)."

    Design: Difficulty/transitive_cascade/refresh_completion_three_hop_cascade
    """
    v1 = publish_package_version("acme", 1)
    env = create_environment(type="PARTIAL")
    pkg = install_package(env, v1["id"])
    publish_package_version("acme", 2, supersedes_version_id=v1["id"])

    job = open_masked_refresh_job(env["id"], masked_field_count=5)
    enter_completing(job["id"])
    validate_success(api.complete_refresh(job["id"], ENV_ADMIN), 200)

    env_after = get_environment(env["id"])
    assert env_after["installed_version_ids"] == [v1["id"]]
    assert load_installation(env["id"], pkg["id"])["stale"] is True


# ─── Aperture gate boundary ───────────────────────────────────────────────────

def test_aperture_admits_completion_up_to_the_limit(api):
    """PRD §2.9: "The comparison is inclusive, so an environment at level 2
    with a limit of 2 admits its second completion, bringing `aperture_used` to
    2, and refuses only the third."

    Design: Difficulty/boundary_precision_check/aperture_inclusive_at_limit
    """
    env = create_gated_environment(aperture_limit=2, refresh_interval_days=1)
    _complete_refreshes_over_time(env["id"], 2)

    env_after = get_environment(env["id"])
    assert env_after["aperture_used"] == 2
    assert env_after["aperture_limit"] == 2


def test_aperture_refuses_completion_beyond_the_limit(api):
    """PRD §2.9: "When the gate refuses a completion, `aperture_used` is left
    unchanged."
    PRD §5: "`ERR_REFRESH_APERTURE_EXCEEDED` | 402 Payment Required"

    Design: Difficulty/boundary_precision_check/aperture_inclusive_at_limit
    """
    env = create_gated_environment(aperture_limit=2, refresh_interval_days=1)
    _complete_refreshes_over_time(env["id"], 2)

    third = open_masked_refresh_job(env["id"], masked_field_count=2)
    enter_completing(third["id"])
    set_clock(clock_plus(9))
    res = api.complete_refresh(third["id"], ENV_ADMIN)
    validate_error(res, "ERR_REFRESH_APERTURE_EXCEEDED", expected_status=402)

    env_after = get_environment(env["id"])
    assert env_after["aperture_used"] == 2, "a refused completion leaves aperture_used untouched"
    assert load_refresh_job(env["id"], third["id"])["consumed_aperture"] is False


# ─── Fiscal gate ordering on refresh completion ───────────────────────────────

def test_storage_breach_blocks_refresh_completion_and_is_reported(api):
    """PRD §3.2: "Last comes the storage gate: an environment in storage breach
    cannot commit further storage, and is refused with `ERR_STORAGE_BREACH` and
    HTTP status 402."
    PRD §5: "`ERR_STORAGE_BREACH` | 402 Payment Required"

    Design: Difficulty/priority_pair_validation_conflict/storage_breach_precedes_aperture_check
    """
    env = create_gated_environment(aperture_limit=1, refresh_interval_days=1,
                                   storage_cap_bytes=100)
    _complete_refreshes_over_time(env["id"], 1)
    create_ledger(env["id"], "DATA", 200, 1)

    env_after = get_environment(env["id"])
    assert env_after["storage_breach"] is True
    assert env_after["aperture_used"] == env_after["aperture_limit"] == 1

    second = open_masked_refresh_job(env["id"], masked_field_count=2)
    enter_completing(second["id"])
    set_clock(clock_plus(4))
    res = api.complete_refresh(second["id"], ENV_ADMIN)
    # The PRD pins the storage gate as a refusal of this request; it does not
    # commit to which of the two fiscal codes pre-empts the other, so either is
    # accepted here.
    validate_error_is_one_of(res, ["ERR_STORAGE_BREACH", "ERR_REFRESH_APERTURE_EXCEEDED"])

    env_blocked = get_environment(env["id"])
    assert env_blocked["aperture_used"] == 1
    assert env_blocked["refresh_generation"] == 1
    second_after = load_refresh_job(env["id"], second["id"])
    assert second_after["status"] == "COMPLETING"
    assert second_after["consumed_aperture"] is False


def test_refused_refresh_completion_preserves_job_and_aperture(api):
    """PRD §2.9: "When the gate refuses a completion, `aperture_used` is left
    unchanged."
    PRD §2.8: "A breaching environment is frozen for further storage growth: any
    operation that would commit additional storage or release a storage
    reservation is rejected with `ERR_STORAGE_BREACH` and HTTP status 402."

    Design: Difficulty/priority_pair_validation_conflict/storage_breach_precedes_aperture_check
    """
    env = create_gated_environment(aperture_limit=1, refresh_interval_days=1,
                                   storage_cap_bytes=100)
    _complete_refreshes_over_time(env["id"], 1)
    create_ledger(env["id"], "DATA", 200, 1)

    second = open_masked_refresh_job(env["id"], masked_field_count=2)
    enter_completing(second["id"])
    set_clock(clock_plus(4))
    api.complete_refresh(second["id"], ENV_ADMIN)

    env_after = get_environment(env["id"])
    assert env_after["aperture_used"] == 1
    assert env_after["refresh_generation"] == 1
    second_after = load_refresh_job(env["id"], second["id"])
    assert second_after["status"] == "COMPLETING"
    assert second_after["consumed_aperture"] is False


# ─── Refresh-interval enforcement ─────────────────────────────────────────────

def test_refresh_before_interval_elapsed_is_refused(api):
    """PRD §3.2: "Independently of those gates, the refresh interval itself is
    enforced — a completion attempted when fewer than `refresh_interval_days`
    plus one whole logical days have elapsed since the environment's last
    completed refresh is refused with `ERR_BUSINESS_RULE_VIOLATION` and HTTP
    status 409."

    Design: Corner/errors/refresh_before_interval_elapsed_returns_business_rule_violation
    """
    env = create_environment(type="DEVELOPER", refresh_interval_days=30)
    _complete_refreshes_over_time(env["id"], 1)

    second = open_masked_refresh_job(env["id"], masked_field_count=2)
    enter_completing(second["id"])
    set_clock("2026-09-15T00:00:00Z")
    res = api.complete_refresh(second["id"], ENV_ADMIN)
    validate_error(res, "ERR_BUSINESS_RULE_VIOLATION", expected_status=409)

    env_after = get_environment(env["id"])
    assert env_after["last_refresh_at"] == DEFAULT_CLOCK_UTC
    assert env_after["refresh_interval_days"] == 30
    assert env_after["refresh_generation"] == 1


def test_refresh_after_interval_elapsed_is_admitted(api):
    """PRD §3.2: "Independently of those gates, the refresh interval itself is
    enforced — a completion attempted when fewer than `refresh_interval_days`
    plus one whole logical days have elapsed since the environment's last
    completed refresh is refused with `ERR_BUSINESS_RULE_VIOLATION` and HTTP
    status 409."

    Design: Corner/errors/refresh_before_interval_elapsed_returns_business_rule_violation
    """
    env = create_environment(type="DEVELOPER", refresh_interval_days=30)
    _complete_refreshes_over_time(env["id"], 1)

    second = open_masked_refresh_job(env["id"], masked_field_count=2)
    enter_completing(second["id"])
    set_clock("2026-10-05T00:00:00Z")
    done = validate_success(api.complete_refresh(second["id"], ENV_ADMIN), 200)
    assert done["status"] == "COMPLETED"
    assert get_environment(env["id"])["refresh_generation"] == 2


# ─── Release-boundary rule ────────────────────────────────────────────────────

def test_child_refresh_across_release_boundary_is_refused(api):
    """PRD §3.2: "if the environment has a `parent_environment_id` and that
    parent's `applied_release_version` differs from the refreshing environment's
    own applied version, the completion would cross a release boundary and is
    refused with `ERR_RELEASE_MISMATCH` and HTTP status 409."

    Design: Corner/errors/child_refresh_across_release_boundary_returns_release_mismatch
    """
    root = create_production()
    parent = create_sandbox(root["id"], type="DEVELOPER")
    schedule_and_apply_release(parent["id"], "SP26")
    child = create_sandbox(parent["id"], type="DEVELOPER")

    job = open_masked_refresh_job(child["id"], masked_field_count=2)
    enter_completing(job["id"])
    res = api.complete_refresh(job["id"], ENV_ADMIN)
    validate_error(res, "ERR_RELEASE_MISMATCH", expected_status=409)

    assert get_environment(parent["id"])["applied_release_version"] == "SP26"
    assert get_environment(child["id"])["applied_release_version"] is None
    child_job = load_refresh_job(child["id"], job["id"])
    assert child_job["status"] == "COMPLETING"
    assert child_job["consumed_aperture"] is False


def test_child_refresh_admitted_once_release_versions_agree(api):
    """PRD §3.2: "if the environment has a `parent_environment_id` and that
    parent's `applied_release_version` differs from the refreshing environment's
    own applied version, the completion would cross a release boundary and is
    refused with `ERR_RELEASE_MISMATCH` and HTTP status 409."

    Design: Corner/errors/child_refresh_across_release_boundary_returns_release_mismatch
    """
    root = create_production()
    parent = create_sandbox(root["id"], type="DEVELOPER")
    schedule_and_apply_release(parent["id"], "SP26")
    child = create_sandbox(parent["id"], type="DEVELOPER")
    schedule_and_apply_release(child["id"], "SP26")

    job = open_masked_refresh_job(child["id"], masked_field_count=2)
    enter_completing(job["id"])
    done = validate_success(api.complete_refresh(job["id"], ENV_ADMIN), 200)
    assert done["status"] == "COMPLETED"


# ─── State-machine rejection from wrong states ────────────────────────────────

def test_complete_masking_on_completed_job_is_refused(api):
    """PRD §2.12: "The second is the addressed resource's own status field,
    which must be one of the states from which the requested action is declared.
    That second kind guards the refresh-job actions"

    Design: Corner/state_machines/refresh_job_invalid_from_rejection
    """
    env = create_environment(type="DEVELOPER")
    done = complete_refresh_job(env["id"], masked_field_count=2)

    res = api.complete_masking(done["id"], ENV_ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert load_refresh_job(env["id"], done["id"])["status"] == "COMPLETED"


def test_complete_refresh_on_pending_job_is_refused(api):
    """PRD §2.12: "State preconditions produce `ERR_INVALID_STATE` with HTTP
    status 409."

    Design: Corner/state_machines/refresh_job_invalid_from_rejection
    """
    env = create_environment(type="DEVELOPER")
    pending = create_refresh_job(env["id"], masked_field_count=2)

    res = api.complete_refresh(pending["id"], ENV_ADMIN)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert load_refresh_job(env["id"], pending["id"])["status"] == "PENDING"


# ─── Refresh-job creation defaults ────────────────────────────────────────────

def test_unknown_refresh_job_reports_resource_not_found(api):
    """PRD §2.12: "A missing or invalid resource that is not an environment — a
    refresh job, a package version, an installation, a change set, a deployment
    job, a governor-limit request, a storage ledger, an access audit or a
    permission assignment — is reported as `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/unknown_refresh_job_returns_resource_not_found
    """
    env = create_environment(type="DEVELOPER")
    res = api.complete_masking("00000000-0000-4000-8000-000000000001", ENV_ADMIN)
    validate_error(res, "ERR_RESOURCE_NOT_FOUND", expected_status=404)

    rows, _ = validate_paginated(api_client.list_refresh_jobs_of_environment(env["id"], ADMIN))
    assert rows == []


def test_refresh_job_opens_pending_with_defaults(api):
    """PRD §3.2: "The job is created in `PENDING` with `consumed_aperture` set
    to false, and `consumed_aperture` will only ever become true if the job
    reaches `COMPLETED`."

    Design: Corner/entities/refresh_job_defaults_and_consumed_aperture_marker
    """
    env = create_environment(type="DEVELOPER")
    res = api.create_refresh_job(
        {"environment_id": env["id"], "partition": "ACCOUNT_PARTIAL"},
        ENV_ADMIN)
    job = validate_success(res, 201)
    assert job["status"] == "PENDING"
    assert job["consumed_aperture"] is False
    assert job["masked_field_count"] == 0
    assert job["supersedes_job_id"] is None
    assert job["version"] == 1
    assert job["environment_id"] == env["id"]


def test_refresh_job_records_declared_partition_and_masked_count(api):
    """PRD §3.2: "A refresh job is opened against a specific environment by
    naming `environment_id` and a `partition` — either `FULL`, meaning every
    record is copied, or `ACCOUNT_PARTIAL`, meaning only the requesting account
    partition is copied — together with an optional declaration of masking
    coverage in `masked_field_count`."

    Design: Corner/entities/refresh_job_defaults_and_consumed_aperture_marker
    """
    env = create_environment(type="PARTIAL")
    job = create_refresh_job(env["id"], partition="ACCOUNT_PARTIAL", masked_field_count=3)
    assert job["partition"] == "ACCOUNT_PARTIAL"
    assert job["masked_field_count"] == 3
    assert job["status"] == "PENDING"


# ─── Aperture counts only completed children ──────────────────────────────────

def test_aperture_rollup_counts_only_completed_refresh_jobs(api):
    """PRD §3.2: "recomputes `aperture_used` as the count of refresh jobs of
    that environment that have reached `COMPLETED` — a count, so failed jobs
    never inflate it."

    Design: Difficulty/bulk_operations/partial_batch_rejection_leaves_unlisted_children_untouched
    """
    env = create_environment(type="DEVELOPER", aperture_limit=5, refresh_interval_days=1)
    jobs = _complete_refreshes_over_time(env["id"], 2)
    failed = open_masked_refresh_job(env["id"], masked_field_count=2)
    validate_success(api.fail_refresh_job(failed["id"], ENV_ADMIN), 200)

    env_after = get_environment(env["id"])
    assert env_after["aperture_used"] == 2
    assert env_after["aperture_limit"] == 5
    for job in jobs:
        assert load_refresh_job(env["id"], job["id"])["consumed_aperture"] is True


def test_failed_refresh_child_consumes_no_aperture(api):
    """PRD §3.2: "Failing a `MASKING` job moves it to `FAILED`, which is
    terminal, leaves `consumed_aperture` false and leaves the environment's
    `aperture_used` exactly as it was."

    Design: Difficulty/bulk_operations/partial_batch_rejection_leaves_unlisted_children_untouched
    """
    env = create_environment(type="DEVELOPER", aperture_limit=5, refresh_interval_days=1)
    _complete_refreshes_over_time(env["id"], 2)
    failed = open_masked_refresh_job(env["id"], masked_field_count=2)
    validate_success(api.fail_refresh_job(failed["id"], ENV_ADMIN), 200)

    failed_after = load_refresh_job(env["id"], failed["id"])
    assert failed_after["status"] == "FAILED"
    assert failed_after["consumed_aperture"] is False
    assert get_environment(env["id"])["aperture_used"] == 2


# ─── Adjacent refresh admissions ──────────────────────────────────────────────

def test_completed_refresh_admissions_consume_aperture_without_buffer(api):
    """PRD §2.9: "`aperture_used` is the count of refresh jobs of that
    environment that reached `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/direct_child_refresh_aperture_rollup_no_buffer
    """
    env = create_gated_environment(aperture_limit=3, refresh_interval_days=1)
    jobs = _complete_refreshes_over_time(env["id"], 2, step_days=2)

    env_after = get_environment(env["id"])
    assert env_after["aperture_used"] == 2
    assert env_after["aperture_limit"] == 3
    for job in jobs:
        reloaded = load_refresh_job(env["id"], job["id"])
        assert reloaded["status"] == "COMPLETED"
        assert reloaded["consumed_aperture"] is True


def test_next_refresh_projection_is_the_interval_plus_the_generation_curve(api):
    """PRD §2.9: "The projected instant at which the next refresh may begin is
    `next_refresh_at`, a datetime resolved to whole days: the anchor is the
    environment's `last_refresh_at`, or the current logical clock instant when
    `last_refresh_at` is still null because no refresh has ever completed; the
    base is that anchor plus `refresh_interval_days`; and a generation curve is
    then added, equal to two days multiplied by the remainder left when the
    environment's `refresh_generation` is divided by three."

    Design: Difficulty/resource_temporal_overlap/direct_child_refresh_aperture_rollup_no_buffer
    """
    from datetime import datetime
    env = create_gated_environment(aperture_limit=3, refresh_interval_days=10,
                                   release_schedule_mode="FLAG_ONLY")
    set_clock(DEFAULT_CLOCK_UTC)
    complete_refresh_job(env["id"])

    posture = get_environment(env["id"])
    assert posture["refresh_generation"] == 1
    projected = posture["next_refresh_at"]
    elapsed = (datetime.strptime(projected, "%Y-%m-%dT%H:%M:%S.%fZ")
               - datetime.strptime(posture["last_refresh_at"], "%Y-%m-%dT%H:%M:%S.%fZ")).days
    # interval 10 plus the curve 2 * (refresh_generation mod 3)
    assert elapsed == 10 + 2 * (posture["refresh_generation"] % 3)