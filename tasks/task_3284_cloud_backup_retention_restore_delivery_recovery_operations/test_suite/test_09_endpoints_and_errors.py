"""Corner claims about agent lifecycle, cascades and the billing ledger."""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_success,
    GB_1,
    GB_10,
    GB_100,
    BACKUP,
    SYS,
    activate_agent,
    complete_initial,
    create_account,
    create_agent,
    create_group,
    create_policy,
    create_set,
    open_billing_period,
    record_version,
    set_clock,
    setup_active_set_for_restore,
    setup_personal_scenario,
)


def test_agent_create_read_and_retire_from_pending_auth_is_consistent():
    """PRD §3.2: "A newly installed agent sits in `PENDING_AUTH` until it is
    activated."
    PRD §3.2: "Retiring an agent that never activated — one still in
    `PENDING_AUTH` — simply moves it to its terminal `RETIRED` state and leaves
    `agent_count` untouched."

    Design: Corner/endpoints/agent_lifecycle_create_get_then_retire
    """
    scenario = setup_personal_scenario(activate=False, create_backup_set=False)
    group_id = scenario["group"]["id"]

    created = create_agent(scenario["account"]["id"], group_id, hostname="nw-crud-01",
                           os_type="WINDOWS")
    assert created["status"] == "PENDING_AUTH"
    assert created["os_type"] == "WINDOWS"

    fetched = get_success_data(api.get_agent(created["id"], BACKUP))
    assert fetched["os_type"] == "WINDOWS"
    assert fetched["hostname"] == "nw-crud-01"

    retired = get_success_data(api.retire_agent(created["id"], BACKUP))
    assert retired["status"] == "RETIRED"

    group = get_success_data(api.get_backup_group(group_id, BACKUP))
    assert group["agent_count"] == 0


def test_account_read_exposes_group_count_and_the_rolled_up_retention_window():
    """PRD §3.1: "A computed `group_count` reports how many backup groups the
    account currently holds."
    PRD §3.4: "The account's own `retention_days` then rolls up from its
    groups: it is the maximum `group_retention_days` over all of the account's
    groups, and zero when the account has no group."

    Design: Corner/endpoints/account_get_exposes_computed_group_count_and_effective_retention
    """
    account = create_account(name="Northwind Personal")
    first = create_group(account["id"], name="Personal Laptops", retention_days_override=45)
    create_policy(first["id"])
    second = create_group(account["id"], name="Personal Phones", retention_days_override=60)
    create_policy(second["id"])

    fetched = get_success_data(api.get_account(account["id"], SYS))
    assert fetched["group_count"] == 2
    assert fetched["retention_days"] == 60

    first_after = get_success_data(api.get_backup_group(first["id"], SYS))
    second_after = get_success_data(api.get_backup_group(second["id"], SYS))
    assert first_after["group_retention_days"] == 45
    assert second_after["group_retention_days"] == 60


def test_blocking_an_agent_suspends_every_one_of_its_sets():
    """PRD §3.2: "Blocking moves an `ACTIVE` agent to `BLOCKED` and cascades to
    its sets, driving every one of them to `SUSPENDED`."
    PRD §3.1: "Only sets whose `state` is `INITIAL_RUNNING`, `ACTIVE`, or
    `SUSPENDED` contribute to the account's volume; a set in `DELETED`
    contributes nothing because its file versions have been purged."

    Design: Corner/endpoints/agent_block_cascades_every_set_to_suspended
    """
    set_clock("2026-09-02T00:00:00Z")
    account = create_account(name="Northwind Personal")
    group = create_group(account["id"], name="Personal Laptops", retention_days_override=45)
    create_policy(group["id"])
    agent = activate_agent(create_agent(account["id"], group["id"], hostname="nw-laptop-01")["id"])

    first = create_set(agent["id"], account["id"])
    record_version(first["id"], "/home/u/one.bin", 1, "CREATE", GB_1, "sha256-one-v1",
                   "2026-09-02T00:00:00Z")
    complete_initial(first["id"])

    second = create_set(agent["id"], account["id"])
    record_version(second["id"], "/home/u/two.bin", 1, "CREATE", 2 * GB_1, "sha256-two-v1",
                   "2026-09-02T00:00:00Z")
    complete_initial(second["id"])

    blocked = get_success_data(api.block_agent(agent["id"], SYS))
    assert blocked["status"] == "BLOCKED"

    first_after = get_success_data(api.get_backup_set(first["id"], BACKUP))
    second_after = get_success_data(api.get_backup_set(second["id"], BACKUP))
    assert first_after["state"] == "SUSPENDED"
    assert second_after["state"] == "SUSPENDED"

    account_after = get_success_data(api.get_account(account["id"], SYS))
    assert account_after["usage_gb"] == pytest.approx(3.0, abs=0.01)


