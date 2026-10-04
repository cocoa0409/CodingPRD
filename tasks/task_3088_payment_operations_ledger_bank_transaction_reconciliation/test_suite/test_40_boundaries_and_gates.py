"""Queue A (difficulty design), rules boundary_precision_check,
cross_entity_state_dependency and resource_temporal_overlap.

Boundary precision (strict versus inclusive ceilings), cross-entity state gates,
and the temporal-overlap rules that sit on the statement cycle and the calendar.
"""
import pytest

from test_helpers import (
    ANALYST,
    APPROVER,
    CONTROLLER,
    INITIATOR,
    TEST_USERS,
    api_client,
    append_line,
    assign_exception,
    close_period,
    create_counterparty,
    create_relationship,
    create_statement_payload,
    first_exception,
    get_success_data,
    ledger_scenario,
    reconcile,
    refresh_account,
    resolve_exception,
    statement_scenario,
    unmatched_deposit_scenario,
    validate_error,
    validate_success,
)

OPS_APPROVER = TEST_USERS["payment_ops_approver_headers"]


# ─── Velocity limit: strict ceiling ───────────────────

def _limited_counterparty_scenario(limit_cents=10_000):
    scenario = ledger_scenario()
    counterparty = create_counterparty(
        scenario["entity"]["id"], display_name="Vector Freight", external_ref="VF-1",
        velocity_limit_cents=limit_cents)
    scenario["counterparty"] = counterparty
    return scenario


def test_amount_exactly_equal_to_the_limit_is_refused():
    """PRD §3.5: "An order is admitted only when its `amount_cents` is strictly
    less than that effective limit, so an order whose amount exactly equals the
    limit is refused with `ERR_VELOCITY_LIMIT_EXCEEDED` and HTTP 409".

    Design: Difficulty/boundary_precision_check/velocity_limit_strict_boundary_on_amount_cents
    """
    scenario = _limited_counterparty_scenario()
    payload = {
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": scenario["counterparty"]["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "ACH", "direction": "CREDIT", "amount_cents": 10_000,
        "idempotency_key": "idem-edge-at-limit", "payable_to_name": "Vector Freight",
    }
    res = api_client.create_payment_order(payload, INITIATOR)
    validate_error(res, "ERR_VELOCITY_LIMIT_EXCEEDED")
    assert res.status_code == 409


def test_amount_one_cent_below_the_limit_is_admitted():
    """PRD §3.5: "while an order one cent below the limit is admitted".

    Design: Difficulty/boundary_precision_check/velocity_limit_strict_boundary_on_amount_cents
    """
    scenario = _limited_counterparty_scenario()
    payload = {
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": scenario["counterparty"]["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "ACH", "direction": "CREDIT", "amount_cents": 9_999,
        "idempotency_key": "idem-edge-below-limit", "payable_to_name": "Vector Freight",
    }
    res = api_client.create_payment_order(payload, INITIATOR)
    order = validate_success(res, 201)
    assert order["status"] == "PENDING_APPROVAL", (
        f"9999 is below the 10000 limit, expected PENDING_APPROVAL, got {order['status']}"
    )


def test_the_counterpartys_own_limit_overrides_the_institution_default():
    """PRD §3.5: "The effective limit for an order is the counterparty's own
    `velocity_limit_cents` when that field is not null, and otherwise it is the
    counterparty's legal entity's `default_velocity_limit_cents`".

    Design: Difficulty/boundary_precision_check/velocity_limit_strict_boundary_on_amount_cents
    """
    scenario = _limited_counterparty_scenario()
    assert scenario["entity"]["default_velocity_limit_cents"] == 5_000_000
    counterparty = get_success_data(
        api_client.get_counterparty(scenario["counterparty"]["id"], APPROVER))
    assert counterparty["velocity_limit_cents"] == 10_000

    # 9999 would be admitted against the 5000000 default, so the 10000 rejection
    # above proves the counterparty's own field is the one in force.
    payload = {
        "legal_entity_id": scenario["entity"]["id"],
        "ledger_id": scenario["ledger"]["id"],
        "counterparty_id": scenario["counterparty"]["id"],
        "source_account_id": scenario["account"]["id"],
        "rail": "ACH", "direction": "CREDIT", "amount_cents": 10_000,
        "idempotency_key": "idem-edge-limit-again", "payable_to_name": "Vector Freight",
    }
    validate_error(api_client.create_payment_order(payload, INITIATOR),
                   "ERR_VELOCITY_LIMIT_EXCEEDED")


