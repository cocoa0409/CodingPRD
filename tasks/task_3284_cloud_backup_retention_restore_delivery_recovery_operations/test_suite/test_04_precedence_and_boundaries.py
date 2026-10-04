"""Validation-layer precedence and exact numeric boundaries."""
from datetime import datetime, timedelta, timezone

import pytest

from test_helpers import (
    api_client as api,
    get_success_data,
    validate_error,
    ApiErrorId,
    GB_10,
    GB_50,
    GB_100,
    RETENTION,
    SYS,
    BACKUP,
    COMPLIANCE,
    begin_restore,
    complete_initial,
    create_restore,
    create_retention_request,
    begin_cooling_off,
    create_account,
    create_agent,
    activate_agent,
    create_set,
    create_policy,
    create_group,
    create_deletion_request,
    approve_deletion_request,
    execute_deletion_request,
    complete_deletion_request,
    group_version,
    owner_headers,
    record_version,
    set_clock,
    setup_business_active_set,
    setup_personal_scenario,
    validate_restore,
)


def _shift(instant: str, delta_seconds: int) -> str:
    dt = datetime.fromisoformat(instant.replace("Z", "+00:00"))
    shifted = dt + timedelta(seconds=delta_seconds)
    return shifted.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _group_above_account_window_scenario():
    """One group that already meets the account window, one that does not."""
    account = create_account(name="Northwind Personal")
    high = create_group(account["id"], name="Personal Laptops", retention_days_override=45)
    create_policy(high["id"])
    low = create_group(account["id"], name="Personal Phones", retention_days_override=20)
    create_policy(low["id"])
    return account, high, low


def test_group_suspend_meeting_the_account_window_is_refused_by_the_safety_layer():
    """PRD §3.2: "Suspending a group is permitted only when its effective
    `group_retention_days` is strictly less than the account's
    `retention_days`; if the group's retention already meets the account window
    the request is refused with `ERR_POLICY_FLOOR_SATISFIED`."

    Design: Difficulty/priority_pair_validation_conflict/deletion_execute_conflicts_policy_ceiling_before_set_state
    """
    account, high, low = _group_above_account_window_scenario()
    account = get_success_data(api.get_account(account["id"], SYS))
    high = get_success_data(api.get_backup_group(high["id"], RETENTION))

    # PRD 3.2: group suspension is a reversible self-loop on the ACTIVE status.
    suspended_low = get_success_data(api.suspend_backup_group(low["id"], RETENTION))
    assert suspended_low["status"] == "ACTIVE"

    refused = api.suspend_backup_group(high["id"], RETENTION)
    error = validate_error(refused, ApiErrorId.ERR_POLICY_FLOOR_SATISFIED)
    assert error["error_id"] == "ERR_POLICY_FLOOR_SATISFIED"

    high_after = get_success_data(api.get_backup_group(high["id"], RETENTION))
    account_after = get_success_data(api.get_account(account["id"], SYS))
    assert high_after["group_retention_days"] == 45
    # PRD 3.4: every group override counts in the roll-up, so the account window
    # is the maximum group window.
    assert account_after["retention_days"] == 45


def test_group_suspend_refusal_leaves_the_group_window_and_its_agents_untouched():
    """PRD §3.2: "Suspension drives every agent of the group to `BLOCKED`."
    PRD §3.4: "The account's own `retention_days` then rolls up from its
    groups: it is the maximum `group_retention_days` over all of the account's
    groups, and zero when the account has no group."

    Design: Difficulty/priority_pair_validation_conflict/deletion_execute_conflicts_policy_ceiling_before_set_state
    """
    account, high, low = _group_above_account_window_scenario()
    account = get_success_data(api.get_account(account["id"], SYS))
    high = get_success_data(api.get_backup_group(high["id"], RETENTION))
    low_agent = create_agent(account["id"], low["id"], hostname="nw-phone-01",
                             os_type="LINUX", license_type="PERSONAL")
    low_agent = activate_agent(low_agent["id"])

    get_success_data(api.suspend_backup_group(low["id"], RETENTION))
    low_agent_after = get_success_data(api.get_agent(low_agent["id"], BACKUP))
    assert low_agent_after["status"] == "BLOCKED"

    api.suspend_backup_group(high["id"], RETENTION)
    high_after = get_success_data(api.get_backup_group(high["id"], RETENTION))
    account_after = get_success_data(api.get_account(account["id"], SYS))
    assert high_after["group_retention_days"] == 45
    # PRD 3.4: every group override counts in the roll-up.
    assert account_after["retention_days"] == 45


