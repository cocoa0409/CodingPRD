"""The two interval rules: closed and buffered on habitat, half-open on permits."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_error_envelope, assert_unpaginated_list
from test_helpers.factories import database_query_payload, field_survey_payload
from test_helpers.fixtures import (
    adjudicate_report,
    read_permit,
    setup_permit_with_accepted_first_quarter_report,
    setup_two_actions_sharing_a_habitat_unit,
)


class TestSurveyWindowsAreClosedAndBuffered:
    """A three-day buffer on both sides, contended across every project action."""

    def _survey(self, unit_id, start, end, acres=5.00):
        return field_survey_payload(
            None,
            critical_habitat_unit_id=unit_id,
            survey_window_start=start,
            survey_window_end=end,
            habitat_overlap_acres=acres,
        )

    def _post(self, api, scenario, unit_id, start, end):
        payload = self._survey(unit_id, start, end)
        payload["species_id"] = scenario["species"]["id"]
        return api.create_presence_determination(
            scenario["action_b"]["id"], payload, scenario["proponent_headers"]
        )

    def test_touching_the_right_buffer_edge_conflicts_across_actions(self, api):
        """A start exactly three days after the existing end is a conflict.

        PRD: "Two field-survey windows citing the **same** critical habitat unit conflict
        when they come within a three-day buffer of one another, and the comparison
        deliberately reaches across **all** project actions - the buffer protects the
        habitat, not the project."
        PRD: "Concretely, a new window conflicts with an existing one when the new
        window's start date is at or before the existing window's end date advanced by
        three days, **and** the new window's end date advanced by three days is at or
        after the existing window's start date."

        Design: Difficulty/resource_temporal_overlap/survey_windows_on_a_habitat_unit_are_closed_intervals_with_a_buffer
        """
        scenario = setup_two_actions_sharing_a_habitat_unit()
        assert scenario["pd1"]["survey_window_start"] == "2026-05-04"
        assert scenario["pd1"]["survey_window_end"] == "2026-05-08"

        response = self._post(
            api, scenario, scenario["unit"]["id"], "2026-05-11", "2026-05-15"
        )

        assert_error_envelope(response, ApiErrorId.ERR_SURVEY_WINDOW_CONFLICT, 409)

    def test_four_days_apart_clears_the_buffer(self, api):
        """One day further out is accepted and derives a confirmed presence.

        PRD: "Both bounds are inclusive, so two windows three days apart conflict while
        two windows four days apart do not."
        PRD: "A `FIELD_SURVEY` can: `DETECTED` yields `PRESENT`"

        Design: Difficulty/resource_temporal_overlap/survey_windows_on_a_habitat_unit_are_closed_intervals_with_a_buffer
        """
        scenario = setup_two_actions_sharing_a_habitat_unit()

        determination = get_success_data(
            self._post(
                api, scenario, scenario["unit"]["id"], "2026-05-12", "2026-05-16"
            ),
            201,
        )

        assert determination["presence_status"] == "PRESENT"
        assert determination["survey_in_season"] is True

    def test_the_buffer_applies_on_the_left_as_well(self, api):
        """A window ending three days before the existing start also conflicts.

        PRD: "the new window's end date advanced by three days is at or after the
        existing window's start date"

        Design: Difficulty/resource_temporal_overlap/survey_windows_on_a_habitat_unit_are_closed_intervals_with_a_buffer
        """
        scenario = setup_two_actions_sharing_a_habitat_unit()

        assert_error_envelope(
            self._post(
                api, scenario, scenario["unit"]["id"], "2026-04-28", "2026-05-01"
            ),
            ApiErrorId.ERR_SURVEY_WINDOW_CONFLICT,
            409,
        )

        earlier = get_success_data(
            self._post(
                api, scenario, scenario["unit"]["id"], "2026-04-27", "2026-04-30"
            ),
            201,
        )
        assert earlier["presence_status"] == "PRESENT"

    def test_the_conflict_is_scoped_to_one_habitat_unit(self, api):
        """The refused window is accepted verbatim when it cites the other unit.

        PRD: "Two field-survey windows citing the **same** critical habitat unit conflict
        when they come within a three-day buffer of one another"

        Design: Difficulty/resource_temporal_overlap/survey_windows_on_a_habitat_unit_are_closed_intervals_with_a_buffer
        """
        scenario = setup_two_actions_sharing_a_habitat_unit()

        determination = get_success_data(
            self._post(
                api, scenario, scenario["unit_2"]["id"], "2026-05-11", "2026-05-15"
            ),
            201,
        )
        assert determination["critical_habitat_unit_id"] == scenario["unit_2"]["id"]

        units = assert_unpaginated_list(
            api.list_critical_habitat_units(
                scenario["species"]["id"], scenario["proponent_headers"]
            )
        )
        assert len(units) == 2
        assert sorted(row["unit_code"] for row in units) == ["CHU-1", "CHU-2"]

    def test_non_participants_never_conflict(self, api):
        """A desk query and a survey citing no unit both sit inside the buffered span.

        PRD: "Database-query determinations and determinations with a null
        `critical_habitat_unit_id` never participate on either side of the comparison."
        PRD: "For a `DATABASE_QUERY` determination, `survey_in_season` is always false."

        Design: Difficulty/resource_temporal_overlap/survey_windows_on_a_habitat_unit_are_closed_intervals_with_a_buffer
        """
        scenario = setup_two_actions_sharing_a_habitat_unit()
        headers = scenario["proponent_headers"]
        action_b = scenario["action_b"]["id"]

        query = get_success_data(
            api.create_presence_determination(
                action_b,
                database_query_payload(scenario["species"]["id"]),
                headers,
            ),
            201,
        )
        assert query["survey_in_season"] is False

        unitless = get_success_data(
            api.create_presence_determination(
                action_b,
                field_survey_payload(
                    scenario["species"]["id"],
                    survey_window_start="2026-05-05",
                    survey_window_end="2026-05-07",
                ),
                headers,
            ),
            201,
        )
        assert unitless["critical_habitat_unit_id"] is None
        assert unitless["presence_status"] == "PRESENT"

    def test_an_identical_window_is_also_a_conflict(self, api):
        """The buffered comparison subsumes plain containment.

        PRD: "A conflict is `ERR_SURVEY_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/survey_windows_on_a_habitat_unit_are_closed_intervals_with_a_buffer
        """
        scenario = setup_two_actions_sharing_a_habitat_unit()

        assert_error_envelope(
            self._post(
                api, scenario, scenario["unit"]["id"], "2026-05-04", "2026-05-08"
            ),
            ApiErrorId.ERR_SURVEY_WINDOW_CONFLICT,
            409,
        )


class TestReportingPeriodsAreHalfOpenAndUnbuffered:
    """The same system's other interval rule allows exact adjacency."""

    def _body(self, version, period_start, period_end, take=1.00):
        return {
            "period_start": period_start,
            "period_end": period_end,
            "take_units_reported": take,
            "mitigation_units_verified": 59.72,
            "expected_permit_version": version,
        }

    def test_a_period_beginning_on_another_periods_end_is_accepted(self, api):
        """Back-to-back quarters coexist and both takes land on the ledger.

        PRD: "Two intervals overlap when the new `period_start` is strictly earlier than
        the existing `period_end` **and** the new `period_end` is strictly later than the
        existing `period_start`; there is no buffer, and exact adjacency is explicitly
        allowed, so a period beginning precisely on another period's `period_end`
        coexists with it."
        PRD: "`due_at` is `period_end` advanced by 45 calendar days, and it is a
        date-only value."

        Design: Difficulty/resource_temporal_overlap/reporting_periods_on_a_permit_are_half_open_and_may_be_adjacent
        """
        scenario = setup_permit_with_accepted_first_quarter_report()
        permit = scenario["permit"]
        assert scenario["r1"]["due_at"] == "2027-05-16"
        assert scenario["r1"]["is_late"] is False
        assert permit["take_consumed_units"] == 1.00

        report = get_success_data(
            api.create_monitoring_report(
                permit["id"],
                self._body(permit["version"], "2027-04-01", "2027-07-01"),
                scenario["proponent_headers"],
            ),
            201,
        )

        assert report["due_at"] == "2027-08-15"
        assert report["is_late"] is False

        after = read_permit(permit["id"])
        assert after["take_consumed_units"] == 2.00
        assert after["take_remaining_units"] == 2.00
        assert after["status"] == "ACTIVE"

    def test_one_day_of_overlap_is_enough(self, api):
        """A period straddling both existing reports by any amount is refused.

        PRD: "Separately, the new half-open interval must not overlap the interval of any
        report on the **same** permit whose `status` is `SUBMITTED` or `ACCEPTED`."
        PRD: "An overlap is `ERR_REPORTING_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/reporting_periods_on_a_permit_are_half_open_and_may_be_adjacent
        """
        scenario = setup_permit_with_accepted_first_quarter_report()
        permit_id = scenario["permit"]["id"]
        headers = scenario["proponent_headers"]

        get_success_data(
            api.create_monitoring_report(
                permit_id,
                self._body(scenario["permit"]["version"], "2027-04-01", "2027-07-01"),
                headers,
            ),
            201,
        )

        response = api.create_monitoring_report(
            permit_id,
            self._body(read_permit(permit_id)["version"], "2027-03-31", "2027-06-30"),
            headers,
        )

        assert_error_envelope(response, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP, 409)
        assert read_permit(permit_id)["take_consumed_units"] == 2.00

    def test_a_zero_length_period_fails_the_bounds_rule_first(self, api):
        """Rung 19 reports the degenerate interval before the overlap rule is reached.

        PRD: "Four temporal conditions bound the period, all reported as
        `ERR_PERIOD_OUTSIDE_PERMIT_TERM` (HTTP 422): `period_start` must be strictly
        earlier than `period_end`"

        Design: Difficulty/resource_temporal_overlap/reporting_periods_on_a_permit_are_half_open_and_may_be_adjacent
        """
        scenario = setup_permit_with_accepted_first_quarter_report()
        permit = scenario["permit"]

        response = api.create_monitoring_report(
            permit["id"],
            self._body(permit["version"], "2027-07-01", "2027-07-01"),
            scenario["proponent_headers"],
        )

        assert_error_envelope(
            response, ApiErrorId.ERR_PERIOD_OUTSIDE_PERMIT_TERM, 422
        )

    def test_a_rejected_report_frees_its_interval(self, api):
        """The same quarter can be re-filed once its report is rejected.

        PRD: "`REJECTED` reports free their interval and never participate in this
        check."
        PRD: "`REJECT` moves the report `SUBMITTED - REJECTED` and is a full
        compensation: the permit's `take_consumed_units` decreases by that report's
        `take_units_reported` and `take_remaining_units` is restored by the same amount,
        both rounded half up to two decimal places, and the report's half-open interval
        stops blocking new reports."

        Design: Difficulty/resource_temporal_overlap/reporting_periods_on_a_permit_are_half_open_and_may_be_adjacent
        """
        scenario = setup_permit_with_accepted_first_quarter_report()
        permit_id = scenario["permit"]["id"]
        headers = scenario["proponent_headers"]

        r2 = get_success_data(
            api.create_monitoring_report(
                permit_id,
                self._body(scenario["permit"]["version"], "2027-04-01", "2027-07-01"),
                headers,
            ),
            201,
        )
        adjudicate_report(r2["id"], "REJECT")
        assert read_permit(permit_id)["take_consumed_units"] == 1.00

        replacement = get_success_data(
            api.create_monitoring_report(
                permit_id,
                self._body(read_permit(permit_id)["version"], "2027-04-01", "2027-07-01"),
                headers,
            ),
            201,
        )
        assert replacement["status"] == "SUBMITTED"
        assert read_permit(permit_id)["take_consumed_units"] == 2.00

    def test_the_freed_interval_rule_is_status_scoped(self, api):
        """An ACCEPTED report keeps blocking its own interval.

        PRD: "Separately, the new half-open interval must not overlap the interval of any
        report on the **same** permit whose `status` is `SUBMITTED` or `ACCEPTED`."
        PRD: "`ACCEPT` moves the report `SUBMITTED - ACCEPTED` and leaves the reported
        take applied to the permit ledger."

        Design: Difficulty/resource_temporal_overlap/reporting_periods_on_a_permit_are_half_open_and_may_be_adjacent
        """
        scenario = setup_permit_with_accepted_first_quarter_report()
        permit = scenario["permit"]

        response = api.create_monitoring_report(
            permit["id"],
            self._body(permit["version"], "2027-01-01", "2027-04-01"),
            scenario["proponent_headers"],
        )

        assert_error_envelope(response, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP, 409)