# ─── Sole-open virtual account cardinality ────────────

def test_two_open_virtual_accounts_leave_the_deposit_unattributed():
    """PRD §3.8: "Third, a sole-open fallback: exactly one virtual account of
    that bank account is `OPEN`."

    Design: Difficulty/boundary_precision_check/sole_open_virtual_account_cardinality_boundary
    """
    scenario = unmatched_deposit_scenario(
        amount_cents=100_000, institution_ref="STMT-F",
        virtual_accounts=[{"virtual_account_number": "9000000010", "reference_code": "DEPXAA"},
                          {"virtual_account_number": "9000000011", "reference_code": "DEPYBB"}],
    )
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    assert item["status"] == "OPEN", "two open virtual accounts means no fallback resolves"
    assert item["amount_cents"] == 100_000


def test_closing_down_to_one_open_virtual_account_resolves_the_fallback():
    """PRD §3.2: "a `CLOSED` virtual account is excluded from every branch of
    the attribution rule in §3.7".
    PRD §3.8: "Third, a sole-open fallback: exactly one virtual account of that
    bank account is `OPEN`."

    Design: Difficulty/boundary_precision_check/sole_open_virtual_account_cardinality_boundary
    """
    scenario = unmatched_deposit_scenario(
        amount_cents=100_000, institution_ref="STMT-F",
        virtual_accounts=[{"virtual_account_number": "9000000010", "reference_code": "DEPXAA"},
                          {"virtual_account_number": "9000000011", "reference_code": "DEPYBB"}],
    )
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    virtuals = get_success_data(
        api_client.list_virtual_accounts(ANALYST,
                                         params={"bank_account_id": scenario["account"]["id"]}))
    second = [v for v in virtuals if v["reference_code"] == "DEPYBB"][0]
    get_success_data(api_client.close_virtual_account(second["id"], ANALYST))

    reevaluated = get_success_data(
        api_client.reevaluate_exception_aging(item["id"], ANALYST))
    assert reevaluated["attributed_fee_cents"] == 1_000, (
        f"one open account now resolves, expected fee 1000, "
        f"got {reevaluated['attributed_fee_cents']}"
    )
    assert reevaluated["attributable_amount_cents"] == 99_000


def test_the_amount_is_not_the_discriminator_across_both_outcomes():
    """PRD §3.8: "Third, a sole-open fallback: exactly one virtual account of
    that bank account is `OPEN`."

    Design: Difficulty/boundary_precision_check/sole_open_virtual_account_cardinality_boundary
    """
    scenario = unmatched_deposit_scenario(
        amount_cents=100_000, institution_ref="STMT-F",
        virtual_accounts=[{"virtual_account_number": "9000000010", "reference_code": "DEPXAA"},
                          {"virtual_account_number": "9000000011", "reference_code": "DEPYBB"}],
    )
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    assert item["amount_cents"] == 100_000
    virtuals = get_success_data(
        api_client.list_virtual_accounts(ANALYST,
                                         params={"bank_account_id": scenario["account"]["id"]}))
    second = [v for v in virtuals if v["reference_code"] == "DEPYBB"][0]
    get_success_data(api_client.close_virtual_account(second["id"], ANALYST))
    reevaluated = get_success_data(
        api_client.reevaluate_exception_aging(item["id"], ANALYST))
    assert reevaluated["amount_cents"] == 100_000, (
        "the gross is unchanged across both outcomes; cardinality is the discriminator"
    )


