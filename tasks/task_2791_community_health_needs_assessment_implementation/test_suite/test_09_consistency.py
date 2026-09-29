"""Consistency corners: derived figures are current in the write response and the next read."""

from test_helpers import (
    BOARD,
    COMPLIANCE,
    PUBLIC,
    ApprovalState,
    Category,
    CycleStatus,
    ExecutionState,
    ObjectiveStatus,
    Posture,
    PostingStatus,
    ReportStatus,
    ValuationBasis,
    assert_close,
    create_cycle,
    open_report,
    submitted_strategy,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_the_first_posting_response_already_carries_its_own_valuation(api):
    """PRD §3.9: "A new report starts with `status` at `OPEN` and `valuation_basis` at
    `PROVISIONAL`."

    PRD §3.9: "For a charge-based posting, `valued_cents` is the posting's `charges_cents`
    multiplied by the report's current `cost_to_charge_ratio`, rounded half up to a whole
    number of cents, and `ratio_applied` stores the exact ratio used."

    PRD §3.9: "All four of these figures are recomputed from scratch whenever the set of
    `POSTED` postings changes or the report's ratio changes."

    Design: Corner/consistency_model/every_derived_total_is_current_in_the_write_response_and_the_next_read
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    assert report["status"] == ReportStatus.OPEN
    assert report["valuation_basis"] == ValuationBasis.PROVISIONAL
    assert_close(report["cost_to_charge_ratio"], C.PRIOR_YEAR_RATIO, "cost_to_charge_ratio")
    assert_close(report["overhead_rate"], 0.05, "overhead_rate")
    assert report["total_valued_cents"] == 0
    assert_close(report["benefit_pct_of_expense"], 0.00, "benefit_pct_of_expense")
    version_at_open = report["version"]

    # The create response itself is already valued: nothing is deferred to a later read.
    posted = validate_success(
        api.create_posting(
            F.charge_based_posting_payload(
                report["id"], version_at_open, 1234567, category=Category.FINANCIAL_ASSISTANCE
            )
        ),
        201,
    )
    assert posted["valued_cents"] == 395061
    assert posted["status"] == PostingStatus.POSTED
    assert_close(posted["ratio_applied"], C.PRIOR_YEAR_RATIO, "ratio_applied")

    after_one = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    assert after_one["financial_assistance_cents"] == 395061
    assert after_one["subsidized_services_cents"] == 0
    assert after_one["total_valued_cents"] == 395061
    assert_close(after_one["overhead_rate"], 0.05, "overhead_rate")
    # 0.05 * 395061 = 19753.05 -> 19753; 395061 + 19753 = 414814.
    assert after_one["indirect_allocation_cents"] == 19753
    assert after_one["grand_total_cents"] == 414814
    # 414814 / 120000000 * 100 = 0.34568 -> 0.35.
    assert_close(after_one["benefit_pct_of_expense"], 0.35, "benefit_pct_of_expense")
    assert after_one["version"] == version_at_open + 1


def test_the_second_posting_lands_on_the_totals_the_first_one_left(api):
    """PRD §3.9: "The `total_valued_cents` is the sum of those five category totals."

    PRD §3.9: "The `indirect_allocation_cents` is the base multiplied by the selected
    `overhead_rate`, rounded half up to a whole number of cents, and `grand_total_cents` is
    the base plus that allocation."

    Design: Corner/consistency_model/every_derived_total_is_current_in_the_write_response_and_the_next_read
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    validate_success(
        api.create_posting(
            F.charge_based_posting_payload(
                report["id"], report["version"], 1234567, category=Category.FINANCIAL_ASSISTANCE
            )
        ),
        201,
    )
    after_one = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    version_after_one = after_one["version"]

    second = validate_success(
        api.create_posting(
            F.charge_based_posting_payload(
                report["id"], version_after_one, 500000, category=Category.SUBSIDIZED_SERVICES
            )
        ),
        201,
    )
    # 500000 * 0.32 = 160000 exactly.
    assert second["valued_cents"] == 160000

    after_two = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    assert after_two["financial_assistance_cents"] == 395061
    assert after_two["subsidized_services_cents"] == 160000
    assert after_two["total_valued_cents"] == 555061
    # Still below 5,000,000, so the tier is unchanged: 0.05 * 555061 = 27753.05 -> 27753.
    assert_close(after_two["overhead_rate"], 0.05, "overhead_rate")
    assert after_two["indirect_allocation_cents"] == 27753
    assert after_two["grand_total_cents"] == 582814
    # 582814 / 120000000 * 100 = 0.48568 -> 0.49.
    assert_close(after_two["benefit_pct_of_expense"], 0.49, "benefit_pct_of_expense")
    assert after_two["version"] == version_after_one + 1

    # A repeated read returns the same figures — nothing converges after the fact.
    again = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    assert again["total_valued_cents"] == 555061
    assert again["grand_total_cents"] == 582814
    assert again["version"] == after_two["version"]


def test_the_board_action_response_already_reports_the_adoption_it_records(api):
    """PRD §3.7: "On success the cycle's `status` moves `BOARD_REVIEW` to `ADOPTED`;
    `adopted_at` is stamped from the logical clock, `adoption_board_user_id` records the
    acting `X-User-ID`, and `votes_for_at_adoption` and `votes_against_at_adoption` preserve
    the tallies exactly as recorded."

    PRD §3.7: "The cycle's `posture` is then recomputed, becoming `OPEN` when
    `review_flag_count` is 0."

    Design: Corner/consistency_model/cascade_results_are_visible_to_the_next_read_with_no_settling_period
    """
    sc = submitted_strategy(api)
    assert sc.cycle()["posture"] == Posture.RESTRICTED

    adopted = validate_success(
        api.board_action(
            sc.cycle_id,
            F.board_action_payload(quorum_present=True, votes_for=9, votes_against=2),
            headers=BOARD,
        )
    )
    assert adopted["status"] == CycleStatus.ADOPTED
    assert adopted["votes_for_at_adoption"] == 9
    assert adopted["votes_against_at_adoption"] == 2
    assert adopted["adoption_board_user_id"] == BOARD["X-User-ID"]
    assert adopted["adopted_at"] is not None
    assert adopted["review_flag_count"] == 0
    assert adopted["posture"] == Posture.OPEN

    # The very next read agrees with the write response, field for field.
    read_back = sc.cycle()
    assert read_back["status"] == CycleStatus.ADOPTED
    assert read_back["posture"] == Posture.OPEN
    assert read_back["votes_for_at_adoption"] == 9
    assert read_back["votes_against_at_adoption"] == 2


def test_the_first_read_after_adoption_shows_the_whole_cascade_settled(api):
    """PRD §3.7: "**Link one — strategies are approved.** Every implementation strategy
    reachable from the cycle whose `approval_state` is `SUBMITTED` moves to `APPROVED` and has
    `approved_at` stamped from the logical clock."

    PRD §3.7: "In the same link, that strategy's `execution_state` moves `NOT_STARTED` to
    `ON_TRACK`, provided at least one of its objectives actually moved from `DRAFT` to
    `ACTIVE`; the delivery axis begins running only when there is something measurable to run
    against, and the `approval_state` axis is not touched a second time."

    PRD §3.7: "For each strategy that link one just moved to `APPROVED`, every objective of
    that strategy whose `status` is `DRAFT` moves to `ACTIVE` and has `baseline_locked_at`
    stamped from the logical clock, at which point that objective's `baseline_value` becomes
    immutable — a strategy cannot be judged against a baseline it is allowed to move."

    Design: Corner/consistency_model/cascade_results_are_visible_to_the_next_read_with_no_settling_period
    """
    sc = submitted_strategy(api)
    validate_success(
        api.board_action(
            sc.cycle_id,
            F.board_action_payload(quorum_present=True, votes_for=9, votes_against=2),
            headers=BOARD,
        )
    )

    # First read after the cascade: no intermediate or stale values.
    strategy = validate_success(api.get_strategy(sc.strategy_id, headers=BOARD))
    assert strategy["approval_state"] == ApprovalState.APPROVED
    assert strategy["execution_state"] == ExecutionState.ON_TRACK
    assert strategy["approved_at"] is not None
    assert strategy["active_objective_count"] == 1

    objective = validate_success(api.get_objective(sc.objective_id, headers=BOARD))
    assert objective["status"] == ObjectiveStatus.ACTIVE
    assert objective["baseline_locked_at"] is not None
    assert objective["baseline_value"] == C.OBJECTIVE_BASELINE_VALUE
    assert objective["target_value"] == C.OBJECTIVE_TARGET_VALUE

    # A different role's read sees exactly the same state — there is no per-reader convergence.
    public_view = validate_success(api.get_cycle(sc.cycle_id, headers=PUBLIC))
    assert public_view["status"] == CycleStatus.ADOPTED
    assert public_view["public_availability_met"] is False
