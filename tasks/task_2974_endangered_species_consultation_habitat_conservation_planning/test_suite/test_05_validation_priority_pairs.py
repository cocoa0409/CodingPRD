"""The four declared validation-priority pairs, each violated by one request."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_bank_ledger_identity,
    assert_error_envelope,
    assert_unpaginated_list,
)
from test_helpers.factories import plan_decision_payload
from test_helpers.fixtures import (
    APPROVER,
    adjudicate_report,
    establish_out_of_area_bank,
    read_bank,
    read_permit,
    read_plan,
    setup_jeopardy_submitted_plan,
    setup_permit_with_one_report,
    setup_suspended_permit,
    build_scenario,
)


def _report_body(version, period_start, period_end, take=1.00):
    return {
        "period_start": period_start,
        "period_end": period_end,
        "take_units_reported": take,
        "mitigation_units_verified": 59.72,
        "expected_permit_version": version,
    }


class TestPermitNotActiveBeatsTakeLimit:
    """Rung 10 beats rung 28 on the same request."""

    def test_the_permit_status_rule_is_reported_not_the_take_ceiling(self, api):
        """A suspended permit refuses a report that also busts the ceiling.

        PRD: "A monitoring report filed against a permit that an earlier exceedance
        already suspended, and whose `take_units_reported` also exceeds what the permit
        has left, is reported as `ERR_PERMIT_NOT_ACTIVE` - the state rule at rung 10
        beats the fiscal rule at rung 28."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_active_beats_take_limit_exceeded
        """
        scenario = setup_suspended_permit()
        permit = scenario["permit"]
        assert permit["status"] == "SUSPENDED"
        assert permit["take_consumed_units"] == 3.60
        assert permit["take_remaining_units"] == 0.40

        response = api.create_monitoring_report(
            permit["id"],
            _report_body(permit["version"], "2027-01-01", "2027-03-31"),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_PERMIT_NOT_ACTIVE, 409)

    def test_the_refused_report_moves_neither_ledger_nor_collection(self, api):
        """A rejected request leaves every row exactly as it was.

        PRD: "an excess is `ERR_TAKE_LIMIT_EXCEEDED` (HTTP 422) that leaves the ledger
        and the permit status completely untouched."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_active_beats_take_limit_exceeded
        """
        scenario = setup_suspended_permit()
        permit = scenario["permit"]
        api.create_monitoring_report(
            permit["id"],
            _report_body(permit["version"], "2027-01-01", "2027-03-31"),
            scenario["proponent_headers"],
        )

        after = read_permit(permit["id"])
        assert after["take_consumed_units"] == 3.60
        assert after["take_remaining_units"] == 0.40
        assert after["status"] == "SUSPENDED"
        assert after["suspension_count"] == 1
        rows = assert_unpaginated_list(
            api.list_permit_monitoring_reports(permit["id"], scenario["proponent_headers"])
        )
        assert len(rows) == 1

    def test_the_version_guard_is_reported_ahead_of_the_permit_status(self, api):
        """Rung 8 precedes rung 10 when both are violated.

        PRD: "Both version checks sit at rung 8 of the validation ladder - after body
        shape conformance, before any state check."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_active_beats_take_limit_exceeded
        """
        scenario = setup_suspended_permit()

        response = api.create_monitoring_report(
            scenario["permit"]["id"],
            _report_body(scenario["permit_v1"], "2027-01-01", "2027-03-31"),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_STALE_PERMIT_VERSION, 412)

    def test_rejecting_the_first_report_makes_the_same_body_acceptable(self, api):
        """The 409 was about the permit state, not about the payload.

        PRD: "`REJECT` moves the report `SUBMITTED - REJECTED` and is a full
        compensation: the permit's `take_consumed_units` decreases by that report's
        `take_units_reported` and `take_remaining_units` is restored by the same amount
        ... If the reversal brings `take_consumed_units` **strictly below**
        `reinitiation_trigger_units` while the permit is `SUSPENDED`, the cascade
        unwinds: the permit moves `SUSPENDED - ACTIVE`".

        Design: Difficulty/priority_pair_validation_conflict/permit_not_active_beats_take_limit_exceeded
        """
        scenario = setup_suspended_permit()

        adjudicate_report(scenario["r1"]["id"], "REJECT")

        permit = read_permit(scenario["permit"]["id"])
        assert permit["status"] == "ACTIVE"
        assert permit["take_consumed_units"] == 0.00
        response = api.create_monitoring_report(
            permit["id"],
            _report_body(permit["version"], "2027-01-01", "2027-03-31"),
            scenario["proponent_headers"],
        )
        get_success_data(response, 201)


class TestJeopardyBeatsMitigationShortfall:
    """Rung 16 beats rung 27 on the same approval."""

    def test_the_opinion_concludes_jeopardy_on_the_inclusive_threshold(self, api):
        """A fraction of exactly 0.0500 is jeopardy, not no-jeopardy.

        PRD: "When that rounded fraction is at or above 0.0500 - five hundredths, the
        threshold being inclusive, so a fraction rounding to exactly 0.0500 **is** a
        jeopardy result - `rpa_required` is set to true, and `conclusion` becomes
        `JEOPARDY_WITH_RPA` when an `rpa_description` was supplied and `JEOPARDY` when
        none was."

        Ten acres of designated critical habitat at 0.40 individuals per acre authorises
        4.00 individuals against a recovery unit of 80.

        Design: Difficulty/priority_pair_validation_conflict/jeopardy_unresolved_beats_mitigation_shortfall
        """
        scenario = setup_jeopardy_submitted_plan()
        opinion = scenario["opinion"]

        assert opinion["authorized_take_units"] == 4.00
        assert opinion["jeopardy_fraction"] == 0.0500
        assert opinion["conclusion"] == "JEOPARDY"
        assert opinion["rpa_required"] is True

    def test_the_jeopardy_gate_is_reported_not_the_shortfall(self, api):
        """Both approval gates fail and the safety rule wins.

        PRD: "An approval decision on a plan whose action carries an unresolved jeopardy
        opinion *and* whose secured mitigation falls short of the final requirement is
        reported as `ERR_JEOPARDY_UNRESOLVED` - the safety rule at rung 16 beats the
        fiscal rule at rung 27."

        Design: Difficulty/priority_pair_validation_conflict/jeopardy_unresolved_beats_mitigation_shortfall
        """
        scenario = setup_jeopardy_submitted_plan()
        plan = scenario["plan"]
        assert plan["funding_status"] == "FULLY_ASSURED"
        assert plan["final_mitigation_units"] == 45.00
        assert plan["secured_mitigation_units"] == 1.00
        assert plan["plan_status"] == "SUBMITTED"

        response = api.decide_plan(plan["id"], plan_decision_payload("APPROVE"), APPROVER)

        assert_error_envelope(response, ApiErrorId.ERR_JEOPARDY_UNRESOLVED, 422)

    def test_the_refused_approval_runs_none_of_its_side_effects(self, api):
        """No commitment is secured and no credit is transferred.

        PRD: "a cascade either completes in full or, when a validation rejects the
        request, leaves every row exactly as it was - there are no partial cascades."

        Design: Difficulty/priority_pair_validation_conflict/jeopardy_unresolved_beats_mitigation_shortfall
        """
        scenario = setup_jeopardy_submitted_plan()
        api.decide_plan(
            scenario["plan"]["id"], plan_decision_payload("APPROVE"), APPROVER
        )

        plan = read_plan(scenario["plan"]["id"])
        assert plan["plan_status"] == "SUBMITTED"
        assert plan.get("approved_by_user_id") is None
        rows = assert_unpaginated_list(
            api.list_plan_mitigation_commitments(
                plan["id"], scenario["proponent_headers"]
            )
        )
        assert [row["status"] for row in rows] == ["RESERVED"]
        bank = read_bank(scenario["bank"]["id"])
        assert bank["credits_reserved"] == 1.00
        assert bank["credits_transferred"] == 0.00

    def test_an_opinion_with_an_alternative_reaches_the_shortfall_gate(self, api):
        """Clearing rung 16 lets rung 27 surface on the same call.

        PRD: "No biological opinion of the action's active consultation may carry a
        `conclusion` of `JEOPARDY` - an opinion whose `conclusion` is
        `JEOPARDY_WITH_RPA` passes the gate ... And `secured_mitigation_units` must be at
        least `final_mitigation_units`, a shortfall being `ERR_MITIGATION_SHORTFALL`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/jeopardy_unresolved_beats_mitigation_shortfall
        """
        scenario = setup_jeopardy_submitted_plan(
            opinion_payload={
                "rpa_description": "Seasonal work restrictions and translocation of burrows."
            }
        )
        assert scenario["opinion"]["conclusion"] == "JEOPARDY_WITH_RPA"

        response = api.decide_plan(
            scenario["plan"]["id"], plan_decision_payload("APPROVE"), APPROVER
        )

        assert_error_envelope(response, ApiErrorId.ERR_MITIGATION_SHORTFALL, 422)


class TestPeriodBoundsBeatPeriodOverlap:
    """Rung 19 beats rung 21 on the same report."""

    def test_the_temporal_rule_is_reported_not_the_overlap(self, api):
        """A period past the term and past the clock is a bounds failure.

        PRD: "A monitoring report whose `period_end` lies beyond the current logical
        clock *and* which overlaps an already-submitted report on the same permit is
        reported as `ERR_PERIOD_OUTSIDE_PERMIT_TERM` - the temporal rule at rung 19 beats
        the constraint rule at rung 21."

        The permit runs to 2027-10-01 and the clock stands at 2027-02-14, so a period
        ending 2027-12-31 breaks two of the four bounds while also swallowing the report
        already on file.

        Design: Difficulty/priority_pair_validation_conflict/period_outside_permit_term_beats_reporting_period_overlap
        """
        scenario = setup_permit_with_one_report()
        assert scenario["permit"]["term_end"] == "2027-10-01"
        assert scenario["r1"]["status"] == "SUBMITTED"

        response = api.create_monitoring_report(
            scenario["permit"]["id"],
            _report_body(
                scenario["permit"]["version"], "2026-12-01", "2027-12-31", take=0.50
            ),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_PERIOD_OUTSIDE_PERMIT_TERM, 422)

    def test_the_refused_report_creates_no_row_and_moves_no_take(self, api):
        """The collection and the ledger are untouched by the refusal.

        PRD: "Before the ledger is touched at all, the take ceiling is checked".

        PRD: "a cascade either completes in full or, when a validation rejects the
        request, leaves every row exactly as it was - there are no partial cascades."

        Design: Difficulty/priority_pair_validation_conflict/period_outside_permit_term_beats_reporting_period_overlap
        """
        scenario = setup_permit_with_one_report()
        api.create_monitoring_report(
            scenario["permit"]["id"],
            _report_body(
                scenario["permit"]["version"], "2026-12-01", "2027-12-31", take=0.50
            ),
            scenario["proponent_headers"],
        )

        rows = assert_unpaginated_list(
            api.list_permit_monitoring_reports(
                scenario["permit"]["id"], scenario["proponent_headers"]
            )
        )
        assert len(rows) == 1
        assert read_permit(scenario["permit"]["id"])["take_consumed_units"] == 1.00

    def test_the_overlap_rule_surfaces_once_the_bounds_are_satisfied(self, api):
        """An in-term period that still overlaps reports the overlap.

        PRD: "Two intervals overlap when the new `period_start` is strictly earlier than
        the existing `period_end` **and** the new `period_end` is strictly later than the
        existing `period_start`". An overlap is "`ERR_REPORTING_PERIOD_OVERLAP` (HTTP
        409)."

        Design: Difficulty/priority_pair_validation_conflict/period_outside_permit_term_beats_reporting_period_overlap
        """
        scenario = setup_permit_with_one_report()

        response = api.create_monitoring_report(
            scenario["permit"]["id"],
            _report_body(
                scenario["permit"]["version"], "2026-12-01", "2027-01-31", take=0.50
            ),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP, 409)

    def test_exact_adjacency_is_accepted(self, api):
        """A period beginning on another's end coexists with it.

        PRD: "there is no buffer, and exact adjacency is explicitly allowed, so a period
        beginning precisely on another period's `period_end` coexists with it."

        PRD: "`period_end` must not be later than the current logical clock", so a period
        ending exactly on the clock value is inside the bound.

        Design: Difficulty/priority_pair_validation_conflict/period_outside_permit_term_beats_reporting_period_overlap
        """
        scenario = setup_permit_with_one_report()

        response = api.create_monitoring_report(
            scenario["permit"]["id"],
            _report_body(
                scenario["permit"]["version"], "2027-01-31", "2027-02-14", take=0.50
            ),
            scenario["proponent_headers"],
        )

        report = get_success_data(response, 201)
        assert report["status"] == "SUBMITTED"

    def test_a_period_starting_before_the_term_is_out_of_bounds(self, api):
        """The lower bound bites with no overlapping report at all.

        PRD: "`period_start` must not be earlier than the permit's `term_start`".

        Design: Difficulty/priority_pair_validation_conflict/period_outside_permit_term_beats_reporting_period_overlap
        """
        scenario = setup_permit_with_one_report()

        response = api.create_monitoring_report(
            scenario["permit"]["id"],
            _report_body(
                scenario["permit"]["version"], "2026-09-30", "2026-11-30", take=0.50
            ),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_PERIOD_OUTSIDE_PERMIT_TERM, 422)


class TestBankEligibilityBeatsCreditAvailability:
    """Rung 24 beats rung 25 on the same commitment."""

    def _plan_with_an_out_of_area_bank(self):
        scenario = build_scenario("plan")
        scenario["bank2"] = establish_out_of_area_bank(scenario["species"]["id"])
        return scenario

    def _commitment_body(self, scenario, units, bank_id=None, mechanism="CONSERVATION_BANK_CREDIT"):
        plan = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
        body = {
            "mechanism": mechanism,
            "units": units,
            "expected_hcp_version": plan["version"],
        }
        if bank_id is not None:
            body["conservation_bank_id"] = bank_id
        return body

    def test_the_eligibility_rule_is_reported_not_the_shortfall(self, api):
        """An out-of-area bank asked for more than it holds reports eligibility.

        PRD: "a bank-credit commitment citing a bank whose service area excludes the
        action's county *and* requesting more units than the bank has available is
        reported as `ERR_BANK_NOT_ELIGIBLE` - the referential rule at rung 24 beats the
        fiscal rule at rung 25."

        Design: Difficulty/priority_pair_validation_conflict/bank_not_eligible_beats_insufficient_bank_credits
        """
        scenario = self._plan_with_an_out_of_area_bank()

        response = api.create_mitigation_commitment(
            scenario["plan"]["id"],
            self._commitment_body(scenario, 10.00, scenario["bank2"]["id"]),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_BANK_NOT_ELIGIBLE, 422)

    def test_eligibility_is_amount_independent(self, api):
        """A request well inside the balance still fails on service area.

        PRD: "And the action's `county_code` must appear somewhere in the bank's
        `service_area_county_codes`. Only once eligibility passes does the credit balance
        matter".

        Design: Difficulty/priority_pair_validation_conflict/bank_not_eligible_beats_insufficient_bank_credits
        """
        scenario = self._plan_with_an_out_of_area_bank()

        response = api.create_mitigation_commitment(
            scenario["plan"]["id"],
            self._commitment_body(scenario, 3.00, scenario["bank2"]["id"]),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_BANK_NOT_ELIGIBLE, 422)

    def test_the_availability_rule_surfaces_on_an_eligible_bank(self, api):
        """Six hundred credits from a five-hundred-credit bank is a shortfall.

        PRD: "the bank's `credits_available` must be at least the requested `units`, and a
        shortfall is `ERR_INSUFFICIENT_BANK_CREDITS` (HTTP 409). Eligibility is checked
        before availability, so a commitment that is both out of service area and over
        budget reports the eligibility failure."

        Design: Difficulty/priority_pair_validation_conflict/bank_not_eligible_beats_insufficient_bank_credits
        """
        scenario = self._plan_with_an_out_of_area_bank()

        response = api.create_mitigation_commitment(
            scenario["plan"]["id"],
            self._commitment_body(scenario, 600.00, scenario["bank"]["id"]),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_INSUFFICIENT_BANK_CREDITS, 409)

    def test_a_bank_id_on_a_non_bank_mechanism_is_the_same_error(self, api):
        """The mechanism/bank pairing rule shares the eligibility code.

        PRD: "Violating either half of the pairing - omitting the bank on a bank-credit
        commitment, or supplying a bank on an in-lieu-fee or permittee-responsible
        commitment - is `ERR_BANK_NOT_ELIGIBLE` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/bank_not_eligible_beats_insufficient_bank_credits
        """
        scenario = self._plan_with_an_out_of_area_bank()

        response = api.create_mitigation_commitment(
            scenario["plan"]["id"],
            self._commitment_body(
                scenario, 10.00, scenario["bank"]["id"], mechanism="IN_LIEU_FEE"
            ),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_BANK_NOT_ELIGIBLE, 422)

    def test_no_refused_attempt_touches_a_ledger_or_the_plan(self, api):
        """After four refusals the plan has no commitment and no requirement.

        PRD: "If `expected_hcp_version` does not equal the plan's current `version`, the
        request is rejected with `ERR_STALE_HCP_VERSION` (HTTP 412) and **nothing** is
        written: no commitment row appears, no bank credit moves, no endowment aggregate
        changes."

        PRD: "An `endowment_required_cents` of 0 is a reachable and legitimate state".

        Design: Difficulty/priority_pair_validation_conflict/bank_not_eligible_beats_insufficient_bank_credits
        """
        scenario = self._plan_with_an_out_of_area_bank()
        for units, bank_id, mechanism in (
            (10.00, scenario["bank2"]["id"], "CONSERVATION_BANK_CREDIT"),
            (3.00, scenario["bank2"]["id"], "CONSERVATION_BANK_CREDIT"),
            (600.00, scenario["bank"]["id"], "CONSERVATION_BANK_CREDIT"),
            (10.00, scenario["bank"]["id"], "IN_LIEU_FEE"),
        ):
            api.create_mitigation_commitment(
                scenario["plan"]["id"],
                self._commitment_body(scenario, units, bank_id, mechanism),
                scenario["proponent_headers"],
            )

        rows = assert_unpaginated_list(
            api.list_plan_mitigation_commitments(
                scenario["plan"]["id"], scenario["proponent_headers"]
            )
        )
        assert rows == []
        plan = read_plan(scenario["plan"]["id"], scenario["proponent_headers"])
        assert plan["endowment_required_cents"] == 0
        assert plan["funding_status"] == "UNFUNDED"
        for bank in (read_bank(scenario["bank"]["id"]), read_bank(scenario["bank2"]["id"])):
            assert bank["credits_reserved"] == 0.00
            assert bank["credits_transferred"] == 0.00
            assert_bank_ledger_identity(bank)
