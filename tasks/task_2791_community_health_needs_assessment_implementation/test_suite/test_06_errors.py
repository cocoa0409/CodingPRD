"""Error corners: the rejection ladder from the identity headers down to filing."""

from test_helpers import (
    BOARD,
    COMPLIANCE,
    OFFICER,
    OFFICER_2,
    NON_EXISTENT_UUID,
    ApiErrorId,
    ApprovalState,
    BoardActionType,
    CandidateStatus,
    CycleStatus,
    EvalType,
    IndicatorDomain,
    InterviewStatus,
    Posture,
    ReportStatus,
    ScoringVariant,
    add_candidate,
    add_evaluation,
    add_indicator,
    add_interview,
    advance_to,
    assert_close,
    build_scenario,
    complete_interview,
    create_cycle,
    finalize_report,
    make_indicator_sufficient,
    open_report,
    post_charge_based,
    publish_cycle,
    score_candidate,
    select_candidate,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_a_read_with_either_identity_header_missing_is_unauthenticated(api):
    """PRD §2.1: "Every request to every endpoint — reads included — must carry two
    headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
    role that user is acting in."

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the six
    role names declared below, the request is rejected with `ERR_UNAUTHENTICATED` and
    HTTP 401."

    Design: Corner/errors/missing_or_unknown_role_headers_return_unauthenticated
    """
    cycle = create_cycle(api)
    path = f"/assessment-cycles/{cycle['id']}"

    # The same read, properly identified, is a plain 200.
    baseline = validate_success(api.raw("GET", path, headers=dict(OFFICER)))
    assert baseline["id"] == cycle["id"]

    no_role = {k: v for k, v in OFFICER.items() if k != "X-User-Role"}
    validate_error(api.raw("GET", path, headers=no_role), ApiErrorId.UNAUTHENTICATED, 401)

    no_user = {k: v for k, v in OFFICER.items() if k != "X-User-ID"}
    validate_error(api.raw("GET", path, headers=no_user), ApiErrorId.UNAUTHENTICATED, 401)

    validate_error(api.raw("GET", path, headers={}), ApiErrorId.UNAUTHENTICATED, 401)


def test_an_unknown_role_name_is_unauthenticated_and_precedes_path_resolution(api):
    """PRD §2.1: "This check runs before anything else, including before the server
    attempts to resolve any identifier in the path."

    PRD §2.11: "Header presence and role-name validity — `ERR_UNAUTHENTICATED`."

    Design: Corner/errors/missing_or_unknown_role_headers_return_unauthenticated
    """
    cycle = create_cycle(api)

    unknown_role = dict(OFFICER)
    unknown_role["X-User-Role"] = "Auditor"
    # A role outside the six is 401, not the 403 an unauthorized-but-known role gets.
    validate_error(
        api.raw("GET", f"/assessment-cycles/{cycle['id']}", headers=unknown_role),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )

    # Rung 1 outranks rung 3: the unknown cycle id is never even looked up.
    no_role = {k: v for k, v in OFFICER.items() if k != "X-User-Role"}
    validate_error(
        api.raw("GET", f"/assessment-cycles/{NON_EXISTENT_UUID}", headers=no_role),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.raw("GET", f"/assessment-cycles/{NON_EXISTENT_UUID}", headers=unknown_role),
        ApiErrorId.UNAUTHENTICATED,
        401,
    )


def test_every_path_variable_carries_its_own_not_found_code(api):
    """PRD §2.6: "Each path variable has its own dedicated error code: `{cycle_id}`
    yields `ERR_CYCLE_NOT_FOUND`, `{indicator_id}` yields `ERR_INDICATOR_NOT_FOUND`,
    `{data_point_id}` yields `ERR_DATA_POINT_NOT_FOUND`, `{party_id}` yields
    `ERR_PARTY_NOT_FOUND`, `{interview_id}` yields `ERR_INTERVIEW_NOT_FOUND`,
    `{candidate_id}` yields `ERR_CANDIDATE_NOT_FOUND`, `{strategy_id}` yields
    `ERR_STRATEGY_NOT_FOUND`, `{objective_id}` yields `ERR_OBJECTIVE_NOT_FOUND`,
    `{agreement_id}` yields `ERR_PARTNERSHIP_NOT_FOUND`, `{commitment_id}` yields
    `ERR_COMMITMENT_NOT_FOUND`, `{report_id}` yields `ERR_REPORT_NOT_FOUND`,
    `{posting_id}` yields `ERR_POSTING_NOT_FOUND`, and `{evaluation_id}` yields
    `ERR_EVALUATION_NOT_FOUND`."

    PRD §2.6: "All thirteen are HTTP 404."

    Design: Corner/errors/unknown_path_ids_return_their_own_not_found_error
    """
    # A wholly empty database: nothing at all resolves.
    validate_error(
        api.get_data_point(NON_EXISTENT_UUID), ApiErrorId.DATA_POINT_NOT_FOUND, 404
    )
    validate_error(api.get_party(NON_EXISTENT_UUID), ApiErrorId.PARTY_NOT_FOUND, 404)
    validate_error(api.get_interview(NON_EXISTENT_UUID), ApiErrorId.INTERVIEW_NOT_FOUND, 404)
    validate_error(api.get_candidate(NON_EXISTENT_UUID), ApiErrorId.CANDIDATE_NOT_FOUND, 404)
    validate_error(api.get_strategy(NON_EXISTENT_UUID), ApiErrorId.STRATEGY_NOT_FOUND, 404)
    validate_error(api.get_objective(NON_EXISTENT_UUID), ApiErrorId.OBJECTIVE_NOT_FOUND, 404)
    validate_error(api.get_agreement(NON_EXISTENT_UUID), ApiErrorId.PARTNERSHIP_NOT_FOUND, 404)
    validate_error(api.get_commitment(NON_EXISTENT_UUID), ApiErrorId.COMMITMENT_NOT_FOUND, 404)
    validate_error(api.get_report(NON_EXISTENT_UUID), ApiErrorId.REPORT_NOT_FOUND, 404)
    validate_error(api.get_posting(NON_EXISTENT_UUID), ApiErrorId.POSTING_NOT_FOUND, 404)
    validate_error(api.get_evaluation(NON_EXISTENT_UUID), ApiErrorId.EVALUATION_NOT_FOUND, 404)


def test_the_two_outer_path_variables_resolve_before_the_nested_collection(api):
    """PRD §2.6: "Path identifiers are resolved strictly left to right, so that the
    outermost segment's failure is what the client sees when several segments are wrong
    at once."

    Design: Corner/errors/unknown_path_ids_return_their_own_not_found_error
    """
    validate_error(api.get_cycle(NON_EXISTENT_UUID), ApiErrorId.CYCLE_NOT_FOUND, 404)
    validate_error(api.get_indicator(NON_EXISTENT_UUID), ApiErrorId.INDICATOR_NOT_FOUND, 404)

    # The nested list endpoints report the outer segment, not an empty collection.
    validate_error(
        api.list_cycle_evaluations(NON_EXISTENT_UUID), ApiErrorId.CYCLE_NOT_FOUND, 404
    )
    validate_error(
        api.list_indicator_data_points(NON_EXISTENT_UUID), ApiErrorId.INDICATOR_NOT_FOUND, 404
    )
    validate_error(
        api.list_strategy_objectives(NON_EXISTENT_UUID), ApiErrorId.STRATEGY_NOT_FOUND, 404
    )


def test_a_second_report_for_the_same_cycle_and_year_is_rejected(api):
    """PRD §3.9: "A cycle may hold at most one report per `fiscal_year`; a second
    attempt at the same year under the same cycle is rejected with
    `ERR_DUPLICATE_REPORT`."

    Design: Corner/errors/duplicate_report_for_the_same_cycle_and_fiscal_year_rejected
    """
    cycle = create_cycle(api)
    first = open_report(api, cycle["id"], fiscal_year=C.FISCAL_YEAR)
    assert first["status"] == ReportStatus.OPEN

    # A different officer does not get a second bite at the same year.
    duplicate = api.create_report(
        F.report_payload(cycle["id"], fiscal_year=C.FISCAL_YEAR), headers=OFFICER_2
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_REPORT, 409)

    next_year = open_report(api, cycle["id"], fiscal_year=C.FISCAL_YEAR + 1)
    assert next_year["fiscal_year"] == C.FISCAL_YEAR + 1

    rows, meta = validate_paginated(api.list_reports(cycle_id=cycle["id"]))
    assert meta["total_count"] == 2
    assert {row["status"] for row in rows} == {ReportStatus.OPEN}


def test_a_board_action_without_quorum_is_refused_whichever_action_it_is(api):
    """PRD §3.7: "The cycle's `status` must be `BOARD_REVIEW`, and both action types
    require `quorum_present` to be true — a board action recorded without quorum is
    rejected with `ERR_QUORUM_NOT_MET` regardless of the tallies, and regardless of
    which `action_type` was requested."

    PRD §2.11: "On a board action, the quorum check at rung 23 runs before the
    vote-margin check at rung 24, so a board action with no quorum and a losing vote
    reports `ERR_QUORUM_NOT_MET`."

    Design: Corner/errors/board_action_quorum_and_vote_rules_rejected_before_adoption
    """
    sc = build_scenario(api, stage="BOARD_REVIEW")

    no_quorum_and_losing = api.board_action(
        sc.cycle_id,
        F.board_action_payload(quorum_present=False, votes_for=3, votes_against=8),
        headers=BOARD,
    )
    validate_error(no_quorum_and_losing, ApiErrorId.QUORUM_NOT_MET, 409)

    deferral_without_quorum = api.board_action(
        sc.cycle_id,
        F.board_action_payload(
            action_type=BoardActionType.DEFER,
            quorum_present=False,
            votes_for=9,
            votes_against=2,
        ),
        headers=BOARD,
    )
    validate_error(deferral_without_quorum, ApiErrorId.QUORUM_NOT_MET, 409)

    held = sc.cycle()
    assert held["status"] == CycleStatus.BOARD_REVIEW
    assert held["posture"] == Posture.RESTRICTED
    assert held["board_deferral_count"] == 0
    assert held["adopted_at"] is None


def test_a_tied_adoption_vote_fails_and_a_winning_one_records_the_tallies(api):
    """PRD §3.7: "An `ADOPT` action requires one more thing after quorum: `votes_for`
    must be strictly greater than `votes_against`, and a tie or a loss is rejected with
    `ERR_ADOPTION_VOTE_FAILED`."

    PRD §3.7: "On success the cycle's `status` moves `BOARD_REVIEW` to `ADOPTED`;
    `adopted_at` is stamped from the logical clock, `adoption_board_user_id` records the
    acting `X-User-ID`, and `votes_for_at_adoption` and `votes_against_at_adoption`
    preserve the tallies exactly as recorded."

    Design: Corner/errors/board_action_quorum_and_vote_rules_rejected_before_adoption
    """
    sc = build_scenario(api, stage="BOARD_REVIEW")

    tie = api.board_action(
        sc.cycle_id,
        F.board_action_payload(quorum_present=True, votes_for=5, votes_against=5),
        headers=BOARD,
    )
    validate_error(tie, ApiErrorId.ADOPTION_VOTE_FAILED, 409)
    assert sc.cycle()["status"] == CycleStatus.BOARD_REVIEW

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
    assert adopted["board_deferral_count"] == 0


def test_the_strategy_set_gate_fires_on_submission_and_on_the_board_review_advance(api):
    """PRD §3.5: "It further requires the strategy to carry at least one objective whose
    `status` is `DRAFT`, rejecting an objective-free submission with
    `ERR_STRATEGY_SET_INCOMPLETE`."

    PRD §3.1: "And the advance into `BOARD_REVIEW` requires that *every* priority
    candidate on the cycle whose `status` is `SELECTED` has at least one implementation
    strategy whose `approval_state` is `SUBMITTED` and which itself carries at least one
    objective whose `status` is either `DRAFT` or `ACTIVE`; if a single selected priority
    falls short, the advance fails with `ERR_STRATEGY_SET_INCOMPLETE`."

    Design: Corner/errors/strategy_set_incomplete_on_submit_and_on_board_review_advance
    """
    sc = build_scenario(api, stage="STRATEGY_DEVELOPMENT")
    assert sc.strategy()["approval_state"] == ApprovalState.DRAFT

    objective_free = api.submit_strategy(sc.strategy_id)
    validate_error(objective_free, ApiErrorId.STRATEGY_SET_INCOMPLETE, 409)

    # The same code guards the phase advance, reading the strategy's own axis.
    premature = api.advance_cycle(sc.cycle_id, CycleStatus.BOARD_REVIEW)
    validate_error(premature, ApiErrorId.STRATEGY_SET_INCOMPLETE, 409)
    assert sc.cycle()["status"] == CycleStatus.STRATEGY_DEVELOPMENT

    validate_success(api.create_objective(sc.strategy_id, F.objective_payload()), 201)
    submitted = validate_success(api.submit_strategy(sc.strategy_id))
    assert submitted["approval_state"] == ApprovalState.SUBMITTED

    advanced = validate_success(api.advance_cycle(sc.cycle_id, CycleStatus.BOARD_REVIEW))
    assert advanced["status"] == CycleStatus.BOARD_REVIEW
    assert advanced["posture"] == Posture.RESTRICTED


def test_scoring_needs_community_input_in_the_indicators_own_domain(api):
    """PRD §3.4: "And at least one completed session on the cycle must carry a
    `concern_ratings` key equal to the indicator's `domain`, or the run fails with
    `ERR_NO_DOMAIN_INPUT` — without that, the concern term would have no input set at
    all."

    Design: Corner/errors/candidate_score_without_domain_specific_community_input_rejected
    """
    sc = build_scenario(api, stage="INDICATOR")
    chronic = add_indicator(
        api,
        sc.cycle_id,
        name="Adult diabetes prevalence",
        domain=IndicatorDomain.CHRONIC_DISEASE,
    )
    make_indicator_sufficient(api, chronic["id"])
    advance_to(api, sc.cycle_id, CycleStatus.INPUT_GATHERING)
    session = add_interview(api, sc.cycle_id, sc.facilitator_party_id)
    # The only community voice on file speaks to behavioural health.
    complete_interview(api, session["id"], domain=IndicatorDomain.BEHAVIORAL_HEALTH)
    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)

    behavioral_candidate = add_candidate(api, sc.cycle_id, sc.indicator_id)
    chronic_candidate = add_candidate(api, sc.cycle_id, chronic["id"])

    starved = api.score_candidate(chronic_candidate["id"], ScoringVariant.EQUAL_WEIGHT)
    validate_error(starved, ApiErrorId.NO_DOMAIN_INPUT, 409)

    scored = score_candidate(api, behavioral_candidate["id"])
    assert_close(scored["community_concern_index"], 100.00, "community_concern_index")
    assert_close(scored["composite_score"], 76.88, "composite_score")

    # The rejected scoring run left nothing behind on the starved candidate.
    untouched = validate_success(api.get_candidate(chronic_candidate["id"], headers=BOARD))
    assert untouched["status"] == CandidateStatus.DRAFT
    assert untouched["composite_score"] is None
    assert untouched["community_concern_index"] is None


