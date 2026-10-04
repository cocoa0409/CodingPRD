"""Pool draw-down consistency: the state-before-fiscal order, the inclusive
pool boundary, the double-void guard, and the computed prizing summary."""
from test_helpers import (
    TEST_USERS,
    api_client,
    file_report,
    get_allocation,
    get_distribution,
    pass_distribution,
    propose_distribution,
    setup_application,
    setup_completed_application,
    suspend_store,
    validate_error,
    validate_success,
    void_distribution,
)


def test_a_pass_on_a_released_allocation_is_refused_as_a_state_error(api):
    """PRD §2.12: "Within the state-and-business band, the state rungs fire before
    the business rungs: an operation attempted from the wrong starting state is
    rejected as `ERR_INVALID_STATE` rather than being evaluated against the
    commercial constraints that would also have blocked it."

    Design: Difficulty/priority_pair_validation_conflict/released_allocation_outranks_insufficient_pool
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")

    # A draw larger than the 16-point pool, so the fiscal rule would also fail.
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=99, recipient_ref="PLAYER-99"
    )
    suspend_store(store["id"])
    assert get_allocation(allocation["id"])["status"] == "RELEASED"

    refused = api_client.transition_prize_distribution(
        distribution["id"], {"action": "PASS"}, TEST_USERS["ops_admin_headers"]
    )
    validate_error(refused, "ERR_INVALID_STATE", expected_status=409)


def test_the_refused_pass_leaves_the_distribution_and_the_pool_untouched(api):
    """PRD §2.12: "Within the state-and-business band, the state rungs fire before
    the business rungs: an operation attempted from the wrong starting state is
    rejected as `ERR_INVALID_STATE` rather than being evaluated against the
    commercial constraints that would also have blocked it."
    PRD §3.5: "A prize distribution attached to a pool begins `PROPOSED` and draws
    nothing until it passes"

    Design: Difficulty/priority_pair_validation_conflict/released_allocation_outranks_insufficient_pool
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=99, recipient_ref="PLAYER-98"
    )
    suspend_store(store["id"])

    refused = api_client.transition_prize_distribution(
        distribution["id"], {"action": "PASS"}, TEST_USERS["ops_admin_headers"]
    )
    validate_error(refused, "ERR_INVALID_STATE", expected_status=409)

    assert refused.status_code != 402, (
        "the fiscal rejection would have been ERR_INSUFFICIENT_POOL at 402"
    )
    assert get_distribution(distribution["id"])["status"] == "PROPOSED"
    released = get_allocation(allocation["id"])
    assert released["total_drawn_tp"] == 0
    assert released["status"] == "RELEASED"


def test_a_draw_of_exactly_the_remaining_balance_is_legal_and_leaves_zero(api):
    """PRD §3.5: "Passing it is permitted only while the pool is still `OPEN` and
    only when the quantity being drawn does not exceed the pool's current
    `remaining_tp` — a draw of exactly the whole remaining balance is legal and
    leaves the balance at zero, while anything larger is rejected with
    `ERR_INSUFFICIENT_POOL`."

    Design: Corner/errors/insufficient_pool_boundary_at_exact_remaining_is_legal
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER"
    )
    exact = propose_distribution(
        allocation["id"], store["id"], quantity=48, recipient_ref="PLAYER-EXACT"
    )

    after = pass_distribution(exact["id"])
    assert after is not None

    pool = get_allocation(allocation["id"])
    assert pool["remaining_tp"] == 0
    assert pool["total_drawn_tp"] == 48
    assert get_distribution(exact["id"])["status"] == "PASSED"


def test_a_draw_one_point_over_the_balance_is_refused_without_a_draw(api):
    """PRD §3.5: "a draw of exactly the whole remaining balance is legal and
    leaves the balance at zero, while anything larger is rejected with
    `ERR_INSUFFICIENT_POOL`."

    Design: Corner/errors/insufficient_pool_boundary_at_exact_remaining_is_legal
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER"
    )
    exact = propose_distribution(
        allocation["id"], store["id"], quantity=48, recipient_ref="PLAYER-EXACT2"
    )
    over = propose_distribution(
        allocation["id"], store["id"], quantity=49, recipient_ref="PLAYER-OVER"
    )

    pass_distribution(exact["id"])

    refused = api_client.transition_prize_distribution(
        over["id"], {"action": "PASS"}, TEST_USERS["ops_admin_headers"]
    )
    validate_error(refused, "ERR_INSUFFICIENT_POOL", expected_status=402)

    pool = get_allocation(allocation["id"])
    assert pool["remaining_tp"] == 0
    assert pool["total_drawn_tp"] == 48
    assert get_distribution(over["id"])["status"] == "PROPOSED"


def test_a_second_void_on_an_already_voided_distribution_is_refused(api):
    """PRD §3.5: "Attempting to void a distribution that is already `VOIDED` is
    rejected with `ERR_INVALID_STATE`, since the first void already performed its
    compensating restore and a second one would double-count the movement."

    Design: Difficulty/compensating_invariant/pool_points_conserved_across_pass_void_pair
    """
    store, _set_release, _fmt, application, allocation = setup_application(
        tier="QUALIFIER"
    )
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=20, recipient_ref="PLAYER-TWICE"
    )
    pass_distribution(distribution["id"])
    void_distribution(distribution["id"])
    assert get_allocation(allocation["id"])["total_restored_tp"] == 20

    refused = api_client.transition_prize_distribution(
        distribution["id"], {"action": "VOID"}, TEST_USERS["ops_admin_headers"]
    )
    validate_error(refused, "ERR_INVALID_STATE", expected_status=409)

    pool = get_allocation(allocation["id"])
    assert pool["total_restored_tp"] == 20, "the movement is not double-counted"
    assert pool["remaining_tp"] == 48


