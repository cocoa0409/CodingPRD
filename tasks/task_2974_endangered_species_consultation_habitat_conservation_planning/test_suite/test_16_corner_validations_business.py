"""Business-rule validations that sit above the shape rung of the ladder.

Each test drives one §1.9 `validations` recipe: the federal restriction on plan
creation, the method-gated survey window, the information-request deadline, the
four reporting-period bounds, the commitment prerequisite on submission, the four
bank-ineligibility grounds, the credit-availability boundary, the ordering of the
two approval gates, and the take ceiling that reads the ledger before it writes.
"""

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_error_envelope,
    assert_same_instant,
    assert_unpaginated_list,
)
from test_helpers.factories import (
    database_query_payload,
    field_survey_payload,
    habitat_conservation_plan_payload,
    information_request_payload,
    mitigation_commitment_payload,
    monitoring_report_payload,
    plan_decision_payload,
)
from test_helpers.fixtures import (
    APPROVER,
    REVIEWER,
    add_commitment,
    add_funding_assurance,
    build_scenario,
    decide_plan,
    establish_conservation_bank,
    establish_out_of_area_bank,
    file_monitoring_report,
    issue_biological_opinion,
    read_action,
    read_bank,
    read_consultation,
    read_permit,
    read_plan,
    record_field_survey,
    run_effect_determination,
    set_clock,
    setup_canonical_permit,
    setup_plan_with_permittee_responsible_commitment,
    setup_second_action,
    submit_biological_assessment,
    submit_plan,
)


class TestFederalActionPlanGate:
    """`action_type` is read only at plan creation, after the whole file is built."""

    def test_a_federal_action_completes_consultation_and_is_still_refused_a_plan(
        self, api
    ):
        """Both federal action types conclude consultation and then 422 on the plan.

        PRD: "The action's `action_type` must be `NON_FEDERAL` - `FEDERAL_FUNDED` and
        `FEDERAL_PERMITTED` actions are covered by the federal consultation's own
        incidental take statement, so attempting a plan on either is
        `ERR_HCP_NOT_ALLOWED_FOR_FEDERAL_ACTION` (HTTP 422)."

        PRD: "when a formal consultation reaches `OPINION_ISSUED`, its action moves
        `FORMAL_CONSULTATION - CONSULTATION_CONCLUDED`"

        A 200.00-acre federal action with one 10.00-acre confirmed ENDANGERED
        determination screens to `LAA`, runs a formal consultation to a biological
        opinion, and only then meets the gate; the action keeps its concluded status
        and its plan list stays empty.

        Design: Corner/validations/federal_actions_may_not_host_a_habitat_conservation_plan
        """
        scenario = build_scenario(
            "opinion",
            include_threatened=False,
            include_database_query=False,
            action_overrides={"action_type": "FEDERAL_PERMITTED"},
        )
        permitted_id = scenario["action"]["id"]
        headers = scenario["proponent_headers"]

        assert scenario["action"]["action_type"] == "FEDERAL_PERMITTED"
        assert scenario["action"]["effect_determination"] == "LAA"
        assert scenario["action"]["overlap_pct"] == 5.00
        assert scenario["action"]["status"] == "CONSULTATION_CONCLUDED"
        assert scenario["consultation"]["consultation_type"] == "FORMAL"
        assert scenario["consultation"]["status"] == "OPINION_ISSUED"

        refused = api_client.create_habitat_conservation_plan(
            permitted_id,
            habitat_conservation_plan_payload(plan_name="Harbor Channel HCP"),
            headers,
        )
        assert_error_envelope(
            refused, ApiErrorId.ERR_HCP_NOT_ALLOWED_FOR_FEDERAL_ACTION, 422
        )

        assert read_action(permitted_id)["status"] == "CONSULTATION_CONCLUDED"
        assert (
            assert_unpaginated_list(
                api_client.list_action_habitat_conservation_plans(permitted_id, headers)
            )
            == []
        )

        funded_action = setup_second_action(
            scenario,
            action_name="Harbor Channel Dredging",
            action_type="FEDERAL_FUNDED",
        )
        record_field_survey(
            funded_action,
            scenario["proponent"],
            scenario["species"]["id"],
            survey_window_start="2026-06-10",
            survey_window_end="2026-06-14",
        )
        funded_action = run_effect_determination(funded_action, scenario["proponent"])
        funded_consultation_id = funded_action["active_consultation_id"]
        submit_biological_assessment(funded_consultation_id, scenario["proponent"])
        issue_biological_opinion(funded_consultation_id)
        funded_action = read_action(funded_action["id"])

        assert funded_action["effect_determination"] == "LAA"
        assert funded_action["status"] == "CONSULTATION_CONCLUDED"

        refused_funded = api_client.create_habitat_conservation_plan(
            funded_action["id"],
            habitat_conservation_plan_payload(plan_name="Harbor Dredging HCP"),
            headers,
        )
        assert_error_envelope(
            refused_funded, ApiErrorId.ERR_HCP_NOT_ALLOWED_FOR_FEDERAL_ACTION, 422
        )
        assert read_action(funded_action["id"])["status"] == "CONSULTATION_CONCLUDED"