def _scored_candidate_with_a_session_still_outstanding(api):
    """A ``PRIORITIZATION`` cycle whose candidate was scored on one completed session
    while a second session, scheduled in time, is still waiting to be held."""
    sc = build_scenario(api, stage="INTERVIEW_COMPLETED")
    late_session = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Riverbend Housing Trust",
        starts_at="2026-04-13T14:00:00Z",
        ends_at="2026-04-13T15:00:00Z",
    )
    assert late_session["status"] == InterviewStatus.SCHEDULED

    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)
    sc.candidate_id = add_candidate(api, sc.cycle_id, sc.indicator_id)["id"]
    scored = score_candidate(api, sc.candidate_id)
    assert_close(scored["community_concern_index"], 100.00, "community_concern_index")
    assert_close(scored["composite_score"], 76.88, "composite_score")
    assert scored["concern_input_dirty"] is False
    return sc, late_session["id"]


def test_a_late_session_dirties_the_scored_candidate_and_blocks_its_selection(api):
    """PRD §3.3: "When that happens, every priority candidate on the same cycle whose
    `status` is `SCORED` and whose indicator's `domain` appears as a key in the newly
    recorded `concern_ratings` has its `concern_input_dirty` flag set to true."

    PRD §3.4: "It then requires `concern_input_dirty` to be false, failing with
    `ERR_STALE_CONCERN_INPUT` when community input has arrived since the last scoring
    run."

    Design: Corner/errors/late_interview_completion_makes_candidate_selection_stale
    """
    sc, late_session_id = _scored_candidate_with_a_session_still_outstanding(api)

    completed = validate_success(
        api.complete_interview(
            late_session_id,
            F.complete_interview_payload(
                domain=IndicatorDomain.BEHAVIORAL_HEALTH, rating=3, attendee_count=8
            ),
        )
    )
    assert completed["status"] == InterviewStatus.COMPLETED

    dirtied = sc.candidate()
    assert dirtied["concern_input_dirty"] is True
    # The stored score is untouched; only the claim about its currency changed.
    assert_close(dirtied["composite_score"], 76.88, "composite_score")

    stale = api.select_candidate(sc.candidate_id, "Highest composite need with hospital capacity to act")
    validate_error(stale, ApiErrorId.STALE_CONCERN_INPUT, 409)
    assert sc.candidate()["status"] == CandidateStatus.SCORED
    assert sc.cycle()["selected_priority_count"] == 0


