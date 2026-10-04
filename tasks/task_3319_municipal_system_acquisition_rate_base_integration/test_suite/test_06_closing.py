"""Closing-phase tests: migration, deposit settlement, tariff, crew capacity."""
from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId,
    assert_customer_account, assert_tariff_case, assert_deposit_settlement_invariants,
    setup_target_in_closing, setup_target_in_regulatory_review,
    setup_target_in_valuation,
    transition_item_ids_by_category, resolve_transition_item,
    register_account, create_tariff_case, adopt_tariff_case,
    create_capital_item_payload,
    create_target, create_assessment_with_items, submit_assessment,
    accept_assessment, set_clock,
    open_valuation_case, submit_entry, finalize_case,
    setup_hearing_held, pass_council_vote,
    file_application, decide_application,
    make_headers,
)


def test_deposit_settlement_conservation(api):
    """PRD §3.7: "First, `deposit_offset_cents` is the deposit or the
    outstanding AR balance, whichever is smaller. Second, `new_ar_balance_cents`
    is the AR balance minus that offset — what carries into the acquirer's
    billing system. Third, `refund_cents` is the deposit minus the offset — the
    remainder returned to the customer."

    Design: Difficulty/compensating_invariant/deposit_settlement_conservation
    """
    ctx = setup_target_in_closing(customer_count=10)
    target_id = ctx["target"]["id"]
    items = transition_item_ids_by_category(target_id)
    resp = resolve_transition_item(items["BILLING_RECORDS"], "billing converted")
    get_success_data(resp)
    account = register_account(target_id, account_ref="CA-1",
                               deposit_cents=50000, ar_balance_cents=30000)
    resp = api.migrate_customer_account(account["id"],
                                        TEST_USERS["transition_mgr_headers"])
    migrated = validate_success(resp, 200)
    assert migrated["status"] == "MIGRATED"
    assert migrated["deposit_offset_cents"] == 30000
    assert migrated["refund_cents"] == 20000
    assert migrated["new_ar_balance_cents"] == 0
    assert_deposit_settlement_invariants({
        "deposit_cents": 50000, "ar_balance_cents": 30000,
        "deposit_offset_cents": migrated["deposit_offset_cents"],
        "refund_cents": migrated["refund_cents"],
        "new_ar_balance_cents": migrated["new_ar_balance_cents"],
    })


def test_deposit_settlement_conservation_ar_exceeds_deposit(api):
    """PRD §3.7: "The settlement conserves both sides: refund plus offset equals
    the original deposit, and new AR plus offset equals the original AR
    balance."

    Design: Difficulty/compensating_invariant/deposit_settlement_conservation
    """
    ctx = setup_target_in_closing(customer_count=10)
    target_id = ctx["target"]["id"]
    items = transition_item_ids_by_category(target_id)
    get_success_data(resolve_transition_item(items["BILLING_RECORDS"]))
    account = register_account(target_id, account_ref="CA-2",
                               deposit_cents=20000, ar_balance_cents=45000)
    migrated = get_success_data(api.migrate_customer_account(
        account["id"], TEST_USERS["transition_mgr_headers"]))
    assert migrated["deposit_offset_cents"] == 20000
    assert migrated["refund_cents"] == 0
    assert migrated["new_ar_balance_cents"] == 25000
    assert_deposit_settlement_invariants({
        "deposit_cents": 20000, "ar_balance_cents": 45000,
        "deposit_offset_cents": migrated["deposit_offset_cents"],
        "refund_cents": migrated["refund_cents"],
        "new_ar_balance_cents": migrated["new_ar_balance_cents"],
    })


