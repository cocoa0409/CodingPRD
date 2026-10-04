"""Queue A (difficulty design), rules non_linear_state_machine,
transitive_cascade and priority_pair_validation_conflict.

These are the multi-dimensional state machines: the Transaction's two
independent axes, the BankStatement revision cycle, the three-hop return
cascade, and the two validation-priority pairs.
"""
import pytest

from test_helpers import (
    ANALYST,
    APPROVER,
    CONTROLLER,
    INITIATOR_USER_ID,
    api_client,
    approve_order,
    close_period,
    create_manual_entry,
    create_order,
    create_relationship,
    dispatched_order_scenario,
    get_success_data,
    headers_for,
    ledger_scenario,
    ledger_version,
    list_exceptions,
    list_transactions,
    post_entry,
    statement_discrepancy_scenario,
    revise_statement,
    mark_in_flight,
    dispatch_order,
    reconcile,
    validate_error,
    validate_success,
)

# The scenario ledger is created with the logical clock at its startup default,
# so its books open on 2026-09-01 and the first close runs on that date.
DAY_OF_CLOSE = "2026-09-01T09:00:00Z"


def _activate(relationship):
    # PRD §2.7: activation requires `expected_relationship_version` matching the
    # relationship's current version, so the value must be re-read from the
    # relationship rather than carried over from an earlier response that the
    # earlier creation call has already consumed.
    current = get_success_data(
        api_client.get_relationship(relationship["id"], APPROVER))
    return get_success_data(api_client.activate_relationship(
        relationship["id"], {"expected_relationship_version": current["version"]},
        APPROVER))


# ─── Transaction: two independent axes ────────────────

def test_void_leaves_the_settlement_axis_untouched():
    """PRD §3.6: "Because the two dimensions are genuinely independent, a
    reversal of a not-yet-settled entry changes only one of them."
    PRD §3.6: "A void sets the row's `lifecycle_status` to `VOID`, recomputes
    the ledger's `pending_balance_cents` with the row contributing zero".

    Design: Difficulty/non_linear_state_machine/transaction_lifecycle_axis_voids_while_settlement_axis_stays_unsettled
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="DEBIT", amount_cents=7_500,
        value_effective_utc="2026-09-01T11:00:00Z")
    post_entry(entry["id"])

    version = ledger_version(ledger_id)
    voided = get_success_data(api_client.void_transaction(
        entry["id"], {"expected_ledger_version": version}, CONTROLLER))

    assert voided["lifecycle_status"] == "VOID", (
        f"expected VOID, got {voided['lifecycle_status']}"
    )
    assert voided["settlement_status"] == "UNSETTLED", (
        f"the settlement axis must be untouched, got {voided['settlement_status']}"
    )


def test_voided_row_is_excluded_from_the_pending_projection_entirely():
    """PRD §3.6: "Rows whose `lifecycle_status` is `VOID` or `REJECTED`
    contribute zero to both sums."

    Design: Difficulty/non_linear_state_machine/transaction_lifecycle_axis_voids_while_settlement_axis_stays_unsettled
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="DEBIT", amount_cents=7_500,
        value_effective_utc="2026-09-01T11:00:00Z")
    post_entry(entry["id"])
    version = ledger_version(ledger_id)
    api_client.void_transaction(entry["id"], {"expected_ledger_version": version}, CONTROLLER)

    ledger = get_success_data(api_client.get_ledger(ledger_id, CONTROLLER))
    assert ledger["pending_balance_cents"] == 0, (
        f"the voided row must contribute nothing, got {ledger['pending_balance_cents']}"
    )


def test_void_is_refused_once_the_settlement_axis_is_in_settlement():
    """PRD §3.6: "A void requires the row to be `POSTED`, requires its
    settlement axis to be `UNSETTLED` so that an already-settled entry cannot be
    erased".
    PRD §2.10: "A request that is legal on a transaction's lifecycle axis but
    illegal on its settlement axis is rejected with `ERR_INVALID_SETTLEMENT_AXIS`
    and HTTP 409".

    Design: Difficulty/non_linear_state_machine/transaction_lifecycle_axis_voids_while_settlement_axis_stays_unsettled
    """
    scenario = dispatched_order_scenario(rail="WIRE", direction="CREDIT", amount_cents=300_000)
    ledger_id = scenario["ledger"]["id"]
    originating = [t for t in list_transactions(ledger_id, entry_type="ORIGINATING")][0]
    assert originating["settlement_status"] == "IN_SETTLEMENT"
    post_entry(originating["id"])

    version = ledger_version(ledger_id)
    res = api_client.void_transaction(
        originating["id"], {"expected_ledger_version": version}, CONTROLLER)
    validate_error(res, "ERR_INVALID_SETTLEMENT_AXIS")


