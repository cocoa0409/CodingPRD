"""Corner claims about state machines, transitions and computed history."""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    validate_success,
    ApiErrorId,
    GB_1,
    GB_10,
    GB_100,
    BACKUP,
    RETENTION,
    SYS,
    complete_initial,
    create_pod,
    create_retention_request,
    fail_shards,
    prepare_restore,
    record_version,
    restore_shards,
    set_clock,
    setup_personal_scenario,
    setup_active_set_for_restore,
)


def test_a_freshly_provisioned_set_starts_in_provisioning():
    """PRD §3.2: "A new set starts in `PROVISIONING` and receives an
    agent-scoped monotonic `created_seq`."
    PRD §3.3: "On a set that has never captured data, the first non-`DELETE`
    version does more than append a row: it starts the throttled initial full
    backup."

    Design: Corner/state_machines/backup_set_starts_in_provisioning_before_any_version
    """
    scenario = setup_personal_scenario(create_backup_set=False)
    agent_id = scenario["agent"]["id"]
    response = api.create_backup_set(
        {"agent_id": agent_id, "account_id": scenario["account"]["id"],
         "durability_class": "STANDARD"},
        BACKUP)
    created = validate_success(response, 201)

    assert created["state"] == "PROVISIONING"
    assert created["is_initial_flush"] is False
    agent = get_success_data(api.get_agent(agent_id, BACKUP))
    assert agent["in_throttle_window"] is False


def test_completing_the_initial_backup_from_provisioning_is_rejected():
    """PRD §3.3: "A `BackupOperator` ends the throttle by completing the
    initial backup, which promotes the set from `INITIAL_RUNNING` to `ACTIVE`"
    PRD §2.9: "At the fourth level, the target resource must be in a state that
    admits the requested operation, failing with one of `ERR_INVALID_STATE`"

    Design: Corner/state_machines/complete_initial_from_provisioning_returns_invalid_state
    """
    scenario = setup_personal_scenario()
    set_id = scenario["set"]["id"]
    response = api.complete_initial_backup(set_id, BACKUP)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    fetched = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert fetched["state"] == "PROVISIONING"
    assert fetched["is_initial_flush"] is False


def test_applying_a_retention_change_directly_from_submitted_is_rejected():
    """PRD §3.4: "From `SUBMITTED`, beginning the cooling-off window — moving to
    `COOLING_OFF` — checks two bounds against the group's `ACTIVE` retention
    policy"
    PRD §3.4: "A retention change is a deliberately slow, auditable act."
    PRD §2.9: "the target resource must be in a state that admits the requested
    operation, failing with one of `ERR_INVALID_STATE`"

    Design: Corner/state_machines/retention_change_apply_from_submitted_returns_invalid_state
    """
    scenario = setup_personal_scenario()
    group_id = scenario["group"]["id"]
    request = create_retention_request(scenario, requested_retention_days=120,
                                       reason_code="UPGRADE")

    response = api.apply_retention_change(request["id"], RETENTION)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)

    fetched = get_success_data(api.get_retention_change_request(request["id"], RETENTION))
    assert fetched["state"] == "SUBMITTED"
    group = get_success_data(api.get_backup_group(group_id, RETENTION))
    assert group["group_retention_days"] == 45


def test_a_completed_restore_cannot_be_reversed_or_cancelled():
    """PRD §3.5: "A `SystemOperator` may reverse a restore that is in `READY`,
    moving it to the terminal `REVERSED` state"
    PRD §3.5: "A restore that has not yet begun producing output can be
    cancelled directly from either `REQUESTED` or `VALIDATING` into the terminal
    `CANCELLED` state, with no egress accruing and no further side effects."

    Design: Corner/state_machines/restore_request_completed_state_has_no_outgoing_transition
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/small.bin",
                                event_utc="2026-09-02T00:00:00Z",
                                require_mfa_for_restore=False)
    account_id = scenario["account"]["id"]
    set_clock("2026-09-04T00:00:00Z")

    from test_helpers import (
        create_restore as _create, validate_restore as _validate,
        begin_restore as _begin, owner_headers,
    )
    restore = _create(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                      requested_size_gb=10.0)
    restore = _validate(restore["id"], account_id)
    restore = _begin(restore["id"], account_id)
    prepare_restore(restore["id"], account_id)
    get_success_data(api.complete_restore(restore["id"], owner_headers(account_id)))

    reverse = api.reverse_restore(restore["id"], SYS)
    validate_error(reverse, ApiErrorId.ERR_INVALID_STATE)
    cancel = api.cancel_restore(restore["id"], owner_headers(account_id))
    validate_error(cancel, ApiErrorId.ERR_INVALID_STATE)

    fetched = get_success_data(api.get_restore_request(restore["id"], owner_headers(account_id)))
    account = get_success_data(api.get_account(account_id, SYS))
    assert fetched["state"] == "COMPLETED"
    assert account["restore_download_gb"] == pytest.approx(9.0, abs=0.01)


def test_deleting_a_file_removes_it_from_usage_but_not_from_the_version_chain():
    """PRD §3.1: "To that live total the platform adds nothing: content that
    has been superseded by a `DELETE` but is still recoverable is tracked in a
    separate staged pool and does not contribute to `usage_gb`."
    PRD §3.1: "`peak_usage_gb` is the larger of its own prior value and the
    freshly computed `usage_gb`."

    Design: Corner/calculations/account_usage_gb_excludes_staged_delete_versions
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_100, file_path="/home/u/doomed.bin",
                                event_utc="2026-09-02T00:00:00Z")
    set_id = scenario["set"]["id"]
    account_id = scenario["account"]["id"]

    deleted = record_version(set_id, "/home/u/doomed.bin", 2, "DELETE", 0,
                             "sha256-doom-del", "2026-09-03T00:00:00Z")
    account = get_success_data(api.get_account(account_id, SYS))

    assert deleted["is_deleted"] is True
    assert deleted["is_expired"] is False
    assert account["usage_gb"] == pytest.approx(0.0, abs=0.01)
    assert account["peak_usage_gb"] == pytest.approx(100.0, abs=0.01)

    rows = get_success_data(api.list_file_versions(
        set_id, BACKUP, {"include_expired": True}))
    assert len(rows) == 2
    fetched = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert fetched["version_chain_depth"] == 0


