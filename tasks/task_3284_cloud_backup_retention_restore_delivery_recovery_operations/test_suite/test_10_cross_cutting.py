"""Cross-cutting concerns: optimistic concurrency, filtering, thresholds and
cross-entity restore dependencies."""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    validate_paginated,
    ApiErrorId,
    GB_1,
    GB_10,
    BACKUP,
    SYS,
    activate_agent,
    begin_restore,
    block_agent,
    complete_initial,
    create_account,
    create_agent,
    create_group,
    create_policy,
    create_restore,
    create_set,
    owner_headers,
    prepare_restore,
    record_version,
    set_clock,
    setup_active_set_for_restore,
    setup_business_active_set,
    validate_restore,
)


def test_restore_creation_with_a_stale_account_version_is_refused():
    """PRD §2.6: "Creating a restore request requires the payload to carry
    `expected_account_version` matching the target `Account`'s current
    `version`. Such a `POST /restore-requests` request is rejected with
    `ERR_STALE_VERSION` at HTTP 412 if the account's version has advanced since
    the client last read it"

    Design: Corner/cross_cutting_complexity_layers/restore_create_with_stale_account_version_is_rejected
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/stale.bin",
                                event_utc="2026-09-02T00:00:00Z",
                                require_mfa_for_restore=False)
    account_id = scenario["account"]["id"]
    set_clock("2026-09-02T00:00:00Z")

    observed = get_success_data(api.get_account(account_id, SYS))["version"]
    payload = {
        "account_id": account_id,
        "subject_agent_id": scenario["agent"]["id"],
        "restore_point_in_utc": "2026-09-02T00:00:00Z",
        "restore_type": "FILE_DOWNLOAD",
        "requested_file_count": 1,
        "requested_size_gb": 10.0,
        "restore_transaction_count": 0,
        "expected_account_version": observed,
    }
    first = get_success_data(api.create_restore_request(payload, owner_headers(account_id)))
    assert first["state"] == "REQUESTED"

    second = api.create_restore_request(payload, owner_headers(account_id))
    error = validate_error(second, ApiErrorId.ERR_STALE_VERSION)
    assert error["error_id"] == "ERR_STALE_VERSION"

    rows = get_success_data(api.list_restore_requests(SYS, {"account_id": account_id}))
    assert len(rows) == 1


def test_file_version_list_filters_and_paginates_together():
    """PRD §2.3: "Some collection endpoints accept a filter that narrows the
    result set before pagination is applied"
    PRD §2.3: "`limit` caps the number of records returned, defaulting to 10
    when it is not supplied"
    PRD §3.3: "A set's versions can be narrowed by `file_path`, by `operation`,
    by `is_expired`, and by `is_deleted`, and by the `include_expired` flag"

    Design: Corner/cross_cutting_complexity_layers/file_version_list_filters_and_paginates_together
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_1, file_path="/home/u/p1.bin",
                                event_utc="2026-09-02T00:00:00Z")
    set_id = scenario["set"]["id"]

    record_version(set_id, "/home/u/p2.bin", 1, "CREATE", GB_1, "sha256-p2-v1",
                   "2026-09-02T00:00:00Z")
    record_version(set_id, "/home/u/p3.bin", 1, "CREATE", GB_1, "sha256-p3-v1",
                   "2026-09-02T00:00:00Z")
    record_version(set_id, "/home/u/p1.bin", 2, "MODIFY", 2 * GB_1, "sha256-p1-v2",
                   "2026-09-02T01:00:00Z")
    record_version(set_id, "/home/u/p2.bin", 2, "MODIFY", 2 * GB_1, "sha256-p2-v2",
                   "2026-09-02T02:00:00Z")

    page, meta = validate_paginated(api.list_file_versions(
        set_id, BACKUP, {"operation": "CREATE", "limit": 2, "offset": 0}))
    assert len(page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    page2, meta2 = validate_paginated(api.list_file_versions(
        set_id, BACKUP, {"operation": "CREATE", "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    modifies, _ = validate_paginated(api.list_file_versions(
        set_id, BACKUP, {"operation": "MODIFY"}))
    assert len(modifies) == 2

    everything, _ = validate_paginated(api.list_file_versions(set_id, BACKUP))
    assert len(everything) == 5


def test_billable_egress_consumes_the_one_gigabyte_allowance_inclusively():
    """PRD §3.6: "In the ordinary metered case, the free allowance is the raw
    requested volume limited to 1.0 gigabyte, the billable partial volume is the
    raw volume minus that allowance"
    PRD §3.6: "Billable egress is reported at two decimal places, rounded half
    up."

    Design: Corner/cross_cutting_complexity_layers/billable_egress_free_allowance_boundary
    """
    scenario = setup_active_set_for_restore(size_bytes=2 * GB_1, file_path="/home/u/allowance.bin",
                                event_utc="2026-09-02T00:00:00Z",
                                require_mfa_for_restore=False, storage_tier="PRO")
    account_id = scenario["account"]["id"]
    set_clock("2026-09-03T00:00:00Z")

    at_allowance = create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                                  requested_size_gb=1.0)
    validate_restore(at_allowance["id"], account_id)
    begun_exact = begin_restore(at_allowance["id"], account_id)
    assert begun_exact["egress_gb"] == pytest.approx(0.0, abs=0.01)
    assert begun_exact["egress_fee_cents"] == 0

    over_allowance = create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                                    requested_size_gb=1.01)
    validate_restore(over_allowance["id"], account_id)
    begun_over = begin_restore(over_allowance["id"], account_id)
    assert begun_over["egress_gb"] == pytest.approx(0.01, abs=0.001)
    assert begun_over["egress_fee_cents"] == 1


