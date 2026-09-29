"""
State machines that are not straight lines: two independent dimensions on one
breeding line, and a re-enterable review loop on a stewardship agreement.
"""

from test_helpers import (
    DIRECTOR_HEADERS,
    REGULATORY_APPROVER_HEADERS,
    REGULATORY_APPROVER_USER_ID,
    REGULATORY_HEADERS,
    AdvancementReadiness,
    AgreementStatus,
    ApiErrorId,
    DecisionType,
    PipelineStage,
    StewardshipStatus,
    approx2,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _approved_line_ready_to_advance(api):
    """Line A holding an APPROVED stewardship package against an ANALYZED series."""
    net = fixtures.single_site_data_complete(api)
    agreement = fixtures.approved_agreement(api, net.line_a_id)
    fixtures.run_analysis(api, net.series_id)
    net.agreement_id = agreement["id"]
    return net


def test_advance_moves_the_stage_and_leaves_stewardship_alone(api):
    """
    The two dimensions of a breeding line are independent, so a stage transition
    must not disturb an APPROVED stewardship status.

    PRD 2.10: "Two state dimensions on a `BreedingLine` illustrate how
    independent the derived machinery is: `pipeline_stage` is driven only by
    advancement decisions and `stewardship_status` only by stewardship agreement
    transitions."
    PRD 2.10: "Neither gates the other's transitions, so the combinations
    `STAGE_2` with `SUSPENDED`, `PRE_COMMERCIAL` with `NOT_REQUIRED`, and
    `STAGE_1` with `APPROVED` are all legal simultaneous states."
    PRD 3.8: "On success the stage moves, `granted_plots` is added to the
    programme's `committed_plot_count` with `plot_budget_remaining` recomputed,
    and the line's `advancement_readiness` is reset to `NOT_READY` for the next
    stage."

    Design: Difficulty/non_linear_state_machine/line_parallel_dimensions_advance_without_disturbing_stewardship
    """
    net = _approved_line_ready_to_advance(api)
    before = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert before["pipeline_stage"] == PipelineStage.NURSERY
    assert before["stewardship_status"] == StewardshipStatus.APPROVED

    decision = fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.ADVANCE,
        granted_plots=40,
        rationale="clears the bar at 91.40",
    )

    line = validate_success(api.get_line(net.line_a_id, DIRECTOR_HEADERS))
    assert line["pipeline_stage"] == PipelineStage.STAGE_1
    assert line["stewardship_status"] == StewardshipStatus.APPROVED
    assert line["advancement_readiness"] == AdvancementReadiness.NOT_READY
    assert line["generation_number"] == 6
    assert decision["from_stage"] == PipelineStage.NURSERY
    assert decision["to_stage"] == PipelineStage.STAGE_1
    # 0.50*109.09 + 0.30*100.00 + 0.20*85.00 = 101.55, then 101.55 * 0.90.
    assert decision["decision_index_value"] == approx2(91.40)


def test_advance_books_the_granted_plots_without_touching_the_agreement(api):
    """
    The plot budget moves and the agreement record does not.

    PRD 3.8: "Every rung additionally requires that the frozen CUMULATIVE index
    reach the objective's `min_advancement_index`, failing which the decision is
    refused with `ERR_INDEX_BELOW_THRESHOLD`, and that `granted_plots` fit inside
    the programme's `plot_budget_remaining`, failing which it is refused with
    `ERR_PROGRAM_PLOT_BUDGET_EXCEEDED`."

    Design: Difficulty/non_linear_state_machine/line_parallel_dimensions_advance_without_disturbing_stewardship
    """
    net = _approved_line_ready_to_advance(api)
    fixtures.record_decision(
        api,
        net.line_a_id,
        net.series_id,
        decision=DecisionType.ADVANCE,
        granted_plots=40,
    )

    program = validate_success(api.get_program(net.program_id, DIRECTOR_HEADERS))
    # 8 + 8 entry plots plus the 40 granted to the advancing line.
    assert program["committed_plot_count"] == 56
    assert program["plot_budget_remaining"] == 4944

    agreement = validate_success(api.get_agreement(net.agreement_id, REGULATORY_HEADERS))
    assert agreement["status"] == AgreementStatus.APPROVED
    assert agreement["revision_round"] == 0