def test_rescoring_absorbs_the_late_voice_and_reopens_the_selection(api):
    """PRD §3.4: "A successful run stores `scoring_variant`, `severity_input`,
    `disparity_points`, `community_concern_index` and `composite_score`, moves `status`
    to `SCORED`, and resets `concern_input_dirty` to false."

    PRD §3.4: "On success the supplied `selection_rationale` is stored, `status` moves
    `SCORED` to `SELECTED`, and the cycle's `selected_priority_count` increases by 1."

    Design: Corner/errors/late_interview_completion_makes_candidate_selection_stale
    """
    sc, late_session_id = _scored_candidate_with_a_session_still_outstanding(api)
    validate_success(
        api.complete_interview(
            late_session_id,
            F.complete_interview_payload(
                domain=IndicatorDomain.BEHAVIORAL_HEALTH, rating=3, attendee_count=8
            ),
        )
    )

    # (5 * 12 + 3 * 8) / 20 = 4.2 of 5, so the concern term drops to 84.00.
    rescored = score_candidate(api, sc.candidate_id)
    assert_close(rescored["community_concern_index"], 84.00, "community_concern_index")
    assert_close(rescored["composite_score"], 72.88, "composite_score")
    assert rescored["concern_input_dirty"] is False

    selected = select_candidate(api, sc.candidate_id)
    assert selected["status"] == CandidateStatus.SELECTED
    assert selected["selection_rationale"] == "Highest composite need with hospital capacity to act"
    assert sc.cycle()["selected_priority_count"] == 1


