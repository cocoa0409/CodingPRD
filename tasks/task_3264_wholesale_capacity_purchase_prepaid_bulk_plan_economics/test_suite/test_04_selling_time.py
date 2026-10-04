"""Selling time: quoting, purchasing, renewal step-up, refund and terminal terms."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_revenue_complement,
    make_subscriber_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers.fixtures import (
    create_subscriber,
    current_agreement_version,
    get_subscriber,
    get_summary,
    get_term,
    next_msisdn,
    offer_plan,
    purchase_term,
    quote_term,
    set_clock,
    setup_active_agreement,
    setup_activated_subscriber,
    setup_agreement_with_offered_plan,
    setup_renewal_due_term,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_quoting_a_term_lands_in_quoted_with_zero_price(api):
    """PRD §3.5: "the server creates a term in `QUOTED` with `term_price_cents`
    at 0 and both revenue fields at 0."

    Design: Corner/state_machines/prepaid_term_create_lands_in_quoted_with_zero_price
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()

    resp = api.create_term(
        {
            "subscriber_id": subscriber["id"],
            "plan_id": plan["id"],
            "expected_CapacityAgreement_version": agreement["version"],
        },
        make_subscriber_headers(subscriber["id"]),
    )
    term = validate_success(resp, expected_status=201)
    assert term["term_status"] == "QUOTED"
    assert term["term_price_cents"] == 0
    assert term["deferred_revenue_cents"] == 0
    assert term["earned_revenue_cents"] == 0
    assert term["starts_at"] is None
    assert term["breakage_days"] == 0
    assert term["void_reason"] is None
    assert get_summary(agreement["id"])["allocated_data_mb"] == 0


def test_purchase_seeds_the_provisional_schedule(api):
    """PRD §3.6: "At purchase the term is seeded at the first ordinal, so
    `earned_revenue_cents` becomes one month's share of the
    price rounded up and `deferred_revenue_cents` becomes the remainder."

    Design: Difficulty/dual_variant_calc/deferred_revenue_provisional_schedule_vs_final_blended
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()
    term = quote_term(subscriber["id"], plan["id"], agreement["version"])

    purchased = api.purchase_term(
        term["id"], make_subscriber_headers(subscriber["id"])
    ).json()["data"]
    assert purchased["term_price_cents"] == 1999
    assert purchased["earned_revenue_cents"] == 667
    assert purchased["deferred_revenue_cents"] == 1332
    assert_revenue_complement(purchased)


def test_purchase_moves_the_plan_to_active(api):
    """PRD §3.2: "The first purchase against a plan moves it from
    `OFFERED` to `ACTIVE`".

    Design: Difficulty/dual_variant_calc/deferred_revenue_provisional_schedule_vs_final_blended
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()
    term = quote_term(subscriber["id"], plan["id"], agreement["version"])
    purchase_term(term["id"], subscriber["id"])

    assert api.get_plan(plan["id"], TEST_USERS["planner_headers"]).json()["data"][
        "plan_status"
    ] == "ACTIVE"
    assert get_summary(agreement["id"])["allocated_data_mb"] == 3000


def test_first_term_is_charged_the_intro_price(api):
    """PRD §3.5: "A subscriber's first term on a given plan — the term whose ordinal
    equals `FIRST_TERM_ORDINAL`, which is 1 — is charged the plan's `intro_price_cents`".

    Design: Difficulty/non_linear_state_machine/prepaid_term_cyclic_renewal_loop
    """
    set_clock()
    setup = setup_activated_subscriber()
    assert setup["term"]["term_status"] == "ACTIVE"
    assert setup["term"]["term_price_cents"] == 1999