# ─── BankStatement revision cycle ─────────────────────

def test_discrepancy_is_not_reconciled_when_the_variance_is_non_zero():
    """PRD §3.7: "when `unmatched_amount_cents` is anything other than zero the
    statement becomes `DISCREPANCY` and an `ExceptionItem` of kind
    `STATEMENT_VARIANCE` is raised against it in status `OPEN`".

    Design: Difficulty/non_linear_state_machine/bank_statement_revision_cycle_reenters_reconciling
    """
    scenario = statement_discrepancy_scenario(amount_cents=750_000)
    statement = scenario["statement"]
    assert statement["status"] == "DISCREPANCY", (
        f"expected DISCREPANCY, got {statement['status']}"
    )
    assert statement["unmatched_amount_cents"] != 0


def test_revision_creates_the_next_revision_and_supersedes_the_predecessor():
    """PRD §3.7: "a new `BankStatement` row is created directly in status
    `REVISED` with `revision_number` equal to the predecessor's
    `revision_number` plus one and `supersedes_statement_id` set to the
    predecessor's id".

    Design: Difficulty/non_linear_state_machine/bank_statement_revision_cycle_reenters_reconciling
    """
    scenario = statement_discrepancy_scenario(amount_cents=750_000, institution_ref="STMT-C")
    predecessor = scenario["statement"]
    successor = revise_statement(predecessor, institution_ref="STMT-C-REV",
                                 closing_balance_cents=750_000)

    assert successor["revision_number"] == 2, (
        f"expected revision_number 2, got {successor['revision_number']}"
    )
    assert successor["supersedes_statement_id"] == predecessor["id"], (
        "the successor must name its predecessor in supersedes_statement_id"
    )
    assert successor["status"] == "REVISED", (
        f"a successor is born REVISED, got {successor['status']}"
    )


def test_successor_re_enters_reconciling_closing_the_cycle():
    """PRD §3.7: "Because the successor is born in `REVISED` and re-enters the
    loop, a statement may be revised any number of times before it stabilises at
    `RECONCILED`."

    Design: Difficulty/non_linear_state_machine/bank_statement_revision_cycle_reenters_reconciling
    """
    scenario = statement_discrepancy_scenario(amount_cents=750_000, institution_ref="STMT-C")
    predecessor = scenario["statement"]
    successor = revise_statement(predecessor, institution_ref="STMT-C-REV",
                                 closing_balance_cents=750_000)

    reentered = reconcile(successor)
    assert reentered["status"] in ("RECONCILING", "RECONCILED", "DISCREPANCY"), (
        f"the successor must re-enter the lifecycle, got {reentered['status']}"
    )

    refreshed = get_success_data(api_client.get_statement(predecessor["id"], ANALYST))
    assert refreshed["status"] == "SUPERSEDED", (
        f"the predecessor must read SUPERSEDED, got {refreshed['status']}"
    )


# ─── Return cascade ───────────────────────────────────

def _relationship_scenario(**overrides):
    scenario = ledger_scenario(with_partner=True, **overrides)
    relationship = create_relationship(
        scenario["entity"]["id"], scenario["entity2"]["id"],
        purpose="ACCOUNT_SHARING", account_data_sharing=True)
    scenario["relationship"] = _activate(relationship)
    return scenario