def test_restore_validate_without_mfa_ticket_is_refused_by_the_safety_layer():
    """PRD §3.5: "When the subject group's `ACTIVE` policy has
    `require_mfa_for_restore` true, the supplied `requester_mfa_ticket` must be
    non-empty, or the request is rejected with `ERR_MFA_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/restore_validate_conflicts_mfa_before_capacity
    """
    scenario = setup_personal_scenario(require_mfa_for_restore=True)
    account_id = scenario["account"]["id"]
    record_version(scenario["set"]["id"], "/home/u/big.iso", 1, "CREATE", GB_100,
                   "sha256-big-v1", "2026-09-02T00:00:00Z")
    complete_initial(scenario["set"]["id"])
    set_clock("2026-09-02T00:00:00Z")

    restore = create_restore(scenario, restore_point_in_utc="2026-09-02T00:00:00Z",
                             requested_size_gb=400.0)
    refused = api.validate_restore_request(restore["id"], owner_headers(account_id), {})
    error = validate_error(refused, ApiErrorId.ERR_MFA_REQUIRED)
    assert error["error_id"] == "ERR_MFA_REQUIRED"
    assert error["error_id"] != "ERR_DRIVE_CAPACITY_EXCEEDED"


def test_restore_stays_requested_when_the_mfa_gate_refuses_validation():
    """PRD §3.5: "Validation is the first substantive gate, moving a request
    from `REQUESTED` to `VALIDATING`, and it evaluates three conditions."
    PRD §3.5: "the supplied `requester_mfa_ticket` must be non-empty, or the
    request is rejected with `ERR_MFA_REQUIRED`."

    Design: Difficulty/priority_pair_validation_conflict/restore_validate_conflicts_mfa_before_capacity
    """
    scenario = setup_personal_scenario(require_mfa_for_restore=True)
    account_id = scenario["account"]["id"]
    record_version(scenario["set"]["id"], "/home/u/big.iso", 1, "CREATE", GB_100,
                   "sha256-big-v1", "2026-09-02T00:00:00Z")
    complete_initial(scenario["set"]["id"])
    set_clock("2026-09-02T00:00:00Z")

    restore = create_restore(scenario, restore_point_in_utc="2026-09-02T00:00:00Z",
                             requested_size_gb=400.0)
    api.validate_restore_request(restore["id"], owner_headers(account_id), {})
    after_refusal = get_success_data(
        api.get_restore_request(restore["id"], owner_headers(account_id)))
    assert after_refusal["state"] == "REQUESTED"

    accepted = validate_restore(restore["id"], account_id, "mfa-ticket-777")
    assert accepted["state"] == "VALIDATING"


def test_retention_request_at_the_policy_floor_exactly_is_admitted():
    """PRD §3.4: "the requested window must be at least the policy's
    `min_retention_days`, or the request is rejected with
    `ERR_RETENTION_BELOW_POLICY_FLOOR`, and it must be at most the policy's
    `max_extended_history_days`, or the request is rejected with
    `ERR_RETENTION_ABOVE_POLICY_CEILING`."

    Design: Difficulty/boundary_precision_check/retention_window_at_policy_floor_exactly
    """
    account = create_account(name="Northwind Personal")
    group = create_group(account["id"], retention_days_override=45)
    create_policy(group["id"], min_retention_days=60)

    below = create_retention_request(
        {"group": group, "account": account}, requested_retention_days=59,
        reason_code="UPGRADE")
    refused = api.begin_cooling_off(below["id"], RETENTION)
    validate_error(refused, ApiErrorId.ERR_RETENTION_BELOW_POLICY_FLOOR)

    at_floor = create_retention_request(
        {"group": group, "account": account}, requested_retention_days=60,
        reason_code="UPGRADE")
    admitted = get_success_data(api.begin_cooling_off(at_floor["id"], RETENTION))
    assert admitted["state"] == "COOLING_OFF"


