"""Transitive cascades: one action driving a chain of consequences."""
import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    ApiErrorId,
    GB_50,
    GB_100,
    SYS,
    BACKUP,
    COMPLIANCE,
    close_billing_period,
    complete_initial,
    execute_closure_deletion,
    complete_deletion_request,
    open_billing_period,
    owner_headers,
    record_version,
    set_clock,
    setup_business_active_set,
)


def _setup_returned_shipment(account_id, agent_id, scenario):
    """DRIVE_SHIPMENT restore walked to READY with its shipment RETURNED."""
    from test_helpers import (
        create_restore, validate_restore, begin_restore, find_shipment_for_restore,
        prepare_restore,
    )
    restore = create_restore(
        scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
        restore_type="DRIVE_SHIPMENT", requested_file_count=1,
        requested_size_gb=50.0, drive_capacity_gb=100.0, drive_count=1,
        deposit_fee_cents=5000)
    restore = validate_restore(restore["id"], account_id)
    restore = begin_restore(restore["id"], account_id)
    shipment = find_shipment_for_restore(restore["id"], account_id)
    assert shipment is not None, "Setup failed: no DriveShipment synthesized by begin"

    shipment = get_success_data(api.ship_drive_shipment(shipment["id"], SYS))
    shipment = get_success_data(api.deliver_drive_shipment(shipment["id"], SYS))
    shipment = get_success_data(api.open_return_window(shipment["id"], owner_headers(account_id)))
    shipment = get_success_data(api.receive_return(shipment["id"], SYS))
    restore = prepare_restore(restore["id"], account_id)
    return restore, shipment


def test_completing_a_restore_closes_its_returned_shipment():
    """PRD §3.5: "Completion also drives the first hop of the restore-side
    cascade: when the restore is a shipment restore whose `DriveShipment` is in
    `RETURNED`, that shipment takes its `RETURNED` to `CLOSED` edge."
    PRD §3.7: "A `SystemOperator` closes a `RETURNED` shipment, moving it to
    its terminal `CLOSED` state; this releases the shipment's refundable deposit
    and, when the shipment was delinquent, folds its forfeited late penalty into
    the account's held-deposit figure."

    Design: Difficulty/transitive_cascade/restore_completion_closes_shipment_then_account_ledger
    """
    scenario = setup_business_active_set(size_bytes=GB_50, file_path="/srv/data/ledger.db",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    set_clock("2026-09-04T00:00:00Z")

    restore, shipment = _setup_returned_shipment(account_id, scenario["agent"]["id"], scenario)
    assert shipment["state"] == "RETURNED"
    assert shipment["return_credit_cents"] == 5000

    completed = get_success_data(api.complete_restore(restore["id"], owner_headers(account_id)))
    shipment_after = get_success_data(api.get_drive_shipment(shipment["id"], SYS))

    assert completed["state"] == "COMPLETED"
    assert shipment_after["state"] == "CLOSED"


def test_completing_a_restore_releases_the_deposit_ledger_the_shipment_close_held():
    """PRD §3.7: "A `CLOSED` shipment contributes nothing refundable but keeps
    its forfeited penalty outstanding, and `RETURNED` shipments contribute no
    held deposit because their deposit has been decided."
    PRD §3.5: "the restore's `egress_gb` is added to the account's
    `restore_download_gb`, and the account's `transaction_count` is incremented
    by one."

    Design: Difficulty/transitive_cascade/restore_completion_closes_shipment_then_account_ledger
    """
    scenario = setup_business_active_set(size_bytes=GB_50, file_path="/srv/data/ledger.db",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    set_clock("2026-09-04T00:00:00Z")

    restore, shipment = _setup_returned_shipment(account_id, scenario["agent"]["id"], scenario)
    # PRD 3.7: a timely RETURNED shipment has had its deposit decided, so it
    # contributes no held deposit before the close; the close itself is what
    # settles the ledger, and the restore completion is what drives that close.
    held_before = get_success_data(api.get_account(account_id, SYS))
    assert held_before["deposit_held_cents"] == 0

    completed = get_success_data(api.complete_restore(restore["id"], owner_headers(account_id)))
    account = get_success_data(api.get_account(account_id, SYS))

    assert completed["state"] == "COMPLETED"
    # PRD 3.6 metered variant: a 50 GB restore bills the raw volume minus the
    # 1 GB free allowance = 49.0 GB, and PRD 3.5 accrues exactly that to the
    # account's restore_download_gb at completion.
    assert completed["egress_gb"] == pytest.approx(49.0, abs=0.01)
    assert account["deposit_held_cents"] == 0
    assert account["transaction_count"] == 1


def test_closure_deletion_execution_deletes_every_set_of_the_account():
    """PRD §3.8: "When the scope is `ACCOUNT_CLOSURE`, execution additionally
    sets the account's `status` to `CLOSED`, retires every agent of the account
    to `RETIRED`, and moves every set of the account to `DELETED`."
    PRD §3.8: "it recomputes each affected set's `storage_gb`,
    `version_chain_depth`, `recovery_points`, and `retention_floor_utc` as the
    first hop"

    Design: Difficulty/transitive_cascade/deletion_execute_cascades_set_then_account_then_agent
    """
    scenario = setup_business_active_set(size_bytes=GB_100, file_path="/srv/data/payroll.db",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    set_id = scenario["set"]["id"]

    ctx = execute_closure_deletion(scenario)
    executing = ctx["request"]
    backup_set = get_success_data(api.get_backup_set(set_id, BACKUP))

    assert executing["state"] == "EXECUTING"
    assert backup_set["state"] == "DELETED"
    assert backup_set["version_chain_depth"] == 0
    assert backup_set["storage_gb"] == 0.0


def test_closure_deletion_execution_zeroes_usage_then_closes_account_and_retires_agent():
    """PRD §3.8: "then recomputes the account's `usage_gb` and `peak_usage_gb`
    from the surviving sets as the second hop."
    PRD §3.8: "Completion closes the request out, moving it from `EXECUTING` to
    its terminal `COMPLETED` state and stamping the two purge counters —
    `files_purged`, the number of file versions removed, and `bytes_purged`, the
    total bytes released."

    Design: Difficulty/transitive_cascade/deletion_execute_cascades_set_then_account_then_agent
    """
    scenario = setup_business_active_set(size_bytes=GB_100, file_path="/srv/data/payroll.db",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    agent_id = scenario["agent"]["id"]

    ctx = execute_closure_deletion(scenario)
    request = ctx["request"]
    executing = request

    account = get_success_data(api.get_account(account_id, SYS))
    agent = get_success_data(api.get_agent(agent_id, BACKUP))

    assert account["usage_gb"] == 0.0
    assert account["peak_usage_gb"] == pytest.approx(100.0, abs=0.01)
    assert account["status"] == "CLOSED"
    assert agent["status"] == "RETIRED"
    assert executing["files_purged"] == 0

    completed = complete_deletion_request(request["id"])
    assert completed["state"] == "COMPLETED"
    assert completed["files_purged"] == 1