def test_the_version_chain_collapses_on_a_delete_and_restarts_at_one():
    """PRD §3.3: "A `DELETE` closes the chain and resets the depth to zero. The
    reported depth is the value after the final version, so a delete collapses
    the chain to zero and a later modify restarts it at one — it does not resume
    the pre-delete count."

    Design: Corner/calculations/version_chain_depth_collapses_after_a_delete_event
    """
    scenario = setup_personal_scenario()
    set_id = scenario["set"]["id"]
    record_version(set_id, "/home/u/x.bin", 1, "CREATE", GB_1, "sha256-x-v1",
                   "2026-09-02T00:00:00Z")
    record_version(set_id, "/home/u/x.bin", 2, "MODIFY", 2 * GB_1, "sha256-x-v2",
                   "2026-09-03T00:00:00Z")
    record_version(set_id, "/home/u/x.bin", 3, "MODIFY", 3 * GB_1, "sha256-x-v3",
                   "2026-09-04T00:00:00Z")
    complete_initial(set_id)

    record_version(set_id, "/home/u/x.bin", 4, "DELETE", 0, "sha256-x-del",
                   "2026-09-05T00:00:00Z")
    after_delete = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert after_delete["version_chain_depth"] == 0

    record_version(set_id, "/home/u/x.bin", 5, "CREATE", GB_1, "sha256-x-v5",
                   "2026-09-06T00:00:00Z")
    after_recreate = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert after_recreate["version_chain_depth"] == 1


def test_pod_status_branches_at_the_parity_boundary():
    """PRD §2.7: "Pod status follows a first-match-wins cascade over the
    instantaneous shard count, evaluated in this order: zero failed shards means
    `HEALTHY`; one or more failed shards up to and including `parity_shards`
    means `DEGRADED`; and a failed-shard count strictly greater than
    `parity_shards` means `FAILED`."

    Design: Corner/calculations/pod_shard_geometry_branches_at_the_parity_boundary
    """
    pod = create_pod(region="US_WEST", total_shards=16, data_shards=12, failed_shards=0)
    assert pod["parity_shards"] == 4

    at_parity = fail_shards(pod["id"], 4)
    assert at_parity["failed_shards"] == 4
    assert at_parity["status"] == "DEGRADED"
    assert at_parity["is_reconstructable"] is True

    over = fail_shards(pod["id"], 1)
    assert over["failed_shards"] == 5
    assert over["status"] == "FAILED"
    assert over["is_reconstructable"] is False


def test_a_pod_beyond_parity_cannot_begin_repair():
    """PRD §2.7: "Repair cannot begin while the pod is beyond recovery: an
    attempt to move a pod into `REPAIRING` while `failed_shards` still exceeds
    `parity_shards` is rejected with `ERR_POD_UNRECOVERABLE`. Shards must first
    be restored until the count is back within tolerance."

    Design: Corner/calculations/pod_shard_geometry_branches_at_the_parity_boundary
    """
    pod = create_pod(region="US_WEST", total_shards=16, data_shards=12, failed_shards=0)
    fail_shards(pod["id"], 5)

    refused = api.begin_pod_repair(pod["id"], SYS)
    validate_error(refused, ApiErrorId.ERR_POD_UNRECOVERABLE)
    still_failed = get_success_data(api.get_storage_pod(pod["id"], SYS))
    assert still_failed["status"] == "FAILED"

    back_in_tolerance = restore_shards(pod["id"], 1)
    assert back_in_tolerance["failed_shards"] == 4
    assert back_in_tolerance["is_reconstructable"] is True
    repaired = get_success_data(api.begin_pod_repair(pod["id"], SYS))
    assert repaired["status"] == "REPAIRING"