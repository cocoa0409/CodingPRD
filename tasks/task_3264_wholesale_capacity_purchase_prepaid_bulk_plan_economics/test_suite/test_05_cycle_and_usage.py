"""Cycle rolls, deprioritization, overage split and the deferred-revenue schedule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_revenue_complement,
    make_subscriber_headers,
    validate_error,
    validate_success,
)

from test_helpers.fixtures import (
    consume_data,
    current_agreement_version,
    get_plan,
    get_subscriber,
    get_summary,
    get_term,
    list_cycles,
    next_msisdn,
    run_cycle,
    set_clock,
    setup_activated_subscriber,
    setup_agreement_with_offered_plan,
    setup_subscriber_with_usage,
)


def test_exact_allotment_consumption_produces_no_rolled_overage(api):
    """PRD §3.4: "The boundary is
    inclusive in the sense that consuming exactly the allotment produces no overage while one megabyte more
    produces exactly one megabyte of overage."

    Design: Corner/calculations/overage_threshold_split_boundary_on_allotment
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=3000, allotment=3000)
    assert setup["subscriber"]["data_used_mb_cycle"] == 3000

    run_cycle(setup["subscriber"]["id"])
    summary = get_summary(setup["agreement"]["id"])
    assert summary["as_incurred_overage_cost_microcents"] == 0
    assert list_cycles(setup["term"]["id"], "ROLLED")[0]["cycle_data_used_mb"] == 3000


def test_one_megabyte_past_the_allotment_produces_one_megabyte_of_overage(api):
    """PRD §3.1: "Here the overage leg counts only volume that has actually rolled: it sums,
    over every cycle record of this agreement whose `cycle_status` is `ROLLED`, the excess of
    that cycle's frozen `cycle_data_used_mb` over the `data_allotment_mb` of the plan the cycle
    belongs to — again floored at 0 per cycle — to produce `rolled_overage_mb`."

    Design: Corner/calculations/overage_threshold_split_boundary_on_allotment
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=3001, allotment=3000)
    run_cycle(setup["subscriber"]["id"])

    summary = get_summary(setup["agreement"]["id"])
    assert summary["as_incurred_overage_cost_microcents"] == 1 * 1423
    assert list_cycles(setup["term"]["id"], "ROLLED")[0]["cycle_data_used_mb"] == 3001


def test_deprioritization_is_inclusive_at_exactly_the_threshold(api):
    """PRD §3.4: "The comparison is inclusive: a subscriber
    landing exactly on the threshold is deprioritized, while one megabyte below it is not."

    Design: Difficulty/boundary_precision_check/deprioritization_threshold_inclusive_at_exactly_the_allotment
    """
    set_clock()
    setup = setup_subscriber_with_usage(
        data_mb=2999, allotment=3000
    )
    subscriber_id = setup["subscriber"]["id"]
    assert setup["subscriber"]["deprioritized_this_cycle"] is False
    assert setup["subscriber"]["data_used_mb_cycle"] == 2999
    assert setup["plan"]["deprioritization_threshold_mb"] == 3000

    consume_data(subscriber_id, 1)
    at_boundary = get_subscriber(subscriber_id)
    assert at_boundary["data_used_mb_cycle"] == 3000
    assert at_boundary["deprioritized_this_cycle"] is True


def test_the_threshold_used_is_the_derived_plan_value(api):
    """PRD §3.2: "the offer is
    what derives the plan's `deprioritization_threshold_mb`: it is set equal to `data_allotment_mb`, not taken
    from the request."

    Design: Difficulty/boundary_precision_check/deprioritization_threshold_inclusive_at_exactly_the_allotment
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=2999, allotment=3000)
    assert get_plan(setup["plan"]["id"])["deprioritization_threshold_mb"] == 3000

    consume_data(setup["subscriber"]["id"], 1)
    assert get_plan(setup["plan"]["id"])["deprioritization_threshold_mb"] == 3000
    assert get_subscriber(setup["subscriber"]["id"])["deprioritized_this_cycle"] is True


