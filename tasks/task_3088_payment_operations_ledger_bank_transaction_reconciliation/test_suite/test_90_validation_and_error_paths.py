"""Queue B (corner design), sections ``validations``, ``endpoints`` and ``errors``.

Validation preconditions and priorities, computed reads, conditional actions and
the violation-to-error mappings.
"""
import uuid

import pytest

from test_helpers import (
    ANALYST,
    APPROVER,
    CONTROLLER,
    INITIATOR,
    TEST_USERS,
    UNKNOWN_ID,
    api_client,
    approve_order,
    close_period,
    create_bank_account,
    create_ledger,
    create_manual_entry,
    create_order,
    dispatch_order,
    first_exception,
    get_success_data,
    ledger_scenario,
    ledger_summary,
    list_payment_orders,
    list_transactions,
    mark_entry_settled,
    post_entry,
    reconcile,
    statement_scenario,
    validate_error,
    validate_success,
)

OPS_APPROVER_HEADERS = TEST_USERS["payment_ops_approver_headers"]


def test_dispatch_without_prior_approval_violates_the_state_precondition():
    """PRD §3.5: "An `APPROVED` order is pushed onto its rail by a
    `PaymentApprover`."
    PRD §3.5: "The state gate precedes all of these".

    Design: Corner/validations/dispatch_without_prior_approval_violates_the_state_precondition
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=2_200)
    assert order["status"] == "PENDING_APPROVAL"

    res = api_client.dispatch_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]}, APPROVER)
    validate_error(res, "ERR_INVALID_TRANSITION")
    assert res.status_code == 409

    after = get_success_data(api_client.get_payment_order(order["id"], ANALYST))
    assert after["status"] == "PENDING_APPROVAL"


def test_dispatch_without_prior_approval_books_no_ledger_legs():
    """PRD §3.5: "every branch creates the same trio of consequences" — the trio
    is created only on a successful dispatch.

    Design: Corner/validations/dispatch_without_prior_approval_violates_the_state_precondition
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="ACH", direction="CREDIT", amount_cents=2_200)
    api_client.dispatch_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]}, APPROVER)

    rows = list_transactions(scenario["ledger"]["id"])
    assert rows == [], f"a refused dispatch must book no legs, got {len(rows)}"


