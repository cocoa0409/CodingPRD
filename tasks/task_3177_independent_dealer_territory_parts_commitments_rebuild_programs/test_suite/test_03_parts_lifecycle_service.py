"""Parts commitment and batch lifecycle, plus the service bench cascade."""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    ApiErrorId,
    create_batch,
    create_service_order,
    get_batch,
    get_commitment,
    get_dealer,
    parts_manager_headers,
    place_batch_order,
    receive_batch,
    setup_commitment_order_ready,
    technician_supervisor_headers,
)


def test_escalating_a_service_order_drives_the_commitment_deficient():
    """PRD §3.10: "Escalating sets the commitment's `status` to
    `PERFORMANCE_DEFICIENT`, stamps `backorder_opened_at` with the server
    timestamp, recalculates `Dealer.open_backorder_units` and deactivates the
    default deferred shortage rule."
    PRD §3.10: "Escalation moves `IN_PROGRESS` to `ESCALATED` and requires `orderable_ref_enabled` to be false, so the two branches of `IN_PROGRESS` are exact complements"

    Design: Difficulty/transitive_cascade/restriction_order_escalation_cascades_three_hops_to_dealer_backorders
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=False, sla_hours=6.0)
    assert validate_success(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))["status"] == "IN_PROGRESS"

    data = validate_success(api_client.escalate_service_order(
        order["id"], technician_supervisor_headers()))
    assert data["status"] == "ESCALATED"

    commitment_after = get_commitment(commitment["id"])
    assert commitment_after["status"] == "PERFORMANCE_DEFICIENT"
    assert commitment_after["backorder_opened_at"] is not None


def test_escalation_backorder_recompute_is_a_consequence_of_the_commitment():
    """PRD §3.1: "`open_backorder_units` sums `unfilled_units` across the
    parts-order batches whose commitment belongs to this dealer and whose
    `status` is `OPEN` or `CORE_PENDING`."
    PRD §3.10: "stamps `backorder_opened_at` with the server timestamp,
    recalculates `Dealer.open_backorder_units` and deactivates the default
    deferred shortage rule."

    Design: Difficulty/transitive_cascade/restriction_order_escalation_cascades_three_hops_to_dealer_backorders
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=False, sla_hours=6.0)
    get_success_data(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))
    get_success_data(api_client.escalate_service_order(
        order["id"], technician_supervisor_headers()))

    # No batch of the commitment is OPEN or CORE_PENDING, so the dealer counter reads 0.
    assert get_dealer(dealer["id"])["open_backorder_units"] == 0


def test_second_identical_batch_receipt_is_idempotent():
    """PRD §3.5: "A receipt whose unreceipted quantity is already covered by
    this batch writes no second credit and leaves `committed_units` untouched,
    so a repeated receipt is idempotent."

    Design: Difficulty/compensating_invariant/batch_receipt_replay_leaves_units_and_credit_unchanged
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10, core_units=10)
    place_batch_order(batch["id"])

    first = validate_success(api_client.receive_batch(
        batch["id"], {"ordered_ref": "OEM-ORD-8001"}, parts_manager_headers()))
    commitment_after_first = get_commitment(commitment["id"])

    second = validate_success(api_client.receive_batch(
        batch["id"], {"ordered_ref": "OEM-ORD-8001"}, parts_manager_headers()))
    commitment_after_second = get_commitment(commitment["id"])

    assert first["unfilled_units"] == 0
    assert second["unfilled_units"] == 0
    assert (commitment_after_second["fulfilled_units"]
            == commitment_after_first["fulfilled_units"])
    assert (commitment_after_second["credit_balance_cents"]
            == commitment_after_first["credit_balance_cents"])


def test_second_identical_receipt_applies_no_second_credit():
    """PRD §3.5: "The commitment's `credit_balance_cents` is increased by exactly
    the batch's `core_units` multiplied by the credited settlement units
    increment — never by a repriced figure — whenever `core_units` is at least
    1." PRD §3.5: "A receipt whose unreceipted quantity is already covered by this batch writes no second credit"

    Design: Difficulty/compensating_invariant/batch_receipt_replay_leaves_units_and_credit_unchanged
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10, core_units=10)
    place_batch_order(batch["id"])
    validate_success(api_client.receive_batch(
        batch["id"], {"ordered_ref": "OEM-ORD-8001"}, parts_manager_headers()))
    mid_credit = get_commitment(commitment["id"])["credit_balance_cents"]
    assert mid_credit > 0

    validate_success(api_client.receive_batch(
        batch["id"], {"ordered_ref": "OEM-ORD-8001"}, parts_manager_headers()))
    final_credit = get_commitment(commitment["id"])["credit_balance_cents"]

    assert final_credit == mid_credit


