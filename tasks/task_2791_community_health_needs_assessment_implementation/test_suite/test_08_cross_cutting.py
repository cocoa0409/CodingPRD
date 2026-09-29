"""Cross-cutting layers: concurrency tokens, counter reconciliation and threshold resets."""

from test_helpers import (
    COMPLIANCE,
    STEWARD,
    ApiErrorId,
    ApprovalState,
    CandidateStatus,
    Category,
    CycleStatus,
    DataSourceType,
    DataState,
    ExecutionState,
    IndicatorDomain,
    InterviewStatus,
    Sector,
    Subgroup,
    add_candidate,
    add_indicator,
    add_interview,
    advance_to,
    assert_close,
    build_scenario,
    complete_interview,
    create_cycle,
    make_indicator_sufficient,
    open_report,
    score_candidate,
    select_candidate,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def _selected_candidate_holding_its_pre_select_version(api):
    """A ``STRATEGY_DEVELOPMENT`` cycle plus the candidate version the client observed
    when it scored — one behind the version the selection left."""
    sc = build_scenario(api, stage="CANDIDATE_SCORED")
    version_at_score = sc.candidate()["version"]
    select_candidate(api, sc.candidate_id)
    advance_to(api, sc.cycle_id, CycleStatus.STRATEGY_DEVELOPMENT)
    version_now = api.candidate_version(sc.candidate_id)
    assert version_now > version_at_score
    return sc, version_at_score, version_now


def test_a_strategy_drafted_on_a_pre_selection_view_of_the_candidate_is_refused(api):
    """PRD §2.7: "A `POST /implementation-strategies` request must carry
    `expected_candidate_version` matching the target `PriorityCandidate`'s current
    `version`."

    PRD §2.7: "If the candidate's version has advanced since the client last read it, the
    create is rejected with `ERR_STALE_CANDIDATE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_candidate_version_rejects_the_strategy_create
    """
    sc, version_at_score, _version_now = _selected_candidate_holding_its_pre_select_version(api)

    stale = api.create_strategy(F.strategy_payload(sc.candidate_id, version_at_score))
    validate_error(stale, ApiErrorId.STALE_CANDIDATE_VERSION, 412)

    _rows, meta = validate_paginated(api.list_strategies(candidate_id=sc.candidate_id))
    assert meta["total_count"] == 0
    assert sc.candidate()["strategy_count"] == 0


def test_the_refreshed_candidate_token_is_consumed_by_the_create_it_authorizes(api):
    """PRD §2.7: "The version token is what forces the client to re-read the candidate —
    including its `strategy_count` and its current score fields — before it supersedes work
    it has not seen."

    PRD §3.5: "The owning candidate's `strategy_count` rises by 1 and the candidate's
    `version` increments, which is precisely why the next client to draft against the same
    candidate needs a fresh read."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_candidate_version_rejects_the_strategy_create
    """
    sc, _version_at_score, version_now = _selected_candidate_holding_its_pre_select_version(api)

    created = validate_success(
        api.create_strategy(F.strategy_payload(sc.candidate_id, version_now)), 201
    )
    assert created["approval_state"] == ApprovalState.DRAFT
    assert created["execution_state"] == ExecutionState.NOT_STARTED
    assert created["budget_available_cents"] == C.AUTHORIZED_BUDGET_CENTS

    # The accepted create bumped the candidate past the token that authorized it.
    replayed = api.create_strategy(
        F.strategy_payload(
            sc.candidate_id, version_now, title="Integrated behavioural health access, revision 2"
        )
    )
    validate_error(replayed, ApiErrorId.STALE_CANDIDATE_VERSION, 412)

    rows, meta = validate_paginated(api.list_strategies(candidate_id=sc.candidate_id))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == created["id"]
    assert rows[0]["approval_state"] == ApprovalState.DRAFT

    candidate = sc.candidate()
    assert candidate["version"] == version_now + 1
    assert candidate["strategy_count"] == 1


def test_a_posting_computed_on_the_reports_creation_version_is_refused(api):
    """PRD §2.7: "A `POST /expense-postings` request must carry `expected_report_version`
    matching the target `CommunityBenefitReport`'s current `version`. A mismatch is rejected
    with `ERR_STALE_REPORT_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_report_version_rejects_the_expense_posting
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    version_at_create = report["version"]

    validate_success(
        api.create_posting(
            F.charge_based_posting_payload(report["id"], version_at_create, 1234567)
        ),
        201,
    )

    stale = api.create_posting(
        F.charge_based_posting_payload(report["id"], version_at_create, 500000)
    )
    validate_error(stale, ApiErrorId.STALE_REPORT_VERSION, 412)

    # The refused posting was never valued into the ledger.
    stored = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    assert stored["version"] == version_at_create + 1
    assert stored["financial_assistance_cents"] == 395061
    _rows, meta = validate_paginated(api.list_postings(report_id=report["id"]))
    assert meta["total_count"] == 1


def test_the_refreshed_report_token_is_consumed_by_the_posting_it_authorizes(api):
    """PRD §2.7: "Here the reason is arithmetic rather than governance: a posting's valued
    amount is derived from the report's current cost-to-charge ratio and valuation basis,
    both of which the finalization step rewrites, so a posting computed against a stale view
    of the report would enter the ledger on the wrong valuation basis."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_report_version_rejects_the_expense_posting
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    validate_success(
        api.create_posting(
            F.charge_based_posting_payload(report["id"], report["version"], 1234567)
        ),
        201,
    )
    version_now = api.report_version(report["id"])

    accepted = validate_success(
        api.create_posting(
            F.charge_based_posting_payload(report["id"], version_now, 500000)
        ),
        201,
    )
    # 500000 * 0.32 = 160000 exactly.
    assert accepted["valued_cents"] == 160000
    assert validate_success(api.get_report(report["id"], headers=COMPLIANCE))[
        "financial_assistance_cents"
    ] == 555061

    # That success consumed the token, so a second posting on it is refused.
    replayed = api.create_posting(
        F.charge_based_posting_payload(
            report["id"], version_now, 500000, category=Category.SUBSIDIZED_SERVICES
        )
    )
    validate_error(replayed, ApiErrorId.STALE_REPORT_VERSION, 412)
    assert validate_success(api.get_report(report["id"], headers=COMPLIANCE))[
        "subsidized_services_cents"
    ] == 0


def test_the_completed_session_counter_ignores_a_cancellation(api):
    """PRD §3.3: "On success `status` moves `SCHEDULED` to `COMPLETED`, `completed_at` is
    stamped from the logical clock, and the cycle's `completed_interview_count` increases by
    1."

    PRD §3.3: "The supplied `reason` is stored in `cancel_reason`, `status` moves
    `SCHEDULED` to `CANCELLED`, and the row leaves both the facilitator occupancy set and the
    organization-name uniqueness set — so a cancellation genuinely frees the slot and the
    name for reuse."

    Design: Corner/cross_cutting_complexity_layers/cycle_child_counters_reconcile_after_create_change_and_removal
    """
    sc = build_scenario(api, stage="INPUT_GATHERING")
    second = add_interview(
        api,
        sc.cycle_id,
        sc.facilitator_party_id,
        organization_name="Northside Housing Trust",
        sector=Sector.PUBLIC_HEALTH_AGENCY,
        starts_at="2026-04-08T14:00:00Z",
        ends_at="2026-04-08T15:00:00Z",
    )
    assert sc.cycle()["completed_interview_count"] == 0

    complete_interview(api, sc.interview_id)
    assert sc.cycle()["completed_interview_count"] == 1

    cancelled = validate_success(
        api.cancel_interview(second["id"], "Organization withdrew from the session")
    )
    assert cancelled["status"] == InterviewStatus.CANCELLED
    assert cancelled["cancel_reason"] == "Organization withdrew from the session"
    # Cancelling a SCHEDULED session never touched the completed counter.
    assert sc.cycle()["completed_interview_count"] == 1


def test_the_selected_priority_counter_falls_back_when_a_selection_is_deferred(api):
    """PRD §3.4: "On success the supplied `selection_rationale` is stored, `status` moves
    `SCORED` to `SELECTED`, and the cycle's `selected_priority_count` increases by 1."

    PRD §3.4: "Deferring a candidate that was `SELECTED` carries two extra consequences:
    the cycle's `selected_priority_count` is reduced by 1, and every implementation strategy
    whose `candidate_id` names this candidate and whose `approval_state` is `DRAFT` or
    `RETURNED` moves to `SUPERSEDED`, so the draft strategy work built on a deferred need is
    retired rather than left dangling."

    Design: Corner/cross_cutting_complexity_layers/cycle_child_counters_reconcile_after_create_change_and_removal
    """
    sc = build_scenario(api, stage="INDICATOR")
    second_indicator = add_indicator(
        api,
        sc.cycle_id,
        name="Youth suicidal ideation rate",
        domain=IndicatorDomain.BEHAVIORAL_HEALTH,
    )
    make_indicator_sufficient(api, second_indicator["id"])
    assert sc.cycle()["sufficient_indicator_count"] == 2

    advance_to(api, sc.cycle_id, CycleStatus.INPUT_GATHERING)
    session = add_interview(api, sc.cycle_id, sc.facilitator_party_id)
    complete_interview(api, session["id"])
    advance_to(api, sc.cycle_id, CycleStatus.PRIORITIZATION)

    first = add_candidate(api, sc.cycle_id, sc.indicator_id)
    score_candidate(api, first["id"])
    select_candidate(api, first["id"], rationale="Adult depression is the cycle's leading need")
    assert sc.cycle()["selected_priority_count"] == 1

    second = add_candidate(api, sc.cycle_id, second_indicator["id"])
    scored = score_candidate(api, second["id"])
    assert_close(scored["composite_score"], 76.88, "composite_score")
    select_candidate(api, second["id"], rationale="Youth ideation shares the same service model")
    assert sc.cycle()["selected_priority_count"] == 2

    deferred = validate_success(
        api.defer_candidate(second["id"], "No school-based capacity in this cycle")
    )
    assert deferred["status"] == CandidateStatus.DEFERRED
    assert deferred["defer_reason"] == "No school-based capacity in this cycle"

    reconciled = sc.cycle()
    assert reconciled["completed_interview_count"] == 1
    assert reconciled["selected_priority_count"] == 1
    assert reconciled["sufficient_indicator_count"] == 2
    assert reconciled["review_flag_count"] == 0


def test_sufficiency_arms_only_when_the_second_subgroup_arrives(api):
    """PRD §3.2: "When fewer than two such subgroups exist, `disparity_ratio` is null;
    otherwise `disparity_ratio` is the largest representative rate divided by the smallest,
    rounded half up to two decimal places."

    PRD §3.2: "Finally `data_state` is `SUFFICIENT` when `latest_overall_value` is not null
    *and* `subgroup_count` is at least 2, and `INSUFFICIENT` in every other case."

    PRD §3.1: "Leaving `DATA_COLLECTION` requires `sufficient_indicator_count` to be at
    least 1 — the assessment must rest on at least one adequately evidenced health indicator
    — and otherwise fails with `ERR_INSUFFICIENT_INDICATOR_COVERAGE`."

    Design: Corner/cross_cutting_complexity_layers/indicator_sufficiency_threshold_arms_at_two_subgroups_and_resets_on_void
    """
    sc = build_scenario(api, stage="DATA_COLLECTION")
    indicator = add_indicator(api, sc.cycle_id, benchmark_value=C.BENCHMARK_VALUE)

    validate_success(
        api.create_data_point(
            indicator["id"],
            F.data_point_payload(
                population_subgroup=Subgroup.OVERALL,
                source_type=DataSourceType.PUBLIC_DATASET,
                value=C.OVERALL_VALUE,
            ),
            headers=STEWARD,
        ),
        201,
    )
    only_overall = validate_success(api.get_indicator(indicator["id"], headers=STEWARD))
    assert_close(only_overall["latest_overall_value"], 18.6, "latest_overall_value")
    assert_close(only_overall["severity_score"], 77.50, "severity_score")
    assert only_overall["subgroup_count"] == 0
    assert only_overall["disparity_ratio"] is None
    assert only_overall["evidence_count"] == 1
    assert only_overall["data_state"] == DataState.INSUFFICIENT

    validate_success(
        api.create_data_point(
            indicator["id"],
            F.data_point_payload(
                population_subgroup=Subgroup.BLACK_NH, value=C.SUBGROUP_HIGH_VALUE
            ),
            headers=STEWARD,
        ),
        201,
    )
    one_short = validate_success(api.get_indicator(indicator["id"], headers=STEWARD))
    assert one_short["subgroup_count"] == 1
    assert one_short["disparity_ratio"] is None
    assert one_short["data_state"] == DataState.INSUFFICIENT
    assert sc.cycle()["sufficient_indicator_count"] == 0

    # One subgroup short, the phase gate holds the cycle where it is.
    blocked = api.advance_cycle(sc.cycle_id, CycleStatus.INPUT_GATHERING)
    validate_error(blocked, ApiErrorId.INSUFFICIENT_INDICATOR_COVERAGE, 409)
    assert sc.cycle()["status"] == CycleStatus.DATA_COLLECTION

    validate_success(
        api.create_data_point(
            indicator["id"],
            F.data_point_payload(
                population_subgroup=Subgroup.WHITE_NH, value=C.SUBGROUP_LOW_VALUE
            ),
            headers=STEWARD,
        ),
        201,
    )
    armed = validate_success(api.get_indicator(indicator["id"], headers=STEWARD))
    assert armed["subgroup_count"] == 2
    # 24.8 / 15.5 = 1.60 exactly.
    assert_close(armed["disparity_ratio"], 1.60, "disparity_ratio")
    assert armed["data_state"] == DataState.SUFFICIENT
    assert sc.cycle()["sufficient_indicator_count"] == 1


def test_a_retracted_subgroup_disarms_sufficiency_and_a_replacement_re_arms_it(api):
    """PRD §3.2: "**Link one:** the owning indicator re-derives all five computed fields,
    and `severity_score` and `disparity_ratio` become null when their inputs disappear."

    PRD §3.2: "If the re-derivation leaves `latest_overall_value` null or `subgroup_count`
    below 2, the indicator moves `SUFFICIENT` to `INSUFFICIENT` and the cycle's
    `sufficient_indicator_count` is reduced by 1."

    Design: Corner/cross_cutting_complexity_layers/indicator_sufficiency_threshold_arms_at_two_subgroups_and_resets_on_void
    """
    sc = build_scenario(api, stage="INDICATOR")
    white_point_id = sc.data_point_ids[2]
    assert sc.indicator()["data_state"] == DataState.SUFFICIENT

    validate_success(
        api.void_data_point(
            white_point_id, "Subgroup extract superseded by the county", headers=STEWARD
        )
    )
    disarmed = sc.indicator()
    assert disarmed["subgroup_count"] == 1
    assert disarmed["disparity_ratio"] is None
    # The OVERALL row is untouched, so severity survives the retraction.
    assert disarmed["evidence_count"] == 2
    assert_close(disarmed["severity_score"], 77.50, "severity_score")
    assert disarmed["data_state"] == DataState.INSUFFICIENT
    assert sc.cycle()["sufficient_indicator_count"] == 0

    # Re-adding the subgroup re-arms the threshold: the void did not disable it.
    validate_success(
        api.create_data_point(
            sc.indicator_id,
            F.data_point_payload(
                population_subgroup=Subgroup.WHITE_NH, value=C.SUBGROUP_LOW_VALUE
            ),
            headers=STEWARD,
        ),
        201,
    )
    re_armed = sc.indicator()
    assert re_armed["data_state"] == DataState.SUFFICIENT
    assert re_armed["evidence_count"] == 3
    assert sc.cycle()["sufficient_indicator_count"] == 1

    advanced = validate_success(api.advance_cycle(sc.cycle_id, CycleStatus.INPUT_GATHERING))
    assert advanced["status"] == CycleStatus.INPUT_GATHERING