def test_account_migration_requires_billing_transition_done(api):
    """PRD §3.7: "Migration becomes possible once the target is in `CLOSING` and
    the billing records have moved: the target's `BILLING_RECORDS` transition
    item must be `DONE`, otherwise migration is rejected with
    `ERR_TRANSITION_PREREQ` (HTTP 409)".

    Design: Difficulty/cross_entity_state_dependency/account_migration_requires_billing_transition_done
    """
    ctx = setup_target_in_closing(customer_count=10)
    target_id = ctx["target"]["id"]
    account = register_account(target_id, account_ref="CA-1",
                               deposit_cents=50000, ar_balance_cents=30000)
    resp = api.migrate_customer_account(account["id"],
                                        TEST_USERS["transition_mgr_headers"])
    validate_error(resp, ApiErrorId.ERR_TRANSITION_PREREQ)
    fresh = get_success_data(api.get_customer_account(account["id"],
                                                      TEST_USERS["transition_mgr_headers"]))
    assert fresh["status"] == "LEGACY"


def test_account_migration_requires_billing_transition_done_deposits_first(api):
    """PRD §3.7: "a target not in `CLOSING` is rejected with `ERR_INVALID_STATE`
    (HTTP 409)". Resolve attempt before CLOSING must fail the same way; once in
    CLOSING but billing pending, migrate still fails with ERR_TRANSITION_PREREQ.

    Design: Difficulty/cross_entity_state_dependency/account_migration_requires_billing_transition_done
    """
    ctx = setup_target_in_closing(customer_count=10)
    target_id = ctx["target"]["id"]
    # Resolve a non-gated item first; BILLING_RECORDS still PENDING.
    items = transition_item_ids_by_category(target_id)
    get_success_data(resolve_transition_item(items["SERVICE_AGREEMENTS"]))
    account = register_account(target_id, account_ref="CA-7",
                               deposit_cents=100, ar_balance_cents=0)
    resp = api.migrate_customer_account(account["id"],
                                        TEST_USERS["transition_mgr_headers"])
    validate_error(resp, ApiErrorId.ERR_TRANSITION_PREREQ)


def test_orphan_with_balance_rejected(api):
    """PRD §3.7: "only when both `ar_balance_cents` and `deposit_cents` are
    exactly zero; orphaning an account with money still on it is rejected with
    `ERR_ACCOUNT_NOT_SETTLED` (HTTP 409)."

    Design: Corner/validations/orphan_with_balance_rejected
    """
    ctx = setup_target_in_closing(customer_count=5)
    account = register_account(ctx["target"]["id"], account_ref="CA-9",
                               deposit_cents=100, ar_balance_cents=0)
    resp = api.orphan_customer_account(account["id"],
                                       TEST_USERS["transition_mgr_headers"])
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_SETTLED)
    fresh = get_success_data(api.get_customer_account(account["id"],
                                                      TEST_USERS["transition_mgr_headers"]))
    assert fresh["status"] == "LEGACY"