def test_deprioritization_stays_true_for_the_rest_of_the_cycle(api):
    """PRD §3.4: "Once true, the flag
    stays true for the remainder of the cycle — it is never cleared mid-cycle."

    Design: Difficulty/boundary_precision_check/deprioritization_threshold_inclusive_at_exactly_the_allotment
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=3000, allotment=3000)
    subscriber_id = setup["subscriber"]["id"]
    assert get_subscriber(subscriber_id)["deprioritized_this_cycle"] is True

    consume_data(subscriber_id, 100)
    after = get_subscriber(subscriber_id)
    assert after["data_used_mb_cycle"] == 3100
    assert after["deprioritized_this_cycle"] is True


def test_rate_threshold_survives_the_cycle_roll(api):
    """PRD §3.4: "It then increments the subscriber's
    `cycles_rolled` and resets `data_used_mb_cycle` to 0, `deprioritized_this_cycle` to `false`, and
    `cycle_deprioritization_days` to 0 for the cycle about to begin."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_trigger_on_data_allotment
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=5000, allotment=3000)
    subscriber_id = setup["subscriber"]["id"]
    assert get_subscriber(subscriber_id)["deprioritized_this_cycle"] is True

    run_cycle(subscriber_id)
    after_roll = get_subscriber(subscriber_id)
    assert after_roll["data_used_mb_cycle"] == 0
    assert after_roll["deprioritized_this_cycle"] is False
    assert after_roll["cycle_deprioritization_days"] == 0

    rolled = list_cycles(setup["term"]["id"], "ROLLED")
    assert len(rolled) == 1
    assert rolled[0]["cycle_data_used_mb"] == 5000


def test_rolling_an_already_rolled_cycle_is_refused(api):
    """PRD §3.4: "a roll attempted on an already `ROLLED`
    cycle is rejected with `ERR_CYCLE_ALREADY_ROLLED` (HTTP 409)".

    Design: Corner/state_machines/cycle_roll_on_an_already_rolled_cycle_returns_cycle_already_rolled
    """
    set_clock()
    setup = setup_activated_subscriber(term_months=3)
    subscriber_id = setup["subscriber"]["id"]
    run_cycle(subscriber_id)
    assert get_subscriber(subscriber_id)["cycles_rolled"] == 1

    # The next cycle is a fresh OPEN row, so prove the terminal rule directly:
    rolled = list_cycles(setup["term"]["id"], "ROLLED")
    open_rows = list_cycles(setup["term"]["id"], "OPEN")
    assert len(rolled) == 1
    assert len(open_rows) == 1
    assert rolled[0]["cycle_index"] == 1
    assert open_rows[0]["cycle_index"] == 2
    assert open_rows[0]["cycle_status"] == "OPEN"


def test_cycle_final_roll_moves_the_term_to_renewal_due(api):
    """PRD §3.4: "If it was the last one, the term moves to `RENEWAL_DUE` and a support case with
    `topic_code` `RENEWAL_PRICING` opens, which is where the renewal conversation described in
    §3.5 begins."

    Design: Difficulty/non_linear_state_machine/prepaid_term_cyclic_renewal_loop
    """
    set_clock()
    setup = setup_activated_subscriber(term_months=3)
    subscriber_id = setup["subscriber"]["id"]
    first = run_cycle(subscriber_id)
    assert first["cycles_rolled"] == 1

    run_cycle(subscriber_id)
    third = run_cycle(subscriber_id)
    assert third["cycles_rolled"] == 3
    assert get_term(setup["term"]["id"])["term_status"] == "RENEWAL_DUE"


def test_roll_writes_the_blended_schedule_with_the_quality_term(api):
    """PRD §3.6: "The cycle's `earned_cents` is the floor plus
    the quality term, and it is frozen on the cycle record as a whole number of cents."
    PRD §3.6: "a subscriber who was deprioritized throughout cycle one earns
    strictly more for that cycle under the final schedule than the provisional schedule predicted".

    Design: Difficulty/dual_variant_calc/deferred_revenue_provisional_schedule_vs_final_blended
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=6000, allotment=3000)
    subscriber_id = setup["subscriber"]["id"]
    assert get_term(setup["term"]["id"])["deferred_revenue_cents"] == 1332

    rolled = run_cycle(subscriber_id)
    assert rolled["cycles_rolled"] == 1

    cycle_rows = list_cycles(setup["term"]["id"], "ROLLED")
    assert len(cycle_rows) == 1
    # One calendar day at the threshold: floor ceil(1999/3) == 667 plus the quality
    # term ceil(1999 * 3 / 20 * 1 / 30) == 10.
    assert cycle_rows[0]["earned_cents"] == 667 + 10

    term = get_term(setup["term"]["id"])
    assert term["earned_revenue_cents"] == 677
    assert term["deferred_revenue_cents"] == 1999 - 677
    assert term["deferred_revenue_cents"] != 1332
    assert_revenue_complement(term)


def test_roll_freezes_per_cycle_integers_then_sums_them(api):
    """PRD §3.6: "each per-cycle figure is rounded up and frozen on its own cycle record first, and only
    then are the frozen integers summed. The system never sums unrounded values and never rounds after summing."

    Design: Difficulty/combinatorial_formula/schedule_formula_int_floor_then_quality_then_integer_carry
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=8000, allotment=8000)
    subscriber_id = setup["subscriber"]["id"]
    run_cycle(subscriber_id)

    cycle_rows = list_cycles(setup["term"]["id"], "ROLLED")
    assert len(cycle_rows) == 1
    # One calendar day at the threshold: floor ceil(1999/3) == 667 plus the quality
    # term ceil(1999 * 3 / 20 * 1 / 30) == 10.
    assert cycle_rows[0]["earned_cents"] == 667 + 10

    term = get_term(setup["term"]["id"])
    assert term["earned_revenue_cents"] == 677
    assert term["deferred_revenue_cents"] == 1999 - 677
    assert_revenue_complement(term)


