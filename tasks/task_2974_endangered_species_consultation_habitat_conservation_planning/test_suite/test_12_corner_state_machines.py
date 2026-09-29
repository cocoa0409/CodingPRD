"""Declared lifecycles: initial states, terminal lockdowns, and side-effect sets.

Every test in this file translates one `state_machines` instance of the corner
design index: the eight lifecycles' initial states, the two terminal lockdowns,
the rung-9 refusals that outrank every business rule, the non-idempotent
transitions, the three cascades that write more than one aggregate, the
three-way circumstance branch, and the edge that closes the reinitiation cycle.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_changed_circumstance_event,
    assert_error_envelope,
    assert_response_cost_identity,
    assert_same_instant,
    assert_unpaginated_list,
)
from test_helpers.factories import (
    adjudication_payload,
    biological_assessment_payload,
    changed_circumstance_event_payload,
    circumstance_response_payload,
    concurrence_payload,
    funding_assurance_payload,
    habitat_conservation_plan_payload,
    incidental_take_permit_payload,
    information_request_payload,
    plan_decision_payload,
)
from test_helpers.fixtures import (
    ADJUDICATOR,
    APPROVER,
    ISSUER,
    REVIEWER,
    add_commitment,
    build_scenario,
    file_monitoring_report,
    read_action,
    read_bank,
    read_consultation,
    read_permit,
    read_plan,
    read_proponent,
    run_effect_determination,
    set_clock,
    setup_action_with_absent_determinations,
    setup_informal_consultation_under_review,
    setup_take_exceedance,
    submit_biological_assessment,
)


class TestDeclaredInitialStates:
    """Every lifecycle opens in its own declared initial state."""

    def test_a_new_plan_reports_two_initial_states_on_one_row(self, api):
        """The plan dimension and the funding dimension start independently.

        PRD: "On success the action moves `CONSULTATION_CONCLUDED -
        HCP_DEVELOPMENT` and the plan is created with `plan_status` `DRAFT` and
        `funding_status` `UNFUNDED`."

        PRD: "Every accepted commitment is created in `status` `RESERVED`."

        Design: Corner/state_machines/every_lifecycle_starts_in_its_declared_initial_state
        """
        scenario = build_scenario("plan")

        assert scenario["plan"]["plan_status"] == "DRAFT"
        assert scenario["plan"]["funding_status"] == "UNFUNDED"
        commitment = add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 45.01,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )
        assert commitment["status"] == "RESERVED"
        plan = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
        assert plan["plan_status"] == "DRAFT"
        assert plan["funding_status"] == "UNFUNDED"

    def test_the_action_and_its_consultation_open_in_their_own_initial_states(self, api):
        """Registration seeds SCREENING and the fork seeds DRAFT_BA.

        PRD: "Every new action begins with `status` at `SCREENING`,
        `effect_determination` at `PENDING`, `total_overlap_acres` at 0.00,
        `overlap_pct` at 0.00, `active_consultation_id` null, and
        `reinitiation_reason` at `NONE`."

        PRD: "It opens in `DRAFT_BA`, meaning the proponent still owes the agency a
        biological assessment."

        Design: Corner/state_machines/every_lifecycle_starts_in_its_declared_initial_state
        """
        scenario = build_scenario("determinations")

        assert scenario["action"]["status"] == "SCREENING"
        assert scenario["action"]["effect_determination"] == "PENDING"
        assert scenario["action"]["active_consultation_id"] is None
        action = run_effect_determination(scenario["action"], scenario["proponent"])
        consultation = read_consultation(action["active_consultation_id"])
        assert consultation["status"] == "DRAFT_BA"
        assert consultation["ba_revision_number"] == 0

    def test_the_permit_opens_active_and_its_first_report_opens_submitted(self, api):
        """Two more lifecycles seeded by two different writes.

        PRD: "The permit is created in `status` `ACTIVE`, the plan moves
        `APPROVED - IMPLEMENTING`, and the action moves `HCP_DEVELOPMENT -
        PERMITTED`."

        PRD: "The report is created in `status` `SUBMITTED` and the permit's
        `version` increases by 1."

        Design: Corner/state_machines/every_lifecycle_starts_in_its_declared_initial_state
        """
        scenario = build_scenario("permit")
        assert scenario["permit"]["status"] == "ACTIVE"
        assert scenario["permit"]["suspension_count"] == 0
        set_clock("2027-04-15T00:00:00Z")

        report = file_monitoring_report(
            scenario["permit"]["id"],
            scenario["proponent"],
            mitigation_units_verified=59.72,
        )

        assert report["status"] == "SUBMITTED"
        permit = read_permit(scenario["permit"]["id"])
        assert permit["status"] == "ACTIVE"
        assert permit["version"] == scenario["permit"]["version"] + 1


class TestClearedNoEffectLockdown:
    """CLEARED_NO_EFFECT is a terminal state with no outgoing transition at all."""

    def test_a_cleared_action_admits_no_further_transition(self, api):
        """The clean no-effect outcome closes the file permanently.

        PRD: "An action with determinations that are all absent has an **empty**
        candidate set, which is a legitimate outcome rather than an error:
        `total_overlap_acres` and `overlap_pct` are both written as 0.00 and the
        determination is `NO_EFFECT`."

        PRD: "**no consultation row is created at all** - `active_consultation_id`
        stays null and no statutory clock ever starts. `CLEARED_NO_EFFECT` is
        terminal; nothing further happens to that action."

        PRD: "it is available only while the action's `status` is `SCREENING`, so a
        second determination on the same action is `ERR_INVALID_STATE_TRANSITION`
        (HTTP 409)."

        PRD: "The action's `status` must be `CONSULTATION_CONCLUDED`."

        Design: Corner/state_machines/cleared_no_effect_action_is_locked_down
        """
        scenario = setup_action_with_absent_determinations()

        action = run_effect_determination(scenario["action"], scenario["proponent"])

        assert action["effect_determination"] == "NO_EFFECT"
        assert action["status"] == "CLEARED_NO_EFFECT"
        assert action["active_consultation_id"] is None
        assert_error_envelope(
            api.run_effect_determination(action["id"], scenario["proponent_headers"]),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        assert_error_envelope(
            api.create_habitat_conservation_plan(
                action["id"],
                habitat_conservation_plan_payload(),
                scenario["proponent_headers"],
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        assert (
            assert_unpaginated_list(
                api.list_action_consultations(action["id"], scenario["proponent_headers"])
            )
            == []
        )
        reread = read_action(action["id"])
        assert reread["total_overlap_acres"] == 0.00
        assert reread["overlap_pct"] == 0.00
        assert reread["status"] == "CLEARED_NO_EFFECT"


class TestConcludedConcurrenceTerminality:
    """The informal branch's join point is the consultation machine's only terminal."""

    def test_concurrence_locks_the_consultation_and_the_action(self, api):
        """Neither a fresh assessment nor a second concurrence is accepted after it.

        PRD: "Concurrence moves the consultation `UNDER_REVIEW -
        CONCLUDED_CONCURRENCE`, which is terminal, and moves the action from
        `INFORMAL_CONSULTATION` to `CONSULTATION_CONCLUDED`."

        PRD: "of which only `CONCLUDED_CONCURRENCE` is terminal."

        PRD: "(9) The target row's current state being a legal source state for the
        requested transition - `ERR_INVALID_STATE_TRANSITION`."

        PRD: "A formal consultation must end in a biological opinion, where an
        informal one may end in a written concurrence."

        Design: Corner/state_machines/concluded_concurrence_is_a_terminal_consultation_state
        """
        scenario = setup_informal_consultation_under_review()
        consultation_id = scenario["consultation_id"]
        get_success_data(
            api.record_concurrence(consultation_id, concurrence_payload(), REVIEWER), 200
        )

        assert_error_envelope(
            api.submit_biological_assessment(
                consultation_id,
                biological_assessment_payload(ba_narrative="Revised effects analysis."),
                scenario["proponent_headers"],
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        assert_error_envelope(
            api.record_concurrence(consultation_id, concurrence_payload(), REVIEWER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        consultation = read_consultation(consultation_id)
        assert consultation["status"] == "CONCLUDED_CONCURRENCE"
        assert consultation["consultation_type"] == "INFORMAL"
        assert consultation["statutory_days"] == 60
        assert consultation["ba_revision_number"] == 1
        action = read_action(scenario["action"]["id"])
        assert action["status"] == "CONSULTATION_CONCLUDED"
        assert action["effect_determination"] == "NLAA"
        assert (
            assert_unpaginated_list(
                api.list_biological_opinions(consultation_id, REVIEWER)
            )
            == []
        )


class TestUntabledTransitions:
    """A transition absent from the table is refused before any business rule runs."""

    def test_three_machines_refuse_state_illegal_requests_ahead_of_business_rules(
        self, api
    ):
        """One fixture probes the consultation, the plan, and the event machine.

        PRD: "Requests are checked against an ordered ladder of 29 rules, and the
        **first** rule violated decides the response. Later violations are never
        reported, never merged into the message, and never influence the status code."

        PRD: "Doing so moves the consultation `UNDER_REVIEW - INFO_REQUESTED`,
        stamps `info_requested_at` with the current logical clock, and increases
        `info_request_count` by 1."

        PRD: "A decision is available only while `plan_status` is `SUBMITTED`."

        PRD: "A circumstance event is reported against a plan whose `plan_status` is
        `IMPLEMENTING` or `SUSPENDED_IMPLEMENTATION`; reporting one against a plan in
        any other plan state is `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        The consultation sits in OPINION_ISSUED, the plan in DRAFT with one
        commitment, so none of the three answers is a deadline, funding, shortfall
        or contribution error.

        Design: Corner/state_machines/transitions_absent_from_the_table_are_refused_with_409
        """
        scenario = build_scenario("plan")
        add_commitment(
            scenario["plan"]["id"],
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 45.01,
                "conservation_bank_id": scenario["bank"]["id"],
            },
        )
        plan_id = scenario["plan"]["id"]
        consultation_id = scenario["consultation"]["id"]
        assert scenario["consultation"]["status"] == "OPINION_ISSUED"

        assert_error_envelope(
            api.request_information(
                consultation_id, information_request_payload(), REVIEWER
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        assert_error_envelope(
            api.decide_plan(plan_id, plan_decision_payload("APPROVE"), APPROVER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        assert_error_envelope(
            api.create_changed_circumstance_event(
                plan_id,
                changed_circumstance_event_payload(response_cost_cents=100_000),
                scenario["proponent_headers"],
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        plan = read_plan(plan_id)
        assert plan["plan_status"] == "DRAFT"
        assert plan["approved_by_user_id"] is None
        assert plan["reserve_drawn_cents"] == 0
        assert plan["funding_status"] == "UNFUNDED"
        assert (
            assert_unpaginated_list(
                api.list_plan_changed_circumstance_events(
                    plan_id, scenario["proponent_headers"]
                )
            )
            == []
        )
        consultation = read_consultation(consultation_id)
        assert consultation["info_request_count"] == 0
        assert consultation["info_requested_at"] is None


class TestFundingDimensionGate:
    """The funding dimension is gated on the plan dimension, not on itself."""

    def test_an_approved_plan_refuses_a_further_funding_assurance(self, api):
        """A harmless-looking top-up on a FULLY_ASSURED plan is still a 409.

        PRD: "Funding assurances are recorded against the plan while its
        `plan_status` is `DRAFT` or `SUBMITTED`."

        PRD: "(9) The target row's current state being a legal source state for the
        requested transition - `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/funding_assurance_refused_once_the_plan_is_approved
        """
        scenario = build_scenario("approved")
        plan_id = scenario["plan"]["id"]
        before = read_plan(plan_id, scenario["proponent_headers"])
        assert before["plan_status"] == "APPROVED"
        assert before["funding_status"] == "FULLY_ASSURED"
        assert before["endowment_required_cents"] == 5_026_514
        assert before["endowment_secured_cents"] == 5_026_514

        assert_error_envelope(
            api.create_funding_assurance(
                plan_id,
                funding_assurance_payload(100_000),
                scenario["proponent_headers"],
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        after = read_plan(plan_id, scenario["proponent_headers"])
        assert after["endowment_secured_cents"] == 5_026_514
        assert after["funded_ratio"] == 1.0000
        assert after["funding_status"] == "FULLY_ASSURED"
        assert after["plan_status"] == "APPROVED"
        assert after["version"] == before["version"]


class TestNonIdempotentTransitions:
    """Replaying a fired transition is a refusal rather than a no-op or a duplicate."""

    def test_replaying_submission_and_issuance_mints_nothing(self, api):
        """A second issuance must not mint ITP-000002 against the same plan.

        PRD: "Submitting the plan moves it `DRAFT - SUBMITTED` and takes no body
        fields."

        PRD: "A plan that already has a permit cannot receive a second one; the
        attempt is `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        PRD: "`permit_number` is the literal prefix `ITP-` followed by a six-digit
        zero-padded ordinal equal to one more than the number of incidental take
        permits created before this one, counting the whole global permit table
        ordered by `created_at` ascending - never by `id`."

        Design: Corner/state_machines/submission_and_permit_issuance_are_not_idempotent
        """
        scenario = build_scenario("permit")
        plan_id = scenario["plan"]["id"]
        assert scenario["plan"]["plan_status"] == "IMPLEMENTING"
        assert scenario["permit"]["permit_number"] == "ITP-000001"

        assert_error_envelope(
            api.submit_plan(plan_id, scenario["proponent_headers"]),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )
        assert_error_envelope(
            api.issue_incidental_take_permit(
                plan_id,
                incidental_take_permit_payload(
                    implementing_agreement_reference="IA-2026-0418"
                ),
                ISSUER,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        permits = assert_unpaginated_list(
            api.list_plan_incidental_take_permits(plan_id, scenario["proponent_headers"])
        )
        assert len(permits) == 1
        assert permits[0]["permit_number"] == "ITP-000001"
        plan = read_plan(plan_id)
        assert plan["plan_status"] == "IMPLEMENTING"
        assert plan["final_mitigation_units"] == 59.70
        assert plan["mitigation_delta_units"] == -0.30
        assert read_action(scenario["action"]["id"])["status"] == "PERMITTED"


class TestApprovalCascade:
    """One APPROVE decision writes the plan, every commitment, and the bank."""

    def test_approval_secures_every_commitment_and_transfers_bank_credits(self, api):
        """The units leave `credits_reserved` for `credits_transferred`, not for available.

        PRD: "An accepted `APPROVE` moves the plan `SUBMITTED - APPROVED`, records
        the deciding official's `X-User-ID` as `approved_by_user_id`, and converts the
        commitment set: every commitment in `RESERVED` moves `RESERVED - SECURED` in
        `created_at` ascending order"

        PRD: "for each such commitment whose `mechanism` is
        `CONSERVATION_BANK_CREDIT` the bank's `credits_reserved` decreases by `units`
        while its `credits_transferred` increases by the same `units`, preserving the
        ledger identity. `reserve_remaining_cents` is refreshed as
        `changed_circumstance_reserve_cents` minus `reserve_drawn_cents`."

        The two commitments of 45.01 and 14.71 units move 59.72 credits out of
        reserved and into transferred, leaving `credits_available` at 440.28 - the
        release semantics of a return for revision would instead restore it to 500.00.

        Design: Corner/state_machines/plan_approval_secures_commitments_and_moves_the_bank_ledger
        """
        scenario = build_scenario("submitted")
        plan_id = scenario["plan"]["id"]
        assert scenario["plan"]["plan_status"] == "SUBMITTED"
        assert scenario["plan"]["funding_status"] == "FULLY_ASSURED"

        plan = get_success_data(
            api.decide_plan(plan_id, plan_decision_payload("APPROVE"), APPROVER), 200
        )

        assert plan["plan_status"] == "APPROVED"
        assert plan["approved_by_user_id"] == "fws-user-approver"
        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_reserved"] == 0.00
        assert bank["credits_transferred"] == 59.72
        assert bank["credits_available"] == 440.28
        assert bank["credits_total_minted"] == 500.00
        assert_bank_ledger_identity(bank)
        commitments = assert_unpaginated_list(
            api.list_plan_mitigation_commitments(plan_id, scenario["proponent_headers"])
        )
        assert [row["units"] for row in commitments] == [45.01, 14.71]
        assert [row["status"] for row in commitments] == ["SECURED", "SECURED"]
        assert plan["funding_status"] == "FULLY_ASSURED"
        assert plan["endowment_secured_cents"] == 5_026_514
        assert plan["reserve_remaining_cents"] == 538_555
        assert plan["reserve_drawn_cents"] == 0


class TestPermitIssuanceCascade:
    """One POST writes the permit, the plan, and the action two levels up."""

    def test_issuance_writes_the_permit_the_plan_and_the_action(self, api):
        """The funding dimension and the consultation are deliberately untouched.

        PRD: "Issuing the incidental take permit is the agency's last act of
        authorisation, and it requires an `APPROVED` plan."

        PRD: "The permit is created in `status` `ACTIVE`, the plan moves
        `APPROVED - IMPLEMENTING`, and the action moves `HCP_DEVELOPMENT -
        PERMITTED`."

        Design: Corner/state_machines/permit_issuance_bubbles_up_through_plan_and_action
        """
        scenario = build_scenario("approved")
        plan_id = scenario["plan"]["id"]
        assert scenario["plan"]["plan_status"] == "APPROVED"
        assert read_action(scenario["action"]["id"])["status"] == "HCP_DEVELOPMENT"
        assert scenario["consultation"]["status"] == "OPINION_ISSUED"

        permit = get_success_data(
            api.issue_incidental_take_permit(
                plan_id, incidental_take_permit_payload(), ISSUER
            ),
            201,
        )

        assert permit["status"] == "ACTIVE"
        plan = read_plan(plan_id)
        assert plan["plan_status"] == "IMPLEMENTING"
        assert plan["funding_status"] == "FULLY_ASSURED"
        action = read_action(scenario["action"]["id"])
        assert action["status"] == "PERMITTED"
        assert action["reinitiation_reason"] == "NONE"
        consultation = read_consultation(scenario["consultation"]["id"])
        assert consultation["status"] == "OPINION_ISSUED"
        assert consultation["reinitiation_count"] == 0
        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_reserved"] == 0.00
        assert bank["credits_transferred"] == 59.72
        assert bank["credits_available"] == 440.28


class TestReportAcceptance:
    """ACCEPT records the adjudication triple and moves no ledger figure."""

    def test_acceptance_records_the_adjudication_and_leaves_the_take_applied(self, api):
        """The take was counted at submission and must not be counted again.

        PRD: "The reported take is applied at **submission**, before any
        adjudication, and the ledger is maintained incrementally rather than
        recomputed from scratch."

        PRD: "Both outcomes stamp `adjudicated_at` with the current logical clock,
        record `adjudicated_by_user_id` as the official's `X-User-ID`, and store the
        `adjudication_note`."

        PRD: "`ACCEPT` moves the report `SUBMITTED - ACCEPTED` and leaves the
        reported take applied to the permit ledger."

        PRD: "It is available only while the report's `status` is `SUBMITTED`, so
        re-adjudicating an already-adjudicated report is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)"

        Design: Corner/state_machines/report_acceptance_records_adjudication_and_keeps_take_applied
        """
        scenario = build_scenario("permit")
        set_clock("2027-04-15T00:00:00Z")
        report = file_monitoring_report(
            scenario["permit"]["id"],
            scenario["proponent"],
            take_units_reported=1.00,
            mitigation_units_verified=59.72,
        )

        adjudicated = get_success_data(
            api.adjudicate_monitoring_report(
                report["id"],
                adjudication_payload(
                    "ACCEPT", adjudication_note="Take within authorized limits."
                ),
                ADJUDICATOR,
            ),
            200,
        )

        assert adjudicated["status"] == "ACCEPTED"
        assert_same_instant(adjudicated["adjudicated_at"], "2027-04-15T00:00:00Z")
        assert adjudicated["adjudicated_by_user_id"] == "fws-user-adjudicator"
        assert adjudicated["adjudication_note"] == "Take within authorized limits."
        assert adjudicated["is_late"] is False
        permit = read_permit(scenario["permit"]["id"])
        assert permit["take_consumed_units"] == 1.00
        assert permit["take_remaining_units"] == 3.00
        assert permit["status"] == "ACTIVE"
        assert permit["suspension_count"] == 0
        plan = read_plan(scenario["plan"]["id"])
        assert plan["plan_status"] == "IMPLEMENTING"
        assert plan["assurance_review_required"] is False
        assert_error_envelope(
            api.adjudicate_monitoring_report(
                report["id"], adjudication_payload("ACCEPT"), ADJUDICATOR
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )


class TestCircumstanceBranching:
    """One endpoint reaches all three landing states, so REPORTED never rests."""

    def test_one_endpoint_reaches_all_three_landing_states(self, api):
        """The type and the reserve balance choose the branch.

        PRD: "The resulting state branches on the shortfall: when
        `required_additional_cents` is greater than 0 the event lands in
        `RESPONSE_REQUIRED`, and when the reserve covered the whole cost so that
        `required_additional_cents` is 0, the event lands directly in the terminal
        `RESPONDED` with `reserve_draw_cents` equal to `response_cost_cents`."

        PRD: "Regardless of how the two buckets split, `permittee_borne_cents` is the
        **whole** `response_cost_cents`, `agency_borne_cents` is 0, and
        `assurances_invoked` is false"

        PRD: "For an `UNFORESEEN` circumstance the reserve is **not touched at all**:
        `reserve_draw_cents` is 0 and the plan's `reserve_drawn_cents` and
        `reserve_remaining_cents` are unchanged."

        PRD: "`required_additional_cents` is 0, `assurances_invoked` is true, and the
        event lands in the terminal `ASSURANCES_INVOKED`."

        PRD: "A response to an event that is not in `RESPONSE_REQUIRED` - one already
        `RESPONDED`, or one in `ASSURANCES_INVOKED` - is
        `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        A CHANGED cost of 500,000 cents sits inside the 538,555-cent reserve and
        lands RESPONDED; an UNFORESEEN cost of 700,000 caps the permittee at five
        percent of the 5,026,514 endowed, that is 251,326, and puts 448,674 on the
        agency; a second CHANGED cost of 700,000 now finds only 38,555 left and lands
        in RESPONSE_REQUIRED owing 661,445.

        Design: Corner/state_machines/changed_circumstance_event_branches_three_ways_on_one_endpoint
        """
        scenario = build_scenario("permit")
        plan_id = scenario["plan"]["id"]
        headers = scenario["proponent_headers"]

        first = get_success_data(
            api.create_changed_circumstance_event(
                plan_id,
                changed_circumstance_event_payload(
                    circumstance_type="CHANGED",
                    description=(
                        "Prolonged drought reduced forage cover across the "
                        "mitigation parcel."
                    ),
                    response_cost_cents=500_000,
                ),
                headers,
            ),
            201,
        )
        second = get_success_data(
            api.create_changed_circumstance_event(
                plan_id,
                changed_circumstance_event_payload(
                    circumstance_type="UNFORESEEN",
                    description=(
                        "A novel pathogen reduced the recovery unit population "
                        "range-wide."
                    ),
                    response_cost_cents=700_000,
                ),
                headers,
            ),
            201,
        )

        assert_changed_circumstance_event(first)
        assert first["status"] == "RESPONDED"
        assert first["reserve_draw_cents"] == 500_000
        assert first["required_additional_cents"] == 0
        assert first["permittee_borne_cents"] == 500_000
        assert first["agency_borne_cents"] == 0
        assert first["assurances_invoked"] is False
        assert_changed_circumstance_event(second)
        assert second["status"] == "ASSURANCES_INVOKED"
        assert second["reserve_draw_cents"] == 0
        assert second["required_additional_cents"] == 0
        assert second["assurances_invoked"] is True
        assert second["permittee_borne_cents"] == 251_326
        assert second["agency_borne_cents"] == 448_674
        assert_response_cost_identity(second)
        plan = read_plan(plan_id, headers)
        assert plan["reserve_drawn_cents"] == 500_000
        assert plan["reserve_remaining_cents"] == 38_555

        third = get_success_data(
            api.create_changed_circumstance_event(
                plan_id,
                changed_circumstance_event_payload(
                    circumstance_type="CHANGED",
                    description=(
                        "A wildfire removed shrub cover from the northern "
                        "mitigation block."
                    ),
                    response_cost_cents=700_000,
                ),
                headers,
            ),
            201,
        )
        assert third["status"] == "RESPONSE_REQUIRED"
        assert third["reserve_draw_cents"] == 38_555
        assert third["required_additional_cents"] == 661_445
        assert_error_envelope(
            api.respond_to_circumstance_event(
                second["id"], circumstance_response_payload(700_000), headers
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )


class TestReinitiationCloseOut:
    """The closing edge of the reinitiation cycle restarts the statutory clock."""

    def test_a_fresh_assessment_restarts_the_clock_and_frees_the_action(self, api):
        """The counter is history: it survives the restart while the clock does not.

        PRD: "From `REINITIATION_REQUIRED - UNDER_REVIEW`, the statutory clock
        **restarts** rather than extends: `clock_started_at` is reset to the current
        logical clock, `tolled_days` is reset to 0, `info_request_count` is reset to
        0, and `deadline_at` is recomputed from scratch"

        PRD: "in the same request the action named by `project_action_id` leaves
        `REINITIATION_PENDING` for `FORMAL_CONSULTATION` with its
        `reinitiation_reason` reset to `NONE`, and the owning proponent's
        `open_reinitiation_count` and `compliance_standing_score` are recomputed."

        PRD: "`deadline_at` is `clock_started_at` advanced by a number of days equal
        to `statutory_days` plus `tolled_days`"

        The suspension survives the restart because only a report rejection unwinds
        it. PRD: "Rejecting a report that leaves the permit still at or above its
        trigger leaves the permit `SUSPENDED` and the plan suspended."

        Restarted at 2027-04-15 a formal consultation of 135 statutory days and no
        tolling is due 2027-08-28.

        Design: Corner/state_machines/reinitiation_cycle_closes_back_into_formal_consultation
        """
        scenario = setup_take_exceedance(take_units=4.00)
        consultation_id = scenario["consultation"]["id"]
        assert scenario["consultation"]["status"] == "REINITIATION_REQUIRED"
        assert scenario["consultation"]["reinitiation_count"] == 1
        assert_same_instant(
            scenario["consultation"]["reinitiation_triggered_at"], "2027-04-15T00:00:00Z"
        )

        consultation = submit_biological_assessment(
            consultation_id,
            scenario["proponent"],
            ba_narrative="Reinitiated effects analysis after take exceedance.",
        )

        assert consultation["status"] == "UNDER_REVIEW"
        assert consultation["ba_revision_number"] == 2
        assert_same_instant(consultation["clock_started_at"], "2027-04-15T00:00:00Z")
        assert consultation["tolled_days"] == 0
        assert consultation["info_request_count"] == 0
        assert_same_instant(consultation["deadline_at"], "2027-08-28T00:00:00Z")
        assert consultation["reinitiation_count"] == 1
        action = read_action(scenario["action"]["id"])
        assert action["status"] == "FORMAL_CONSULTATION"
        assert action["reinitiation_reason"] == "NONE"
        permit = read_permit(scenario["permit"]["id"])
        assert permit["status"] == "SUSPENDED"
        assert permit["suspension_count"] == 1
        plan = read_plan(scenario["plan"]["id"])
        assert plan["plan_status"] == "SUSPENDED_IMPLEMENTATION"
        assert plan["assurance_review_required"] is True
        assert read_proponent(scenario["proponent"]["id"])["open_reinitiation_count"] == 0


class TestAssessmentAttestation:
    """A false completeness attestation is a request error, not a state error."""

    def test_a_false_completeness_attestation_leaves_no_trace(self, api):
        """Rung 7 answers before the state machine is ever consulted.

        PRD: "That attestation must be supplied as **true**; submitting it as false is
        rejected as `ERR_INVALID_REQUEST` (HTTP 400) at rung 7 of the ladder rather
        than treated as a state problem."

        PRD: "`ba_effects_analysis_complete` must be supplied as true on a biological
        assessment - supplying it as false is `ERR_INVALID_REQUEST`, not a state
        error."

        PRD: "Every accepted submission increases `ba_revision_number` by 1, stamps
        `ba_submitted_at` with the current logical clock, stores the supplied
        `ba_narrative` and `ba_effects_analysis_complete`, and moves the consultation
        into `UNDER_REVIEW`."

        Design: Corner/state_machines/biological_assessment_requires_a_true_completeness_attestation
        """
        scenario = build_scenario("effect_determination")
        consultation_id = scenario["consultation"]["id"]
        assert scenario["consultation"]["status"] == "DRAFT_BA"
        body = biological_assessment_payload(
            ba_narrative="Draft effects analysis, still in progress.",
            ba_effects_analysis_complete=False,
        )

        assert_error_envelope(
            api.submit_biological_assessment(
                consultation_id, body, scenario["proponent_headers"]
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            400,
        )

        consultation = read_consultation(consultation_id)
        assert consultation["status"] == "DRAFT_BA"
        assert consultation["ba_revision_number"] == 0
        assert_error_envelope(
            api.issue_biological_opinion(consultation_id, {}, ISSUER),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
            409,
        )

        body["ba_effects_analysis_complete"] = True
        accepted = get_success_data(
            api.submit_biological_assessment(
                consultation_id, body, scenario["proponent_headers"]
            ),
            200,
        )
        assert accepted["status"] == "UNDER_REVIEW"
        assert accepted["ba_revision_number"] == 1
