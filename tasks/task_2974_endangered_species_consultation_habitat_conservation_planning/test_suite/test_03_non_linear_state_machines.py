"""State machines that fork, re-join, cycle, and regress independently."""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_error_envelope,
    assert_same_instant,
    assert_unpaginated_list,
)
from test_helpers.factories import (
    concurrence_payload,
    habitat_conservation_plan_payload,
    information_request_payload,
    plan_decision_payload,
)
from test_helpers.fixtures import (
    APPROVER,
    ISSUER,
    REVIEWER,
    add_commitment,
    read_action,
    read_plan,
    submit_plan,
    read_consultation,
    setup_fully_assured_draft_plan,
    setup_informal_consultation_under_review,
    setup_tolled_consultation,
)


class TestInformalForkJoin:
    """The informal branch converges on the same join as the formal one."""

    def test_concurrence_carries_the_informal_branch_into_the_join(self, api):
        """A written concurrence closes the consultation and moves the action.

        PRD: "An informal consultation concludes by written concurrence, carrying a
        `concurrence_note`. Concurrence moves the consultation `UNDER_REVIEW -
        CONCLUDED_CONCURRENCE`, which is terminal, and moves the action from
        `INFORMAL_CONSULTATION` to `CONSULTATION_CONCLUDED`."

        PRD: "Both join hops change nothing on the action but its `status`, its
        `updated_at`, and its `version`."

        Design: Difficulty/non_linear_state_machine/project_action_fork_join_informal_branch_converges_and_locks
        """
        scenario = setup_informal_consultation_under_review()
        assert scenario["action"]["status"] == "INFORMAL_CONSULTATION"
        assert scenario["action"]["effect_determination"] == "NLAA"
        assert scenario["consultation"]["status"] == "UNDER_REVIEW"
        assert scenario["consultation"]["ba_revision_number"] == 1

        response = api.record_concurrence(
            scenario["consultation_id"], concurrence_payload(), REVIEWER
        )

        consultation = get_success_data(response, 200)
        assert consultation["status"] == "CONCLUDED_CONCURRENCE"
        action = read_action(scenario["action"]["id"])
        assert action["status"] == "CONSULTATION_CONCLUDED"
        assert action["active_consultation_id"] == scenario["consultation_id"]
        assert action["effect_determination"] == "NLAA"
        assert action["total_overlap_acres"] == 10.00
        assert action["overlap_pct"] == 5.00

    def test_the_informal_branch_never_produces_a_biological_opinion(self, api):
        """The opinion list of a concurred consultation stays empty.

        PRD: "A formal consultation must end in a biological opinion, where an
        informal one may end in a written concurrence."

        PRD: "Biological opinions are immutable and are discoverable only through the
        consultation's opinion list beyond the creation response itself."

        Design: Difficulty/non_linear_state_machine/project_action_fork_join_informal_branch_converges_and_locks
        """
        scenario = setup_informal_consultation_under_review()
        validate_success(
            api.record_concurrence(
                scenario["consultation_id"], concurrence_payload(), REVIEWER
            ),
            200,
        )

        rows = assert_unpaginated_list(
            api.list_biological_opinions(scenario["consultation_id"], REVIEWER)
        )

        assert rows == []

    def test_the_terminal_state_refuses_every_further_consultation_transition(self, api):
        """Concurrence is not idempotent and the cycle cannot be re-entered.

        PRD: "Concurrence moves the consultation `UNDER_REVIEW -
        CONCLUDED_CONCURRENCE`, which is terminal".

        PRD: "of which only `CONCLUDED_CONCURRENCE` is terminal."

        Design: Difficulty/non_linear_state_machine/project_action_fork_join_informal_branch_converges_and_locks
        """
        scenario = setup_informal_consultation_under_review()
        validate_success(
            api.record_concurrence(
                scenario["consultation_id"], concurrence_payload(), REVIEWER
            ),
            200,
        )

        assert_error_envelope(
            api.record_concurrence(
                scenario["consultation_id"], concurrence_payload(), REVIEWER
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        assert_error_envelope(
            api.request_information(
                scenario["consultation_id"], information_request_payload(), REVIEWER
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        assert_error_envelope(
            api.run_effect_determination(
                scenario["action"]["id"], scenario["proponent_headers"]
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

    def test_the_state_check_outranks_the_consultation_type_check(self, api):
        """An opinion on a concluded informal consultation is a state error.

        PRD: "The ladder runs in this sequence. ... (9) The target row's current state
        being a legal source state for the requested transition -
        `ERR_INVALID_STATE_TRANSITION`. ... (14) The consultation-type match on
        concurrence and on opinion issuance - `ERR_CONSULTATION_TYPE_MISMATCH`."

        PRD: "attempting an opinion on an `INFORMAL` consultation is the same
        `ERR_CONSULTATION_TYPE_MISMATCH`."

        Both conditions are violated at once, and the earlier rung decides.

        Design: Difficulty/non_linear_state_machine/project_action_fork_join_informal_branch_converges_and_locks
        """
        scenario = setup_informal_consultation_under_review()
        validate_success(
            api.record_concurrence(
                scenario["consultation_id"], concurrence_payload(), REVIEWER
            ),
            200,
        )

        assert_error_envelope(
            api.issue_biological_opinion(scenario["consultation_id"], {}, ISSUER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

    def test_the_join_and_not_the_branch_gates_plan_development(self, api):
        """A plan opens on the informal branch exactly as on the formal one.

        PRD: "Three gates apply. The action's `status` must be
        `CONSULTATION_CONCLUDED`."

        PRD: "On success the action moves `CONSULTATION_CONCLUDED - HCP_DEVELOPMENT`
        and the plan is created with `plan_status` `DRAFT` and `funding_status`
        `UNFUNDED`."

        Design: Difficulty/non_linear_state_machine/project_action_fork_join_informal_branch_converges_and_locks
        """
        scenario = setup_informal_consultation_under_review()
        validate_success(
            api.record_concurrence(
                scenario["consultation_id"], concurrence_payload(), REVIEWER
            ),
            200,
        )

        response = api.create_habitat_conservation_plan(
            scenario["action"]["id"],
            habitat_conservation_plan_payload(),
            scenario["proponent_headers"],
        )

        plan = get_success_data(response, 201)
        assert plan["plan_status"] == "DRAFT"
        assert plan["funding_status"] == "UNFUNDED"
        assert read_action(scenario["action"]["id"])["status"] == "HCP_DEVELOPMENT"


class TestInformationRequestCycle:
    """The cycle is bounded by a counter, not by a terminal state."""

    def test_the_first_episode_tolls_its_whole_days_and_slides_the_deadline(self, api):
        """Seven whole days of an information request move the deadline seven days.

        PRD: "Doing so moves the consultation `UNDER_REVIEW - INFO_REQUESTED`, stamps
        `info_requested_at` with the current logical clock, and increases
        `info_request_count` by 1."

        PRD: "From `INFO_REQUESTED - UNDER_REVIEW`, the information-request episode
        closes: the whole days elapsed between `info_requested_at` and the current
        logical clock are computed by discarding any partial day, that whole-day count
        is **added** to `tolled_days`, `info_requested_at` is set back to null, and
        `deadline_at` is recomputed as `clock_started_at` advanced by `statutory_days`
        plus the new `tolled_days`."

        Design: Difficulty/non_linear_state_machine/consultation_info_request_cycle_tolls_deadline_twice_then_refuses
        """
        scenario = setup_tolled_consultation()

        assert scenario["rq1"]["status"] == "INFO_REQUESTED"
        assert scenario["rq1"]["info_request_count"] == 1
        assert_same_instant(scenario["rq1"]["info_requested_at"], "2026-10-05T00:00:00Z")
        assert scenario["rev2"]["tolled_days"] == 7
        assert scenario["rev2"]["ba_revision_number"] == 2
        assert scenario["rev2"].get("info_requested_at") is None
        assert_same_instant(scenario["rev2"]["deadline_at"], "2027-02-20T00:00:00Z")

    def test_the_second_episode_accumulates_rather_than_overwrites(self, api):
        """Three more tolled days add to seven, they do not replace them.

        PRD: "An episode still open contributes nothing, and each closed episode
        contributes exactly once."

        PRD: "Every accepted submission increases `ba_revision_number` by 1".

        Design: Difficulty/non_linear_state_machine/consultation_info_request_cycle_tolls_deadline_twice_then_refuses
        """
        scenario = setup_tolled_consultation()

        assert scenario["rq2"]["info_request_count"] == 2
        assert scenario["rev3"]["tolled_days"] == 10
        assert scenario["rev3"]["ba_revision_number"] == 3
        assert scenario["rev3"]["status"] == "UNDER_REVIEW"
        assert_same_instant(scenario["rev3"]["deadline_at"], "2027-02-23T00:00:00Z")

    def test_a_third_information_request_is_refused_with_no_partial_effect(self, api):
        """The counter bound is a state error, not a deadline error.

        PRD: "And `info_request_count` must be **below** two before the request, so a
        consultation may sustain at most two information requests; a third attempt is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409), not a deadline error."

        Design: Difficulty/non_linear_state_machine/consultation_info_request_cycle_tolls_deadline_twice_then_refuses
        """
        scenario = setup_tolled_consultation()

        assert_error_envelope(
            api.request_information(
                scenario["consultation_id"],
                information_request_payload(
                    request_note="Third request - reviewer wants a further round of edits."
                ),
                REVIEWER,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        consultation = read_consultation(scenario["consultation_id"])
        assert consultation["info_request_count"] == 2
        assert consultation["tolled_days"] == 10
        assert consultation["status"] == "UNDER_REVIEW"
        assert consultation.get("info_requested_at") is None
        assert_same_instant(consultation["deadline_at"], "2027-02-23T00:00:00Z")

    def test_the_cycle_reuses_one_consultation_row(self, api):
        """Two traversals open no additional consultations.

        PRD: "The resulting cycle `UNDER_REVIEW - INFO_REQUESTED - UNDER_REVIEW` is
        therefore repeatable up to twice."

        PRD: "exactly one consultation is created with `consultation_type` `FORMAL`".

        Design: Difficulty/non_linear_state_machine/consultation_info_request_cycle_tolls_deadline_twice_then_refuses
        """
        scenario = setup_tolled_consultation()

        rows = assert_unpaginated_list(
            api.list_action_consultations(
                scenario["action"]["id"], scenario["proponent_headers"]
            )
        )

        assert len(rows) == 1
        assert rows[0]["id"] == scenario["consultation_id"]

    def test_the_bounded_cycle_still_exits_into_opinion_issued(self, api):
        """Exhausting the counter does not trap the consultation.

        PRD: "The deadline gates **only** the information request. Issuing a biological
        opinion after `deadline_at` has passed is permitted".

        PRD: "The consultation moves `UNDER_REVIEW - OPINION_ISSUED` and the action
        moves `FORMAL_CONSULTATION - CONSULTATION_CONCLUDED`."

        Design: Difficulty/non_linear_state_machine/consultation_info_request_cycle_tolls_deadline_twice_then_refuses
        """
        scenario = setup_tolled_consultation()

        response = api.issue_biological_opinion(scenario["consultation_id"], {}, ISSUER)

        get_success_data(response, 201)
        assert read_consultation(scenario["consultation_id"])["status"] == "OPINION_ISSUED"
        assert read_action(scenario["action"]["id"])["status"] == "CONSULTATION_CONCLUDED"


class TestFundingDimensionRegression:
    """Two independent state dimensions on one plan row, one of them regressing."""

    def test_one_sufficient_assurance_reaches_fully_assured_while_the_plan_holds(
        self, api
    ):
        """The funding dimension moves in one hop and the plan dimension does not.

        PRD: "A single sufficient contribution can therefore carry the plan
        `UNFUNDED - FULLY_ASSURED` in one hop".

        PRD: "The funding dimension can regress while the plan dimension stands
        perfectly still, and the plan dimension can advance without the funding
        dimension moving at all."

        A single 10.00-credit commitment endows 751,500 with a 90,180 reserve, so
        841,680 cents covers it exactly.

        Design: Difficulty/non_linear_state_machine/hcp_funding_dimension_regresses_while_plan_status_dimension_holds
        """
        scenario = setup_fully_assured_draft_plan()
        plan = scenario["plan"]

        assert plan["endowment_base_cents"] == 751_500
        assert plan["changed_circumstance_reserve_cents"] == 90_180
        assert plan["endowment_required_cents"] == 841_680
        assert plan["endowment_secured_cents"] == 841_680
        assert plan["funding_status"] == "FULLY_ASSURED"
        assert plan["funded_ratio"] == 1.0000
        assert plan["plan_status"] == "DRAFT"

    def test_a_further_commitment_regresses_funding_without_moving_plan_status(self, api):
        """Raising the requirement walks the funding dimension backwards.

        PRD: "That re-derivation can move `funding_status` **backwards**: a plan
        sitting at `FULLY_ASSURED` whose new commitment pushes
        `endowment_required_cents` above what is already secured regresses
        `FULLY_ASSURED - PARTIALLY_ASSURED` while `plan_status` does not budge from
        `DRAFT`."

        PRD: "otherwise it becomes `PARTIALLY_ASSURED` when twice
        `endowment_secured_cents` is at least `endowment_required_cents`".

        Design: Difficulty/non_linear_state_machine/hcp_funding_dimension_regresses_while_plan_status_dimension_holds
        """
        scenario = setup_fully_assured_draft_plan()

        commitment = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 5.00,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )

        assert commitment["status"] == "RESERVED"
        assert commitment["base_fee_cents"] == 1_250_000
        assert commitment["endowment_contribution_cents"] == 375_750
        plan = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
        assert plan["endowment_base_cents"] == 1_127_250
        assert plan["changed_circumstance_reserve_cents"] == 135_270
        assert plan["endowment_required_cents"] == 1_262_520
        assert plan["endowment_secured_cents"] == 841_680
        assert plan["funding_status"] == "PARTIALLY_ASSURED"
        assert plan["funded_ratio"] == 0.6667
        assert plan["plan_status"] == "DRAFT"
        assert plan.get("approved_by_user_id") is None

    def test_submission_advances_the_plan_dimension_alone(self, api):
        """The plan may advance while the funding dimension stands still.

        PRD: "Submitting the plan moves it `DRAFT - SUBMITTED` and takes no body
        fields. ... Submission recomputes `final_mitigation_units` with the FINAL
        variant, writes `mitigation_delta_units`, and recomputes
        `secured_mitigation_units` as the sum of `units` over the plan's `RESERVED` and
        `SECURED` commitments, rounded half up to two decimal places."

        Design: Difficulty/non_linear_state_machine/hcp_funding_dimension_regresses_while_plan_status_dimension_holds
        """
        scenario = setup_fully_assured_draft_plan()
        add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 5.00,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )

        plan = submit_plan(scenario["plan"]["id"], scenario["proponent"])

        assert plan["plan_status"] == "SUBMITTED"
        assert plan["funding_status"] == "PARTIALLY_ASSURED"
        assert plan["final_mitigation_units"] == 59.70
        assert plan["mitigation_delta_units"] == -0.30
        assert plan["secured_mitigation_units"] == 15.00

    def test_the_funding_gate_is_reported_ahead_of_the_shortfall_gate(self, api):
        """Both approval gates fail and the earlier rung decides.

        PRD: "`funding_status` must be `FULLY_ASSURED`, and `UNFUNDED` or
        `PARTIALLY_ASSURED` is `ERR_FUNDING_NOT_ASSURED` (HTTP 422). And
        `secured_mitigation_units` must be at least `final_mitigation_units`, a
        shortfall being `ERR_MITIGATION_SHORTFALL` (HTTP 422)."

        PRD: "(26) The funding-assurance gate on approval - `ERR_FUNDING_NOT_ASSURED`.
        (27) The mitigation-sufficiency gate on approval - `ERR_MITIGATION_SHORTFALL`."

        Design: Difficulty/non_linear_state_machine/hcp_funding_dimension_regresses_while_plan_status_dimension_holds
        """
        scenario = setup_fully_assured_draft_plan()
        add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 5.00,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )
        submit_plan(scenario["plan"]["id"], scenario["proponent"])

        response = api.decide_plan(
            scenario["plan"]["id"], plan_decision_payload("APPROVE"), APPROVER
        )

        assert_error_envelope(response, ApiErrorId.ERR_FUNDING_NOT_ASSURED, 422)