class TestSurveyWindowMethodGate:
    """The window fields are required on one method and forbidden on the other."""

    def test_the_window_is_required_on_a_survey_and_forbidden_on_a_desk_query(self, api):
        """Three method/window mismatches are 422, and a one-day window is legal.

        PRD: "When `method` is `FIELD_SURVEY`, both `survey_window_start` and
        `survey_window_end` are required and the start must not be later than the
        end. When `method` is `DATABASE_QUERY`, both must be omitted or supplied as
        null - a desk query has no field window. Any violation of either half of that
        rule is `ERR_SURVEY_WINDOW_INVALID` (HTTP 422), whether the failure is a
        missing window on a survey, an inverted window on a survey, or a window
        supplied non-null alongside a database query."

        PRD: "`survey_in_season` is computed from the calendar month of
        `survey_window_start` and the calendar month of `survey_window_end`, tested
        against the species' detectability season, and it is true only when **both**
        months fall inside that season."

        PRD: "For a `DATABASE_QUERY` determination, `survey_in_season` is always
        false."

        A start equal to the end is not later than the end, so a single-day May
        survey is accepted and reads in season against the April-to-July window; the
        three refusals leave the action's determination list holding only that row.

        Design: Corner/validations/survey_window_fields_are_required_exactly_when_the_method_is_a_field_survey
        """
        scenario = build_scenario("action", include_unit=False, include_bank=False)
        action_id = scenario["action"]["id"]
        headers = scenario["proponent_headers"]
        species_id = scenario["species"]["id"]
        threatened_id = scenario["threatened_species"]["id"]

        no_window = field_survey_payload(species_id)
        del no_window["survey_window_start"]
        del no_window["survey_window_end"]
        assert_error_envelope(
            api_client.create_presence_determination(action_id, no_window, headers),
            ApiErrorId.ERR_SURVEY_WINDOW_INVALID,
            422,
        )

        inverted = field_survey_payload(
            species_id, survey_window_start="2026-05-08", survey_window_end="2026-05-04"
        )
        assert_error_envelope(
            api_client.create_presence_determination(action_id, inverted, headers),
            ApiErrorId.ERR_SURVEY_WINDOW_INVALID,
            422,
        )

        windowed_query = database_query_payload(
            threatened_id,
            survey_window_start="2026-05-04",
            survey_window_end="2026-05-08",
        )
        assert_error_envelope(
            api_client.create_presence_determination(action_id, windowed_query, headers),
            ApiErrorId.ERR_SURVEY_WINDOW_INVALID,
            422,
        )

        single_day = get_success_data(
            api_client.create_presence_determination(
                action_id,
                field_survey_payload(
                    species_id,
                    survey_window_start="2026-05-04",
                    survey_window_end="2026-05-04",
                ),
                headers,
            ),
            201,
        )

        assert single_day["survey_window_start"] == "2026-05-04"
        assert single_day["survey_window_end"] == "2026-05-04"
        assert single_day["survey_in_season"] is True
        assert single_day["presence_status"] == "PRESENT"

        rows, meta = validate_paginated(
            api_client.list_presence_determinations(
                headers, params={"project_action_id": action_id}
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [single_day["id"]]

        null_window_query = get_success_data(
            api_client.create_presence_determination(
                action_id,
                database_query_payload(
                    threatened_id, survey_window_start=None, survey_window_end=None
                ),
                headers,
            ),
            201,
        )

        assert null_window_query["survey_window_start"] is None
        assert null_window_query["survey_window_end"] is None
        assert null_window_query["survey_in_season"] is False
        assert null_window_query["presence_status"] == "PRESUMED_PRESENT"


class TestInformationRequestDeadlineBoundary:
    """The clock standing exactly on `deadline_at` is still inside the deadline."""

    def test_the_deadline_day_admits_a_request_while_the_passed_one_does_not(self, api):
        """One consultation is on its deadline and the other is past it.

        PRD: "The current logical clock must not be later than `deadline_at`; asking
        for information after the deadline has passed is
        `ERR_CONSULTATION_DEADLINE_PASSED` (HTTP 422)."

        PRD: "`deadline_at` is `clock_started_at` advanced by a number of days equal
        to `statutory_days` plus `tolled_days` - so a fresh formal consultation is due
        135 days after it opened and a fresh informal one 60 days after."

        Both consultations opened at 2026-10-01, so the formal one is due
        2027-02-13 and the informal one was due 2026-11-30. Read at exactly
        2027-02-13T00:00:00Z the informal request is refused with its counter still
        at 0 while the formal request succeeds.

        Design: Corner/validations/information_request_deadline_boundary_is_inclusive
        """
        scenario = build_scenario("ba_submitted")
        formal_id = scenario["consultation"]["id"]

        informal_action = setup_second_action(scenario)
        record_field_survey(
            informal_action,
            scenario["proponent"],
            scenario["threatened_species"]["id"],
            habitat_overlap_acres=10.00,
        )
        informal_action = run_effect_determination(informal_action, scenario["proponent"])
        informal_id = informal_action["active_consultation_id"]
        informal = submit_biological_assessment(informal_id, scenario["proponent"])

        assert scenario["consultation"]["consultation_type"] == "FORMAL"
        assert scenario["consultation"]["statutory_days"] == 135
        assert_same_instant(scenario["consultation"]["deadline_at"], "2027-02-13T00:00:00Z")
        assert informal["consultation_type"] == "INFORMAL"
        assert informal["statutory_days"] == 60
        assert_same_instant(informal["deadline_at"], "2026-11-30T00:00:00Z")
        assert informal["status"] == "UNDER_REVIEW"

        set_clock("2027-02-13T00:00:00Z")

        expired = api_client.request_information(
            informal_id, information_request_payload(), REVIEWER
        )
        assert_error_envelope(expired, ApiErrorId.ERR_CONSULTATION_DEADLINE_PASSED, 422)

        untouched = read_consultation(informal_id)

        assert untouched["status"] == "UNDER_REVIEW"
        assert untouched["info_request_count"] == 0
        assert untouched["info_requested_at"] is None

        on_deadline = get_success_data(
            api_client.request_information(
                formal_id, information_request_payload(), REVIEWER
            ),
            200,
        )

        assert on_deadline["status"] == "INFO_REQUESTED"
        assert on_deadline["info_request_count"] == 1
        assert on_deadline["tolled_days"] == 0
        assert_same_instant(on_deadline["info_requested_at"], "2027-02-13T00:00:00Z")
        assert_same_instant(on_deadline["deadline_at"], "2027-02-13T00:00:00Z")


class TestReportingPeriodBounds:
    """Four temporal grounds share one error id, and every bound is inclusive."""

    def test_four_grounds_refuse_the_period_and_both_boundaries_are_inclusive(self, api):
        """A period before the term, past the clock, inverted, or past the term all 422.

        PRD: "Four temporal conditions bound the period, all reported as
        `ERR_PERIOD_OUTSIDE_PERMIT_TERM` (HTTP 422): `period_start` must be strictly
        earlier than `period_end`, `period_start` must not be earlier than the
        permit's `term_start`, `period_end` must not be later than the permit's
        `term_end`, and `period_end` must not be later than the current logical clock
        - there is no reporting on a period that has not yet closed."

        PRD: "a cascade either completes in full or, when a validation rejects the
        request, leaves every row exactly as it was - there are no partial cascades."

        The permit runs 2026-10-01 to 2056-10-01 and the clock stands at 2027-05-16.
        None of the four refusals moves the permit's `version` or reserves an
        interval, and afterwards a period starting exactly on `term_start` and a
        period ending exactly on the clock are both accepted.

        Design: Corner/validations/reporting_period_bounds_are_checked_against_both_the_term_and_the_clock
        """
        scenario = setup_canonical_permit()
        permit_id = scenario["permit"]["id"]
        headers = scenario["proponent_headers"]

        assert scenario["permit"]["term_start"] == "2026-10-01"
        assert scenario["permit"]["term_end"] == "2056-10-01"

        set_clock("2027-05-16T00:00:00Z")
        baseline = read_permit(permit_id)

        probes = (
            ("2026-09-01", "2026-12-01"),
            ("2027-01-01", "2027-06-01"),
            ("2027-04-01", "2027-01-01"),
            ("2056-06-01", "2056-12-01"),
        )
        for period_start, period_end in probes:
            refused = api_client.create_monitoring_report(
                permit_id,
                monitoring_report_payload(
                    baseline["version"],
                    period_start=period_start,
                    period_end=period_end,
                    take_units_reported=1.00,
                ),
                headers,
            )
            assert_error_envelope(
                refused, ApiErrorId.ERR_PERIOD_OUTSIDE_PERMIT_TERM, 422
            )

        unchanged = read_permit(permit_id)

        assert unchanged["version"] == baseline["version"]
        assert unchanged["take_consumed_units"] == 0.00
        assert unchanged["take_remaining_units"] == 4.00
        assert (
            assert_unpaginated_list(
                api_client.list_permit_monitoring_reports(permit_id, headers)
            )
            == []
        )

        first = file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-01-01",
            period_end="2027-04-01",
            take_units_reported=1.00,
        )
        at_term_start = file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2026-10-01",
            period_end="2027-01-01",
            take_units_reported=1.00,
        )
        at_the_clock = file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-04-01",
            period_end="2027-05-16",
            take_units_reported=1.00,
        )

        assert first["status"] == "SUBMITTED"
        assert at_term_start["period_start"] == "2026-10-01"
        assert at_term_start["status"] == "SUBMITTED"
        assert at_the_clock["period_end"] == "2027-05-16"
        assert at_the_clock["status"] == "SUBMITTED"

        settled = read_permit(permit_id)

        assert settled["take_consumed_units"] == 3.00
        assert settled["take_remaining_units"] == 1.00
        assert settled["status"] == "ACTIVE"
        assert settled["version"] == baseline["version"] + 3