def test_return_restricts_the_counterparty_above_the_threshold():
    """PRD §3.5: "When the returned `amount_cents` is at or above 100000 cents,
    the linked counterparty is moved `ACTIVE` → `RESTRICTED`".

    Design: Difficulty/transitive_cascade/return_suspends_relationship_via_counterparty_restriction
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=250_000)
    order = approve_order(order)
    dispatch_order(order)
    in_flight = mark_in_flight(order)
    returned = get_success_data(api_client.return_payment_order(
        in_flight["id"], {"return_reason": "R01",
                          "expected_payment_order_version": in_flight["version"]}, ANALYST))

    assert returned["status"] == "RETURNED", f"expected RETURNED, got {returned['status']}"
    counterparty = get_success_data(
        api_client.get_counterparty(scenario["counterparty"]["id"], APPROVER))
    assert counterparty["status"] == "RESTRICTED", (
        f"a 250000-cent return clears the threshold, got {counterparty['status']}"
    )


def test_counterparty_restriction_suspends_an_account_sharing_relationship():
    """PRD §3.5: "that posture change in turn suspends every one of its `ACTIVE`
    `ACCOUNT_SHARING` relationships".

    Design: Difficulty/transitive_cascade/return_suspends_relationship_via_counterparty_restriction
    """
    scenario = _relationship_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=250_000)
    order = approve_order(order)
    dispatch_order(order)
    in_flight = mark_in_flight(order)
    api_client.return_payment_order(
        in_flight["id"], {"return_reason": "R01",
                          "expected_payment_order_version": in_flight["version"]}, ANALYST)

    relationship = get_success_data(
        api_client.get_relationship(scenario["relationship"]["id"], APPROVER))
    assert relationship["status"] == "SUSPENDED", (
        f"the ACTIVE account-sharing relationship must be suspended, "
        f"got {relationship['status']}"
    )


def test_return_below_the_threshold_leaves_posture_and_relationship_untouched():
    """PRD §3.5: "When the returned `amount_cents` is at or above 100000 cents,
    the linked counterparty is moved `ACTIVE` → `RESTRICTED`".

    Design: Difficulty/transitive_cascade/return_suspends_relationship_via_counterparty_restriction
    """
    scenario = _relationship_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=50_000)
    order = approve_order(order)
    dispatch_order(order)
    in_flight = mark_in_flight(order)
    api_client.return_payment_order(
        in_flight["id"], {"return_reason": "R01",
                          "expected_payment_order_version": in_flight["version"]}, ANALYST)

    counterparty = get_success_data(
        api_client.get_counterparty(scenario["counterparty"]["id"], APPROVER))
    relationship = get_success_data(
        api_client.get_relationship(scenario["relationship"]["id"], APPROVER))
    assert counterparty["status"] == "ACTIVE", (
        f"a 50000-cent return is below the threshold, got {counterparty['status']}"
    )
    assert relationship["status"] == "ACTIVE", (
        f"the relationship must be untouched, got {relationship['status']}"
    )


# ─── Revision second hop ──────────────────────────────

def test_revise_resolves_the_predecessor_statement_variance_exception():
    """PRD §3.7: "the predecessor's `STATEMENT_VARIANCE` exception is resolved
    with a resolution note recording that it was superseded by revision N plus
    one".

    Design: Difficulty/transitive_cascade/revision_second_hop_raises_unmatched_deposit_exception
    """
    scenario = statement_discrepancy_scenario(amount_cents=400_000, institution_ref="STMT-D")
    predecessor = scenario["statement"]
    revise_statement(predecessor, institution_ref="STMT-D-REV",
                     closing_balance_cents=400_000)

    variances = list_exceptions(scenario["ledger"]["id"], kind="STATEMENT_VARIANCE")
    assert len(variances) == 1
    assert variances[0]["status"] == "RESOLVED", (
        f"the superseded revision's variance must be resolved, got {variances[0]['status']}"
    )


def test_revise_second_hop_raises_an_unmatched_deposit_exception():
    """PRD §3.7: "deposit attribution is re-run over the predecessor's
    still-unmatched lines, and every line that still resolves to no destination
    raises an `UNMATCHED_DEPOSIT` exception whose `amount_cents` equals the
    line's amount".

    Design: Difficulty/transitive_cascade/revision_second_hop_raises_unmatched_deposit_exception
    """
    scenario = statement_discrepancy_scenario(amount_cents=400_000, institution_ref="STMT-D")
    predecessor = scenario["statement"]
    revise_statement(predecessor, institution_ref="STMT-D-REV",
                     closing_balance_cents=400_000)

    deposits = list_exceptions(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    assert len(deposits) == 1, f"expected exactly one UNMATCHED_DEPOSIT, got {len(deposits)}"
    assert deposits[0]["amount_cents"] == 400_000, (
        f"the raised deposit equals the line amount, got {deposits[0]['amount_cents']}"
    )


def test_no_statement_variance_remains_open_after_the_second_hop():
    """PRD §3.7: "the predecessor's `STATEMENT_VARIANCE` exception is resolved
    with a resolution note recording that it was superseded by revision N plus
    one".

    Design: Difficulty/transitive_cascade/revision_second_hop_raises_unmatched_deposit_exception
    """
    scenario = statement_discrepancy_scenario(amount_cents=400_000, institution_ref="STMT-D")
    revise_statement(scenario["statement"], institution_ref="STMT-D-REV",
                     closing_balance_cents=400_000)

    ledger_id = scenario["ledger"]["id"]
    open_variances = [e for e in list_exceptions(ledger_id, kind="STATEMENT_VARIANCE")
                      if e["status"] in ("OPEN", "ASSIGNED", "ESCALATED")]
    assert open_variances == [], f"expected no open variance, got {open_variances}"


# ─── Priority pair: posture before separateness ───────

def _order_awaiting_release(amount_cents=50_000):
    scenario = ledger_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=amount_cents)
    return scenario, order


def test_blocked_counterparty_is_reported_even_when_the_approver_is_the_initiator():
    """PRD §3.5: "Because the counterparty check precedes the separateness check,
    a counterparty that is not `ACTIVE` is reported as `ERR_COUNTERPARTY_BLOCKED`
    with HTTP 409 even when the approver would also fail the separateness rule".

    Design: Difficulty/priority_pair_validation_conflict/posture_constraint_outranks_separateness_on_approve
    """
    scenario, order = _order_awaiting_release()
    api_client.block_counterparty(scenario["counterparty"]["id"], APPROVER)

    # Same operator identity that drafted the order, presenting the release role.
    res = api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]},
        headers_for("PaymentApprover", INITIATOR_USER_ID))
    error = validate_error(res, "ERR_COUNTERPARTY_BLOCKED")
    assert res.status_code == 409
    assert error["error_id"] != "ERR_SELF_APPROVAL_FORBIDDEN"


def test_restoring_the_counterparty_surfaces_the_separateness_violation():
    """PRD §3.5: "`ERR_SELF_APPROVAL_FORBIDDEN` is reported only when no earlier
    business rule already rejected the release. It carries HTTP status 403."

    Design: Difficulty/priority_pair_validation_conflict/posture_constraint_outranks_separateness_on_approve
    """
    scenario, order = _order_awaiting_release()
    counterparty_id = scenario["counterparty"]["id"]
    api_client.block_counterparty(counterparty_id, APPROVER)
    api_client.unblock_counterparty(counterparty_id, APPROVER)
    get_success_data(api_client.restore_counterparty(counterparty_id, APPROVER))

    res = api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]},
        headers_for("PaymentApprover", INITIATOR_USER_ID))
    validate_error(res, "ERR_SELF_APPROVAL_FORBIDDEN")
    assert res.status_code == 403


def test_a_different_approver_releases_the_order_once_posture_is_restored():
    """PRD §3.5: "The separateness check requires that the `X-User-ID` of the
    approving operator differ from the order's `initiator_user_id`".

    Design: Difficulty/priority_pair_validation_conflict/posture_constraint_outranks_separateness_on_approve
    """
    scenario, order = _order_awaiting_release()
    counterparty_id = scenario["counterparty"]["id"]
    api_client.block_counterparty(counterparty_id, APPROVER)
    api_client.unblock_counterparty(counterparty_id, APPROVER)
    get_success_data(api_client.restore_counterparty(counterparty_id, APPROVER))

    res = api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]}, APPROVER)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"
    assert approved["approver_user_id"] != approved["initiator_user_id"]


# ─── Priority pair: finished state before closed period ──

def test_rejected_entry_reports_the_state_precondition_not_the_closed_period():
    """PRD §3.6: "It is refused with `ERR_INVALID_TRANSITION` and HTTP 409 when
    the entry is not `PENDING`".
    PRD §2.10: "Fifth comes the state gate, sixth the settlement-axis gate, and
    then the business checks".

    Design: Difficulty/priority_pair_validation_conflict/finished_state_precedes_closed_period_on_post
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    entry = _parked_entry(ledger_id)
    version = ledger_version(ledger_id)
    close_period(ledger_id, force_resolve=True, expected_version=version)

    res = api_client.post_transaction(entry["id"], ANALYST)
    error = validate_error(res, "ERR_INVALID_TRANSITION")
    assert res.status_code == 409
    assert error["error_id"] != "ERR_PERIOD_CLOSED"


