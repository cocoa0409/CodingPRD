"""
State machines that do not run forwards only: a case that cycles back to
evaluation, and a session row whose operational and fiscal dimensions advance on
different edges.
"""

from test_helpers import (
    ADMIN_HEADERS,
    EVALUATOR_HEADERS,
    assert_case_weight,
    assert_cents,
    assert_ledger,
    assert_timeline,
    assert_unit_pool,
    build_cost_share_case,
    build_plan_with_line,
    create_authorization,
    create_provider,
    document_visit,
    factories,
    read_assessment,
    read_authorization,
    read_coordinator,
    read_cost_share,
    read_ifsp,
    read_referral,
    read_service_line,
    read_visit,
    schedule_visit,
    set_clock,
    validate_success,
)


def _schedule_supplemental(api, referral_id):
    response = api.create_assessment(
        factories.assessment_payload(
            referral_id,
            assessment_type="SUPPLEMENTAL_EVALUATION",
            scheduled_date="2026-03-25",
        ),
        EVALUATOR_HEADERS,
    )
    return validate_success(response, 201)


class TestSupplementalEvaluationRevert:
    """The backward edge from plan development to evaluation."""

    def test_supplemental_evaluation_cycles_the_case_backwards(self, api):
        """
        Scheduling a supplemental evaluation on a case awaiting its plan sends
        the case back a stage and withdraws the un-consented plan behind it.

        PRD 3.4: "The revert drags a four-hop cascade behind it. Every plan on
        the case whose `status` is `DRAFT` or `PENDING_CONSENT` transitions to
        `WITHDRAWN`. Every service line on each withdrawn plan whose `status` is
        not already `DISCONTINUED` transitions to `DISCONTINUED`."

        Design: Difficulty/non_linear_state_machine/referral_ifsp_pending_reverts_to_evaluation_pending_on_supplemental
        """
        case = build_plan_with_line(api)
        assert read_referral(api, case.referral_id)["status"] == "IFSP_PENDING"

        supplemental = _schedule_supplemental(api, case.referral_id)
        assert supplemental["status"] == "SCHEDULED"
        assert supplemental["assessment_type"] == "SUPPLEMENTAL_EVALUATION"

        referral = read_referral(api, case.referral_id)
        assert referral["status"] == "EVALUATION_PENDING"

        plan = read_ifsp(api, case.ifsp_id)
        assert plan["status"] == "WITHDRAWN"
        assert plan["service_line_count"] == 0

        assert read_service_line(api, case.line_id)["status"] == "DISCONTINUED"

        # The pre-plan base returns and the four-line term was never held.
        assert_case_weight(referral["case_weight_points"], 1.50)
        coordinator = read_coordinator(api, case.coordinator_id)
        assert_case_weight(coordinator["weighted_caseload_points"], 1.50)
        assert coordinator["active_case_count"] == 1

    def test_revert_restarts_the_statutory_clock_but_keeps_the_findings(self, api):
        """
        With the plan withdrawn there is no qualifying meeting date left, so the
        stop date falls back to the logical clock and the verdict resumes
        running — while eligibility and the entry ratings stay on the record.

        PRD 3.3: "If the case has an initial plan — a plan whose `ifsp_type` is
        `INITIAL` and whose `status` is `PENDING_CONSENT`, `ACTIVE`,
        `AMENDMENT_PENDING`, `SUPERSEDED` or `CLOSED` — with a recorded
        `meeting_date`, that meeting date is the stop date and the clock has
        stopped. Otherwise the stop date is the current logical clock date and
        the clock is still running."

        Design: Difficulty/non_linear_state_machine/referral_ifsp_pending_reverts_to_evaluation_pending_on_supplemental
        """
        case = build_plan_with_line(api)

        _schedule_supplemental(api, case.referral_id)

        compliance = validate_success(
            api.get_timeline_compliance(case.referral_id, ADMIN_HEADERS), 200
        )
        assert_timeline(
            compliance,
            stop_date="2026-03-20",
            gross_elapsed_days=18,
            excluded_delay_days=0,
            net_elapsed_days=18,
            initial_timeline_status="IN_PROGRESS",
        )

        referral = read_referral(api, case.referral_id)
        assert referral["eligibility_status"] == "ELIGIBLE"
        assert referral["entry_outcomes_date"] == "2026-03-20"
        assert referral["entry_rating_social"] == 3
        assert referral["entry_rating_knowledge"] == 4
        assert referral["entry_rating_needs"] == 3
        assert read_assessment(api, case.eval_id)["status"] == "COMPLETED"


# Two 30-minute sessions on one authorization, against a TIER_1 determination.
DOCUMENT_CLOCK = "2026-03-24T12:00:00Z"
ACCRUED_SHARE_CENTS = 650


