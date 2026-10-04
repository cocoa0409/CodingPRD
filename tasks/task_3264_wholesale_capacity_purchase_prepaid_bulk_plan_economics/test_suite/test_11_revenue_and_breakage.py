"""Revenue recognition, deferred balances, breakage and terminal lifespans."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_revenue_complement,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    create_plan,
    create_subscriber,
    current_agreement_version,
    get_case,
    get_plan,
    get_subscriber,
    get_summary,
    get_term,
    offer_plan,
    purchase_term,
    quote_term,
    run_cycle,
    set_clock,
    setup_active_agreement,
    setup_activated_subscriber,
    setup_agreement_with_offered_plan,
    setup_grace_subscriber,
    setup_renewal_due_term,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_earned_and_deferred_revenue_are_always_complements(api):
    """PRD §3.6: "The two are always complements: the deferred balance is `term_price_cents` minus
    `earned_revenue_cents`, so it falls as revenue is recognised and can never exceed the term price."

    Design: Difficulty/compensating_invariant/deferred_revenue_conserved_across_an_early_churn
    """
    set_clock()
    setup = setup_activated_subscriber(
        term_months=12, intro_price_cents=32000, renewal_price_cents=38000,
        data_allotment_mb=20000, committed_data_mb=50000,
    )
    term = get_term(setup["term"]["id"])
    assert term["earned_revenue_cents"] + term["deferred_revenue_cents"] == 32000
    assert term["earned_revenue_cents"] == 2667
    assert term["deferred_revenue_cents"] == 29333

    run_cycle(setup["subscriber"]["id"])
    first_roll = get_term(setup["term"]["id"])
    assert_revenue_complement(first_roll)
    assert first_roll["earned_revenue_cents"] == 2667

    run_cycle(setup["subscriber"]["id"])
    second_roll = get_term(setup["term"]["id"])
    assert_revenue_complement(second_roll)
    assert second_roll["earned_revenue_cents"] == 5334


def test_the_identity_survives_an_early_churn(api):
    """PRD §3.6: "the breakage window is the smaller of the remaining days and `BREAKAGE_CAP_DAYS`, 30 days, recorded as `breakage_days`."

    Design: Difficulty/compensating_invariant/deferred_revenue_conserved_across_an_early_churn
    """
    set_clock()
    setup = setup_activated_subscriber(
        term_months=12, intro_price_cents=32000, renewal_price_cents=38000,
        data_allotment_mb=20000, committed_data_mb=50000,
    )
    run_cycle(setup["subscriber"]["id"])
    run_cycle(setup["subscriber"]["id"])
    assert get_term(setup["term"]["id"])["earned_revenue_cents"] == 5334

    current = get_subscriber(setup["subscriber"]["id"])
    resp = api.cancel_subscriber(
        setup["subscriber"]["id"],
        make_subscriber_headers(setup["subscriber"]["id"]),
        {"expected_Subscriber_version": current["version"]},
    )
    validate_success(resp)

    churned = get_term(setup["term"]["id"])
    assert churned["breakage_days"] == 30
    assert churned["breakage_cents_recognized"] == (32000 * 30) // 360
    assert churned["earned_revenue_cents"] == 8000
    assert churned["deferred_revenue_cents"] == 24000
    assert_revenue_complement(churned)


def test_breakage_write_back_is_one_way(api):
    """PRD §3.6: "This write-back is one-way: the deferred balance only ever decreases here,
    never increases."

    Design: Difficulty/compensating_invariant/deferred_revenue_conserved_across_an_early_churn
    """
    set_clock()
    setup = setup_activated_subscriber(term_months=3)
    run_cycle(setup["subscriber"]["id"])
    before_churn = get_term(setup["term"]["id"])
    assert before_churn["deferred_revenue_cents"] == 1332

    current = get_subscriber(setup["subscriber"]["id"])
    api.cancel_subscriber(
        setup["subscriber"]["id"],
        make_subscriber_headers(setup["subscriber"]["id"]),
        {"expected_Subscriber_version": current["version"]},
    )
    after_churn = get_term(setup["term"]["id"])
    assert after_churn["deferred_revenue_cents"] < before_churn["deferred_revenue_cents"]
    assert after_churn["deferred_revenue_cents"] == 666


def test_breakage_is_capped_at_one_cycle_for_a_twelve_month_term(api):
    """PRD §3.6: "The 30-day cap is the reason a twelve-month term churned in its first cycle recognises at
    most one extra cycle of revenue rather than eleven."

    Design: Difficulty/compensating_invariant/deferred_revenue_conserved_across_an_early_churn
    """
    set_clock()
    setup = setup_activated_subscriber(
        term_months=12, intro_price_cents=32000, renewal_price_cents=38000,
        data_allotment_mb=20000, committed_data_mb=50000,
    )
    current = get_subscriber(setup["subscriber"]["id"])
    api.cancel_subscriber(
        setup["subscriber"]["id"],
        make_subscriber_headers(setup["subscriber"]["id"]),
        {"expected_Subscriber_version": current["version"]},
    )
    churned = get_term(setup["term"]["id"])
    assert churned["breakage_days"] == 30
    assert churned["breakage_cents_recognized"] == (32000 * 30) // 360
    assert churned["earned_revenue_cents"] == 2667 + 2666


def test_a_second_cancel_on_a_terminal_term_is_refused(api):
    """PRD §3.5: "A cancel attempted on a term already in `REFUNDED` or `VOIDED` is
    refused with `ERR_TERM_ALREADY_TERMINAL` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/churn_on_refunded_term_state_beats_fiscal
    """
    set_clock()
    setup = setup_agreement_with_offered_plan()
    subscriber = create_subscriber()
    term = quote_term(subscriber["id"], setup[1]["id"], setup[0]["version"])
    purchase_term(term["id"], subscriber["id"])
    api.cancel_term(term["id"], make_subscriber_headers(subscriber["id"]))
    assert get_term(term["id"])["term_status"] == "REFUNDED"
    assert get_term(term["id"])["deferred_revenue_cents"] == 0

    resp = api.cancel_term(term["id"], make_subscriber_headers(subscriber["id"]))
    validate_error(resp, ApiErrorId.ERR_TERM_ALREADY_TERMINAL)
    assert get_term(term["id"])["earned_revenue_cents"] == 0


def test_breakage_rate_is_reported_as_whole_parts_per_million(api):
    """PRD §3.6: "The agreement's `breakage_rate_ppm` is
    `BREAKAGE_RATE_SCALE` — one million — times the total breakage divided by the total term price, rounded half up to a whole part per million, and is
    0 when the total term price is 0."

    Design: Corner/calculations/breakage_rate_is_integer_reported_parts_per_million
    """
    set_clock()
    setup = setup_activated_subscriber(term_months=3)
    agreement_id = setup["agreement"]["id"]

    assert get_summary(agreement_id)["breakage_rate_ppm"] == 0

    run_cycle(setup["subscriber"]["id"])
    current = get_subscriber(setup["subscriber"]["id"])
    api.cancel_subscriber(
        setup["subscriber"]["id"],
        make_subscriber_headers(setup["subscriber"]["id"]),
        {"expected_Subscriber_version": current["version"]},
    )
    term = get_term(setup["term"]["id"])
    assert term["term_status"] == "EXPIRED"
    assert term["breakage_cents_recognized"] == 666

    rate = get_summary(agreement_id)["breakage_rate_ppm"]
    assert isinstance(rate, int)
    assert rate == round(1000000 * 666 / 1999)
    assert rate == 333167


def test_expired_book_beyond_the_breakage_denominator_is_included(api):
    """PRD §3.6: "A term that was recognised with zero breakage still sits in the denominator,
    so the rate measures breakage against the entire expired book rather than only against the terms that broke."

    Design: Corner/calculations/breakage_rate_is_integer_reported_parts_per_million
    """
    set_clock()
    setup = setup_activated_subscriber(term_months=3)
    agreement_id = setup["agreement"]["id"]

    # Exhaust every cycle so the term expires with no remaining days and no breakage.
    for _ in range(3):
        run_cycle(setup["subscriber"]["id"])
    current = get_subscriber(setup["subscriber"]["id"])
    api.cancel_subscriber(
        setup["subscriber"]["id"],
        make_subscriber_headers(setup["subscriber"]["id"]),
        {"expected_Subscriber_version": current["version"]},
    )
    assert get_term(setup["term"]["id"])["breakage_cents_recognized"] == 0
    assert get_summary(agreement_id)["breakage_rate_ppm"] == 0


def test_only_offered_and_active_plans_count_toward_allocation(api):
    """PRD §3.1: "the index is the percentage of the bought pipe that sold allotment already occupies".

    Design: Corner/calculations/wholesale_allocated_data_mb_excludes_draft_and_retired_plans
    """
    set_clock()
    agreement = setup_active_agreement()
    offered = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    draft = create_plan(agreement["id"], plan_code="M3", data_allotment_mb=15000)

    subscriber = create_subscriber(state_code="CA")
    term = quote_term(subscriber["id"], offered["id"], current_agreement_version(agreement["id"]))
    purchase_term(term["id"], subscriber["id"])

    summary = get_summary(agreement["id"])
    assert draft["plan_status"] == "DRAFT"
    assert summary["allocated_data_mb"] == 3000
    assert summary["remaining_data_mb"] == 13000
    assert summary["allocated_data_mb"] + summary["remaining_data_mb"] == 16000


def test_closing_an_agreement_retires_every_plan(api):
    """PRD §3.1: "Closing sets `plan_status` to `RETIRED` on every
    plan the agreement contains".

    Design: Corner/state_machines/agreement_close_retires_every_plan
    """
    set_clock()
    agreement = setup_active_agreement()
    first = offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    second = offer_plan(
        create_plan(agreement["id"], plan_code="M3", data_allotment_mb=15000)["id"],
        current_agreement_version(agreement["id"]),
    )

    closed = api.close_agreement(agreement["id"], TEST_USERS["planner_headers"]).json()["data"]
    assert closed["agreement_status"] == "CLOSED"
    assert get_plan(first["id"])["plan_status"] == "RETIRED"
    assert get_plan(second["id"])["plan_status"] == "RETIRED"

    subscriber = create_subscriber(state_code="CA")
    resp = api.create_term(
        {
            "subscriber_id": subscriber["id"],
            "plan_id": first["id"],
            "expected_CapacityAgreement_version": closed["version"],
        },
        make_subscriber_headers(subscriber["id"]),
    )
    # PRD 2.10 ordering: closure of the agreement and retirement of the plan share one
    # priority level, but the agency that read the state first is the agreement's, so a
    # sale on a closed agreement whose plan it just retired reports the agreement's
    # closure. Both are the same HTTP 409 refusal.
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_CLOSED)


def test_closing_an_agreement_leaves_the_summary_readable(api):
    """PRD §3.1: "The summary also exposes the live
    `allocated_data_mb`, `remaining_data_mb`, `congestion_index` and `congestion_active`".

    Design: Corner/state_machines/agreement_close_retires_every_plan
    """
    set_clock()
    agreement = setup_active_agreement()
    offer_plan(
        create_plan(agreement["id"], plan_code="H3", data_allotment_mb=3000)["id"],
        current_agreement_version(agreement["id"]),
    )
    api.close_agreement(agreement["id"], TEST_USERS["planner_headers"])
    assert get_summary(agreement["id"])["allocated_data_mb"] == 0


def test_resolve_purchase_reports_each_leg_of_the_marginal_reading(api):
    """PRD §3.1: "The data leg, `data_volume_cost_microcents`, is
    the marginal reading of the `wholesale_volume_tier_cost` rule and is reported on its own".

    Design: Corner/endpoints/capacity_agreement_resolve_purchase_reports_the_marginal_tier_rate
    """
    set_clock()
    agreement = setup_active_agreement(
        host_network_name="Over Breakpoint Host", committed_data_mb=620000
    )
    resolved = api.resolve_purchase(
        agreement["id"], TEST_USERS["planner_headers"]
    ).json()["data"]
    assert resolved["data_volume_cost_microcents"] == 500000 * 1237 + 120000 * 1139
    assert resolved["marginal_tier_rate_microcents"] == 1139
    assert resolved["monthly_committed_cost_microcents"] == (
        resolved["data_volume_cost_microcents"] + 200000 * 60 + 400000 * 3
    )
    assert resolved["committed_volume_cost_microcents"] == resolved[
        "monthly_committed_cost_microcents"
    ]
    assert resolved["projected_overage_data_mb"] == 0
    assert resolved["projected_overage_cost_microcents"] == 0
    assert resolved["resolved_purchase_cost_microcents"] == resolved[
        "committed_volume_cost_microcents"
    ]


def test_a_cycle_roll_churns_a_subscriber_left_in_grace(api):
    """PRD §3.3: "if the
    subscriber is not resumed, the first cycle roll after they entered `GRACE` churns them automatically."

    Design: Corner/state_machines/subscriber_grace_to_churned_on_cycle_roll_without_remedy
    """
    set_clock()
    setup = setup_grace_subscriber()
    subscriber_id = setup["subscriber"]["id"]

    case = api.create_case(
        {"subscriber_id": subscriber_id, "topic_code": "PORT_STATUS"},
        TEST_USERS["agent_headers"],
    ).json()["data"]
    assert get_subscriber(subscriber_id)["subscriber_status"] == "GRACE"
    assert get_term(setup["term"]["id"])["term_status"] == "PURCHASED"

    run_cycle(subscriber_id)
    assert get_subscriber(subscriber_id)["subscriber_status"] == "CHURNED"
    churned = get_term(setup["term"]["id"])
    assert churned["term_status"] == "EXPIRED"
    assert churned["breakage_days"] == 30
    assert get_case(case["id"])["case_status"] == "CLOSED"
    assert get_summary(setup["agreement"]["id"])["allocated_data_mb"] == 0