def test_pending_entry_in_a_closed_period_reports_the_period_boundary():
    """PRD §3.6: "refused with `ERR_PERIOD_CLOSED` and HTTP 409 when the entry's
    `value_effective_utc` falls at or before the close instant of the ledger's
    `period_closed_through_index`".

    Design: Difficulty/priority_pair_validation_conflict/finished_state_precedes_closed_period_on_post
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    # An entry on the very date the period closes is inside the closed window
    # once the close has run, so it is the genuinely pending case.
    entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="DEBIT", amount_cents=1_250,
        value_effective_utc=DAY_OF_CLOSE)
    version = ledger_version(ledger_id)
    close_period(ledger_id, force_resolve=True, expected_version=version)

    res = api_client.post_transaction(entry["id"], ANALYST)
    validate_error(res, "ERR_PERIOD_CLOSED")


def _parked_entry(ledger_id):
    """A PENDING entry carrying the state 'POSTED' from an earlier choice.

    PRD §3.6's cascade pair needs an entry that is POSTED (so the state gate
    refuses the post) whose effective instant still precedes the close instant
    (so the closed-period rule would also apply).  Moving it to POSTED first is
    what makes the pair discriminate: a REJECTED entry would no longer be POSTED
    and would leave the state gate untested.
    """
    entry = create_manual_entry(
        ledger_id, entry_type="ADJUSTMENT", direction="DEBIT", amount_cents=1_250,
        value_effective_utc=DAY_OF_CLOSE)
    return post_entry(entry["id"])