def test_a_commitment_beyond_the_remaining_envelope_is_refused(api):
    """PRD §3.6: "Last of all, the requested `funding_cents` must not exceed the
    strategy's current `budget_available_cents`, or the create fails with
    `ERR_STRATEGY_BUDGET_EXCEEDED`."

    PRD §3.6: "A strategy's `budget_available_cents` is its `authorized_budget_cents`
    less the sum of `funding_cents` over every commitment on that strategy whose
    `status` is `PENDING` or `COMMITTED`; released commitments are excluded."

    Design: Corner/errors/commitment_funding_exceeding_strategy_budget_rejected
    """
    sc = build_scenario(
        api,
        stage="STRATEGY_DEVELOPMENT",
        strategy_overrides={"authorized_budget_cents": 1000000},
    )
    assert sc.strategy()["budget_available_cents"] == 1000000

    validate_success(
        api.create_commitment(
            F.commitment_payload(
                sc.strategy_id, sc.facilitator_party_id, fte_bp=1000, funding_cents=600000
            )
        ),
        201,
    )
    assert sc.strategy()["budget_available_cents"] == 400000

    over_budget = api.create_commitment(
        F.commitment_payload(
            sc.strategy_id, sc.facilitator_party_id, fte_bp=1000, funding_cents=500000
        )
    )
    validate_error(over_budget, ApiErrorId.STRATEGY_BUDGET_EXCEEDED, 409)

    # The refused row encumbered nothing.
    assert sc.strategy()["budget_available_cents"] == 400000
    assert sc.facilitator()["committed_fte_bp"] == 1000