class TestSubmissionCommitmentPrerequisite:
    """The prerequisite is re-checked after a revision empties the reserved set."""

    def test_a_commitmentless_plan_is_refused_before_and_after_a_revision(self, api):
        """The same plan fails submission twice with one accepted submission between.

        PRD: "It requires at least one commitment on the plan in `status` `RESERVED`; a
        plan with none is `ERR_NO_MITIGATION_COMMITMENTS` (HTTP 422)."

        PRD: "Submission recomputes `final_mitigation_units` with the FINAL variant,
        writes `mitigation_delta_units`, and recomputes `secured_mitigation_units` as
        the sum of `units` over the plan's `RESERVED` and `SECURED` commitments,
        rounded half up to two decimal places."

        PRD: "Every commitment in `RESERVED` moves `RESERVED - RELEASED` in
        `created_at` ascending order, and for each released commitment whose
        `mechanism` is `CONSERVATION_BANK_CREDIT` the bank's `credits_reserved`
        decreases by `units` while its `credits_available` increases by the same
        `units`"

        A single 45.01-unit bank commitment carries the plan through submission with
        `final_mitigation_units` 59.70 and `secured_mitigation_units` 45.01 while the
        funding dimension is still `UNFUNDED`; the return for revision releases that
        row, so the plan is right back where it started with one `RELEASED`
        commitment on file.

        Design: Corner/validations/submission_requires_a_reserved_commitment_before_and_after_a_revision
        """
        scenario = build_scenario("plan")
        plan_id = scenario["plan"]["id"]
        headers = scenario["proponent_headers"]
        bank_id = scenario["bank"]["id"]

        assert scenario["plan"]["plan_status"] == "DRAFT"

        empty_submission = api_client.submit_plan(plan_id, headers)
        assert_error_envelope(
            empty_submission, ApiErrorId.ERR_NO_MITIGATION_COMMITMENTS, 422
        )

        assert read_plan(plan_id)["plan_status"] == "DRAFT"

        commitment = add_commitment(
            plan_id,
            scenario["proponent"],
            {
                "mechanism": "CONSERVATION_BANK_CREDIT",
                "units": 45.01,
                "conservation_bank_id": bank_id,
            },
        )

        assert commitment["status"] == "RESERVED"

        submitted = submit_plan(plan_id, scenario["proponent"])

        assert submitted["plan_status"] == "SUBMITTED"
        assert submitted["final_mitigation_units"] == 59.70
        assert submitted["mitigation_delta_units"] == -0.30
        assert submitted["secured_mitigation_units"] == 45.01
        assert submitted["funding_status"] == "UNFUNDED"

        returned = decide_plan(plan_id, "RETURN_FOR_REVISION")

        assert returned["plan_status"] == "DRAFT"
        assert returned["endowment_required_cents"] == 0
        assert returned["funded_ratio"] == 0.0000
        assert returned["funding_status"] == "UNFUNDED"

        second_submission = api_client.submit_plan(plan_id, headers)
        assert_error_envelope(
            second_submission, ApiErrorId.ERR_NO_MITIGATION_COMMITMENTS, 422
        )

        rows = assert_unpaginated_list(
            api_client.list_plan_mitigation_commitments(plan_id, headers)
        )

        assert len(rows) == 1
        assert rows[0]["id"] == commitment["id"]
        assert rows[0]["status"] == "RELEASED"
        assert read_plan(plan_id)["plan_status"] == "DRAFT"

        bank = read_bank(bank_id)

        assert bank["credits_available"] == 500.00
        assert bank["credits_reserved"] == 0.00
        assert bank["credits_transferred"] == 0.00
        assert_bank_ledger_identity(bank)