def test_closing_a_virtual_account_does_not_re_credit_the_ledger():
    """PRD §3.8: "when a destination resolves, two computed fields are reported
    on the exception" — the fee and residual are reported on the exception, not
    as a ledger leg.

    Design: Difficulty/boundary_precision_check/sole_open_virtual_account_cardinality_boundary
    """
    scenario = unmatched_deposit_scenario(
        amount_cents=100_000, institution_ref="STMT-F",
        virtual_accounts=[{"virtual_account_number": "9000000010", "reference_code": "DEPXAA"},
                          {"virtual_account_number": "9000000011", "reference_code": "DEPYBB"}],
    )
    item = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    virtuals = get_success_data(
        api_client.list_virtual_accounts(ANALYST,
                                         params={"bank_account_id": scenario["account"]["id"]}))
    second = [v for v in virtuals if v["reference_code"] == "DEPYBB"][0]
    get_success_data(api_client.close_virtual_account(second["id"], ANALYST))
    api_client.reevaluate_exception_aging(item["id"], ANALYST)

    ledger = get_success_data(api_client.get_ledger(scenario["ledger"]["id"], CONTROLLER))
    assert ledger["pending_balance_cents"] == 0, (
        "reevaluation alone must not book a re-credit leg"
    )


# ─── Cross-entity: waiver gated by the ledger's closed period ──

def _aged_return_exception_scenario():
    """A RETURN exception opened 2026-09-01, aged into AGING, then assigned.

    The logical clock must move forward before the item is assigned: PRD §3.8
    derives `aging_bucket` from the business-day distance between `opened_utc`
    and the logical clock, so at the startup default the item is CURRENT and
    could never reach the AGING bucket these tests assert on.
    """
    from test_helpers import returned_order_scenario

    scenario = returned_order_scenario(rail="ACH", direction="CREDIT", amount_cents=50_000)
    exception = first_exception(scenario["ledger"]["id"], kind="RETURN")
    api_client.set_current_utc("2026-09-03T00:00:00Z", CONTROLLER)
    assign_exception(exception["id"])
    scenario["exception"] = get_success_data(api_client.get_exception(exception["id"], ANALYST))
    return scenario


def test_waiver_is_refused_after_the_period_containing_the_item_closed():
    """PRD §3.8: "it requires the item's `opened_utc` to be at or after the
    close instant of the ledger's `period_closed_through_index`, because a
    closed period's exception may not be waived retroactively; breaching that is
    reported as `ERR_PERIOD_CLOSED` with HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/exception_waiver_gated_by_ledger_closed_period
    """
    scenario = _aged_return_exception_scenario()
    close_period(scenario["ledger"]["id"], force_resolve=True)

    res = api_client.waive_exception(
        scenario["exception"]["id"],
        {"resolution_note": "attempted after the books closed"},
        OPS_APPROVER)
    validate_error(res, "ERR_PERIOD_CLOSED")
    assert res.status_code == 409


def test_waiver_is_admitted_while_the_period_remains_open():
    """PRD §3.8: "A waive requires the item's `aging_bucket` to be `AGING`,
    `ESCALATED` or `CRITICAL` ... and it requires the item's `opened_utc` to be
    at or after the close instant of the ledger's `period_closed_through_index`".

    Design: Difficulty/cross_entity_state_dependency/exception_waiver_gated_by_ledger_closed_period
    """
    scenario = _aged_return_exception_scenario()
    res = api_client.waive_exception(
        scenario["exception"]["id"],
        {"resolution_note": "aged, still inside the open period"},
        OPS_APPROVER)
    waived = validate_success(res, 200)
    assert waived["status"] == "WAIVED", f"expected WAIVED, got {waived['status']}"


def test_the_exception_status_is_unchanged_by_the_period_gate():
    """PRD §3.8: "it requires the item's `opened_utc` to be at or after the close
    instant of the ledger's `period_closed_through_index`".

    Design: Difficulty/cross_entity_state_dependency/exception_waiver_gated_by_ledger_closed_period
    """
    scenario = _aged_return_exception_scenario()
    before = scenario["exception"]["status"]
    close_period(scenario["ledger"]["id"], force_resolve=True)
    api_client.waive_exception(
        scenario["exception"]["id"], {"resolution_note": "refused"}, OPS_APPROVER)

    after = get_success_data(api_client.get_exception(scenario["exception"]["id"], ANALYST))
    assert before == "ASSIGNED"
    assert after["status"] == "ASSIGNED", (
        f"the gate is the ledger's period, not the item's status; got {after['status']}"
    )