def test_a_commitment_that_consumes_the_envelope_exactly_is_accepted(api):
    """PRD §3.6: "The invariant is that the strategy's `budget_available_cents` plus
    that encumbered sum always equals its `authorized_budget_cents`, after every forward
    action and after every compensating release."

    Design: Corner/errors/commitment_funding_exceeding_strategy_budget_rejected
    """
    sc = build_scenario(
        api,
        stage="STRATEGY_DEVELOPMENT",
        strategy_overrides={"authorized_budget_cents": 1000000},
    )
    validate_success(
        api.create_commitment(
            F.commitment_payload(
                sc.strategy_id, sc.facilitator_party_id, fte_bp=1000, funding_cents=600000
            )
        ),
        201,
    )
    # 600000 + 400000 == 1000000 sits on the inclusive edge and is allowed.
    validate_success(
        api.create_commitment(
            F.commitment_payload(
                sc.strategy_id, sc.facilitator_party_id, fte_bp=1000, funding_cents=400000
            )
        ),
        201,
    )

    drained = sc.strategy()
    assert drained["budget_available_cents"] == 0
    assert drained["authorized_budget_cents"] == 1000000
    assert sc.facilitator()["committed_fte_bp"] == 2000


def test_board_review_refuses_the_assessment_side_writes_with_its_own_code(api):
    """PRD §2.4: "A `RESTRICTED` posture is narrower: it blocks only assessment-side
    work, on the reasoning that the board should not be deliberating over a moving target
    and that a strategy suspended for lost evidence should not be built upon further."

    PRD §2.4: "Rejections carry `ERR_CYCLE_RESTRICTED` with HTTP 409, and the rule
    applies to exactly thirteen operations: creating a health indicator; recording an
    indicator observation; scheduling a stakeholder interview; completing a stakeholder
    interview; cancelling a stakeholder interview; creating a priority candidate; scoring
    a priority candidate; selecting a priority candidate; deferring a priority candidate;
    creating an implementation strategy; submitting an implementation strategy; adding an
    objective to a strategy; and creating a resource commitment."

    Design: Corner/errors/restricted_posture_blocks_assessment_side_writes_during_board_review
    """
    sc = build_scenario(api, stage="BOARD_REVIEW")
    assert sc.cycle()["posture"] == Posture.RESTRICTED

    # Rung 10 outranks the approval-axis lock at rung 11 that would also refuse this.
    blocked_commitment = api.create_commitment(
        F.commitment_payload(sc.strategy_id, sc.facilitator_party_id, funding_cents=500000)
    )
    validate_error(blocked_commitment, ApiErrorId.CYCLE_RESTRICTED, 409)

    # Rung 10 also outranks the creation-time phase gate on an indicator.
    blocked_indicator = api.create_indicator(
        F.indicator_payload(sc.cycle_id, name="Adult diabetes prevalence")
    )
    validate_error(blocked_indicator, ApiErrorId.CYCLE_RESTRICTED, 409)

    blocked_objective = api.create_objective(sc.strategy_id, F.objective_payload())
    validate_error(blocked_objective, ApiErrorId.CYCLE_RESTRICTED, 409)