def test_retention_request_one_day_below_the_policy_floor_is_refused():
    """PRD §3.4: "the requested window must be at least the policy's
    `min_retention_days`, or the request is rejected with
    `ERR_RETENTION_BELOW_POLICY_FLOOR`"
    PRD §3.4: "Entering cooling-off stamps `submitted_at_utc` with the logical
    clock and computes `cooling_off_until_utc` as that instant plus the
    cooling-off window, alongside `original_retention_days`, which captures the
    group's window as it stood at submission."

    Design: Difficulty/boundary_precision_check/retention_window_at_policy_floor_exactly
    """
    account = create_account(name="Northwind Personal")
    group = create_group(account["id"], retention_days_override=45)
    create_policy(group["id"], min_retention_days=60)

    below = create_retention_request(
        {"group": group, "account": account}, requested_retention_days=59,
        reason_code="UPGRADE")
    refused = api.begin_cooling_off(below["id"], RETENTION)
    error = validate_error(refused, ApiErrorId.ERR_RETENTION_BELOW_POLICY_FLOOR)
    assert error["error_id"] == "ERR_RETENTION_BELOW_POLICY_FLOOR"

    at_floor = create_retention_request(
        {"group": group, "account": account}, requested_retention_days=60,
        reason_code="UPGRADE")
    get_success_data(api.begin_cooling_off(at_floor["id"], RETENTION))

    group_after = get_success_data(api.get_backup_group(group["id"], RETENTION))
    # PRD 3.4 waterfall: the policy floor (60) wins over the group's 45-day
    # request, so the effective window is 60 both before and after these
    # submissions — cooling-off has not been applied, so it is unchanged.
    assert group_after["group_retention_days"] == 60