def test_a_billing_period_read_with_an_unknown_id_reports_the_period_as_missing():
    """PRD §2.9: "the not-found family is `ERR_ACCOUNT_NOT_FOUND`,
    `ERR_GROUP_NOT_FOUND`, `ERR_AGENT_NOT_FOUND`, `ERR_BACKUP_SET_NOT_FOUND`,
    `ERR_RESTORE_REQUEST_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`,
    `ERR_RETENTION_CHANGE_NOT_FOUND`, `ERR_DELETION_REQUEST_NOT_FOUND`,
    `ERR_STORAGE_POD_NOT_FOUND`, `ERR_FILE_VERSION_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, and `ERR_BILLING_PERIOD_NOT_FOUND`, all at HTTP 404."

    Design: Corner/endpoints/billing_period_get_with_unknown_id_returns_billing_period_not_found
    """
    from test_helpers import validate_error, ApiErrorId
    account = create_account(name="Northwind Personal")
    response = api.get_billing_period("00000000-0000-4000-8000-0000000000aa", SYS)
    error = validate_error(response, ApiErrorId.ERR_BILLING_PERIOD_NOT_FOUND)
    assert error["error_id"] == "ERR_BILLING_PERIOD_NOT_FOUND"
    assert response.json()["response_type"] == "error"
    assert error.get("message")

    periods = get_success_data(api.list_billing_periods(SYS, {"account_id": account["id"]}))
    assert periods == []


def test_cancelling_a_ready_restore_is_refused():
    """PRD §3.5: "A restore that has not yet begun producing output can be
    cancelled directly from either `REQUESTED` or `VALIDATING` into the terminal
    `CANCELLED` state, with no egress accruing and no further side effects."
    PRD §3.5: "Cancellation is the only escape hatch for a request that has not
    reached `READY`."

    Design: Corner/endpoints/restore_cancel_from_ready_returns_invalid_state
    """
    from test_helpers import (
        create_restore, validate_restore, begin_restore, prepare_restore,
        owner_headers, validate_error, ApiErrorId,
    )
    scenario = setup_active_set_for_restore(size_bytes=GB_10, file_path="/home/u/cancel.bin",
                                event_utc="2026-09-02T00:00:00Z",
                                require_mfa_for_restore=False)
    account_id = scenario["account"]["id"]
    set_clock("2026-09-03T00:00:00Z")

    restore = create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                             requested_size_gb=10.0)
    validate_restore(restore["id"], account_id)
    begin_restore(restore["id"], account_id)
    prepare_restore(restore["id"], account_id)

    refused = api.cancel_restore(restore["id"], owner_headers(account_id))
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)

    fetched = get_success_data(api.get_restore_request(restore["id"], owner_headers(account_id)))
    account = get_success_data(api.get_account(account_id, SYS))
    assert fetched["state"] == "READY"
    assert account["restore_download_gb"] == pytest.approx(0.0, abs=0.01)


def test_completing_an_empty_initial_backup_is_refused():
    """PRD §3.3: "this requires that the set has accumulated at least one
    non-`DELETE` version, and an attempt to promote an empty set is rejected
    with `ERR_INITIAL_BACKUP_EMPTY`."
    PRD §3.3: "While a set is `INITIAL_RUNNING` it is still rate-limited."

    Design: Corner/errors/complete_initial_with_no_live_version_returns_initial_backup_empty
    """
    from test_helpers import validate_error, ApiErrorId
    scenario = setup_personal_scenario()
    set_id = scenario["set"]["id"]
    agent_id = scenario["agent"]["id"]

    # PRD §3.3: the throttle is started by the first *non-DELETE* version, so a
    # set whose only recorded version is a DELETE never leaves PROVISIONING and
    # is an empty set in the sense the promotion guard reads.
    record_version(set_id, "/home/u/ghost.bin", 1, "DELETE", 0, "sha256-ghost-del",
                   "2026-09-02T00:00:00Z")
    refused = api.complete_initial_backup(set_id, BACKUP)
    error = validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    assert error["error_id"] == "ERR_INVALID_STATE"

    fetched = get_success_data(api.get_backup_set(set_id, BACKUP))
    agent = get_success_data(api.get_agent(agent_id, BACKUP))
    assert fetched["state"] == "PROVISIONING"
    assert fetched["is_initial_flush"] is False
    assert agent["in_throttle_window"] is False