"""Endpoint corners: the party registry, evaluation publication and derived reads."""

from test_helpers import (
    BOARD,
    COMPLIANCE,
    PUBLIC,
    ApiErrorId,
    ApprovalState,
    AttainmentStatus,
    Category,
    CycleStatus,
    EvalStatus,
    EvalType,
    ExecutionState,
    ObjectiveStatus,
    PartyType,
    PostingStatus,
    Sector,
    SignatureState,
    add_evaluation,
    add_internal_party,
    add_objective,
    add_partner_party,
    advance_to,
    assert_close,
    assert_common_fields,
    build_scenario,
    create_cycle,
    make_partner_representative_headers,
    open_report,
    post_charge_based,
    post_cost_based,
    publish_evaluation,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import constants as C
from test_helpers import factories as F


def test_the_party_registry_is_reachable_with_no_cycle_in_existence(api):
    """PRD §3.3: "A **responsible party** carries a `name` between 1 and 120
    characters, a `party_type` of either `INTERNAL` or `PARTNER`, and an
    `fte_capacity_bp` — the effort capacity available for commitments, in basis
    points, no lower than 0 and no higher than 100,000, which is to say up to ten
    whole FTE."

    PRD §3.3: "Party registration is not gated by any cycle phase; a party outlives
    any single assessment."

    Design: Corner/endpoints/responsible_party_create_read_and_filtered_list
    """
    empty, empty_meta = validate_paginated(api.list_parties())
    assert empty == []
    assert empty_meta["total_count"] == 0

    internal = add_internal_party(api, name="Community Health Office", fte_capacity_bp=10000)
    partner = add_partner_party(
        api, name="Riverbend Community Coalition", fte_capacity_bp=5000
    )
    for party in (internal, partner):
        assert_common_fields(party, expected_version=1)
        assert party["committed_fte_bp"] == 0

    # A partner representative may read a party row.
    read_back = validate_success(
        api.get_party(internal["id"], headers=make_partner_representative_headers(partner["id"]))
    )
    assert read_back["id"] == internal["id"]
    assert read_back["name"] == "Community Health Office"
    assert read_back["party_type"] == PartyType.INTERNAL
    assert read_back["fte_capacity_bp"] == 10000


def test_the_party_type_filter_partitions_the_registry(api):
    """PRD §3.3: "Its derived `committed_fte_bp` starts at 0."

    Design: Corner/endpoints/responsible_party_create_read_and_filtered_list
    """
    internal = add_internal_party(api, name="Community Health Office", fte_capacity_bp=10000)
    partner = add_partner_party(
        api, name="Riverbend Community Coalition", fte_capacity_bp=5000
    )

    partners, partner_meta = validate_paginated(
        api.list_parties(headers=COMPLIANCE, party_type=PartyType.PARTNER)
    )
    assert partner_meta["total_count"] == 1
    assert [row["id"] for row in partners] == [partner["id"]]
    assert partners[0]["committed_fte_bp"] == 0

    internals, internal_meta = validate_paginated(
        api.list_parties(headers=COMPLIANCE, party_type=PartyType.INTERNAL)
    )
    assert internal_meta["total_count"] == 1
    assert [row["id"] for row in internals] == [internal["id"]]

    everything, all_meta = validate_paginated(api.list_parties())
    assert all_meta["total_count"] == 2
    assert {row["id"] for row in everything} == {internal["id"], partner["id"]}


def test_an_evaluation_drafted_on_a_draft_cycle_cannot_yet_be_published(api):
    """PRD §3.8: "A new evaluation starts with `status` at `DRAFT`,
    `objectives_revised_count` at 0, and `public_url` and `published_at` null."

    PRD §3.8: "It requires the evaluation's `status` to be `DRAFT` and the owning
    cycle's `status` to be `ADOPTED`, `PUBLISHED` or `FILED`; either failure is
    `ERR_INVALID_STATE`."

    Design: Corner/endpoints/progress_evaluation_publish_enforces_cycle_state_and_period_uniqueness
    """
    cycle = create_cycle(api)
    evaluation = add_evaluation(
        api,
        cycle["id"],
        eval_type=EvalType.ANNUAL,
        period_year=2027,
        findings_summary="Year one results",
    )
    assert evaluation["status"] == EvalStatus.DRAFT
    assert evaluation["objectives_revised_count"] == 0
    assert evaluation["published_at"] is None
    assert evaluation["public_url"] is None

    too_early = api.publish_evaluation(evaluation["id"], F.publish_evaluation_payload())
    validate_error(too_early, ApiErrorId.INVALID_STATE, 409)

    stored = validate_success(api.get_evaluation(evaluation["id"]))
    assert stored["status"] == EvalStatus.DRAFT
    assert stored["published_at"] is None
    # The rejected publication incremented nothing.
    assert validate_success(api.get_cycle(cycle["id"]))["annual_report_count"] == 0


def test_the_evaluation_period_key_is_the_type_and_the_year_together(api):
    """PRD §3.8: "A cycle may hold at most one evaluation for any combination of
    `eval_type` and `period_year`; a duplicate is rejected with
    `ERR_DUPLICATE_EVALUATION_PERIOD`."

    Design: Corner/endpoints/progress_evaluation_publish_enforces_cycle_state_and_period_uniqueness
    """
    cycle = create_cycle(api)
    add_evaluation(api, cycle["id"], eval_type=EvalType.ANNUAL, period_year=2027)

    duplicate = api.create_evaluation(
        F.evaluation_payload(
            cycle["id"],
            eval_type=EvalType.ANNUAL,
            period_year=2027,
            findings_summary="Duplicate attempt",
        )
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_EVALUATION_PERIOD, 409)

    other_type = add_evaluation(
        api,
        cycle["id"],
        eval_type=EvalType.MID_CYCLE,
        period_year=2027,
        findings_summary="Mid-cycle check-in",
    )
    assert other_type["eval_type"] == EvalType.MID_CYCLE

    rows, meta = validate_paginated(
        api.list_cycle_evaluations(cycle["id"], headers=PUBLIC, status=EvalStatus.DRAFT)
    )
    assert meta["total_count"] == 2
    assert {row["eval_type"] for row in rows} == {EvalType.ANNUAL, EvalType.MID_CYCLE}


def test_a_partner_may_not_facilitate_a_stakeholder_session(api):
    """PRD §3.3: "A stakeholder session's `facilitator_party_id` must name a party
    whose `party_type` is `INTERNAL`, because the hospital facilitates its own
    community listening."

    Design: Corner/endpoints/party_type_mismatch_rejected_on_both_link_directions
    """
    sc = build_scenario(api, stage="INDICATOR")
    advance_to(api, sc.cycle_id, CycleStatus.INPUT_GATHERING)
    partner = add_partner_party(api, name="Riverbend Community Coalition")

    wrong_side = api.create_interview(
        F.interview_payload(
            sc.cycle_id,
            partner["id"],
            organization_name=C.ORGANIZATION_NAME,
            sector=Sector.SAFETY_NET_PROVIDER,
        )
    )
    validate_error(wrong_side, ApiErrorId.PARTY_TYPE_MISMATCH, 409)

    accepted = validate_success(
        api.create_interview(F.interview_payload(sc.cycle_id, sc.facilitator_party_id)), 201
    )
    assert accepted["facilitator_party_id"] == sc.facilitator_party_id


def test_an_internal_department_may_not_be_the_agreement_counterparty(api):
    """PRD §3.3: "A partnership agreement's `party_id` must name a party whose
    `party_type` is `PARTNER`, because a hospital department cannot be the
    counterparty to its own agreement."

    Design: Corner/endpoints/party_type_mismatch_rejected_on_both_link_directions
    """
    cycle = create_cycle(api)
    internal = add_internal_party(api, name="Community Health Office")
    partner = add_partner_party(api, name="Riverbend Community Coalition")

    wrong_side = api.create_agreement(F.agreement_payload(cycle["id"], internal["id"]))
    validate_error(wrong_side, ApiErrorId.PARTY_TYPE_MISMATCH, 409)

    accepted = validate_success(
        api.create_agreement(F.agreement_payload(cycle["id"], partner["id"])), 201
    )
    assert accepted["party_id"] == partner["id"]
    assert accepted["signature_state"] == SignatureState.NEGOTIATING
    assert accepted["hospital_signed_at"] is None
    assert accepted["partner_signed_at"] is None
    assert accepted["funded_cents"] == 0


def test_the_report_read_mixes_the_two_valuation_families_into_one_grand_total(api):
    """PRD §3.9: "The five categories divide into two valuation families, and which
    family a category belongs to determines which of the two money inputs must be
    populated."

    PRD §3.9: "Finally, `benefit_pct_of_expense` is `grand_total_cents` divided by
    the owning cycle's `total_operating_expense_cents`, multiplied by 100, and
    rounded half up to two decimal places."

    Design: Corner/endpoints/report_computed_read_mixes_charge_and_cost_basis_totals
    """
    cycle = create_cycle(api)
    assert cycle["total_operating_expense_cents"] == 120000000
    report = open_report(api, cycle["id"])

    post_charge_based(api, report["id"], 1234567, category=Category.FINANCIAL_ASSISTANCE)
    post_cost_based(api, report["id"], 850000, category=Category.COMMUNITY_HEALTH_IMPROVEMENT)

    stored = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    # 1234567 * 0.32 = 395061.44 -> 395061; the cost-based row keeps its 850000.
    assert stored["financial_assistance_cents"] == 395061
    assert stored["community_health_improvement_cents"] == 850000
    assert stored["subsidized_services_cents"] == 0
    assert stored["cash_and_inkind_cents"] == 0
    assert stored["community_building_cents"] == 0
    assert stored["total_valued_cents"] == 1245061
    # 0.05 * 1245061 = 62253.05 -> 62253.
    assert_close(stored["overhead_rate"], 0.05, "overhead_rate")
    assert stored["indirect_allocation_cents"] == 62253
    assert stored["grand_total_cents"] == 1307314
    # 1307314 / 120000000 * 100 = 1.08942... -> 1.09.
    assert_close(stored["benefit_pct_of_expense"], 1.09, "benefit_pct_of_expense")


def test_the_posted_rows_sum_to_the_reports_total_valued_figure(api):
    """PRD §3.9: "each posting's `valued_cents` is rounded to a whole number of cents
    when the posting is valued, and the totals are sums of those already-rounded
    integers."

    Design: Corner/endpoints/report_computed_read_mixes_charge_and_cost_basis_totals
    """
    cycle = create_cycle(api)
    report = open_report(api, cycle["id"])
    post_charge_based(api, report["id"], 1234567, category=Category.FINANCIAL_ASSISTANCE)
    post_cost_based(api, report["id"], 850000, category=Category.COMMUNITY_HEALTH_IMPROVEMENT)

    rows, meta = validate_paginated(
        api.list_postings(headers=COMPLIANCE, report_id=report["id"], status=PostingStatus.POSTED)
    )
    assert meta["total_count"] == 2
    assert sum(row["valued_cents"] for row in rows) == 1245061

    stored = validate_success(api.get_report(report["id"], headers=COMPLIANCE))
    assert stored["total_valued_cents"] == sum(row["valued_cents"] for row in rows)


def _behind_strategy_with_one_unmeasured_objective(api):
    """An adopted strategy at ``BEHIND``: its second objective was measured at 49.92
    and revised by a published mid-cycle evaluation, while the first was never
    measured at all."""
    sc = build_scenario(api, stage="STRATEGY_WITH_OBJECTIVE")
    lagging = add_objective(
        api, sc.strategy_id, metric_name="Warm handoffs to behavioural health"
    )
    validate_success(api.submit_strategy(sc.strategy_id))
    advance_to(api, sc.cycle_id, CycleStatus.BOARD_REVIEW)
    validate_success(api.board_action(sc.cycle_id, F.board_action_payload(), headers=BOARD))

    reported = validate_success(
        api.report_progress(lagging["id"], F.report_progress_payload(1799, "2027-01-15"))
    )
    assert_close(reported["attainment_pct"], 49.92, "attainment_pct")

    mid_cycle = add_evaluation(
        api,
        sc.cycle_id,
        eval_type=EvalType.MID_CYCLE,
        period_year=2027,
        findings_summary="Warm handoffs lagging at mid-cycle",
    )
    publish_evaluation(api, mid_cycle["id"])

    assert sc.strategy()["execution_state"] == ExecutionState.BEHIND
    revised = validate_success(api.get_objective(lagging["id"]))
    assert revised["status"] == ObjectiveStatus.REVISED
    unmeasured = validate_success(api.get_objective(sc.objective_id))
    assert unmeasured["attainment_status"] == AttainmentStatus.PENDING
    return sc, lagging["id"]


def test_completing_a_strategy_is_refused_while_an_objective_was_never_measured(api):
    """PRD §3.8: "A move to `COMPLETED` is permitted from `ON_TRACK`, `AT_RISK` or
    `BEHIND`, and it additionally requires that *every* objective of the strategy has
    a `status` of `ACTIVE` or `REVISED` and an `attainment_status` other than
    `PENDING` — in other words that progress has been reported at least once against
    each one."

    Design: Corner/endpoints/execution_status_completed_requires_every_objective_reported
    """
    sc, _lagging_id = _behind_strategy_with_one_unmeasured_objective(api)

    refused = api.set_execution_status(
        sc.strategy_id,
        F.execution_status_payload(
            ExecutionState.COMPLETED, execution_note="Closing out year one"
        ),
    )
    validate_error(refused, ApiErrorId.OBJECTIVE_PROGRESS_MISSING, 409)

    held = sc.strategy()
    assert held["execution_state"] == ExecutionState.BEHIND
    assert held["approval_state"] == ApprovalState.APPROVED


def test_completing_a_strategy_succeeds_once_every_objective_carries_a_figure(api):
    """PRD §3.8: "A strategy with an objective that was never measured cannot be
    declared complete, and the rejection is `ERR_OBJECTIVE_PROGRESS_MISSING`."

    Design: Corner/endpoints/execution_status_completed_requires_every_objective_reported
    """
    sc, _lagging_id = _behind_strategy_with_one_unmeasured_objective(api)

    measured = validate_success(
        api.report_progress(sc.objective_id, F.report_progress_payload(2400, "2027-02-01"))
    )
    assert_close(measured["attainment_pct"], 100.00, "attainment_pct")
    assert measured["attainment_status"] == AttainmentStatus.MET

    completed = validate_success(
        api.set_execution_status(
            sc.strategy_id,
            F.execution_status_payload(
                ExecutionState.COMPLETED, execution_note="Closing out year one"
            ),
        )
    )
    assert completed["execution_state"] == ExecutionState.COMPLETED
    assert completed["execution_note"] == "Closing out year one"
    assert completed["approval_state"] == ApprovalState.APPROVED