def test_board_review_leaves_the_report_and_evaluation_surfaces_open(api):
    """PRD §2.4: "Report-side and evaluation-side endpoints stay open while
    `RESTRICTED`, as does an execution-status change on a strategy — the latter
    deliberately so, because clearing a suspended strategy back to `ON_TRACK` is the only
    way `review_flag_count` ever returns to zero."

    Design: Corner/errors/restricted_posture_blocks_assessment_side_writes_during_board_review
    """
    sc = build_scenario(api, stage="BOARD_REVIEW")
    assert sc.cycle()["posture"] == Posture.RESTRICTED

    report = open_report(api, sc.cycle_id)
    assert report["status"] == ReportStatus.OPEN

    evaluation = add_evaluation(
        api,
        sc.cycle_id,
        eval_type=EvalType.ANNUAL,
        period_year=2027,
        findings_summary="Drafted during board review",
    )
    assert evaluation["cycle_id"] == sc.cycle_id


def _published_cycle_awaiting_its_locked_report(api):
    """An adopted and published cycle: `public_availability_met` is true, so the filing
    gate that fires next is the one about the report."""
    sc = build_scenario(api, stage="ADOPTED")
    published = publish_cycle(api, sc.cycle_id)
    assert published["status"] == CycleStatus.PUBLISHED
    assert published["public_availability_met"] is True
    return sc