def test_customer_account_ref_unique_within_target(api):
    """PRD §3.7: "each with its legacy account number `account_ref` (unique
    within the target; a repeat is rejected with `ERR_DUPLICATE`, HTTP 409)".

    Design: Corner/entities/customer_account_ref_unique_within_target
    """
    t1 = create_target(system_name="T1", municipality_name="M1", customer_count=5)
    t2 = create_target(system_name="T2", municipality_name="M2", state_code="OH",
                       customer_count=5)
    register_account(t1["id"], account_ref="A-1", deposit_cents=100)
    resp = api.create_customer_account(
        t1["id"], {"account_ref": "A-1", "deposit_cents": 200, "ar_balance_cents": 0},
        TEST_USERS["transition_mgr_headers"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)
    resp = api.create_customer_account(
        t2["id"], {"account_ref": "A-1", "deposit_cents": 300, "ar_balance_cents": 0},
        TEST_USERS["transition_mgr_headers"])
    validate_success(resp, 201)


def test_consolidate_requires_adopted_tariff(api):
    """PRD §3.7: "consolidation without an adopted case is rejected with
    `ERR_TARIFF_NOT_ADOPTED` (HTTP 409)."

    Design: Corner/endpoints/consolidate_requires_adopted_tariff
    """
    ctx = setup_target_in_closing(customer_count=5)
    target_id = ctx["target"]["id"]
    items = transition_item_ids_by_category(target_id)
    get_success_data(resolve_transition_item(items["BILLING_RECORDS"]))
    account = register_account(target_id, account_ref="CA-1",
                               deposit_cents=100, ar_balance_cents=0)
    get_success_data(api.migrate_customer_account(account["id"],
                                                  TEST_USERS["transition_mgr_headers"]))
    resp = api.consolidate_customer_account(account["id"],
                                            TEST_USERS["transition_mgr_headers"])
    validate_error(resp, ApiErrorId.ERR_TARIFF_NOT_ADOPTED)
    fresh = get_success_data(api.get_customer_account(account["id"],
                                                      TEST_USERS["transition_mgr_headers"]))
    assert fresh["status"] == "MIGRATED"


def test_phase_in_years_boundary_exact_multiple(api):
    """PRD §3.7: "the cap per year is five percent of the representative old
    bill, rounded half-up to a whole cent; the gap is the consolidated bill
    minus the representative old bill ... otherwise the phase-in is the gap
    divided by the annual cap, rounded **up** to a whole year — so a gap exactly
    equal to some whole multiple of the cap yields exactly that many years,
    never one more."

    Design: Corner/calculations/phase_in_years_boundary_exact_multiple
    """
    ctx = setup_target_in_regulatory_review(customer_count=5)
    case = create_tariff_case(ctx["target"]["id"], mode="STAND_ALONE",
                              representative_old_bill_cents=5000,
                              consolidated_monthly_bill_cents=6000)
    resp = adopt_tariff_case(case["id"])
    adopted = validate_success(resp, 200)
    assert_tariff_case(adopted)
    assert adopted["status"] == "ADOPTED"
    assert adopted["phase_in_years"] == 4  # delta 1000 == exactly 4 * 250


def test_phase_in_delta_exactly_zero_years(api):
    """PRD §3.7: "if the gap is zero or negative, the phase-in is 0 years".

    Design: Corner/calculations/phase_in_delta_exactly_zero_years
    """
    ctx = setup_target_in_regulatory_review(customer_count=5)
    case = create_tariff_case(ctx["target"]["id"], mode="STAND_ALONE",
                              representative_old_bill_cents=5000,
                              consolidated_monthly_bill_cents=5000)
    adopted = get_success_data(adopt_tariff_case(case["id"]))
    assert adopted["phase_in_years"] == 0


def test_single_tariff_requires_approved_application(api):
    """PRD §3.7: "A `SINGLE_TARIFF` adoption further requires the target's
    regulatory application to be `APPROVED`; adopting single-tariff pricing
    before commission approval is rejected with `ERR_APPROVAL_PREREQ`
    (HTTP 409)."

    Design: Corner/validations/single_tariff_requires_approved_application
    """
    ctx = setup_target_in_regulatory_review(customer_count=5)
    case = create_tariff_case(ctx["target"]["id"], mode="SINGLE_TARIFF",
                              representative_old_bill_cents=5000,
                              consolidated_monthly_bill_cents=6200)
    resp = adopt_tariff_case(case["id"])
    validate_error(resp, ApiErrorId.ERR_APPROVAL_PREREQ)
    fresh = get_success_data(api.get_tariff_case(case["id"],
                                                 TEST_USERS["reg_officer_headers"]))
    assert fresh["status"] == "DRAFT"


def test_second_adopted_tariff_case_rejected(api):
    """PRD §3.7: "no other `ADOPTED` tariff case may exist for the target (a
    second adoption is rejected with `ERR_DUPLICATE`, HTTP 409)."

    Design: Corner/cross_cutting_layers/second_adopted_tariff_case_rejected
    """
    ctx = setup_target_in_regulatory_review(customer_count=5)
    target_id = ctx["target"]["id"]
    tc1 = create_tariff_case(target_id, mode="STAND_ALONE",
                             representative_old_bill_cents=5000,
                             consolidated_monthly_bill_cents=5000)
    get_success_data(adopt_tariff_case(tc1["id"]))
    tc2 = create_tariff_case(target_id, mode="STAND_ALONE",
                             representative_old_bill_cents=5000,
                             consolidated_monthly_bill_cents=5500)
    resp = adopt_tariff_case(tc2["id"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE)
    fresh = get_success_data(api.get_tariff_case(tc2["id"],
                                                 TEST_USERS["reg_officer_headers"]))
    assert fresh["status"] == "DRAFT"


def test_capital_item_crew_capacity_aggregation(api):
    """PRD §3.7: "at every instant of the requested window, the sum of
    `crews_required` over this item plus all other `SCHEDULED` items of the same
    target whose windows contain that instant must not exceed 3 crews per
    target. A window that would push concurrent crew demand above 3 at any
    instant is rejected with `ERR_CREW_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/capital_item_crew_capacity_aggregation
    """
    items = [
        create_capital_item_payload(description="d1", cost_low_cents=1000,
                                    cost_high_cents=1000, crews_required=2),
        create_capital_item_payload(description="d2", cost_low_cents=1000,
                                    cost_high_cents=1000, crews_required=1),
        create_capital_item_payload(category="STORAGE", horizon="SHORT_TERM",
                                    description="d3", cost_low_cents=1000,
                                    cost_high_cents=1000, crews_required=1),
    ]
    target, assessment, created = setup_target_in_valuation(state_code="OH",
                                                            item_payloads=items)
    i1, i2, i3 = created
    tm = TEST_USERS["transition_mgr_headers"]
    get_success_data(api.schedule_capital_item(
        i1["id"], {"window_start": "2026-10-01T00:00:00Z",
                   "window_end": "2026-10-05T00:00:00Z"}, tm))
    get_success_data(api.schedule_capital_item(
        i2["id"], {"window_start": "2026-10-03T00:00:00Z",
                   "window_end": "2026-10-07T00:00:00Z"}, tm))
    i1_now = get_success_data(api.get_capital_item(i1["id"], tm))
    i2_now = get_success_data(api.get_capital_item(i2["id"], tm))
    assert i1_now["status"] == "SCHEDULED"
    assert i2_now["status"] == "SCHEDULED"
    # Third item would push concurrent demand to 4 during 10-04..10-05.
    resp = api.schedule_capital_item(
        i3["id"], {"window_start": "2026-10-04T00:00:00Z",
                   "window_end": "2026-10-06T00:00:00Z"}, tm)
    validate_error(resp, ApiErrorId.ERR_CREW_CAPACITY_EXCEEDED)
    i3_now = get_success_data(api.get_capital_item(i3["id"], tm))
    assert i3_now["status"] == "PLANNED"


def test_capital_item_crew_capacity_at_cap_allowed(api):
    """PRD §3.7: "must not exceed 3 crews per target" — summed demand of exactly
    3 at every instant is permitted.

    Design: Difficulty/resource_temporal_overlap/capital_item_crew_capacity_aggregation
    """
    items = [
        create_capital_item_payload(description="d1", crews_required=3),
        create_capital_item_payload(description="d2", crews_required=1),
    ]
    target, assessment, created = setup_target_in_valuation(state_code="OH",
                                                            item_payloads=items)
    tm = TEST_USERS["transition_mgr_headers"]
    i1, i2 = created
    get_success_data(api.schedule_capital_item(
        i1["id"], {"window_start": "2026-11-01T00:00:00Z",
                   "window_end": "2026-11-05T00:00:00Z"}, tm))
    # Adjacent (non-overlapping) window for the 1-crew item -> allowed.
    resp = api.schedule_capital_item(
        i2["id"], {"window_start": "2026-11-05T00:00:00Z",
                   "window_end": "2026-11-08T00:00:00Z"}, tm)
    scheduled = validate_success(resp, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_execute_before_window_open_rejected(api):
    """PRD §3.7: "A scheduled item may be marked executed once the logical clock
    has reached its `window_start` — executing earlier is rejected with
    `ERR_WINDOW_NOT_OPEN` (HTTP 409) — and only while the target is in `CLOSING`
    or `INTEGRATED`; execution moves the item to `EXECUTED`."

    Design: Corner/endpoints/execute_before_window_open_rejected
    """
    items = [create_capital_item_payload(category="GENERAL", cost_low_cents=1000,
                                         cost_high_cents=1000)]
    target, assessment, created = setup_target_in_valuation(item_payloads=items)
    item = created[0]
    tm = TEST_USERS["transition_mgr_headers"]
    get_success_data(api.schedule_capital_item(
        item["id"], {"window_start": "2026-10-01T00:00:00Z",
                     "window_end": "2026-10-05T00:00:00Z"}, tm))

    # Drive the target to CLOSING.
    case = open_valuation_case(target["id"])
    entry = submit_entry(case["id"])
    finalize_case(case["id"], entry["id"])
    setup_hearing_held(target["id"])
    pass_council_vote(target["id"])
    app = file_application(target["id"])
    decide_application(app["id"], "APPROVED")

    # Clock is at 2026-09-10, before window_start 2026-10-01.
    resp = api.execute_capital_item(item["id"], tm)
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)
    set_clock("2026-10-02T00:00:00Z")
    executed = get_success_data(api.execute_capital_item(item["id"], tm))
    assert executed["status"] == "EXECUTED"


def test_transition_item_done_is_terminal(api):
    """PRD §3.7: "The four transition items are resolved by the
    `TransitionManager`, optionally recording a `resolution_note`, but only
    while the target is in `CLOSING`" — a DONE item accepts no further
    resolution (`ERR_INVALID_STATE`).

    Design: Corner/state_machines/transition_item_done_is_terminal
    """
    ctx = setup_target_in_closing(customer_count=5)
    target_id = ctx["target"]["id"]
    items = transition_item_ids_by_category(target_id)
    get_success_data(resolve_transition_item(items["SERVICE_AGREEMENTS"]))
    resp = resolve_transition_item(items["SERVICE_AGREEMENTS"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    fresh = get_success_data(api.get_transition_item(items["SERVICE_AGREEMENTS"],
                                                     TEST_USERS["transition_mgr_headers"]))
    assert fresh["status"] == "DONE"


def test_close_happy_path_reaches_integrated(api):
    """PRD §3.7: "Closing the transaction — moving the target `CLOSING →
    INTEGRATED` — is the final gate, and it checks three things: all four
    transition items must be `DONE` ..., no customer account may remain in
    `LEGACY` ..., and no employee transition may remain in `PENDING`".

    Design: Corner/endpoints/close_happy_path_reaches_integrated
    """
    ctx = setup_target_in_closing(customer_count=5)
    target_id = ctx["target"]["id"]
    items = transition_item_ids_by_category(target_id)
    account = register_account(target_id, account_ref="CA-0",
                               deposit_cents=0, ar_balance_cents=0)
    get_success_data(resolve_transition_item(items["BILLING_RECORDS"]))
    get_success_data(resolve_transition_item(items["SERVICE_AGREEMENTS"]))
    get_success_data(resolve_transition_item(items["METER_READS"]))
    migrated = get_success_data(api.migrate_customer_account(
        account["id"], TEST_USERS["transition_mgr_headers"]))
    assert migrated["status"] == "MIGRATED"
    assert migrated["deposit_offset_cents"] == 0
    assert migrated["refund_cents"] == 0
    assert migrated["new_ar_balance_cents"] == 0
    get_success_data(resolve_transition_item(items["DEPOSITS"]))

    closed = get_success_data(api.close_target(target_id,
                                               TEST_USERS["transition_mgr_headers"]))
    assert closed["status"] == "INTEGRATED"


def test_close_blocked_by_pending_transition_items(api):
    """PRD §3.7: "all four transition items must be `DONE` (otherwise
    `ERR_TRANSITION_INCOMPLETE`, HTTP 409)".

    Design: Corner/endpoints/close_blocked_by_pending_transition_items
    """
    ctx = setup_target_in_closing(customer_count=5)
    target_id = ctx["target"]["id"]
    resp = api.close_target(target_id, TEST_USERS["transition_mgr_headers"])
    validate_error(resp, ApiErrorId.ERR_TRANSITION_INCOMPLETE)
    fresh = get_success_data(api.get_target(target_id, TEST_USERS["analyst_headers"]))
    assert fresh["status"] == "CLOSING"