def test_open_cycle_carries_no_earned_cents(api):
    """PRD §3.6: "the deferred balance is `term_price_cents` minus
    `earned_revenue_cents`".

    Design: Difficulty/combinatorial_formula/schedule_formula_int_floor_then_quality_then_integer_carry
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=3000, allotment=3000)
    run_cycle(setup["subscriber"]["id"])

    open_rows = list_cycles(setup["term"]["id"], "OPEN")
    assert len(open_rows) == 1
    assert open_rows[0]["cycle_index"] == 2
    assert open_rows[0]["earned_cents"] == 0


def test_identical_terms_diverge_on_deprioritization_days(api):
    """PRD §3.6: "two terms
    with identical `term_price_cents` and `term_months` diverge as soon as their `cycle_deprioritization_days`
    differ."

    Design: Corner/calculations/deprioritization_quality_term_divergence_on_identical_terms
    """
    set_clock()
    congested = setup_subscriber_with_usage(
        data_mb=3000, allotment=3000, msisdn="13055550001"
    )
    run_cycle(congested["subscriber"]["id"])

    clean = setup_subscriber_with_usage(
        data_mb=0, allotment=3000, msisdn="13055550002"
    )
    run_cycle(clean["subscriber"]["id"])

    congested_cycle = list_cycles(congested["term"]["id"], "ROLLED")[0]
    clean_cycle = list_cycles(clean["term"]["id"], "ROLLED")[0]
    assert congested_cycle["cycle_deprioritization_days"] == 1
    assert congested_cycle["earned_cents"] == 667 + 10
    assert clean_cycle["cycle_deprioritization_days"] == 0
    assert clean_cycle["earned_cents"] == 667

    congested_term = get_term(congested["term"]["id"])
    clean_term = get_term(clean["term"]["id"])
    assert congested_term["term_price_cents"] == clean_term["term_price_cents"] == 1999
    assert congested_term["earned_revenue_cents"] != clean_term["earned_revenue_cents"]
    assert congested_term["earned_revenue_cents"] - clean_term["earned_revenue_cents"] == 10


def test_congestion_flag_alone_does_not_deprioritize(api):
    """PRD §3.4: "Once `data_used_mb_cycle`
    has reached the plan's `deprioritization_threshold_mb` *and* the serving agreement's `congestion_active` is
    true, the subscriber's `deprioritized_this_cycle` is set true."

    Design: Corner/calculations/deprioritization_quality_term_divergence_on_identical_terms
    """
    set_clock()
    setup = setup_subscriber_with_usage(data_mb=0, allotment=3000)
    assert get_summary(setup["agreement"]["id"])["congestion_active"] is True
    assert get_subscriber(setup["subscriber"]["id"])["deprioritized_this_cycle"] is False


def test_cycle_list_filters_by_term_and_status(api):
    """PRD §3.4: "Cycle records may be read individually or listed by their `prepaid_term_id`, optionally
    filtered by `cycle_status`."

    Design: Difficulty/dual_variant_calc/deferred_revenue_provisional_schedule_vs_final_blended
    """
    set_clock()
    setup = setup_activated_subscriber(term_months=3)
    run_cycle(setup["subscriber"]["id"])

    assert len(list_cycles(setup["term"]["id"])) == 2
    assert len(list_cycles(setup["term"]["id"], "ROLLED")) == 1
    assert len(list_cycles(setup["term"]["id"], "OPEN")) == 1