class TestBankIneligibilityGrounds:
    """Four independent defects all surface as the same eligibility error."""

    def test_species_service_area_and_both_halves_of_the_pairing_rule_all_422(self, api):
        """A wrong species, a wrong county, a missing bank and a stray bank all 422.

        PRD: "The bank's `covered_species_id` must equal the species that the
        incidental take authorization rule selects as **primary** for this plan's
        action, using the identical selection procedure described in §3.5. And the
        action's `county_code` must appear somewhere in the bank's
        `service_area_county_codes`."

        PRD: "Eligibility is checked before availability, so a commitment that is both
        out of service area and over budget reports the eligibility failure."

        PRD: "it is **required** when `mechanism` is `CONSERVATION_BANK_CREDIT` and
        must be omitted or null for every other mechanism. Violating either half of
        the pairing - omitting the bank on a bank-credit commitment, or supplying a
        bank on an in-lieu-fee or permittee-responsible commitment - is
        `ERR_BANK_NOT_ELIGIBLE` (HTTP 422)."

        The plan's primary species is the ENDANGERED row, so a bank covering the
        THREATENED species is refused; the Owens Valley bank holds 5.00 credits and
        serves county 06059 only, so a 10.00-unit request against it reports the
        eligibility failure rather than the shortfall. None of the four refusals
        moves the eligible bank's ledger.

        Design: Corner/validations/bank_ineligibility_has_four_independent_grounds
        """
        scenario = build_scenario("plan")
        plan_id = scenario["plan"]["id"]
        headers = scenario["proponent_headers"]
        bank_id = scenario["bank"]["id"]
        version = scenario["plan"]["version"]

        wrong_species_bank = establish_conservation_bank(
            scenario["threatened_species"]["id"],
            bank_name="Vireo Riparian Bank",
            credits_total_minted=100.00,
        )
        out_of_area_bank = establish_out_of_area_bank(scenario["species"]["id"])

        assert out_of_area_bank["service_area_county_codes"] == ["06059"]
        assert out_of_area_bank["credits_available"] == 5.00

        probes = (
            mitigation_commitment_payload(
                version, units=10.00, conservation_bank_id=wrong_species_bank["id"]
            ),
            mitigation_commitment_payload(
                version, units=10.00, conservation_bank_id=out_of_area_bank["id"]
            ),
            mitigation_commitment_payload(version, units=45.01),
            mitigation_commitment_payload(
                version,
                mechanism="IN_LIEU_FEE",
                units=14.71,
                conservation_bank_id=bank_id,
            ),
        )
        for payload in probes:
            refused = api_client.create_mitigation_commitment(plan_id, payload, headers)
            assert_error_envelope(refused, ApiErrorId.ERR_BANK_NOT_ELIGIBLE, 422)

        untouched = read_bank(bank_id)

        assert untouched["credits_available"] == 500.00
        assert untouched["credits_reserved"] == 0.00
        assert read_plan(plan_id)["version"] == version
        assert (
            assert_unpaginated_list(
                api_client.list_plan_mitigation_commitments(plan_id, headers)
            )
            == []
        )

        accepted = get_success_data(
            api_client.create_mitigation_commitment(
                plan_id,
                mitigation_commitment_payload(
                    version, units=45.01, conservation_bank_id=bank_id
                ),
                headers,
            ),
            201,
        )

        assert accepted["mechanism"] == "CONSERVATION_BANK_CREDIT"
        assert accepted["status"] == "RESERVED"

        moved = read_bank(bank_id)

        assert moved["credits_available"] == 454.99
        assert moved["credits_reserved"] == 45.01
        assert moved["credits_transferred"] == 0.00
        assert_bank_ledger_identity(moved)