def _agreement_after_two_change_requests(api):
    """A DRAFT agreement driven twice around the SUBMITTED/CHANGES_REQUESTED loop."""
    program_id, objective_id = fixtures.program_with_objective(
        api, program_overrides={"name": "Soy Cycle"}
    )
    line = fixtures.create_line(
        api, program_id, objective_id, designation="SX-4001", seed_inventory_g=300000
    )
    agreement = validate_success(
        api.create_agreement(
            line["id"],
            factories.agreement_payload(
                regulatory_dossier_ref="DOS-2852-03",
                grower_agreement_ref="GA-2852-03",
            ),
            REGULATORY_HEADERS,
        ),
        201,
    )
    first = validate_success(api.submit_agreement(agreement["id"], REGULATORY_HEADERS))
    assert first["revision_round"] == 0
    validate_success(
        api.review_agreement(
            agreement["id"],
            factories.request_changes_payload("add the MX_BAJIO refuge annex"),
            REGULATORY_APPROVER_HEADERS,
        )
    )
    validate_success(api.submit_agreement(agreement["id"], REGULATORY_HEADERS))
    validate_success(
        api.review_agreement(
            agreement["id"],
            factories.request_changes_payload(
                "grower agreement countersignature missing"
            ),
            REGULATORY_APPROVER_HEADERS,
        )
    )
    return line["id"], agreement["id"]


def test_only_the_changes_requested_edge_bumps_the_revision_round(api):
    """
    Two passes around the loop leave `revision_round` at 2, because the first
    edge into SUBMITTED came from DRAFT and did not count.

    PRD 3.9: "Submitting an agreement moves it `DRAFT → SUBMITTED` and stamps
    `submitted_by_user_id` with the acting `X-User-ID`, leaving `revision_round`
    at 0 on that first pass; the line must not be `DISCARDED`."
    PRD 3.9: "Re-submitting from there is the cycle edge `CHANGES_REQUESTED →
    SUBMITTED`: it advances `revision_round` by one, clears `requested_changes`
    back to null, and refreshes `submitted_by_user_id`."

    Design: Difficulty/non_linear_state_machine/agreement_submit_changes_requested_cycle_bumps_revision_round
    """
    _line_id, agreement_id = _agreement_after_two_change_requests(api)

    second_pass = validate_success(api.submit_agreement(agreement_id, REGULATORY_HEADERS))
    assert second_pass["revision_round"] == 2
    assert second_pass["requested_changes"] is None
    assert second_pass["status"] == AgreementStatus.SUBMITTED

    approved = validate_success(
        api.review_agreement(
            agreement_id, factories.review_payload(), REGULATORY_APPROVER_HEADERS
        )
    )
    assert approved["status"] == AgreementStatus.APPROVED
    assert approved["revision_round"] == 2
    assert approved["requested_changes"] is None
    assert approved["approved_by_user_id"] == REGULATORY_APPROVER_USER_ID


def test_the_line_stays_pending_through_the_loop_and_approval_closes_it(api):
    """
    Every pass through the review loop leaves the parent line at PENDING, and
    once APPROVED the agreement is outside the loop entirely.

    PRD 3.9: "A `REQUEST_CHANGES` outcome requires `requested_changes` to be a
    non-empty string, moves the agreement `SUBMITTED → CHANGES_REQUESTED`, stores
    that text, and leaves the line's `stewardship_status` at `PENDING`."
    PRD 3.9: "An `APPROVE` outcome moves the agreement `SUBMITTED → APPROVED`,
    stamps `approved_by_user_id` with the approver's `X-User-ID`, and flips the
    line's `stewardship_status` to `APPROVED` with the line's `version`
    incrementing."

    Design: Difficulty/non_linear_state_machine/agreement_submit_changes_requested_cycle_bumps_revision_round
    """
    line_id, agreement_id = _agreement_after_two_change_requests(api)

    mid_loop = validate_success(api.get_line(line_id, DIRECTOR_HEADERS))
    assert mid_loop["stewardship_status"] == StewardshipStatus.PENDING

    validate_success(api.submit_agreement(agreement_id, REGULATORY_HEADERS))
    validate_success(
        api.review_agreement(
            agreement_id, factories.review_payload(), REGULATORY_APPROVER_HEADERS
        )
    )
    line = validate_success(api.get_line(line_id, DIRECTOR_HEADERS))
    assert line["stewardship_status"] == StewardshipStatus.APPROVED

    validate_error(
        api.submit_agreement(agreement_id, REGULATORY_HEADERS),
        ApiErrorId.AGREEMENT_INVALID_STATE,
        409,
    )