def test_service_order_resolve_replay_keeps_the_first_stamp():
    """PRD §3.10: "An order in `OPEN` or in `FILLED` can be resolved explicitly
    by a supervisor, stamping `resolved_at` with the server timestamp; a second
    resolve of the same order is a no-op, keeping the first stamp and reporting
    success."

    Design: Difficulty/compensating_invariant/batch_receipt_replay_leaves_units_and_credit_unchanged
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="SLA_AUDIT",
                                 sla_hours=4.0, machine_serial=None)
    first = validate_success(api_client.resolve_service_order(
        order["id"], technician_supervisor_headers()))
    second = validate_success(api_client.resolve_service_order(
        order["id"], technician_supervisor_headers()))

    assert first["status"] == "RESOLVED"
    assert second["status"] == "RESOLVED"
    assert second["resolved_at"] == first["resolved_at"]


def test_service_order_cycles_through_open_and_in_progress():
    """PRD §3.10: "Beginning work moves `OPEN` to `IN_PROGRESS`"
    PRD §3.10: "Reopening moves `IN_PROGRESS` back to `OPEN` and requires that no batch of the linked commitment be `ORDERED`"

    Design: Difficulty/non_linear_state_machine/service_order_cyclic_raise_and_lower_within_open
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=False, sla_hours=6.0)
    assert validate_success(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))["status"] == "IN_PROGRESS"
    assert validate_success(api_client.reopen_service_order(
        order["id"], technician_supervisor_headers()))["status"] == "OPEN"


def test_restriction_raise_and_lower_restore_scope_and_risk():
    """PRD §2.8: "`risk_score` multiplies `priority_rank` by ten, adds ten when
    the order's `kind` is `EMERGENCY_FILL`, and adds five more when the order's
    `machine_serial` is covered by an `ACTIVE` support agreement whose
    `plan_tier` is `PREMIUM`." PRD §2.8: "The derived `priority_rank` is 3 for
    `FULL_STOP`, 2 for `METER_RUNNING` and 1 for `HOURS_SPENT`."
    PRD §3.10: "A successful raise lifts the restriction scope by one severity
    step and recomputes `priority_rank`, `risk_score` and the `deferral_tier` of
    the dealer's `OPEN` restriction orders."

    Design: Difficulty/non_linear_state_machine/service_order_cyclic_raise_and_lower_within_open
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=False,
                                 restriction_scope="HOURS_SPENT", sla_hours=6.0)
    get_success_data(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))

    raised = validate_success(api_client.raise_service_restriction(
        order["id"], technician_supervisor_headers()))
    assert raised["status"] == "IN_PROGRESS"
    assert raised["restriction_scope"] == "METER_RUNNING"
    assert raised["priority_rank"] == 2
    assert raised["risk_score"] == 30

    lowered = validate_success(api_client.lower_service_restriction(
        order["id"], technician_supervisor_headers()))
    assert lowered["restriction_scope"] == "HOURS_SPENT"
    assert lowered["priority_rank"] == 1
    assert lowered["risk_score"] == 20


def test_raise_restriction_from_hours_spent_moves_the_risk_score():
    """PRD §2.8: "`risk_score` multiplies `priority_rank` by ten, adds ten when the order's `kind` is `EMERGENCY_FILL`"
    PRD §2.8: "The derived `priority_rank` is 3 for `FULL_STOP`, 2 for
    `METER_RUNNING` and 1 for `HOURS_SPENT`."

    Design: Difficulty/non_linear_state_machine/service_order_cyclic_raise_and_lower_within_open
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="EMERGENCY_FILL",
                                 orderable_ref_enabled=False,
                                 restriction_scope="HOURS_SPENT", sla_hours=6.0)
    get_success_data(api_client.begin_service_order(
        order["id"], technician_supervisor_headers()))
    raised = validate_success(api_client.raise_service_restriction(
        order["id"], technician_supervisor_headers()))

    # HOURS_SPENT is priority 1 -> 10, plus the 10 emergency bonus.
    assert raised["risk_score"] == 20 + 10


