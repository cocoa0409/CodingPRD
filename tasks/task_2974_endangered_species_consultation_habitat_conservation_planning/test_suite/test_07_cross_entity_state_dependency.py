"""Two cross-entity state dependencies: plan/opinion and report/permit."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_error_envelope,
    assert_take_ledger_identity,
    assert_unpaginated_list,
)
from test_helpers.factories import plan_decision_payload
from test_helpers.fixtures import (
    ADJUDICATOR,
    APPROVER,
    adjudicate_report,
    build_scenario,
    read_bank,
    read_permit,
    read_plan,
    set_clock,
    setup_jeopardy_submitted_plan,
    setup_suspended_permit,
)


class TestPlanApprovalReadsTheOpinionConclusion:
    """Every plan-local criterion passes; a far aggregate decides the outcome."""

    def test_approve_is_refused_by_a_field_the_request_never_names(self, api):
        """A fully assured, unshortfalled plan still fails on the opinion's conclusion.

        PRD: "No biological opinion of the action's active consultation may carry a
        `conclusion` of `JEOPARDY` - an opinion whose `conclusion` is
        `JEOPARDY_WITH_RPA` passes the gate, as does `NO_JEOPARDY`, and a bare
        `JEOPARDY` is `ERR_JEOPARDY_UNRESOLVED` (HTTP 422)."
        PRD: "`funding_status` must be `FULLY_ASSURED`" ... "And
        `secured_mitigation_units` must be at least `final_mitigation_units`"

        Design: Difficulty/cross_entity_state_dependency/plan_approval_reads_biological_opinion_conclusion_of_another_aggregate
        """
        scenario = setup_jeopardy_submitted_plan(units=45.00)
        opinion = scenario["opinion"]
        plan = scenario["plan"]

        assert opinion["conclusion"] == "JEOPARDY"
        assert opinion["rpa_description"] is None
        assert plan["endowment_required_cents"] == 3_787_560
        assert plan["funding_status"] == "FULLY_ASSURED"
        assert plan["final_mitigation_units"] == 45.00
        assert plan["secured_mitigation_units"] == 45.00
        assert plan["plan_status"] == "SUBMITTED"

        response = api.decide_plan(plan["id"], plan_decision_payload("APPROVE"), APPROVER)

        assert_error_envelope(response, ApiErrorId.ERR_JEOPARDY_UNRESOLVED, 422)

    def test_the_refusal_moves_nothing_in_either_aggregate(self, api):
        """Neither the plan, its commitment, the bank nor the opinion is rewritten.

        PRD: "A decision is available only while `plan_status` is `SUBMITTED`."
        PRD: "All three conclusions are persistable; issuance never fails on the
        jeopardy screen."

        Design: Difficulty/cross_entity_state_dependency/plan_approval_reads_biological_opinion_conclusion_of_another_aggregate
        """
        scenario = setup_jeopardy_submitted_plan(units=45.00)
        plan_id = scenario["plan"]["id"]
        headers = scenario["proponent_headers"]

        api.decide_plan(plan_id, plan_decision_payload("APPROVE"), APPROVER)

        plan = read_plan(plan_id)
        assert plan["plan_status"] == "SUBMITTED"
        assert plan["approved_by_user_id"] is None
        assert plan["funding_status"] == "FULLY_ASSURED"

        commitments = assert_unpaginated_list(
            api.list_plan_mitigation_commitments(plan_id, headers)
        )
        assert [row["status"] for row in commitments] == ["RESERVED"]

        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_reserved"] == 45.00
        assert bank["credits_transferred"] == 0.00
        assert_bank_ledger_identity(bank)

        opinions = assert_unpaginated_list(
            api.list_biological_opinions(scenario["consultation"]["id"], headers)
        )
        assert len(opinions) == 1
        assert opinions[0]["conclusion"] == "JEOPARDY"

    def test_the_same_plan_approves_when_the_opinion_carried_an_rpa(self, api):
        """The dependency is on the conclusion value, not on the opinion's existence.

        PRD: "An unresolved `JEOPARDY` bites later, at plan approval, and supplying
        `rpa_description` at issuance time is what clears that gate."
        PRD: "An accepted `APPROVE` moves the plan `SUBMITTED - APPROVED`, records the
        deciding official's `X-User-ID` as `approved_by_user_id`, and converts the
        commitment set: every commitment in `RESERVED` moves `RESERVED - SECURED` in
        `created_at` ascending order, and for each such commitment whose `mechanism` is
        `CONSERVATION_BANK_CREDIT` the bank's `credits_reserved` decreases by `units`
        while its `credits_transferred` increases by the same `units`, preserving the
        ledger identity."

        Design: Difficulty/cross_entity_state_dependency/plan_approval_reads_biological_opinion_conclusion_of_another_aggregate
        """
        scenario = setup_jeopardy_submitted_plan(
            units=45.00,
            opinion_payload={
                "rpa_description": "Seasonal grading restrictions and burrow relocation."
            },
        )
        assert scenario["opinion"]["conclusion"] == "JEOPARDY_WITH_RPA"

        plan = get_success_data(
            api.decide_plan(
                scenario["plan"]["id"], plan_decision_payload("APPROVE"), APPROVER
            ),
            200,
        )

        assert plan["plan_status"] == "APPROVED"

        commitments = assert_unpaginated_list(
            api.list_plan_mitigation_commitments(
                plan["id"], scenario["proponent_headers"]
            )
        )
        assert [row["status"] for row in commitments] == ["SECURED"]

        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_reserved"] == 0.00
        assert bank["credits_transferred"] == 45.00
        assert_bank_ledger_identity(bank)

    def test_the_gate_is_specific_to_approve(self, api):
        """The same jeopardy plan can still be returned for revision.

        PRD: "An accepted `RETURN_FOR_REVISION` is the compensating path and moves the
        plan `SUBMITTED - DRAFT`."
        PRD: "Because `RELEASED` commitments never contribute, `endowment_base_cents`,
        `changed_circumstance_reserve_cents`, and `endowment_required_cents` all
        recompute to 0 over the now-empty contributing set, `funded_ratio` becomes
        0.0000, and `funding_status` becomes `UNFUNDED`"

        Design: Difficulty/cross_entity_state_dependency/plan_approval_reads_biological_opinion_conclusion_of_another_aggregate
        """
        scenario = setup_jeopardy_submitted_plan(units=45.00)

        plan = get_success_data(
            api.decide_plan(
                scenario["plan"]["id"],
                plan_decision_payload("RETURN_FOR_REVISION"),
                APPROVER,
            ),
            200,
        )

        assert plan["plan_status"] == "DRAFT"
        assert plan["endowment_required_cents"] == 0
        assert plan["funding_status"] == "UNFUNDED"

        commitments = assert_unpaginated_list(
            api.list_plan_mitigation_commitments(
                plan["id"], scenario["proponent_headers"]
            )
        )
        assert [row["status"] for row in commitments] == ["RELEASED"]


class TestMonitoringReportReadsTheParentPermitStatus:
    """A direct parent/child dependency that blocks now and unblocks later."""

    def _body(self, version):
        return {
            "period_start": "2027-01-01",
            "period_end": "2027-03-31",
            "take_units_reported": 0.10,
            "mitigation_units_verified": 59.72,
            "expected_permit_version": version,
        }

    def test_a_suspended_parent_blocks_a_child_that_breaks_no_other_rule(self, api):
        """0.10 units fit the remaining budget and the period does not overlap R1.

        PRD: "Monitoring reports are the proponent's ongoing obligation and are filed
        against an `ACTIVE` permit only; a report aimed at a permit in `SUSPENDED` or
        `EXPIRED` is `ERR_PERMIT_NOT_ACTIVE` (HTTP 409)."
        PRD: "Two intervals overlap when the new `period_start` is strictly earlier than
        the existing `period_end` **and** the new `period_end` is strictly later than the
        existing `period_start`"

        Design: Difficulty/cross_entity_state_dependency/monitoring_report_creation_reads_permit_status_of_parent
        """
        scenario = setup_suspended_permit()
        permit = scenario["permit"]
        assert permit["status"] == "SUSPENDED"
        assert permit["take_remaining_units"] == 0.40

        response = api.create_monitoring_report(
            permit["id"], self._body(permit["version"]), scenario["proponent_headers"]
        )

        assert_error_envelope(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)

        reports = assert_unpaginated_list(
            api.list_permit_monitoring_reports(
                permit["id"], scenario["proponent_headers"]
            )
        )
        assert len(reports) == 1
        after = read_permit(permit["id"])
        assert after["take_consumed_units"] == 3.60
        assert_take_ledger_identity(after)

    def test_rejecting_the_earlier_report_unblocks_the_identical_body(self, api):
        """The parent returning to ACTIVE is what makes the same payload acceptable.

        PRD: "If the reversal brings `take_consumed_units` **strictly below**
        `reinitiation_trigger_units` while the permit is `SUSPENDED`, the cascade
        unwinds: the permit moves `SUSPENDED - ACTIVE` and the plan moves
        `SUSPENDED_IMPLEMENTATION - IMPLEMENTING` with `assurance_review_required` set
        back to false."

        Design: Difficulty/cross_entity_state_dependency/monitoring_report_creation_reads_permit_status_of_parent
        """
        scenario = setup_suspended_permit()
        permit_id = scenario["permit"]["id"]
        headers = scenario["proponent_headers"]

        assert_error_envelope(
            api.create_monitoring_report(
                permit_id, self._body(scenario["permit"]["version"]), headers
            ),
            ApiErrorId.ERR_PERMIT_NOT_ACTIVE,
            409,
        )

        adjudicate_report(scenario["r1"]["id"], "REJECT", ADJUDICATOR)

        permit = read_permit(permit_id)
        assert permit["status"] == "ACTIVE"
        assert permit["take_consumed_units"] == 0.00
        assert permit["take_remaining_units"] == 4.00
        assert permit["suspension_count"] == 1

        plan = read_plan(scenario["plan"]["id"])
        assert plan["plan_status"] == "IMPLEMENTING"
        assert plan["assurance_review_required"] is False

        report = get_success_data(
            api.create_monitoring_report(
                permit_id, self._body(permit["version"]), headers
            ),
            201,
        )
        assert report["status"] == "SUBMITTED"
        assert read_permit(permit_id)["take_consumed_units"] == 0.10

    def test_an_expired_parent_reports_the_same_error(self, api):
        """The error id covers the other non-ACTIVE status too.

        PRD: "a report aimed at a permit in `SUSPENDED` or `EXPIRED` is
        `ERR_PERMIT_NOT_ACTIVE` (HTTP 409)."
        PRD: "When the logical clock is repositioned, every permit whose `status` is
        `ACTIVE` or `SUSPENDED` and whose `term_end` is earlier than the new clock value
        expires"

        Design: Difficulty/cross_entity_state_dependency/monitoring_report_creation_reads_permit_status_of_parent
        """
        scenario = build_scenario("permit", plan_overrides={"permit_term_years": 1})
        permit_id = scenario["permit"]["id"]

        set_clock("2027-10-02T00:00:00Z")
        permit = read_permit(permit_id)
        assert permit["status"] == "EXPIRED"

        response = api.create_monitoring_report(
            permit_id, self._body(permit["version"]), scenario["proponent_headers"]
        )

        assert_error_envelope(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)
        assert read_permit(permit_id)["status"] == "EXPIRED"