# ─── Cross-entity: relationship activation gated by exceptions ──

def _relationship_and_open_deposit():
    scenario = ledger_scenario(with_partner=True)
    relationship = create_relationship(
        scenario["entity"]["id"], scenario["entity2"]["id"],
        purpose="ACCOUNT_SHARING", account_data_sharing=True)
    scenario["relationship"] = relationship

    # The opening deposit must land on the ledger the relationship's two sides
    # share, because PRD §3.2 gates activation on "every `UNMATCHED_DEPOSIT`-kind
    # exception on the ledger of either side".  `statement_scenario` builds its
    # own ledger, so the statement is imported here against the institution's own
    # account instead.
    statement = get_success_data(api_client.import_statement(
        create_statement_payload(scenario["account"]["id"], scenario["account_v"],
                                 institution_ref="STMT-H",
                                 cycle_date="2026-09-01T23:59:59Z"), ANALYST),
        expected_status=201)
    append_line(statement, bank_reference="STMT-H-L0", amount_cents=88_888,
                direction="CREDIT", effective_at="2026-09-01T10:00:00Z")
    scenario["statement"] = reconcile(statement)
    scenario["deposit"] = first_exception(scenario["ledger"]["id"], kind="UNMATCHED_DEPOSIT")
    return scenario


def test_activation_is_refused_while_an_unmatched_deposit_is_still_open():
    """PRD §3.2: "every `UNMATCHED_DEPOSIT`-kind exception on the ledger of
    either side must already be `RESOLVED` or `WAIVED`, because an institution
    may not begin sharing account data while an unattributed deposit is still
    open; when the gate fails the activation is refused with
    `ERR_LEDGER_UNBALANCED` and HTTP 409".

    Design: Difficulty/cross_entity_state_dependency/relationship_activation_gated_by_open_exception_state
    """
    scenario = _relationship_and_open_deposit()
    res = api_client.activate_relationship(
        scenario["relationship"]["id"],
        {"expected_relationship_version": scenario["relationship"]["version"]},
        APPROVER)
    validate_error(res, "ERR_LEDGER_UNBALANCED")
    assert res.status_code == 409


def test_resolving_the_deposit_leaves_the_relationship_still_pending_before_activation():
    """PRD §3.2: "every `UNMATCHED_DEPOSIT`-kind exception on the ledger of
    either side must already be `RESOLVED` or `WAIVED`".

    Design: Difficulty/cross_entity_state_dependency/relationship_activation_gated_by_open_exception_state
    """
    scenario = _relationship_and_open_deposit()
    deposit = scenario["deposit"]
    assign_exception(deposit["id"])
    resolve_exception(deposit["id"], "attributed by hand")
    api_client.set_current_utc("2026-09-02T00:00:00Z", CONTROLLER)

    relationship = get_success_data(
        api_client.get_relationship(scenario["relationship"]["id"], APPROVER))
    assert relationship["status"] == "PENDING", (
        f"the relationship is untouched until an explicit activation, got {relationship['status']}"
    )


def test_activation_succeeds_once_the_deposit_exception_is_resolved():
    """PRD §3.2: "when the gate fails the activation is refused with
    `ERR_LEDGER_UNBALANCED` and HTTP 409".

    Design: Difficulty/cross_entity_state_dependency/relationship_activation_gated_by_open_exception_state
    """
    scenario = _relationship_and_open_deposit()
    deposit = scenario["deposit"]
    assign_exception(deposit["id"])
    resolve_exception(deposit["id"], "attributed by hand")
    api_client.set_current_utc("2026-09-02T00:00:00Z", CONTROLLER)

    relationship = get_success_data(
        api_client.get_relationship(scenario["relationship"]["id"], APPROVER))
    res = api_client.activate_relationship(
        relationship["id"], {"expected_relationship_version": relationship["version"]},
        APPROVER)
    activated = validate_success(res, 200)
    assert activated["status"] == "ACTIVE", (
        f"expected ACTIVE once the gate clears, got {activated['status']}"
    )


# ─── Temporal overlap: statement cycle slot ───────────