def test_settle_core_credit_from_order_ready_reports_invalid_state():
    """PRD §2.5: "The ladder is not merely a set of checks that must all hold —
    it is a priority order, so the first rung that fails determines the error the
    caller sees and later rungs are never reached on that request." PRD §2.5:
    "5. **State admissibility.** The target resource must be in a state that admits the operation, and every from-state not listed for a trigger is refused with that operation's invalid-state error, `ERR_INVALID_STATE` at HTTP 409."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_stocking_mandate_hard_cap
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    resp = api_client.settle_commitment_core_credit(
        commitment["id"], {"credit_settlement_cents": 6200}, parts_manager_headers())

    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert resp.json()["data"]["error_id"] != ApiErrorId.ERR_STOCKING_MANDATE_HARD_CAP


def test_blocked_settlement_leaves_the_commitment_untouched():
    """PRD §2.5: "Nothing above the rung that failed is re-checked after the
    fact, and a rung that passes never re-raises."
    PRD §3.5: "Settling moves `CORE_PENDING` back to `ORDER_READY`; it requires a `credit_balance_cents` of at least the final stocking variant multiplied by 100 and accepts a supplied `credit_settlement_cents` which increases `credit_balance_cents`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_outranks_stocking_mandate_hard_cap
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    api_client.settle_commitment_core_credit(
        commitment["id"], {"credit_settlement_cents": 6200}, parts_manager_headers())

    after = get_commitment(commitment["id"])
    assert after["status"] == "ORDER_READY"
    assert after["credit_balance_cents"] == 0


def test_batch_cancel_from_cancelled_is_refused():
    """PRD §3.5: "Its `status` runs `OPEN`, `ORDERED`, `RECEIVED`, `CLOSED` or
    `CANCELLED`, and `CLOSED` and `CANCELLED` are terminal."
    PRD §3.5: "Cancelling an `OPEN` or `ORDERED` batch releases the batch's `reserved_units` back to `available_commitment_units` and recomputes the commitment's `committed_units`"

    Design: Corner/state_machines/parts_order_batch_cancel_from_cancelled_returns_invalid_state
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10)
    get_success_data(api_client.cancel_batch(batch["id"], parts_manager_headers()))
    assert get_batch(batch["id"])["status"] == "CANCELLED"

    resp = api_client.cancel_batch(batch["id"], parts_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    assert get_batch(batch["id"])["status"] == "CANCELLED"


def test_cancelled_batch_release_is_not_applied_twice():
    """PRD §3.5: "Cancelling an `OPEN` or `ORDERED` batch releases the batch's `reserved_units` back to `available_commitment_units` and recomputes the commitment's `committed_units`"
    PRD §3.5: "`available_commitment_units` is the larger of 0 and the final stocking variant minus `committed_units`"

    Design: Corner/state_machines/parts_order_batch_cancel_from_cancelled_returns_invalid_state
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10)
    get_success_data(api_client.cancel_batch(batch["id"], parts_manager_headers()))
    api_client.cancel_batch(batch["id"], parts_manager_headers())

    after = get_commitment(commitment["id"])
    assert after["committed_units"] == 0
    assert after["available_commitment_units"] == after["required_stocking_units_final"]


def test_service_order_resolve_after_resolved_is_idempotent():
    """PRD §3.10: "An order in `OPEN` or in `FILLED` can be resolved explicitly
    by a supervisor, stamping `resolved_at` with the server timestamp; a second
    resolve of the same order is a no-op, keeping the first stamp and reporting
    success."

    Design: Corner/state_machines/service_order_resolve_after_resolved_is_idempotent
    """
    dealer, _agreement, commitment = setup_commitment_order_ready()
    order = create_service_order(dealer, commitment, kind="SLA_AUDIT",
                                 sla_hours=12.0)
    first = validate_success(api_client.resolve_service_order(
        order["id"], technician_supervisor_headers()))
    second = validate_success(api_client.resolve_service_order(
        order["id"], technician_supervisor_headers()))

    assert first["status"] == "RESOLVED"
    assert second["resolved_at"] == first["resolved_at"]