def _build_two_session_case(api):
    """A case with a provisional determination on file, one session already
    documented as delivered and accrued, and a second still scheduled."""
    case = build_cost_share_case(
        api,
        cost_share={
            "household_size": 4,
            "declared_annual_gross_income_cents": 12_000_000,
            "insurance_use_consent": False,
        },
    )
    case.provider_id = create_provider(api)
    case.provider_ids.append(case.provider_id)
    case.authorization_id = create_authorization(api, case.line_id, case.provider_id)
    case.authorization_ids.append(case.authorization_id)
    for start, end in (
        ("2026-03-23T09:00:00Z", "2026-03-23T09:30:00Z"),
        ("2026-03-24T09:00:00Z", "2026-03-24T09:30:00Z"),
    ):
        case.visit_ids.append(
            schedule_visit(api, case.authorization_id, start, end)
        )
    case.visit_id = case.visit_ids[0]
    set_clock(api, DOCUMENT_CLOCK)
    case.clock = DOCUMENT_CLOCK
    document_visit(
        api,
        case.visit_ids[0],
        case.provider_id,
        visit_status="DELIVERED",
        actual_units=2,
        actual_start="2026-03-23T09:00:00Z",
        actual_end="2026-03-23T09:30:00Z",
    )
    return case


class TestSessionStatusDimensionsAdvanceIndependently:
    """One row, two state fields, four different edges."""

    def test_family_cancellation_charges_nothing_and_owes_no_makeup(self, api):
        """
        A family cancellation moves the operational dimension to
        FAMILY_CANCELLED while the fiscal dimension goes straight to
        CANCELLED_NO_CHARGE, and no makeup obligation is created.

        PRD 3.7: "`FAMILY_CANCELLED` moves the session `SCHEDULED →
        FAMILY_CANCELLED` and explicitly does **not** increase
        `makeup_owed_units`: only a provider's failure creates a makeup
        obligation."

        Design: Difficulty/non_linear_state_machine/service_visit_parallel_status_dimensions_independent
        """
        case = _build_two_session_case(api)
        second_visit_id = case.visit_ids[1]

        response = api.document_visit(
            second_visit_id,
            {"visit_status": "FAMILY_CANCELLED"},
            case.provider_headers,
        )
        cancelled = validate_success(response, 200)

        assert cancelled["visit_status"] == "FAMILY_CANCELLED"
        assert cancelled["billing_status"] == "CANCELLED_NO_CHARGE"
        assert cancelled["actual_units"] == 0
        assert_cents(cancelled["family_share_cents"], 0, "family_share_cents")

        line = read_service_line(api, case.line_id)
        assert line["makeup_owed_units"] == 0
        assert line["status"] == "IN_DELIVERY"

        determination = read_cost_share(api, case.cost_share_id)
        assert_ledger(determination, ACCRUED_SHARE_CENTS, ACCRUED_SHARE_CENTS, 0)
        assert_cents(
            determination["assessed_monthly_fee_cents"],
            2_600,
            "assessed_monthly_fee_cents",
        )

    def test_void_pairs_the_operational_and_fiscal_moves(self, api):
        """
        Voiding the delivered session moves visit_status to VOIDED and
        billing_status to REVERSED in the same act, unwinding the ledger while
        the row keeps its accrued figure as the audit value.

        PRD 3.7: "A void therefore pairs the operational move `DELIVERED →
        VOIDED` with a fiscal move to `REVERSED` from whichever of `ACCRUED`,
        `EXEMPT` or `CAPPED` the session was in."

        Design: Difficulty/non_linear_state_machine/service_visit_parallel_status_dimensions_independent
        """
        case = _build_two_session_case(api)
        first_visit_id = case.visit_ids[0]

        before = read_visit(api, first_visit_id)
        assert before["visit_status"] == "DELIVERED"
        assert before["billing_status"] == "ACCRUED"
        assert_cents(
            before["family_share_cents"], ACCRUED_SHARE_CENTS, "family_share_cents"
        )

        response = api.void_visit(
            first_visit_id, factories.void_visit_payload(), ADMIN_HEADERS
        )
        voided = validate_success(response, 200)

        assert voided["visit_status"] == "VOIDED"
        assert voided["billing_status"] == "REVERSED"
        assert voided["void_reason_code"] == "DOCUMENTATION_ERROR"
        assert_cents(
            voided["family_share_cents"], ACCRUED_SHARE_CENTS, "family_share_cents"
        )

        authorization = read_authorization(api, case.authorization_id)
        assert authorization["units_consumed"] == 0
        assert authorization["units_remaining"] == 24
        assert authorization["status"] == "ACTIVE"

        line = read_service_line(api, case.line_id)
        assert line["units_delivered"] == 0
        assert line["status"] == "IN_DELIVERY"
        assert_unit_pool(line, units_committed=24, units_pool_remaining=72)

        determination = read_cost_share(api, case.cost_share_id)
        assert_ledger(determination, 0, 0, 0)
        assert_cents(
            determination["month_accrued_cents"], 0, "month_accrued_cents"
        )
        assert_cents(
            determination["assessed_monthly_fee_cents"],
            2_600,
            "assessed_monthly_fee_cents",
        )