def test_active_counterparty_satisfies_the_posture_check():
    """PRD §3.5: "The counterparty check requires `Counterparty.status` to be
    exactly `ACTIVE`."

    Design: Corner/validations/active_counterparty_satisfies_the_posture_check
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=400_000)
    res = api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]}, APPROVER)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"
    assert approved["approver_user_id"] == APPROVER["X-User-ID"]
    assert approved["approver_user_id"] != approved["initiator_user_id"]


def test_the_posture_rule_is_a_gate_not_an_unconditional_refusal():
    """PRD §3.5: "The counterparty check requires `Counterparty.status` to be
    exactly `ACTIVE`."

    Design: Corner/validations/active_counterparty_satisfies_the_posture_check
    """
    scenario = ledger_scenario()
    order = create_order(scenario, rail="WIRE", direction="CREDIT", amount_cents=400_000)
    api_client.block_counterparty(scenario["counterparty"]["id"], APPROVER)

    res = api_client.approve_payment_order(
        order["id"], {"expected_payment_order_version": order["version"]}, APPROVER)
    validate_error(res, "ERR_COUNTERPARTY_BLOCKED")


def test_role_check_precedes_not_found_on_a_single_role_endpoint():
    """PRD §2.10: "Third, on the endpoints whose authorized-role list contains
    exactly one role, the caller's role must be that role before any further
    check runs, else `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §2.1: "Several endpoints are single-role by design, and for those the
    role check runs before any other check."

    Design: Corner/validations/role_check_precedes_not_found_on_a_single_role_endpoint
    """
    ledger = create_ledger(name="Priority Ledger")
    res = api_client.close_period(
        UNKNOWN_ID,
        {"expected_ledger_version": ledger["version"] - 1,
         "force_resolve_exceptions": False},
        ANALYST)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")
    assert res.status_code == 403


def test_the_controller_still_reaches_the_not_found_check_on_the_same_path():
    """PRD §2.10: "Fourth, referenced resources must exist, and existence is
    validated left to right in the request-body order declared for the endpoint,
    with the ledger segment of a path validated before the resource segment
    beneath it."
    PRD §2.10: "a missing ledger as `ERR_LEDGER_NOT_FOUND`".

    Design: Corner/validations/role_check_precedes_not_found_on_a_single_role_endpoint
    """
    ledger = create_ledger(name="Priority Ledger")
    res = api_client.close_period(
        UNKNOWN_ID,
        {"expected_ledger_version": ledger["version"] - 1,
         "force_resolve_exceptions": False},
        CONTROLLER)
    validate_error(res, "ERR_LEDGER_NOT_FOUND")
    assert res.status_code == 404


def test_ledger_close_is_blocked_while_an_exception_is_still_open():
    """PRD §3.9: "if any exception on the ledger is still `OPEN`, `ASSIGNED` or
    `ESCALATED`, the command is refused with `ERR_CLOSE_BLOCKED_BY_EXCEPTION` and
    HTTP 409".

    Design: Corner/validations/ledger_close_is_blocked_while_an_exception_is_still_open
    """
    scenario = unmatched_deposit_ledger_scenario()
    current_version = get_success_data(
        api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))["version"]
    res = api_client.close_period(
        scenario["ledger"]["id"],
        {"expected_ledger_version": current_version,
         "force_resolve_exceptions": False},
        CONTROLLER)
    validate_error(res, "ERR_CLOSE_BLOCKED_BY_EXCEPTION")
    assert res.status_code == 409

    ledger = get_success_data(api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))
    assert ledger["period_index"] == 1


def test_force_resolving_exceptions_lets_the_period_advance():
    """PRD §3.9: "unless the caller supplied `force_resolve_exceptions` as true,
    in which case the close proceeds anyway and the unresolved items simply keep
    their status".

    Design: Corner/validations/ledger_close_is_blocked_while_an_exception_is_still_open
    """
    scenario = unmatched_deposit_ledger_scenario()
    advanced = close_period(scenario["ledger"]["id"], force_resolve=True)
    assert advanced["period_index"] == 2, (
        f"expected the period to advance to 2, got {advanced['period_index']}"
    )


def test_ledger_summary_reports_both_balances_and_the_open_exception_count():
    """PRD §3.6: "the summary response reports the `ledger_id`, the
    `provisional_pending_cents` figure, the `posted_balance_cents` figure, the
    `opened_exception_count` of exceptions still open on the ledger, and the
    current `period_index`."

    Design: Corner/endpoints/ledger_summary_reports_both_balances_and_the_open_exception_count
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    entry = create_manual_entry(
        ledger_id, entry_type="DEPOSIT", direction="CREDIT", amount_cents=125_000,
        value_effective_utc="2026-09-01T09:00:00Z")
    post_entry(entry["id"])
    mark_entry_settled(entry["id"])

    summary = ledger_summary(ledger_id, settled=True)
    assert summary["ledger_id"] == ledger_id
    assert summary["posted_balance_cents"] == 125_000
    assert summary["opened_exception_count"] == 0
    assert summary["period_index"] == 1


def test_the_settled_flag_changes_which_projection_the_summary_reports():
    """PRD §3.6: "That view answers with the provisional variant unless the
    request carries a `settled` query parameter whose value is true, in which
    case it answers with the final variant".

    Design: Corner/endpoints/ledger_summary_reports_both_balances_and_the_open_exception_count
    """
    scenario = ledger_scenario()
    ledger_id = scenario["ledger"]["id"]
    entry = create_manual_entry(
        ledger_id, entry_type="DEPOSIT", direction="CREDIT", amount_cents=125_000,
        value_effective_utc="2026-09-01T09:00:00Z")
    post_entry(entry["id"])
    mark_entry_settled(entry["id"])

    provisional = ledger_summary(ledger_id, settled=False)
    final = ledger_summary(ledger_id, settled=True)
    assert provisional["provisional_pending_cents"] == 0
    assert final["posted_balance_cents"] == 125_000


def test_relationship_create_rejects_a_self_pair():
    """PRD §2.8: "Each row names a `legal_entity_id` on one side — the party that
    shares its account data — and a `partner_legal_entity_id` on the other; the
    two must differ, so a self-relationship is rejected."
    PRD §2.10: "A malformed request ... is rejected with `ERR_INVALID_REQUEST` and
    HTTP 400."

    Design: Corner/endpoints/relationship_create_rejects_a_self_pair
    """
    scenario = ledger_scenario(with_partner=True)
    res = api_client.create_relationship(
        {"legal_entity_id": scenario["entity"]["id"],
         "partner_legal_entity_id": scenario["entity"]["id"],
         "purpose": "PAYMENT_RAIL_AGREEMENT", "account_data_sharing": False},
        APPROVER)
    validate_error(res, "ERR_INVALID_REQUEST")
    assert res.status_code == 400


def test_a_genuine_institution_pair_is_accepted_in_pending():
    """PRD §3.2: "Institution-to-institution relationships are requested by a
    `PaymentApprover`, a `PaymentInitiator` or a `PlatformAdmin` and are born at
    `PENDING`."

    Design: Corner/endpoints/relationship_create_rejects_a_self_pair
    """
    scenario = ledger_scenario(with_partner=True)
    res = api_client.create_relationship(
        {"legal_entity_id": scenario["entity"]["id"],
         "partner_legal_entity_id": scenario["entity2"]["id"],
         "purpose": "PAYMENT_RAIL_AGREEMENT", "account_data_sharing": False},
        APPROVER)
    relationship = validate_success(res, 201)
    assert relationship["status"] == "PENDING"


def test_the_rejected_self_pair_creates_no_row():
    """PRD §3.2: "the two must differ, so a self-relationship is rejected".

    Design: Corner/endpoints/relationship_create_rejects_a_self_pair
    """
    scenario = ledger_scenario(with_partner=True)
    api_client.create_relationship(
        {"legal_entity_id": scenario["entity"]["id"],
         "partner_legal_entity_id": scenario["entity"]["id"],
         "purpose": "PAYMENT_RAIL_AGREEMENT", "account_data_sharing": False},
        APPROVER)
    rows = get_success_data(api_client.list_relationships(
        APPROVER, params={"legal_entity_id": scenario["entity"]["id"]}))
    assert rows == [], "the rejected call must create nothing"


def test_waive_is_a_conditional_action_gated_on_age_and_escalation():
    """PRD §3.8: "A waive requires the item's `aging_bucket` to be `AGING`,
    `ESCALATED` or `CRITICAL` — a `CURRENT` item cannot be waived, and the attempt
    is refused with `ERR_EXCEPTION_NOT_AGED` and HTTP 409".

    Design: Corner/endpoints/waive_is_a_conditional_action_gated_on_age_and_escalation
    """
    scenario = unmatched_deposit_ledger_scenario(amount_cents=66_000)
    item = scenario["exception"]
    assert item["aging_bucket"] == "CURRENT"

    res = api_client.waive_exception(
        item["id"], {"resolution_note": "attempted too early"}, OPS_APPROVER_HEADERS)
    validate_error(res, "ERR_EXCEPTION_NOT_AGED")
    assert res.status_code == 409


def test_waive_is_admitted_once_the_aging_pass_pushes_the_bucket_forward():
    """PRD §3.8: "Waiver is the senior approver's exit and it is available only
    to a `PaymentOpsApprover`."

    Design: Corner/endpoints/waive_is_a_conditional_action_gated_on_age_and_escalation
    """
    scenario = unmatched_deposit_ledger_scenario(amount_cents=66_000)
    item = scenario["exception"]
    api_client.set_current_utc("2026-09-03T00:00:00Z", CONTROLLER)
    reevaluated = get_success_data(api_client.reevaluate_exception_aging(item["id"], ANALYST))
    assert reevaluated["aging_bucket"] == "AGING", (
        f"two business days should read AGING, got {reevaluated['aging_bucket']}"
    )

    res = api_client.waive_exception(
        item["id"], {"resolution_note": "aging justified the waiver"},
        OPS_APPROVER_HEADERS)
    waived = validate_success(res, 200)
    assert waived["status"] == "WAIVED"


def test_waive_is_exclusive_to_the_senior_operations_approver():
    """PRD §2.1: "An ... exception waiver are all refused with
    `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403) when presented by any other role,
    regardless of how valid the rest of the payload is."

    Design: Corner/endpoints/waive_is_a_conditional_action_gated_on_age_and_escalation
    """
    scenario = unmatched_deposit_ledger_scenario(amount_cents=66_000)
    item = scenario["exception"]
    api_client.set_current_utc("2026-09-03T00:00:00Z", CONTROLLER)
    get_success_data(api_client.reevaluate_exception_aging(item["id"], ANALYST))

    res = api_client.waive_exception(
        item["id"], {"resolution_note": "not my call"}, ANALYST)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")
    assert res.status_code == 403


def test_check_dispatch_is_refused_when_the_settlement_pool_cannot_cover_amount_plus_fee():
    """PRD §3.5: "for the `CHECK` rail the source account's
    `available_funds_cents` must be at least the order amount plus its fee;
    breaching either is reported as `ERR_SETTLEMENT_POOL_INSUFFICIENT` with HTTP
    409."

    Design: Corner/errors/check_dispatch_is_refused_when_the_settlement_pool_cannot_cover_amount_plus_fee
    """
    scenario = check_scenario(available_funds_cents=4_900_000)
    order = create_check_order(scenario)
    approved = approve_order(order)
    res = api_client.dispatch_payment_order(
        approved["id"], {"expected_payment_order_version": approved["version"]}, APPROVER)
    validate_error(res, "ERR_SETTLEMENT_POOL_INSUFFICIENT")
    assert res.status_code == 409


def test_check_dispatch_succeeds_when_the_account_covers_amount_plus_fee():
    """PRD §3.5: "for the `CHECK` rail the source account's
    `available_funds_cents` must be at least the order amount plus its fee".

    Design: Corner/errors/check_dispatch_is_refused_when_the_settlement_pool_cannot_cover_amount_plus_fee
    """
    scenario = check_scenario(available_funds_cents=5_000_000)
    order = create_check_order(scenario)
    approved = approve_order(order)
    dispatched = dispatch_order(approved)
    assert dispatched["status"] == "CHECK_DISPATCHED"

    legs = list_transactions(scenario["ledger"]["id"],
                             payment_order_id=dispatched["id"])
    assert len(legs) == 2, f"a successful dispatch books exactly two legs, got {len(legs)}"


def test_the_fiscal_gate_is_evaluated_before_any_posting():
    """PRD §3.5: "A separate fiscal precondition then applies ... breaching
    either is reported as `ERR_SETTLEMENT_POOL_INSUFFICIENT` with HTTP 409."

    Design: Corner/errors/check_dispatch_is_refused_when_the_settlement_pool_cannot_cover_amount_plus_fee
    """
    scenario = check_scenario(available_funds_cents=4_900_000)
    order = create_check_order(scenario)
    approved = approve_order(order)
    api_client.dispatch_payment_order(
        approved["id"], {"expected_payment_order_version": approved["version"]}, APPROVER)

    assert list_transactions(scenario["ledger"]["id"]) == []


def test_order_create_is_refused_when_no_open_calendar_cycle_exists():
    """PRD §3.4: "When no open calendar cell for the order's rail exists anywhere
    inside the four-day lookahead window, the draft cannot be created at all and
    is refused with `ERR_CALENDAR_HAS_NO_OPEN_CYCLE` and HTTP 409."

    Design: Corner/errors/order_create_is_refused_when_no_open_calendar_cycle_exists
    """
    scenario = closed_calendar_scenario()
    res = api_client.create_payment_order(
        order_payload_for(scenario), INITIATOR)
    validate_error(res, "ERR_CALENDAR_HAS_NO_OPEN_CYCLE")
    assert res.status_code == 409


def test_the_refused_create_creates_no_order_row():
    """PRD §3.4: "When no open calendar cell for the order's rail exists anywhere
    inside the four-day lookahead window, the draft cannot be created at all and
    is refused with `ERR_CALENDAR_HAS_NO_OPEN_CYCLE` and HTTP 409."

    Design: Corner/errors/order_create_is_refused_when_no_open_calendar_cycle_exists
    """
    scenario = closed_calendar_scenario()
    api_client.create_payment_order(order_payload_for(scenario), INITIATOR)
    rows = list_payment_orders(scenario["ledger"]["id"])
    assert rows == [], "no order row may be created"


def test_publishing_an_open_cell_makes_the_identical_create_succeed():
    """PRD §3.4: "Institutions manage their own calendars through cell
    publication: a `LedgerController`, `PlatformAdmin` or `PaymentApprover`
    publishes a cell carrying its `legal_entity_id`, `calendar_date`, `timezone`,
    `is_open` flag, `cutoffs` array and `allowed_rails` set".

    Design: Corner/errors/order_create_is_refused_when_no_open_calendar_cycle_exists
    """
    scenario = closed_calendar_scenario()
    from test_helpers import publish_calendar_cell
    # An open cycle needs a consecutive open pair: the order opens after the
    # 14:00 cutoff, so its eligible moment is the NEXT open cell's cutoff.
    for date in WINDOW_END_DATES:
        publish_calendar_cell(
            scenario["entity"]["id"], date, is_open=True,
            cutoffs=[{"rail": "ACH", "cutoff_local_time": "14:00:00"}],
            allowed_rails=["ACH"])

    res = api_client.create_payment_order(order_payload_for(scenario), INITIATOR)
    order = validate_success(res, 201)
    assert order["cutoff_snapshot_utc"] is not None


# ─── Local helpers ────────────────────────────────────

def unmatched_deposit_ledger_scenario(amount_cents=52_000):
    """A ledger carrying one OPEN UNMATCHED_DEPOSIT raised by an unmatched line."""
    scenario = statement_scenario(
        institution_ref="STMT-K",
        lines=[{"bank_reference": "STMT-K-L0", "amount_cents": amount_cents,
                "direction": "CREDIT", "effective_at": "2026-09-01T10:00:00Z"}])
    scenario["statement"] = reconcile(scenario["statement"])
    scenario["exception"] = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    return scenario


def check_scenario(available_funds_cents):
    """A CHECK-only institution, account and calendar cell.

    PRD §2.9 states `is_open` false as a fact about the date ("the institution
    does not process payments that date"), not as a relaxation of the cell's own
    declared payload: a cell still names its `cutoffs` and its non-empty
    `allowed_rails` subset.  Publishing the closed cells of the window
    explicitly is what makes the four-calendar-day lookahead in §3.4
    deterministic.
    """
    scenario = ledger_scenario(calendar_rails=("CHECK",), publish_calendar_cells=False)
    from test_helpers import publish_calendar_cell
    check_cutoffs = [{"rail": "CHECK", "cutoff_local_time": "11:00:00"}]
    for date in ("2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"):
        publish_calendar_cell(
            scenario["entity"]["id"], date, is_open=True,
            cutoffs=check_cutoffs, allowed_rails=["CHECK"])
    for date in ("2026-09-05", "2026-09-06", "2026-09-07"):
        publish_calendar_cell(
            scenario["entity"]["id"], date, is_open=False,
            cutoffs=check_cutoffs, allowed_rails=["CHECK"])
    scenario["account"] = create_bank_account(
        scenario["entity"]["id"], supported_rails=["CHECK"],
        available_funds_cents=available_funds_cents)
    scenario["account_v"] = scenario["account"]["version"]
    return scenario


def create_check_order(scenario):
    return create_order(scenario, rail="CHECK", direction="DEBIT",
                        amount_cents=4_900_000, payable_to_name="First Meridian")


def closed_calendar_scenario():
    """Four consecutive closed cells and no open one inside the lookahead window.

    PRD §3.4 opens the window at "the local date of the order's opening instant".
    The logical clock's startup default is 2026-09-01T00:00:00Z, which is
    2026-08-31 20:00 in America/New_York, so the four-cell window these tests
    close is 2026-08-31 through 2026-09-03 and the following date is left
    unpublishable-by-default rather than implicitly open.
    """
    scenario = ledger_scenario(calendar_rails=("ACH",), publish_calendar_cells=False)
    from test_helpers import publish_calendar_cell
    ach = [{"rail": "ACH", "cutoff_local_time": "14:00:00"}]
    for date in CLOSED_WINDOW_DATES:
        publish_calendar_cell(
            scenario["entity"]["id"], date, is_open=False,
            cutoffs=ach, allowed_rails=["ACH"])
    scenario["account"] = create_bank_account(
        scenario["entity"]["id"], supported_rails=["ACH"], available_funds_cents=4_000_000)
    scenario["account_v"] = scenario["account"]["version"]
    return scenario


# The local-date window the startup logical clock opens (PRD §3.4).
CLOSED_WINDOW_DATES = ("2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03")
# Two further dates inside that window, unpublished by the scenario above.
WINDOW_END_DATES = ("2026-09-04", "2026-09-05")


def order_payload_for(scenario):
    return {
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": scenario["counterparty"]["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "ACH", "direction": "CREDIT", "amount_cents": 1_000,
        "idempotency_key": unique_idempotency_key("idem-closed-calendar"),
        "payable_to_name": "Quiet Co",
    }


def unique_idempotency_key(prefix):
    """A fresh draft key.

    PRD §3.10 imposes two independent duplicate guards, and the second is a
    content fingerprint over legal_entity_id / counterparty_id / rail /
    direction / amount_cents that is blind to the caller.  The calendar
    scenarios below issue the identical create twice — once refused, once
    accepted after an open cell is published — so each attempt needs its own
    key; a re-used literal would be refused for the wrong reason and the
    scenario would prove nothing about the calendar.
    """
    return "%s-%s" % (prefix, uuid.uuid4().hex[:8])