def test_credit_already_applied_blocks_the_core_credit_suspension():
    """PRD §3.5: "Moving `ORDER_READY` to `CORE_PENDING` requires `credit_balance_cents` to be exactly 0 — a non-zero balance is refused with `ERR_CREDIT_ALREADY_APPLIED` at HTTP 409"
    PRD §2.5: "The commitment's `credit_balance_cents` is increased by exactly the batch's `core_units` multiplied by the credited settlement units increment — never by a repriced figure — whenever `core_units` is at least 1."

    Design: Corner/errors/credit_already_applied_blocks_the_core_credit_suspension
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10, core_units=2)
    place_batch_order(batch["id"])
    receive_batch(batch["id"], ordered_ref="OEM-ORD-9201")

    balance = get_commitment(commitment["id"])["credit_balance_cents"]
    assert balance > 0

    resp = api_client.suspend_commitment_core_credit(
        commitment["id"], parts_manager_headers())
    validate_error(resp, ApiErrorId.ERR_CREDIT_ALREADY_APPLIED, expected_status=409)


def test_blocked_core_credit_suspension_leaves_the_commitment_healthy():
    """PRD §3.5: "It sets `core_return_required` to true on every `OPEN` batch of the commitment, clears the owning agreement's `trusted_commitment` to false when no other commitment of that agreement remains `ORDER_READY`, recomputes `Dealer.trusted_commitment_count`, deactivates the default deferred shortage rule, and moves every service order of this commitment that is `OPEN` or `IN_PROGRESS` to `ESCALATED`."
    PRD §3.5: "a non-zero balance is refused with `ERR_CREDIT_ALREADY_APPLIED` at HTTP 409"

    Design: Corner/errors/credit_already_applied_blocks_the_core_credit_suspension
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10, core_units=2)
    place_batch_order(batch["id"])
    receive_batch(batch["id"], ordered_ref="OEM-ORD-9201")
    api_client.suspend_commitment_core_credit(commitment["id"], parts_manager_headers())

    after = get_commitment(commitment["id"])
    assert after["status"] == "ORDER_READY"

    escalated = get_success_data(api_client.list_service_orders(
        parts_manager_headers(),
        params={"commitment_id": commitment["id"], "status": "ESCALATED"}))
    assert escalated == []


def test_commitment_read_reports_derived_fill_and_availability():
    """PRD §3.4: "`available_commitment_units` is the larger of 0 and the final stocking variant minus `committed_units`"
    PRD §3.5: "Placing the order recomputes the commitment's `committed_units` and `fill_rate_pct`, and — when the commitment is not emergency and `available_commitment_units` is 0 — caps the batch's `reserved_units` to the floor of `available_commitment_units` divided by two, without confirming the allocation."

    Design: Corner/endpoints/parts_commitment_summary_read_reports_derived_fields
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10)
    place_batch_order(batch["id"])

    data = get_commitment(commitment["id"])
    assert data["committed_units"] == 10
    assert data["available_commitment_units"] == 53
    assert data["fulfilled_units"] == 0
    assert data["fill_rate_pct"] == 0.0


def test_commitment_read_moves_with_a_receipt():
    """PRD §3.5: "Receipt then recomputes `fill_rate_pct`, `committed_units` and `Dealer.open_backorder_units`"
    PRD §3.4: "`available_commitment_units` is the larger of 0 and the final
    stocking variant minus `committed_units`, recomputed whenever either
    `required_stocking_units_final` or `committed_units` changes."

    Design: Corner/endpoints/parts_commitment_summary_read_reports_derived_fields
    """
    _dealer, _agreement, commitment = setup_commitment_order_ready()
    batch = create_batch(commitment, requested_units=10)
    place_batch_order(batch["id"])
    receive_batch(batch["id"], ordered_ref="OEM-ORD-9101")

    data = get_commitment(commitment["id"])
    assert data["fulfilled_units"] == 10
    assert data["fill_rate_pct"] == 100.0
    assert data["committed_units"] == 0
    assert data["available_commitment_units"] == 63