def test_purchase_requires_the_parent_agreement_to_be_active(api):
    """PRD §3.5: "a suspended agreement yields
    `ERR_AGREEMENT_SUSPENDED`".

    Design: Difficulty/cross_entity_state_dependency/term_purchase_requires_parent_agreement_active
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()
    term = quote_term(subscriber["id"], plan["id"], agreement["version"])

    api.suspend_agreement(agreement["id"], TEST_USERS["planner_headers"])
    resp = api.purchase_term(term["id"], make_subscriber_headers(subscriber["id"]))
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_SUSPENDED)
    assert get_term(term["id"])["term_status"] == "QUOTED"
    assert get_term(term["id"])["term_price_cents"] == 0


def test_reactivation_admits_the_identical_purchase(api):
    """PRD §3.1: "A `CapacityPlanner` returns a suspended agreement to service
    once `allocated_data_mb` is back at or below `committed_data_mb`".

    Design: Difficulty/cross_entity_state_dependency/term_purchase_requires_parent_agreement_active
    """
    set_clock()
    agreement, plan = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()
    term = quote_term(subscriber["id"], plan["id"], agreement["version"])

    api.suspend_agreement(agreement["id"], TEST_USERS["planner_headers"])
    api.reactivate_agreement(agreement["id"], TEST_USERS["planner_headers"])
    purchased = api.purchase_term(
        term["id"], make_subscriber_headers(subscriber["id"])
    ).json()["data"]
    assert purchased["term_status"] == "PURCHASED"
    assert purchased["term_price_cents"] == 1999


def test_term_cancel_before_start_refunds_and_releases_capacity(api):
    """PRD §3.5: "If `starts_at` is still null — the term was purchased but never activated —
    cancelling it moves
    it from `PURCHASED` or `AWAITING_ACTIVATION` to `REFUNDED`, zeroes both `deferred_revenue_cents` and
    `earned_revenue_cents`, and releases the capacity the term was holding".

    Design: Difficulty/compensating_invariant/term_purchase_and_refund_conserve_agreement_megabytes
    """
    set_clock()
    agreement, plan, subscriber, term = _purchased_term(api)
    assert get_summary(agreement["id"])["allocated_data_mb"] == 3000

    refunded = api.cancel_term(
        term["id"], make_subscriber_headers(subscriber["id"])
    ).json()["data"]
    assert refunded["term_status"] == "REFUNDED"
    assert refunded["deferred_revenue_cents"] == 0
    assert refunded["earned_revenue_cents"] == 0

    summary = get_summary(agreement["id"])
    assert summary["allocated_data_mb"] == 0
    assert summary["remaining_data_mb"] == 16000
    assert summary["allocated_data_mb"] + summary["remaining_data_mb"] == 16000


def test_refund_restores_the_agreement_balance_exactly(api):
    """PRD §3.1: "a purchase followed by
    a refund of the same term restores the balance exactly."

    Design: Difficulty/compensating_invariant/term_purchase_and_refund_conserve_agreement_megabytes
    """
    set_clock()
    agreement, plan, subscriber, term = _purchased_term(api)
    before = get_summary(agreement["id"])
    assert before["allocated_data_mb"] == 3000
    assert before["remaining_data_mb"] == 13000
    assert before["allocated_data_mb"] + before["remaining_data_mb"] == 16000

    api.cancel_term(term["id"], make_subscriber_headers(subscriber["id"]))
    after = get_summary(agreement["id"])
    assert after["allocated_data_mb"] == 0
    assert after["remaining_data_mb"] == 16000
    assert after["allocated_data_mb"] + after["remaining_data_mb"] == 16000


def test_cancelling_a_refunded_term_is_refused(api):
    """PRD §3.5: "A cancel attempted on a term already in `REFUNDED` or `VOIDED` is
    refused with `ERR_TERM_ALREADY_TERMINAL` (HTTP 409)."
    PRD §2.10: "(6) the target row's lifecycle state, yielding
    `ERR_INVALID_STATE`; (7) terminality of the target row, yielding `ERR_TERM_ALREADY_TERMINAL`".

    Design: Difficulty/priority_pair_validation_conflict/churn_on_refunded_term_state_beats_fiscal
    """
    set_clock()
    agreement, plan, subscriber, term = _purchased_term(api)
    api.cancel_term(term["id"], make_subscriber_headers(subscriber["id"]))
    assert get_term(term["id"])["term_status"] == "REFUNDED"
    assert get_term(term["id"])["deferred_revenue_cents"] == 0

    resp = api.cancel_term(term["id"], make_subscriber_headers(subscriber["id"]))
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_TERM_ALREADY_TERMINAL, ApiErrorId.ERR_INVALID_STATE]
    )
    assert get_term(term["id"])["earned_revenue_cents"] == 0


def test_cancelling_a_started_term_recognises_breakage(api):
    """PRD §3.5: "If the term has already started, a refund-style cancel is refused with
    `ERR_TERM_ALREADY_STARTED` (HTTP 409), because from that point the term leaves the book only through breakage
    recognition".

    Design: Corner/calculations/early_churn_breakage_keeps_the_earned_revenue_identity
    """
    set_clock()
    setup = setup_activated_subscriber()
    api.run_cycle(setup["subscriber"]["id"], TEST_USERS["planner_headers"])
    term = get_term(setup["term"]["id"])
    assert term["earned_revenue_cents"] == 667
    assert term["deferred_revenue_cents"] == 1332

    current = get_subscriber(setup["subscriber"]["id"])
    resp = api.cancel_subscriber(
        setup["subscriber"]["id"],
        make_subscriber_headers(setup["subscriber"]["id"]),
        {"expected_Subscriber_version": current["version"]},
    )
    validate_success(resp)
    churned = get_term(setup["term"]["id"])
    assert churned["term_status"] == "EXPIRED"
    assert churned["breakage_days"] == 30
    assert churned["breakage_cents_recognized"] == 1999 * 30 // 90
    # Recognition adds the floored breakage (1999 * 30 / 90 == 666) to the already
    # earned 667, capped at the term price, and the deferred balance is the remainder.
    assert churned["earned_revenue_cents"] == 667 + 1999 * 30 // 90 == 1333
    assert churned["deferred_revenue_cents"] == 1999 - 1333 == 666
    assert_revenue_complement(churned)


def test_renewal_loop_reprices_the_term_at_the_step_up(api):
    """PRD §3.5: "When the final cycle of a live term rolls, the term enters `RENEWAL_DUE` and a
    `RENEWAL_PRICING` support case opens against the subscriber".

    Design: Difficulty/non_linear_state_machine/prepaid_term_cyclic_renewal_loop
    """
    set_clock()
    setup = setup_renewal_due_term(term_months=3)
    assert setup["term"]["term_status"] == "RENEWAL_DUE"

    cases = api.list_cases(
        TEST_USERS["planner_headers"],
        {"subscriber_id": setup["subscriber"]["id"], "topic_code": "RENEWAL_PRICING"},
    ).json()["data"]
    assert len(cases) == 1
    assert cases[0]["case_status"] == "OPEN"

    renewed = api.accept_step_up(
        setup["term"]["id"], make_subscriber_headers(setup["subscriber"]["id"])
    ).json()["data"]
    assert renewed["term_status"] == "ACTIVE_RENEWAL"
    assert renewed["term_price_cents"] == 3042
    assert get_subscriber(setup["subscriber"]["id"])["cycles_rolled"] == 0


def test_step_up_is_refused_before_the_final_cycle_rolls(api):
    """PRD §3.5: "The subscriber accepts the step-up, moving the term from `RENEWAL_DUE` to
    `ACTIVE_RENEWAL`".

    Design: Difficulty/non_linear_state_machine/prepaid_term_cyclic_renewal_loop
    """
    set_clock()
    setup = setup_activated_subscriber(term_months=3)
    resp = api.accept_step_up(
        setup["term"]["id"], make_subscriber_headers(setup["subscriber"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_term(setup["term"]["id"])["term_status"] == "ACTIVE"


def test_renewal_keeps_the_allocation_counted_exactly_once(api):
    """PRD §2.4: "A subscriber whose `allocation_status` is `HELD` counts exactly once toward
    `allocated_data_mb`".

    Design: Difficulty/non_linear_state_machine/prepaid_term_cyclic_renewal_loop
    """
    set_clock()
    setup = setup_renewal_due_term(term_months=3)
    api.accept_step_up(
        setup["term"]["id"], make_subscriber_headers(setup["subscriber"]["id"])
    )
    summary = get_summary(setup["agreement"]["id"])
    assert summary["allocated_data_mb"] == 3000
    assert summary["remaining_data_mb"] == 13000


def test_accepting_the_step_up_requires_the_agreement_to_be_active(api):
    """PRD §3.5: "that
    acceptance is admitted only when the parent plan is `OFFERED` or `ACTIVE`, the parent agreement is `ACTIVE`,
    and the agreement's `remaining_data_mb` is at least the plan's `data_allotment_mb`."

    Design: Difficulty/non_linear_state_machine/prepaid_term_cyclic_renewal_loop
    """
    set_clock()
    setup = setup_renewal_due_term(term_months=3)
    api.suspend_agreement(setup["agreement"]["id"], TEST_USERS["planner_headers"])

    resp = api.accept_step_up(
        setup["term"]["id"], make_subscriber_headers(setup["subscriber"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_SUSPENDED)


def test_term_read_with_unknown_id_returns_term_not_found(api):
    """PRD §2.9: "a missing prepaid term `ERR_TERM_NOT_FOUND`".

    Design: Corner/errors/not_found_codes_are_entity_specific
    """
    set_clock()
    resp = api.get_term(MISSING_ID, TEST_USERS["planner_headers"])
    validate_error(resp, ApiErrorId.ERR_TERM_NOT_FOUND)


def _purchased_term(api_client_obj):
    agreement, plan = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()
    term = quote_term(subscriber["id"], plan["id"], agreement["version"])
    purchase_term(term["id"], subscriber["id"])
    return agreement, plan, subscriber, get_term(term["id"])