def test_a_second_statement_for_the_same_cycle_is_refused():
    """PRD §3.7: "one statement may be imported per statement cycle".
    PRD §3.7: "A duplicate therefore surfaces as `ERR_LINE_ALREADY_MATCHED` with
    HTTP 409".

    Design: Difficulty/resource_temporal_overlap/statement_cycle_adjacency_closed_zero_length_overlap
    """
    scenario = ledger_scenario()
    scenario["statement"] = get_success_data(api_client.import_statement(
        create_statement_payload_for(scenario, institution_ref="CYC-1",
                                     cycle_date="2026-09-01T08:00:00Z"), ANALYST))
    refresh_account(scenario)

    res = api_client.import_statement(
        create_statement_payload_for(scenario, institution_ref="CYC-2",
                                     cycle_date="2026-09-01T08:00:00Z"), ANALYST)
    validate_error(res, "ERR_LINE_ALREADY_MATCHED")
    assert res.status_code == 409


def test_importing_one_second_later_into_a_fresh_cycle_is_accepted():
    """PRD §3.7: "one statement may be imported per statement cycle".

    Design: Difficulty/resource_temporal_overlap/statement_cycle_adjacency_closed_zero_length_overlap
    """
    scenario = ledger_scenario()
    get_success_data(api_client.import_statement(
        create_statement_payload_for(scenario, institution_ref="CYC-1",
                                     cycle_date="2026-09-01T08:00:00Z"), ANALYST))
    refresh_account(scenario)

    res = api_client.import_statement(
        create_statement_payload_for(scenario, institution_ref="CYC-2",
                                     cycle_date="2026-09-01T08:00:01Z"), ANALYST)
    statement = validate_success(res, 201)
    assert statement["status"] == "IMPORTED"


def test_the_rejected_import_leaves_the_original_slot_untouched():
    """PRD §3.7: "one statement may be imported per statement cycle".

    Design: Difficulty/resource_temporal_overlap/statement_cycle_adjacency_closed_zero_length_overlap
    """
    scenario = ledger_scenario()
    original = get_success_data(api_client.import_statement(
        create_statement_payload_for(scenario, institution_ref="CYC-1",
                                     cycle_date="2026-09-01T08:00:00Z"), ANALYST))
    refresh_account(scenario)
    api_client.import_statement(
        create_statement_payload_for(scenario, institution_ref="CYC-2",
                                     cycle_date="2026-09-01T08:00:00Z"), ANALYST)

    statements = get_success_data(api_client.list_statements(
        ANALYST, params={"bank_account_id": scenario["account"]["id"]}))
    assert len(statements) == 1, f"expected one statement to remain, got {len(statements)}"
    assert statements[0]["id"] == original["id"]


# ─── Temporal overlap: calendar cell buffer ───────────
#
# SKIPPED INSTANCE (queue B): `calendar_cell_second_cutoff_rejected_within_buffer`.
# Its claim is a second calendar cell whose cutoff falls inside a fixed window
# after an already-published cutoff for the same date. PRD prose states no such
# window anywhere: PRD §3.4 says only "subject to the one-cell-per-institution-per-date
# rule and the rule that `allowed_rails` must be a non-empty subset of the rails
# named in `cutoffs`". A PRD-only implementer would reject the second cell
# outright on the same-date rule (or accept it as a replacement), never on a
# time-window rule. Both PRD-first conditions fail: Coverage (no verbatim
# sentence names the window) and Unique derivability. No test is emitted, and no
# tag line is attached.


# ─── Local helpers ────────────────────────────────────

def create_statement_payload_for(scenario, institution_ref, cycle_date,
                                 matching_algorithm="POSTED_NET"):
    from test_helpers import create_statement_payload
    return create_statement_payload(
        scenario["account"]["id"], scenario["account_v"],
        institution_ref=institution_ref, cycle_date=cycle_date,
        matching_algorithm=matching_algorithm)


def create_calendar_payload(legal_entity_id, calendar_date, cutoff_local_time):
    from test_helpers import create_calendar_cell_payload
    return create_calendar_cell_payload(
        legal_entity_id, calendar_date,
        cutoffs=[{"rail": "ACH", "cutoff_local_time": cutoff_local_time}],
        allowed_rails=["ACH"])