def test_the_groups_derived_counters_track_its_agents_and_their_changes():
    """PRD §3.2: "When activation succeeds the agent moves from `PENDING_AUTH`
    to `ACTIVE`, the owning group's `agent_count` increases by one"
    PRD §3.2: "The tier selects the collection cadence: a `HIGH_FREQUENCY` group
    expects 96 incrementals per day, while a `STANDARD` group expects 24."

    Design: Corner/cross_cutting_complexity_layers/backup_group_derived_fields_reconcile_after_each_change
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_1, file_path="/home/u/rec.bin",
                                event_utc="2026-09-02T00:00:00Z")
    group_id = scenario["group"]["id"]
    set_id = scenario["set"]["id"]
    account_id = scenario["account"]["id"]

    second = activate_agent(create_agent(account_id, group_id, hostname="nw-laptop-02",
                                         os_type="WINDOWS")["id"])
    assert second["status"] == "ACTIVE"

    before = get_success_data(api.get_backup_group(group_id, SYS))
    assert before["agent_count"] == 2
    # PRD 3.2: a STANDARD group expects 24 incrementals per day; the field is
    # the per-day projection for a single agent, so two agents leave it at 24.
    assert before["expected_daily_transactions"] == 24

    record_version(set_id, "/home/u/rec.bin", 2, "MODIFY", 2 * GB_1, "sha256-rec-v2",
                   "2026-09-02T03:00:00Z")

    after = get_success_data(api.get_backup_group(group_id, SYS))
    assert after["agent_count"] == 2
    first_agent = get_success_data(api.get_agent(scenario["agent"]["id"], BACKUP))
    assert first_agent["last_change_sequence"] == 2
    assert second["last_change_sequence"] == 0


def test_a_file_change_is_immediately_visible_in_the_recomputed_aggregates():
    """PRD §3.1: "The `usage_gb` value is the live byte total divided by
    `GB_BYTES` and rounded half up to two decimal places, and `peak_usage_gb` is
    the larger of its own prior value and the freshly computed `usage_gb`."
    PRD §3.3: "Accepting an incremental recomputes the set's `storage_gb`,
    `version_chain_depth`, `recovery_points`, and `retention_floor_utc`; the
    account's `usage_gb` and `peak_usage_gb`"

    Design: Corner/consistency_model/file_version_create_response_already_reflects_recomputed_set_totals
    """
    scenario = setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/imm.bin",
                                event_utc="2026-09-02T00:00:00Z")
    set_id = scenario["set"]["id"]
    account_id = scenario["account"]["id"]

    created = record_version(set_id, "/home/u/imm.bin", 2, "MODIFY", 32212254720,
                             "sha256-imm-v2", "2026-09-02T04:00:00Z")
    assert created["version_number"] == 2

    fetched = get_success_data(api.get_backup_set(set_id, BACKUP))
    account = get_success_data(api.get_account(account_id, SYS))
    assert fetched["storage_gb"] == pytest.approx(30.0, abs=0.01)
    assert account["usage_gb"] == pytest.approx(30.0, abs=0.01)
    assert account["peak_usage_gb"] == pytest.approx(30.0, abs=0.01)


# ---------------------------------------------------------------------------
# The remaining depth instance: restore progression versus the set's state
# ---------------------------------------------------------------------------

def test_preparing_a_restore_whose_requested_file_has_expired_is_refused():
    """PRD §3.5: "Preparation moves the request from `IN_PROGRESS` to `READY`,
    and it is the last point at which the restore point's viability is checked:
    every file requested by the restore must still be non-expired at the restore
    point, or the request is rejected with `ERR_RESTORE_POINT_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/restore_begin_requires_agent_backup_set_active
    """
    scenario = setup_business_active_set(size_bytes=GB_10, file_path="/srv/data/ledger.db",
                                         event_utc="2026-09-02T00:00:00Z",
                                         retention_days_override=45)
    account_id = scenario["account"]["id"]
    set_clock("2026-09-01T00:00:00Z")

    restore = create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                             requested_size_gb=10.0)
    validate_restore(restore["id"], account_id)
    begin_restore(restore["id"], account_id)

    # Push the logical clock far past event_utc + 45 days so the version expires.
    set_clock("2026-12-01T00:00:00Z")
    refused = api.prepare_restore(restore["id"], owner_headers(account_id))
    error = validate_error(refused, ApiErrorId.ERR_RESTORE_POINT_EXPIRED)
    assert error["error_id"] == "ERR_RESTORE_POINT_EXPIRED"

    fetched = get_success_data(api.get_restore_request(restore["id"], owner_headers(account_id)))
    assert fetched["state"] == "IN_PROGRESS"


def test_a_blocked_agent_leaves_its_set_suspended_and_the_restore_unpreparable():
    """PRD §3.2: "Blocking moves an `ACTIVE` agent to `BLOCKED` and cascades to
    its sets, driving every one of them to `SUSPENDED`."
    PRD §3.5: "every file requested by the restore must still be non-expired at
    the restore point, or the request is rejected with
    `ERR_RESTORE_POINT_EXPIRED`."

    Design: Difficulty/cross_entity_state_dependency/restore_begin_requires_agent_backup_set_active
    """
    scenario = setup_business_active_set(size_bytes=GB_10, file_path="/srv/data/ledger.db",
                                         event_utc="2026-09-02T00:00:00Z",
                                         retention_days_override=45)
    account_id = scenario["account"]["id"]
    agent_id = scenario["agent"]["id"]
    set_id = scenario["set"]["id"]
    set_clock("2026-09-01T00:00:00Z")

    restore = create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                             requested_size_gb=10.0)
    validate_restore(restore["id"], account_id)
    begin_restore(restore["id"], account_id)

    blocked = block_agent(agent_id, SYS)
    assert blocked["status"] == "BLOCKED"
    suspended = get_success_data(api.get_backup_set(set_id, BACKUP))
    assert suspended["state"] == "SUSPENDED"

    set_clock("2026-12-01T00:00:00Z")
    refused = api.prepare_restore(restore["id"], owner_headers(account_id))
    validate_error(refused, ApiErrorId.ERR_RESTORE_POINT_EXPIRED)

    fetched = get_success_data(api.get_restore_request(restore["id"], owner_headers(account_id)))
    agent_after = get_success_data(api.get_agent(agent_id, SYS))
    assert fetched["state"] == "IN_PROGRESS"
    assert agent_after["status"] == "BLOCKED"