def test_the_prizing_summary_moves_with_the_pool_it_reports(api):
    """PRD §3.13: "It reports the application's reporting deadline as
    `reporting_due_by`; a `reporting_due_status` drawn from exactly three values,
    `NOT_SCHEDULED` when no deadline applies, `OPEN` while the logical clock is at
    or before the deadline, and `PAST_DUE` once the clock has passed it; a
    `qualified_headcount` boolean; the pool's live balance as
    `prize_pool_remaining_tp`; a `report_status` that is `NOT_FILED` or `FILED`"
    PRD §3.13: "A headcount of exactly twenty-four qualifies — the comparison
    admits equality"

    Design: Corner/endpoints/prizing_summary_computed_read_matches_pool_state
    """
    store, _set_release, _fmt, application, allocation = setup_completed_application(
        tier="QUALIFIER"
    )
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=20, recipient_ref="PLAYER-20B"
    )
    pass_distribution(distribution["id"])
    file_report(
        application["id"], allocation["id"], store["id"],
        unclaimed_tp=4, reported_headcount=31,
    )

    summary = validate_success(
        api_client.get_prizing_summary(application["id"], TEST_USERS["judge_headers"]),
        200,
    )
    assert summary["reporting_due_by"] == "2026-10-06T00:00:00Z"
    assert summary["reporting_due_status"] == "OPEN"
    assert summary["qualified_headcount"] is True
    assert summary["headcount_gate_error"] is None
    assert summary["report_status"] == "FILED"
    assert summary["prize_pool_remaining_tp"] == 32, (
        "base 48 minus 20 drawn plus 4 restored"
    )


def test_an_unreported_event_surfaces_the_gate_as_unset_rather_than_failed(api):
    """PRD §3.13: "Applications that have no submitted report at all are not
    evaluated against the gate: they surface as `NOT_FILED` in the read's report
    status rather than as a gate failure."
    PRD §3.13: "a `reporting_due_status` drawn from exactly three values,
    `NOT_SCHEDULED` when no deadline applies, `OPEN` while the logical clock is at
    or before the deadline, and `PAST_DUE` once the clock has passed it"

    Design: Corner/endpoints/prizing_summary_reports_not_filed_gate_for_unreported_events
    """
    store, _set_release, _fmt, application, allocation = setup_completed_application(
        tier="QUALIFIER"
    )

    summary = validate_success(
        api_client.get_prizing_summary(application["id"], TEST_USERS["judge_headers"]),
        200,
    )
    assert summary["report_status"] == "NOT_FILED"
    assert summary["reporting_due_status"] == "OPEN", (
        "the deadline is 2026-10-06 and the clock is still inside the window"
    )
    assert summary["qualified_headcount"] is False
    assert summary["headcount_gate_error"] is None, (
        "the gate is unset rather than failed when no report exists"
    )
    assert summary["prize_pool_remaining_tp"] == 48

def test_a_pass_is_refused_once_the_owning_store_has_been_suspended(api):
    """PRD §3.5: "Passing it is permitted only while the pool is still `OPEN` and
    only when the quantity being drawn does not exceed the pool's current
    `remaining_tp`"
    PRD §3.1: "Every still-open allocation of the store is released, and every
    distribution that had passed under those allocations is voided, with each
    affected allocation's `total_restored_tp` re-derived from the voided
    distributions and the submitted reports rather than incremented, so the
    conserved invariant lands back on the figure it held before the allocation's
    first draw."

    Design: Difficulty/cross_entity_state_dependency/store_must_be_active_before_distributions_can_pass
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=5, recipient_ref="PLAYER-5"
    )

    suspend_store(store["id"])
    assert get_allocation(allocation["id"])["status"] == "RELEASED"

    refused = api_client.transition_prize_distribution(
        distribution["id"], {"action": "PASS"}, TEST_USERS["ops_admin_headers"]
    )
    validate_error(refused, "ERR_INVALID_STATE", expected_status=409)

    assert get_distribution(distribution["id"])["status"] == "PROPOSED"
    assert get_allocation(allocation["id"])["total_drawn_tp"] == 0


def test_the_identical_pass_is_legal_while_the_store_is_still_active(api):
    """PRD §3.5: "Passing it is permitted only while the pool is still `OPEN` and
    only when the quantity being drawn does not exceed the pool's current
    `remaining_tp` — a draw of exactly the whole remaining balance is legal and
    leaves the balance at zero, while anything larger is rejected with
    `ERR_INSUFFICIENT_POOL`."
    PRD §3.1: "Every still-open allocation of the store is released, and every
    distribution that had passed under those allocations is voided, with each
    affected allocation's `total_restored_tp` re-derived from the voided
    distributions and the submitted reports rather than incremented, so the
    conserved invariant lands back on the figure it held before the allocation's
    first draw."

    Design: Difficulty/cross_entity_state_dependency/store_must_be_active_before_distributions_can_pass
    """
    store, _set_release, _fmt, application, allocation = setup_application(tier="LOCAL")
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=5, recipient_ref="PLAYER-5B"
    )

    accepted = api_client.transition_prize_distribution(
        distribution["id"], {"action": "PASS"}, TEST_USERS["ops_admin_headers"]
    )
    validate_success(accepted, 200)
    pool = get_allocation(allocation["id"])
    assert pool["status"] == "OPEN"
    assert pool["total_drawn_tp"] == 5
    assert pool["remaining_tp"] == 11
