"""Disclosure intake: the declared defaults, the cell-count gate and the aggregate refusal branch."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_cell,
    assert_common_fields,
    assert_instant_equals,
    assert_null,
    assert_request_counters,
    assert_version,
    constants as K,
    factories as f,
    fixtures as fx,
)

COORDINATING_BOARD = "State Higher Education Coordinating Board"
PROVOST_OFFICE = "Office of the Provost"
PRESS_BUREAU = "State Capital Press Bureau"
POLICY_INSTITUTE = "Statewide Policy Institute"

HEADCOUNT_METRICS_39 = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 39,
        "prior_year_value": 39,
        "source_field_path": "sis.enrollment.total_headcount",
    },
)
HEADCOUNT_METRICS_30 = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 30,
        "prior_year_value": 30,
        "source_field_path": "sis.enrollment.headcount",
    },
)

REFUSED_RELEASE_NOTE = "Attempting to release a refused request."
AGE_BAND_NOTE = "Released to the policy institute with two age bands withheld."


def _cells_by_key(api, request_id, disclosure):
    """Every disclosure cell of one request, indexed by its dimension_key."""
    rows = validate_success(
        api.list_disclosure_cells(disclosure, request_id=request_id, limit=100)
    )
    return {row["dimension_key"]: row for row in rows}


class TestDataRequestDefaults:
    """Both optional inputs are filled by the server rather than left null."""

    def test_omitting_the_method_and_the_minimum_yields_the_declared_defaults(
        self, api, disclosure
    ):
        """A request created with neither option opens fully configured and fully counted.

        PRD 3.9: "A **data request** is opened against a cycle by a `DisclosureOfficer` who
        supplies the `requester_org` of 3 to 120 characters, the `requester_type` of `INTERNAL`,
        `EXTERNAL` or `MEDIA`, the `requested_metric_key` of 3 to 64 characters, optionally the
        `avoidance_method` of `SMALL_CELL_SUPPRESSION` or `CONTROLLED_ROUNDING` which defaults to
        `SMALL_CELL_SUPPRESSION`, and optionally the `min_cell_size` which defaults to 5 and must
        be between 2 and 10 inclusive."

        PRD 3.9: "The row starts at `status` `RECEIVED`, with `cell_count`,
        `suppressed_cell_count` and `released_cell_count` at 0, `residual_disclosure_risk` false,
        `refusal_reason`, `screened_at`, `screened_by_user_id` and `release_note` null, and
        `version` 1."

        Design: Corner/entities/corner_data_request_defaults_avoidance_method_and_min_cell_size
        """
        scenario = fx.frozen_cycle(api, checksum="c1d2e3f4a5b60106")

        request = validate_success(
            api.create_data_request(
                scenario.cycle_id,
                f.make_data_request_payload(
                    requester_org=COORDINATING_BOARD,
                    requester_type=K.REQUESTER_INTERNAL,
                    requested_metric_key=K.METRIC_TOTAL_HEADCOUNT,
                ),
                disclosure,
            ),
            201,
        )
        assert request["avoidance_method"] == K.AVOIDANCE_SMALL_CELL_SUPPRESSION
        assert request["min_cell_size"] == K.DEFAULT_MIN_CELL_SIZE
        assert_request_counters(
            request,
            cell_count=0,
            released_cell_count=0,
            suppressed_cell_count=0,
            residual_disclosure_risk=False,
            status=K.REQUEST_RECEIVED,
        )
        assert_null(request["refusal_reason"], "data_request.refusal_reason")
        assert_null(request["screened_at"], "data_request.screened_at")
        assert_null(request["screened_by_user_id"], "data_request.screened_by_user_id")
        assert_null(request["release_note"], "data_request.release_note")
        assert_version(request, 1, "data_request")
        assert_common_fields(request, "data_request")

        stored = validate_success(api.get_data_request(request["id"], disclosure))
        assert stored["avoidance_method"] == K.AVOIDANCE_SMALL_CELL_SUPPRESSION
        assert stored["min_cell_size"] == K.DEFAULT_MIN_CELL_SIZE
        assert stored["requester_type"] == K.REQUESTER_INTERNAL


class TestScreeningNeedsAtLeastOneCell:
    """The cell-count gate precedes the aggregate branch entirely."""

    def test_a_cell_less_request_is_neither_screened_nor_refused(self, api, disclosure):
        """No refusal_reason is written, so the request is still screenable once a cell arrives.

        PRD 3.9: "Both branches require the request to be `RECEIVED` (else
        `ERR_INVALID_DATA_REQUEST_STATE`), the cycle to be `FROZEN` or `ARCHIVED` (else
        `ERR_CYCLE_NOT_FROZEN`), and `cell_count` to be at least 1 (else
        `ERR_NO_CELLS_TO_SCREEN`)."

        PRD 3.9: "Each new cell starts at `suppression_state` `PENDING` with `released_count` null
        and `version` 1, and the parent request's `cell_count` is recomputed with the request's
        `version` incremented."

        Design: Corner/validations/corner_val_screening_requires_at_least_one_cell
        """
        scenario = fx.frozen_cycle(
            api, record_count=30, metrics=HEADCOUNT_METRICS_30, checksum="c1d2e3f4a5b60147"
        )
        request = fx.intake_request(
            api,
            scenario,
            requester_org=PROVOST_OFFICE,
            requester_type=K.REQUESTER_INTERNAL,
            requested_metric_key=K.METRIC_TOTAL_HEADCOUNT,
        )

        empty = api.screen_data_request(request["id"], disclosure)
        validate_error(empty, ApiErrorId.NO_CELLS_TO_SCREEN, 422)

        waiting = validate_success(api.get_data_request(request["id"], disclosure))
        assert_request_counters(waiting, cell_count=0, status=K.REQUEST_RECEIVED)
        assert_null(waiting["refusal_reason"], "data_request.refusal_reason")
        assert_null(waiting["screened_at"], "data_request.screened_at")
        assert_version(waiting, 1, "data_request")

        cell = validate_success(
            api.add_disclosure_cell(
                request["id"], f.make_disclosure_cell_payload("GENDER", "FEMALE", 30), disclosure
            ),
            201,
        )
        assert_cell(cell, suppression_state=K.CELL_PENDING, released_count=None, raw_count=30)
        assert_version(cell, 1, "cell")

        screened = validate_success(api.screen_data_request(request["id"], disclosure))
        assert_request_counters(
            screened,
            cell_count=1,
            released_cell_count=1,
            suppressed_cell_count=0,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )
        assert_instant_equals(
            screened["screened_at"], K.CLOCK_AFTER_CENSUS_ECHO, "data_request.screened_at"
        )
        assert screened["screened_by_user_id"] == "disclosure-1"

        released = validate_success(api.get_disclosure_cell(cell["id"], disclosure))
        assert_cell(released, suppression_state=K.CELL_RELEASED, released_count=30)


class TestAggregateBelowMinimumRefusesTheWholeCrosstab:
    """A crosstab too small to protect is refused without touching a single cell."""

    def test_two_cells_summing_to_three_are_refused_and_nothing_further_may_touch_them(
        self, api, disclosure
    ):
        """REFUSED is terminal, so neither a release nor a further cell write is accepted.

        PRD 3.9: "**No cell is mutated on this branch**: every cell keeps `suppression_state`
        `PENDING` and `released_count` null, and nothing is computed at all."

        PRD 3.9: "Cells may be added only while the request is `RECEIVED`; once it has been screened
        the crosstab is fixed, and a later addition reports `ERR_INVALID_DATA_REQUEST_STATE`."

        Design: Corner/state_machines/corner_sm_screen_refuses_the_request_when_the_aggregate_is_below_minimum
        """
        scenario = fx.frozen_cycle(api, checksum="c1d2e3f4a5b60152")
        request = fx.intake_request(
            api,
            scenario,
            requester_org=PRESS_BUREAU,
            requester_type=K.REQUESTER_MEDIA,
            requested_metric_key="HEADCOUNT_BY_RACE",
        )
        assert request["min_cell_size"] == K.DEFAULT_MIN_CELL_SIZE
        fx.add_cells(api, scenario, "RACE_ETHNICITY", (("ASIAN", 1), ("BLACK", 2)))

        refused = validate_success(api.screen_data_request(request["id"], disclosure))
        assert_request_counters(
            refused,
            cell_count=2,
            released_cell_count=0,
            suppressed_cell_count=0,
            residual_disclosure_risk=False,
            status=K.REQUEST_REFUSED,
        )
        assert refused["refusal_reason"] == K.REFUSAL_AGGREGATE_BELOW_MINIMUM
        assert_instant_equals(
            refused["screened_at"], K.CLOCK_AFTER_CENSUS_ECHO, "data_request.screened_at"
        )
        assert refused["screened_by_user_id"] == "disclosure-1"

        untouched = _cells_by_key(api, request["id"], disclosure)
        for key, raw in (("ASIAN", 1), ("BLACK", 2)):
            assert_cell(
                untouched[key],
                suppression_state=K.CELL_PENDING,
                released_count=None,
                raw_count=raw,
            )
            assert_version(untouched[key], 1, f"cell {key}")

        too_late = api.release_data_request(
            request["id"], disclosure, f.make_release_payload(REFUSED_RELEASE_NOTE)
        )
        validate_error(too_late, ApiErrorId.INVALID_DATA_REQUEST_STATE, 409)

        more_cells = api.add_disclosure_cell(
            request["id"],
            f.make_disclosure_cell_payload("RACE_ETHNICITY", "WHITE", 40),
            disclosure,
        )
        validate_error(more_cells, ApiErrorId.INVALID_DATA_REQUEST_STATE, 409)

        rows, meta = validate_paginated(
            api.list_disclosure_cells(disclosure, request_id=request["id"])
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2


HEADCOUNT_METRICS_13 = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 13,
        "prior_year_value": 13,
        "source_field_path": "sis.enrollment.total_headcount",
    },
)


class TestSmallCellWindowIsStrictAtBothEnds:
    """A cell at exactly min_cell_size is released, and a structural zero always is."""

    @staticmethod
    def _age_band_request(api, min_cell_size, counts, checksum, metrics, record_count):
        """An EXTERNAL small-cell request over one AGE_BAND crosstab on a FROZEN cycle."""
        scenario = fx.frozen_cycle(
            api, record_count=record_count, metrics=metrics, checksum=checksum
        )
        request = fx.intake_request(
            api,
            scenario,
            requester_org=POLICY_INSTITUTE,
            requester_type=K.REQUESTER_EXTERNAL,
            requested_metric_key="HEADCOUNT_BY_AGE",
            avoidance_method=K.AVOIDANCE_SMALL_CELL_SUPPRESSION,
            min_cell_size=min_cell_size,
        )
        assert request["min_cell_size"] == min_cell_size
        assert request["avoidance_method"] == K.AVOIDANCE_SMALL_CELL_SUPPRESSION
        fx.add_cells(api, scenario, "AGE_BAND", counts)
        return scenario

    def test_the_cell_at_exactly_five_is_released_and_then_taken_as_the_victim(
        self, api, disclosure
    ):
        """One value sits on both boundaries: too large to suppress, too small to survive the group.

        PRD 3.9: "A cell whose `raw_count` is strictly greater than 0 **and** strictly less than
        `min_cell_size` is a small cell: its `suppression_state` becomes `PRIMARY_SUPPRESSED` and
        its `released_count` is set to null."

        PRD 3.9: "A `raw_count` of exactly 0 is a **structural zero**, not a small count: it
        reveals nothing about any individual because there is nobody in the category, so it is
        always released untouched."

        PRD 3.9: "If the group has at least one candidate, the victim is the candidate with the
        smallest `raw_count`, with ties broken by `dimension_key` ascending; its
        `suppression_state` becomes `COMPLEMENTARY_SUPPRESSED` and its `released_count` is set to
        null."

        Design: Difficulty/boundary_precision_check/small_cell_boundary_at_exactly_min_cell_size_and_structural_zero
        """
        scenario = self._age_band_request(
            api,
            K.DEFAULT_MIN_CELL_SIZE,
            (("A_UNDER_18", 4), ("B_18_24", 5), ("C_25_PLUS", 0), ("D_35_PLUS", 30)),
            "a1b2c3d4e5f60013",
            HEADCOUNT_METRICS_39,
            39,
        )

        screened = validate_success(api.screen_data_request(scenario.request_id, disclosure))
        assert_request_counters(
            screened,
            cell_count=4,
            released_cell_count=2,
            suppressed_cell_count=2,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )

        cells = _cells_by_key(api, scenario.request_id, disclosure)
        assert_cell(
            cells["A_UNDER_18"],
            suppression_state=K.CELL_PRIMARY_SUPPRESSED,
            released_count=None,
            raw_count=4,
        )
        assert_cell(
            cells["B_18_24"],
            suppression_state=K.CELL_COMPLEMENTARY_SUPPRESSED,
            released_count=None,
            raw_count=K.DEFAULT_MIN_CELL_SIZE,
        )
        assert_cell(
            cells["C_25_PLUS"], suppression_state=K.CELL_RELEASED, released_count=0, raw_count=0
        )
        assert_cell(
            cells["D_35_PLUS"], suppression_state=K.CELL_RELEASED, released_count=30, raw_count=30
        )

    def test_the_window_follows_the_requests_own_minimum_down_to_two(self, api, disclosure):
        """With the minimum at 2 the cell holding 2 is released, and only the cell holding 1 is small.

        PRD 3.9: "A cell whose `raw_count` is strictly greater than 0 **and** strictly less than
        `min_cell_size` is a small cell: its `suppression_state` becomes `PRIMARY_SUPPRESSED` and
        its `released_count` is set to null."

        PRD 3.9: "When `released_cell_count` is at least 1 the request moves `SCREENED →
        RELEASED`; when `released_cell_count` is exactly 0, so that suppression consumed the entire
        crosstab, it moves `SCREENED → SUPPRESSED_RELEASE` instead, which records that the request
        was answered with nothing disclosable."

        Design: Difficulty/boundary_precision_check/small_cell_boundary_at_exactly_min_cell_size_and_structural_zero
        """
        scenario = self._age_band_request(
            api,
            K.MIN_CELL_SIZE_FLOOR,
            (("A_ZERO", 0), ("B_ONE", 1), ("C_TWO", 2), ("D_TEN", 10)),
            "a1b2c3d4e5f60014",
            HEADCOUNT_METRICS_13,
            13,
        )

        screened = validate_success(api.screen_data_request(scenario.request_id, disclosure))
        assert_request_counters(
            screened,
            cell_count=4,
            released_cell_count=2,
            suppressed_cell_count=2,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )

        cells = _cells_by_key(api, scenario.request_id, disclosure)
        assert_cell(cells["A_ZERO"], suppression_state=K.CELL_RELEASED, released_count=0)
        assert_cell(
            cells["B_ONE"], suppression_state=K.CELL_PRIMARY_SUPPRESSED, released_count=None
        )
        assert_cell(
            cells["C_TWO"],
            suppression_state=K.CELL_COMPLEMENTARY_SUPPRESSED,
            released_count=None,
            raw_count=K.MIN_CELL_SIZE_FLOOR,
        )
        assert_cell(cells["D_TEN"], suppression_state=K.CELL_RELEASED, released_count=10)

        released = validate_success(
            api.release_data_request(
                scenario.request_id, disclosure, f.make_release_payload(AGE_BAND_NOTE)
            )
        )
        assert_request_counters(
            released, released_cell_count=2, suppressed_cell_count=2, status=K.REQUEST_RELEASED
        )
        assert released["release_note"] == AGE_BAND_NOTE