def test_filing_is_refused_until_exactly_one_report_is_locked(api):
    """PRD §3.9: "The second check is that the cycle has exactly one community benefit
    report whose `status` is `LOCKED`; a cycle with no locked report, or with a report
    still sitting `OPEN`, is rejected with `ERR_REPORT_NOT_LOCKED`."

    PRD §3.9: "When both checks pass the `return_form_id` is stored on the cycle, the
    cycle's `filed_at` is stamped from the logical clock, and `status` moves to `FILED`."

    PRD §3.9: "The locked report moves in step: its `status` goes `LOCKED` to `FILED`
    and its own `filed_at` is stamped from the same logical clock reading."

    Design: Corner/errors/filing_sequence_requires_locked_report_then_published_annual_evaluation
    """
    sc = _published_cycle_awaiting_its_locked_report(api)

    no_report_at_all = api.file_return(
        sc.cycle_id, "F990SCH-H-2026-0001", headers=COMPLIANCE
    )
    validate_error(no_report_at_all, ApiErrorId.REPORT_NOT_LOCKED, 409)

    report = open_report(api, sc.cycle_id)
    post_charge_based(api, report["id"], 1234567)
    still_open = api.file_return(sc.cycle_id, "F990SCH-H-2026-0001", headers=COMPLIANCE)
    validate_error(still_open, ApiErrorId.REPORT_NOT_LOCKED, 409)

    locked = finalize_report(api, report["id"])
    assert locked["status"] == ReportStatus.LOCKED

    filed = validate_success(
        api.file_return(sc.cycle_id, "F990SCH-H-2026-0001", headers=COMPLIANCE)
    )
    assert filed["status"] == CycleStatus.FILED
    assert filed["posture"] == Posture.FROZEN
    assert filed["return_form_id"] == "F990SCH-H-2026-0001"
    assert filed["filed_at"] is not None

    moved_in_step = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    assert moved_in_step["status"] == ReportStatus.FILED
    assert moved_in_step["filed_at"] is not None


def test_a_filed_cycle_cannot_close_and_cannot_take_the_evaluation_it_needs(api):
    """PRD §3.1: "It requires at least one progress evaluation on the cycle whose
    `eval_type` is `ANNUAL` and whose `status` is `PUBLISHED`, failing otherwise with
    `ERR_ANNUAL_REPORT_MISSING`."

    PRD §2.4: "That includes expense postings, releasing a resource commitment, changing
    a strategy's execution status, reporting objective progress, publishing a progress
    evaluation, retracting an indicator observation, and every other write beneath the
    cycle."

    Design: Corner/errors/filing_sequence_requires_locked_report_then_published_annual_evaluation
    """
    sc = _published_cycle_awaiting_its_locked_report(api)
    report = open_report(api, sc.cycle_id)
    post_charge_based(api, report["id"], 1234567)
    finalize_report(api, report["id"])
    validate_success(api.file_return(sc.cycle_id, "F990SCH-H-2026-0001", headers=COMPLIANCE))

    # No ANNUAL evaluation was ever published, so the close-out gate holds.
    unclosable = api.advance_cycle(sc.cycle_id, CycleStatus.CLOSED, headers=COMPLIANCE)
    validate_error(unclosable, ApiErrorId.ANNUAL_REPORT_MISSING, 409)
    assert sc.cycle()["status"] == CycleStatus.FILED

    # And the missing evaluation can never be drafted now: FROZEN refuses child writes
    # that RESTRICTED had allowed.
    too_late = api.create_evaluation(
        F.evaluation_payload(
            sc.cycle_id,
            eval_type=EvalType.ANNUAL,
            period_year=2027,
            findings_summary="Attempted after filing",
        )
    )
    validate_error(too_late, ApiErrorId.CYCLE_FROZEN, 409)

    held = sc.cycle()
    assert held["status"] == CycleStatus.FILED
    assert held["posture"] == Posture.FROZEN
    assert held["annual_report_count"] == 0