class TestBankCreditAvailabilityBoundary:
    """The balance is an aggregate over reservations, tested at both ends."""

    def test_one_hundredth_over_the_balance_is_refused_at_every_size(self, api):
        """500.01 units is refused, 500.00 is taken, and 0.01 more is refused.

        PRD: "Only once eligibility passes does the credit balance matter: the bank's
        `credits_available` must be at least the requested `units`, and a shortfall is
        `ERR_INSUFFICIENT_BANK_CREDITS` (HTTP 409)."

        PRD: "For a `CONSERVATION_BANK_CREDIT` commitment, the bank's
        `credits_available` decreases by `units` and its `credits_reserved` increases
        by the same `units`, which moves credits across the ledger without changing
        the total."

        The bank was minted with 500.00 credits, so the boundary is inclusive at
        exactly the balance; once that reservation lands `credits_available` is 0.00
        and even a single hundredth of a credit is a shortfall, while the ledger
        identity holds throughout.

        Design: Corner/validations/bank_credit_availability_is_an_aggregate_boundary_on_reservations
        """
        scenario = build_scenario("plan")
        plan_id = scenario["plan"]["id"]
        headers = scenario["proponent_headers"]
        bank_id = scenario["bank"]["id"]

        assert scenario["bank"]["credits_total_minted"] == 500.00
        assert scenario["bank"]["credits_available"] == 500.00

        over = api_client.create_mitigation_commitment(
            plan_id,
            mitigation_commitment_payload(
                scenario["plan"]["version"], units=500.01, conservation_bank_id=bank_id
            ),
            headers,
        )
        assert_error_envelope(over, ApiErrorId.ERR_INSUFFICIENT_BANK_CREDITS, 409)

        assert read_bank(bank_id)["credits_available"] == 500.00

        exact = get_success_data(
            api_client.create_mitigation_commitment(
                plan_id,
                mitigation_commitment_payload(
                    read_plan(plan_id)["version"],
                    units=500.00,
                    conservation_bank_id=bank_id,
                ),
                headers,
            ),
            201,
        )

        assert exact["units"] == 500.00
        assert exact["status"] == "RESERVED"

        drained = read_bank(bank_id)

        assert drained["credits_available"] == 0.00
        assert drained["credits_reserved"] == 500.00
        assert drained["credits_transferred"] == 0.00
        assert_bank_ledger_identity(drained)

        hundredth = api_client.create_mitigation_commitment(
            plan_id,
            mitigation_commitment_payload(
                read_plan(plan_id)["version"], units=0.01, conservation_bank_id=bank_id
            ),
            headers,
        )
        assert_error_envelope(hundredth, ApiErrorId.ERR_INSUFFICIENT_BANK_CREDITS, 409)

        still_drained = read_bank(bank_id)

        assert still_drained["credits_available"] == 0.00
        assert still_drained["credits_reserved"] == 500.00
        assert_bank_ledger_identity(still_drained)
        assert (
            len(
                assert_unpaginated_list(
                    api_client.list_plan_mitigation_commitments(plan_id, headers)
                )
            )
            == 1
        )