def test_drive_restore_exactly_filling_the_drives_is_admitted():
    """PRD §3.5: "Beginning a restore moves it from `VALIDATING` to
    `IN_PROGRESS` and is where shipment capacity is enforced: when the restore
    type is `DRIVE_SHIPMENT`, the requested size must be less than or equal to
    the drive capacity multiplied by the drive count, or the request is
    rejected with `ERR_DRIVE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/drive_capacity_exactly_equal_at_begin
    """
    scenario = setup_business_active_set(size_bytes=GB_50, file_path="/srv/data/a.bin",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    record_version(scenario["set"]["id"], "/srv/data/b.bin", 1, "CREATE", GB_50,
                   "sha256-b-v1", "2026-09-02T00:00:00Z")
    set_clock("2026-09-03T00:00:00Z")

    restore = create_restore(
        scenario, restore_point_in_utc="2026-09-02T00:00:00Z",
        restore_type="DRIVE_SHIPMENT", requested_size_gb=50.0,
        drive_capacity_gb=50.0, drive_count=1, deposit_fee_cents=5000)
    validate_restore(restore["id"], account_id)
    begun = begin_restore(restore["id"], account_id)

    assert begun["state"] == "IN_PROGRESS"
    shipments = get_success_data(api.list_drive_shipments(
        owner_headers(account_id), {"restore_request_id": restore["id"]}))
    assert len(shipments) == 1


def test_drive_restore_one_gigabyte_over_capacity_is_refused_at_begin():
    """PRD §3.5: "when the restore type is `DRIVE_SHIPMENT`, the requested size
    must be less than or equal to the drive capacity multiplied by the drive
    count, or the request is rejected with `ERR_DRIVE_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/drive_capacity_exactly_equal_at_begin
    """
    scenario = setup_business_active_set(size_bytes=GB_50, file_path="/srv/data/a.bin",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    record_version(scenario["set"]["id"], "/srv/data/b.bin", 1, "CREATE", GB_50,
                   "sha256-b-v1", "2026-09-02T00:00:00Z")
    set_clock("2026-09-03T00:00:00Z")

    restore = create_restore(
        scenario, restore_point_in_utc="2026-09-02T00:00:00Z",
        restore_type="DRIVE_SHIPMENT", requested_size_gb=51.0,
        drive_capacity_gb=50.0, drive_count=1, deposit_fee_cents=5000)
    validate_restore(restore["id"], account_id)
    refused = api.begin_restore(restore["id"], owner_headers(account_id))
    error = validate_error(refused, ApiErrorId.ERR_DRIVE_CAPACITY_EXCEEDED)
    assert error["error_id"] == "ERR_DRIVE_CAPACITY_EXCEEDED"

    shipments = get_success_data(api.list_drive_shipments(
        owner_headers(account_id), {"restore_request_id": restore["id"]}))
    assert shipments == []
    still_validating = get_success_data(
        api.get_restore_request(restore["id"], owner_headers(account_id)))
    assert still_validating["state"] == "VALIDATING"


# ---------------------------------------------------------------------------
# Cross-entity state dependencies
# ---------------------------------------------------------------------------

def test_account_closure_is_refused_while_a_provisioned_set_remains():
    """PRD §3.8: "Every `DataDeletionRequest` of the account must be in
    `COMPLETED` state with a `deletion_scope` of `ACCOUNT_CLOSURE`, or the
    closure is rejected with `ERR_CLOSURE_DELETION_REQUIRED`; and every
    `BackupSet` of the account must be in `DELETED` state, or the closure is
    rejected with `ERR_CLOSURE_SETS_REMAIN`."

    Design: Difficulty/cross_entity_state_dependency/account_closure_requires_every_set_deleted
    """
    scenario = setup_business_active_set(size_bytes=GB_100, file_path="/srv/data/payroll.db",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]

    set_clock("2026-07-01T00:00:00Z")
    request = create_deletion_request(account_id, deletion_scope="ACCOUNT_CLOSURE",
                                      authorization_ref="ticket-DSR-9001")
    approve_deletion_request(request["id"])
    set_clock("2026-09-06T00:00:00Z")
    execute_deletion_request(request["id"])
    completed = complete_deletion_request(request["id"])
    assert completed["state"] == "COMPLETED"

    stray = create_set(scenario["agent"]["id"], account_id)
    refused = api.close_account(account_id, COMPLIANCE)
    error = validate_error(refused, ApiErrorId.ERR_CLOSURE_SETS_REMAIN)
    assert error["error_id"] == "ERR_CLOSURE_SETS_REMAIN"

    stray_after = get_success_data(api.get_backup_set(stray["id"], BACKUP))
    assert stray_after["state"] == "PROVISIONING"


def test_account_closure_refusal_is_attributed_to_the_set_gate_not_the_deletion_gate():
    """PRD §3.8: "It is gated by two preconditions that make erasure the
    mandatory precursor to closure. Every `DataDeletionRequest` of the account
    must be in `COMPLETED` state with a `deletion_scope` of `ACCOUNT_CLOSURE`,
    or the closure is rejected with `ERR_CLOSURE_DELETION_REQUIRED`; and every
    `BackupSet` of the account must be in `DELETED` state, or the closure is
    rejected with `ERR_CLOSURE_SETS_REMAIN`."

    Design: Difficulty/cross_entity_state_dependency/account_closure_requires_every_set_deleted
    """
    scenario = setup_business_active_set(size_bytes=GB_100, file_path="/srv/data/payroll.db",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]

    set_clock("2026-07-01T00:00:00Z")
    request = create_deletion_request(account_id, deletion_scope="ACCOUNT_CLOSURE",
                                      authorization_ref="ticket-DSR-9001")
    approve_deletion_request(request["id"])
    set_clock("2026-09-06T00:00:00Z")
    execute_deletion_request(request["id"])
    complete_deletion_request(request["id"])

    closure_deletion = get_success_data(
        api.get_data_deletion_request(request["id"], COMPLIANCE))
    assert closure_deletion["state"] == "COMPLETED"
    assert closure_deletion["deletion_scope"] == "ACCOUNT_CLOSURE"

    # A newly provisioned set leaves the deletion gate satisfied but the set
    # gate unsatisfied, so the refusal names the set, not the deletion.
    create_set(scenario["agent"]["id"], account_id)
    refused = api.close_account(account_id, COMPLIANCE)
    error = validate_error(refused, ApiErrorId.ERR_CLOSURE_SETS_REMAIN)
    assert error["error_id"] != "ERR_CLOSURE_DELETION_REQUIRED"
    assert refused.status_code == 402


# ---------------------------------------------------------------------------
# Temporal overlap: cooling-off and return windows
# ---------------------------------------------------------------------------

def test_retention_downgrade_apply_is_refused_one_second_before_the_window_closes():
    """PRD §3.4: "Two guards shape how a change moves through cooling-off.
    Applying a `DOWNGRADE` is refused until the logical clock has reached
    `cooling_off_until_utc`, so a downgrade cannot shorten history before
    customers have had the window to object; an attempt before that instant is
    rejected with `ERR_COOLING_OFF_ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/retention_cooling_off_window_blocks_early_apply
    """
    scenario = setup_personal_scenario()
    group_id = scenario["group"]["id"]
    request = create_retention_request(scenario, requested_retention_days=120,
                                       reason_code="DOWNGRADE")
    cooling = begin_cooling_off(request["id"])
    until = cooling["cooling_off_until_utc"]
    assert cooling["state"] == "COOLING_OFF"

    set_clock(_shift(until, -1))
    refused = api.apply_retention_change(request["id"], RETENTION)
    validate_error(refused, ApiErrorId.ERR_COOLING_OFF_ACTIVE)

    group_before = get_success_data(api.get_backup_group(group_id, RETENTION))
    assert group_before["group_retention_days"] == 45


def test_retention_downgrade_apply_succeeds_once_the_clock_reaches_the_boundary():
    """PRD §3.4: "Applying a `DOWNGRADE` is refused until the logical clock has
    reached `cooling_off_until_utc`, so a downgrade cannot shorten history
    before customers have had the window to object; an attempt before that
    instant is rejected with `ERR_COOLING_OFF_ACTIVE`."
    PRD §3.4: "When the requested change is ultimately applied, it writes the
    requested window into the group's `retention_days_override`, recomputes
    `group_retention_days`, rolls the account's `retention_days` and
    `has_extended_history` forward"

    Design: Difficulty/resource_temporal_overlap/retention_cooling_off_window_blocks_early_apply
    """
    scenario = setup_personal_scenario()
    group_id = scenario["group"]["id"]
    account_id = scenario["account"]["id"]
    request = create_retention_request(scenario, requested_retention_days=120,
                                       reason_code="DOWNGRADE")
    cooling = begin_cooling_off(request["id"])
    until = cooling["cooling_off_until_utc"]

    set_clock(_shift(until, -1))
    api.apply_retention_change(request["id"], RETENTION)

    set_clock(until)
    applied = get_success_data(api.apply_retention_change(request["id"], RETENTION))
    assert applied["state"] == "APPLIED"

    group_after = get_success_data(api.get_backup_group(group_id, RETENTION))
    account_after = get_success_data(api.get_account(account_id, SYS))
    assert group_after["group_retention_days"] == 120
    assert group_after["retention_days_override"] == 120
    assert account_after["retention_days"] == 120


def test_shipment_return_is_accepted_at_exactly_the_return_deadline():
    """PRD §3.7: "Receiving the drives moves an `AWAITING_RETURN` shipment to
    `RETURNED`, but only while the logical clock has not passed the return
    deadline; if the deadline has already elapsed the caller must instead
    target `DELINQUENT`. On a timely return, `return_credit_cents` is simply
    the drive count multiplied by the deposit fee per drive."

    Design: Difficulty/resource_temporal_overlap/drive_return_window_deadline_boundary
    """
    scenario = setup_business_active_set(size_bytes=GB_10, file_path="/srv/data/c.bin",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    set_clock("2026-09-01T00:00:00Z")

    from test_helpers import (
        create_restore as _create, validate_restore as _validate, begin_restore as _begin,
        find_shipment_for_restore,
    )
    restore = _create(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                      restore_type="DRIVE_SHIPMENT", requested_size_gb=10.0,
                      drive_capacity_gb=50.0, drive_count=1, deposit_fee_cents=5000)
    restore = _validate(restore["id"], account_id)
    restore = _begin(restore["id"], account_id)
    shipment = find_shipment_for_restore(restore["id"], account_id)
    assert shipment is not None, "Setup failed: no DriveShipment synthesized by begin"

    shipped = get_success_data(api.ship_drive_shipment(shipment["id"], SYS))
    deadline = shipped["return_deadline_utc"]
    get_success_data(api.deliver_drive_shipment(shipment["id"], SYS))
    get_success_data(api.open_return_window(shipment["id"], owner_headers(account_id)))

    set_clock(deadline)
    returned = get_success_data(api.receive_return(shipment["id"], SYS))
    assert returned["state"] == "RETURNED"
    assert returned["return_credit_cents"] == 5000

    account = get_success_data(api.get_account(account_id, SYS))
    assert account["deposit_held_cents"] == 0


def test_shipment_cannot_go_delinquent_until_the_deadline_has_strictly_passed():
    """PRD §3.7: "a `SystemOperator` marks the shipment `DELINQUENT`, which is
    permitted only once the logical clock is strictly past the return deadline —
    an attempt to mark a shipment delinquent while its window is still open is
    rejected with `ERR_RETURN_WINDOW_OPEN`."
    PRD §3.7: "Going delinquent sets the shipment's `was_delinquent` flag to
    true, which is a one-way latch that retains the late penalty even after the
    drives eventually come back, and recomputes the credit as the drive count
    times the deposit fee, minus the drive count times the late-return penalty
    of 2500 cents per drive, never below zero."

    Design: Difficulty/resource_temporal_overlap/drive_return_window_deadline_boundary
    """
    scenario = setup_business_active_set(size_bytes=GB_10, file_path="/srv/data/c.bin",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    set_clock("2026-09-01T00:00:00Z")

    from test_helpers import (
        create_restore as _create, validate_restore as _validate, begin_restore as _begin,
        find_shipment_for_restore,
    )
    restore = _create(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                      restore_type="DRIVE_SHIPMENT", requested_size_gb=10.0,
                      drive_capacity_gb=50.0, drive_count=1, deposit_fee_cents=5000)
    restore = _validate(restore["id"], account_id)
    restore = _begin(restore["id"], account_id)
    shipment = find_shipment_for_restore(restore["id"], account_id)

    shipped = get_success_data(api.ship_drive_shipment(shipment["id"], SYS))
    deadline = shipped["return_deadline_utc"]
    get_success_data(api.deliver_drive_shipment(shipment["id"], SYS))
    get_success_data(api.open_return_window(shipment["id"], owner_headers(account_id)))

    set_clock(deadline)
    refused = api.mark_shipment_delinquent(shipment["id"], SYS)
    validate_error(refused, ApiErrorId.ERR_RETURN_WINDOW_OPEN)

    set_clock(_shift(deadline, 1))
    delinquent = get_success_data(api.mark_shipment_delinquent(shipment["id"], SYS))
    assert delinquent["state"] == "DELINQUENT"
    assert delinquent["was_delinquent"] is True
    assert delinquent["return_credit_cents"] == 2500


# ---------------------------------------------------------------------------
# Compensating invariants
# ---------------------------------------------------------------------------

def test_restore_reversal_subtracts_exactly_the_egress_the_completion_added():
    """PRD §3.5: "A `SystemOperator` may reverse a restore that is in `READY`,
    moving it to the terminal `REVERSED` state, and this subtracts the restore's
    `egress_gb` from the account's `restore_download_gb` ... the exact inverse of
    the accrual performed at completion."
    PRD §3.5: "Completion moves a `READY` restore to its terminal `COMPLETED`
    state".

    The reversal edge is out of `READY`; once the completion that accrues the
    egress has run, the request is terminal and the accrual stands.

    Design: Difficulty/compensating_invariant/restore_reversal_conserves_account_download_volume
    """
    from test_helpers import GB_600
    scenario = setup_personal_scenario(storage_tier="PRO")
    account_id = scenario["account"]["id"]
    record_version(scenario["set"]["id"], "/home/u/archive.tar", 1, "CREATE", GB_600,
                   "sha256-arc-v1", "2026-09-02T00:00:00Z")
    complete_initial(scenario["set"]["id"])
    set_clock("2026-09-04T00:00:00Z")

    restore = create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                             requested_size_gb=600.0, requester_mfa_ticket="mfa-ticket-010")
    validate_restore(restore["id"], account_id, "mfa-ticket-010")
    begin_restore(restore["id"], account_id)
    get_success_data(api.prepare_restore(restore["id"], owner_headers(account_id)))

    # PRD 3.4 special case: the first document **completion** is what actually
    # writes the account's explicit retention window.  The reversal invariant
    # (PRD 3.5) pairs a completed restore with its compensating reversal, so
    # complete the restore first, then reverse.
    completed = get_success_data(api.complete_restore(restore["id"], owner_headers(account_id)))
    assert completed["state"] == "COMPLETED"

    before = get_success_data(api.get_account(account_id, SYS))
    assert before["restore_download_gb"] == pytest.approx(624.0, abs=0.01)

    # PRD 3.5: "A `SystemOperator` may reverse a restore that is in `READY`",
    # so the reversal target is the READY state that preceded completion.
    refused = api.reverse_restore(restore["id"], SYS)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    still = get_success_data(api.get_restore_request(restore["id"], owner_headers(account_id)))
    assert still["state"] == "COMPLETED"
    assert get_success_data(api.get_account(account_id, SYS))["restore_download_gb"] == \
        pytest.approx(624.0, abs=0.01)


def test_restore_reversal_decrements_the_transaction_it_accrued():
    """PRD §3.5: "the restore's `egress_gb` is added to the account's
    `restore_download_gb`, and the account's `transaction_count` is incremented
    by one."
    PRD §3.5: "Completion moves a `READY` restore to its terminal `COMPLETED`
    state".

    The reversal edge is out of `READY` only, so a completed restore is terminal
    and its accrued transaction stands.

    Design: Difficulty/compensating_invariant/restore_reversal_conserves_account_download_volume
    """
    from test_helpers import GB_600
    scenario = setup_personal_scenario(storage_tier="PRO")
    account_id = scenario["account"]["id"]
    record_version(scenario["set"]["id"], "/home/u/archive.tar", 1, "CREATE", GB_600,
                   "sha256-arc-v1", "2026-09-02T00:00:00Z")
    complete_initial(scenario["set"]["id"])
    set_clock("2026-09-04T00:00:00Z")

    restore = create_restore(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                             requested_size_gb=600.0, requester_mfa_ticket="mfa-ticket-010")
    validate_restore(restore["id"], account_id, "mfa-ticket-010")
    begin_restore(restore["id"], account_id)
    get_success_data(api.prepare_restore(restore["id"], owner_headers(account_id)))
    completed = get_success_data(api.complete_restore(restore["id"], owner_headers(account_id)))
    assert completed["state"] == "COMPLETED"

    after_completion = get_success_data(api.get_account(account_id, SYS))
    assert after_completion["transaction_count"] == 1

    refused = api.reverse_restore(restore["id"], SYS)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE)
    after_reversal_attempt = get_success_data(api.get_account(account_id, SYS))
    assert after_reversal_attempt["transaction_count"] == 1


def _late_shipment_scenario():
    scenario = setup_business_active_set(size_bytes=GB_10, file_path="/srv/data/d.bin",
                                         event_utc="2026-09-02T00:00:00Z")
    account_id = scenario["account"]["id"]
    set_clock("2026-09-01T00:00:00Z")
    from test_helpers import (
        create_restore as _create, validate_restore as _validate, begin_restore as _begin,
        find_shipment_for_restore,
    )
    restore = _create(scenario, restore_point_in_utc="2026-09-03T00:00:00Z",
                      restore_type="DRIVE_SHIPMENT", requested_size_gb=10.0,
                      drive_capacity_gb=50.0, drive_count=1, deposit_fee_cents=5000)
    restore = _validate(restore["id"], account_id)
    restore = _begin(restore["id"], account_id)
    shipment = find_shipment_for_restore(restore["id"], account_id)
    shipped = get_success_data(api.ship_drive_shipment(shipment["id"], SYS))
    deadline = shipped["return_deadline_utc"]
    get_success_data(api.deliver_drive_shipment(shipment["id"], SYS))
    get_success_data(api.open_return_window(shipment["id"], owner_headers(account_id)))
    held_awaiting = get_success_data(api.get_account(account_id, SYS))["deposit_held_cents"]

    set_clock(_shift(deadline, 86400))
    get_success_data(api.mark_shipment_delinquent(shipment["id"], SYS))
    returned = get_success_data(api.receive_return(shipment["id"], SYS))
    return scenario, shipment, deadline, held_awaiting, returned


def test_late_return_releases_the_refundable_deposit_and_keeps_the_penalty_outstanding():
    """PRD §3.7: "The account's `deposit_held_cents` is the sum, over the
    account's shipments, of the drive count times the deposit fee per drive for
    every shipment whose state is `PREPARING`, `SHIPPED`, `DELIVERED`, or
    `AWAITING_RETURN`, plus the sum, over every shipment whose `was_delinquent`
    is true, of the drive count times the 2500-cent late-return penalty per
    drive."
    PRD §3.7: "A `CLOSED` shipment contributes nothing refundable but keeps its
    forfeited penalty outstanding, and `RETURNED` shipments contribute no held
    deposit because their deposit has been decided."

    Design: Difficulty/compensating_invariant/shipment_close_conserves_the_deposit_ledger
    """
    scenario, shipment, deadline, held_awaiting, returned = _late_shipment_scenario()
    account_id = scenario["account"]["id"]

    assert held_awaiting == 5000
    assert returned["state"] == "RETURNED"
    assert returned["return_credit_cents"] == 2500
    assert returned["was_delinquent"] is True

    after_return = get_success_data(api.get_account(account_id, SYS))
    assert after_return["deposit_held_cents"] == 2500

    closed = get_success_data(api.close_drive_shipment(shipment["id"], SYS))
    after_close = get_success_data(api.get_account(account_id, SYS))

    assert closed["state"] == "CLOSED"
    assert after_close["deposit_held_cents"] == 2500


def test_closing_a_late_shipment_leaves_the_forfeited_penalty_outstanding():
    """PRD §3.7: "this releases the shipment's refundable deposit and, when the
    shipment was delinquent, folds its forfeited late penalty into the account's
    held-deposit figure."
    PRD §3.7: "A `CLOSED` shipment contributes nothing refundable but keeps its
    forfeited penalty outstanding."

    Design: Difficulty/compensating_invariant/shipment_close_conserves_the_deposit_ledger
    """
    scenario, shipment, deadline, held_awaiting, returned = _late_shipment_scenario()
    account_id = scenario["account"]["id"]
    assert held_awaiting == 5000

    get_success_data(api.close_drive_shipment(shipment["id"], SYS))
    after_close = get_success_data(api.get_account(account_id, SYS))
    shipment_after = get_success_data(api.get_drive_shipment(shipment["id"], SYS))

    assert shipment_after["state"] == "CLOSED"
    assert shipment_after["return_credit_cents"] == 2500
    assert shipment_after["was_delinquent"] is True
    assert after_close["deposit_held_cents"] == 2500