class TestApprovalGateOrder:
    """Two approval gates fail on the same plan; the ladder decides which speaks."""

    def test_the_funding_gate_is_reported_before_the_mitigation_shortfall(self, api):
        """The same APPROVE call reports funding first and the shortfall only after.

        PRD: "`APPROVE` carries three substantive gates, and they are evaluated in the
        ladder order of §2.7."

        PRD: "`funding_status` must be `FULLY_ASSURED`, and `UNFUNDED` or
        `PARTIALLY_ASSURED` is `ERR_FUNDING_NOT_ASSURED` (HTTP 422). And
        `secured_mitigation_units` must be at least `final_mitigation_units`, a
        shortfall being `ERR_MITIGATION_SHORTFALL` (HTTP 422)."

        PRD: "(26) The funding-assurance gate on approval - `ERR_FUNDING_NOT_ASSURED`.
        (27) The mitigation-sufficiency gate on approval - `ERR_MITIGATION_SHORTFALL`."

        One 10.00-unit permittee-responsible commitment endows the plan at 1,252,500
        cents with a 150,300-cent reserve, so 1,402,800 cents assures it exactly; the
        mitigation side stays 10.00 secured units against 59.70 required, so clearing
        the funding gate simply promotes the plan to the next refusal.

        Design: Corner/validations/unassured_funding_outranks_a_mitigation_shortfall_on_approval
        """
        scenario = setup_plan_with_permittee_responsible_commitment(units=10.00)
        plan_id = scenario["plan"]["id"]

        assert scenario["plan"]["endowment_base_cents"] == 1_252_500
        assert scenario["plan"]["changed_circumstance_reserve_cents"] == 150_300
        assert scenario["plan"]["endowment_required_cents"] == 1_402_800
        assert scenario["plan"]["funding_status"] == "UNFUNDED"

        submitted = submit_plan(plan_id, scenario["proponent"])

        assert submitted["plan_status"] == "SUBMITTED"
        assert submitted["final_mitigation_units"] == 59.70
        assert submitted["secured_mitigation_units"] == 10.00
        assert submitted["funding_status"] == "UNFUNDED"

        unfunded_approval = api_client.decide_plan(
            plan_id, plan_decision_payload("APPROVE"), APPROVER
        )
        assert_error_envelope(unfunded_approval, ApiErrorId.ERR_FUNDING_NOT_ASSURED, 422)

        held = read_plan(plan_id)

        assert held["plan_status"] == "SUBMITTED"
        assert held["approved_by_user_id"] is None

        add_funding_assurance(plan_id, scenario["proponent"], 1_402_800)
        assured = read_plan(plan_id)

        assert assured["endowment_secured_cents"] == 1_402_800
        assert assured["funded_ratio"] == 1.0000
        assert assured["funding_status"] == "FULLY_ASSURED"

        short_approval = api_client.decide_plan(
            plan_id, plan_decision_payload("APPROVE"), APPROVER
        )
        assert_error_envelope(short_approval, ApiErrorId.ERR_MITIGATION_SHORTFALL, 422)

        final = read_plan(plan_id)

        assert final["plan_status"] == "SUBMITTED"
        assert final["approved_by_user_id"] is None
        assert final["funding_status"] == "FULLY_ASSURED"
        assert final["secured_mitigation_units"] == 10.00
        assert final["final_mitigation_units"] == 59.70


class TestTakeCeilingBeforeApplication:
    """The ceiling reads `take_remaining_units` as it stands before the write."""

    def test_the_ceiling_moves_down_as_the_ledger_is_consumed(self, api):
        """4.01 is refused on a fresh permit and 1.01 after 3.00 has been taken.

        PRD: "Before the ledger is touched at all, the take ceiling is checked:
        `take_units_reported` must not exceed the permit's `take_remaining_units` as it
        stands *before* this report is applied, and an excess is
        `ERR_TAKE_LIMIT_EXCEEDED` (HTTP 422) that leaves the ledger and the permit
        status completely untouched."

        PRD: "The reported take is applied at **submission**, before any adjudication,
        and the ledger is maintained incrementally rather than recomputed from
        scratch."

        PRD: "On an incidental take permit, `authorized_take_units` always equals
        `take_consumed_units` plus `take_remaining_units`."

        The permit authorises 4.00 units, so the first refusal sits one hundredth over
        the whole ceiling and the second sits one hundredth over what is left; exactly
        1.00 then drives the ledger to 0.00 remaining.

        Design: Corner/validations/take_limit_is_checked_against_the_remaining_units_before_the_report_is_applied
        """
        scenario = setup_canonical_permit()
        permit_id = scenario["permit"]["id"]
        headers = scenario["proponent_headers"]

        assert scenario["permit"]["authorized_take_units"] == 4.00
        assert scenario["permit"]["take_remaining_units"] == 4.00

        set_clock("2027-05-16T00:00:00Z")
        baseline = read_permit(permit_id)

        over_the_ceiling = api_client.create_monitoring_report(
            permit_id,
            monitoring_report_payload(baseline["version"], take_units_reported=4.01),
            headers,
        )
        assert_error_envelope(over_the_ceiling, ApiErrorId.ERR_TAKE_LIMIT_EXCEEDED, 422)

        untouched = read_permit(permit_id)

        assert untouched["version"] == baseline["version"]
        assert untouched["take_consumed_units"] == 0.00
        assert untouched["take_remaining_units"] == 4.00
        assert untouched["status"] == "ACTIVE"

        first = file_monitoring_report(
            permit_id, scenario["proponent"], take_units_reported=3.00
        )

        assert first["take_units_reported"] == 3.00

        partly_consumed = read_permit(permit_id)

        assert partly_consumed["take_consumed_units"] == 3.00
        assert partly_consumed["take_remaining_units"] == 1.00
        assert partly_consumed["status"] == "ACTIVE"

        over_the_remainder = api_client.create_monitoring_report(
            permit_id,
            monitoring_report_payload(
                partly_consumed["version"],
                period_start="2027-04-01",
                period_end="2027-05-01",
                take_units_reported=1.01,
            ),
            headers,
        )
        assert_error_envelope(over_the_remainder, ApiErrorId.ERR_TAKE_LIMIT_EXCEEDED, 422)

        still_partly_consumed = read_permit(permit_id)

        assert still_partly_consumed["version"] == partly_consumed["version"]
        assert still_partly_consumed["take_consumed_units"] == 3.00
        assert still_partly_consumed["take_remaining_units"] == 1.00

        file_monitoring_report(
            permit_id,
            scenario["proponent"],
            period_start="2027-04-01",
            period_end="2027-05-01",
            take_units_reported=1.00,
        )
        exhausted = read_permit(permit_id)

        assert exhausted["take_consumed_units"] == 4.00
        assert exhausted["take_remaining_units"] == 0.00
        assert (
            exhausted["authorized_take_units"]
            == exhausted["take_consumed_units"] + exhausted["take_remaining_units"]
        )
