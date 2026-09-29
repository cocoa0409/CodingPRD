"""The two avoidance methods: who gets suppressed, who gets perturbed and who is left recoverable."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ApiErrorId,
    assert_cell,
    assert_controlled_rounding,
    assert_null,
    assert_request_counters,
    constants as K,
    factories as f,
    fixtures as fx,
)

RESEARCH_GROUP = "Campus Enrollment Management Research Group"
PRESS_BUREAU = "State Capital Press Bureau"
RESEARCH_CONSORTIUM = "Regional Higher-Ed Research Consortium"
POLICY_INSTITUTE = "Statewide Policy Institute"

PERTURBED_NOTE = "Perturbed counts released to the internal research group."
TWO_SUPPRESSED_NOTE = "Two suppressed race cells; the released total is safe."
UNMASKED_NOTE = "Attempting an external release despite the unmasked small cell."

HEADCOUNT_METRICS_12000 = (
    {
        "metric_key": K.METRIC_TOTAL_HEADCOUNT,
        "reported_value": 12000,
        "prior_year_value": 12000,
        "source_field_path": "sis.enrollment.total_headcount",
    },
)

RACE_CROSSTAB = (("ASIAN", 3), ("BLACK", 12), ("HISPANIC", 20), ("WHITE", 45), ("TWO_OR_MORE", 0))
AGE_CROSSTAB = (("A_18_19", 2), ("B_20_21", 12), ("C_22_24", 20))


def _cells_by_key(api, request_id, disclosure):
    """Every disclosure cell of one request, indexed by its dimension_key."""
    rows = validate_success(
        api.list_disclosure_cells(disclosure, request_id=request_id, limit=100)
    )
    return {row["dimension_key"]: row for row in rows}


def _open_request(api, scenario, disclosure, requester_org, requester_type, **overrides):
    """Open one data request on the frozen cycle without disturbing the scenario's first one."""
    return validate_success(
        api.create_data_request(
            scenario.cycle_id,
            f.make_data_request_payload(
                requester_org=requester_org,
                requester_type=requester_type,
                requested_metric_key="HEADCOUNT_BY_RACE",
                **overrides,
            ),
            disclosure,
        ),
        201,
    )


class TestControlledRoundingSnapsEveryCount:
    """No primary, no victim, no suppression — every count is nudged to a multiple of five."""

    def test_seven_rounds_down_while_eight_rounds_up_and_a_small_cell_survives(
        self, api, disclosure
    ):
        """The raw 2 is published as 0 rather than suppressed, which is the whole difference.

        PRD 3.9: "Every cell of the request becomes `RELEASED`, and its `released_count` is its
        `raw_count` divided by 5, rounded half up to a whole number, multiplied by 5."

        PRD 3.9: "Because no cell is ever suppressed, `residual_disclosure_risk` is always false
        under this method."

        Design: Corner/calculations/corner_calc_controlled_rounding_snaps_counts_half_up_to_multiples_of_five
        """
        scenario = fx.frozen_cycle(api, record_count=30, checksum="c1d2e3f4a5b60134")
        request = fx.intake_request(
            api,
            scenario,
            requester_org=RESEARCH_GROUP,
            requester_type=K.REQUESTER_INTERNAL,
            requested_metric_key=K.METRIC_TOTAL_HEADCOUNT,
            avoidance_method=K.AVOIDANCE_CONTROLLED_ROUNDING,
            min_cell_size=K.DEFAULT_MIN_CELL_SIZE,
        )
        fx.add_cells(
            api,
            scenario,
            "AGE_BAND",
            (("A_18_19", 2), ("B_20_21", 7), ("C_22_24", 8), ("D_25_PLUS", 13)),
        )

        screened = validate_success(api.screen_data_request(request["id"], disclosure))
        assert_request_counters(
            screened,
            cell_count=4,
            released_cell_count=4,
            suppressed_cell_count=0,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )

        cells = _cells_by_key(api, request["id"], disclosure)
        for key, released in (
            ("A_18_19", 0),
            ("B_20_21", 5),
            ("C_22_24", 10),
            ("D_25_PLUS", 15),
        ):
            assert_cell(cells[key], suppression_state=K.CELL_RELEASED, released_count=released)
            assert_controlled_rounding(cells[key])

        released = validate_success(
            api.release_data_request(
                request["id"], disclosure, f.make_release_payload(PERTURBED_NOTE)
            )
        )
        assert_request_counters(released, released_cell_count=4, status=K.REQUEST_RELEASED)
        assert released["release_note"] == PERTURBED_NOTE

        rows, meta = validate_paginated(
            api.list_disclosure_cells(
                disclosure, request_id=request["id"], suppression_state=K.CELL_RELEASED
            )
        )
        assert meta["total_count"] == 4
        assert len(rows) == 4


class TestTwoPrimariesInOneGroupMaskEachOther:
    """The second pass acts on exactly one primary and stays silent on two."""

    def test_a_group_holding_two_small_cells_sacrifices_no_third_cell(self, api, disclosure):
        """The large cell survives untouched, so an external release is still permitted.

        PRD 3.9: "When it contains **two or more** primaries, the primaries already mask each
        other — no single subtraction recovers either — and again nothing is done."

        PRD 3.9: "The two methods share only their tail: `released_cell_count` and
        `suppressed_cell_count` are recomputed the same way afterwards, as the number of cells whose
        `suppression_state` is `RELEASED` and the number whose state is `PRIMARY_SUPPRESSED` or
        `COMPLEMENTARY_SUPPRESSED` respectively."

        Design: Corner/calculations/corner_calc_two_primary_suppressions_in_one_group_mask_each_other
        """
        scenario = fx.frozen_cycle(api, record_count=45, checksum="c1d2e3f4a5b60135")
        request = fx.intake_request(
            api,
            scenario,
            requester_org=POLICY_INSTITUTE,
            requester_type=K.REQUESTER_EXTERNAL,
            requested_metric_key="HEADCOUNT_BY_RACE",
        )
        fx.add_cells(
            api, scenario, "RACE_ETHNICITY", (("ASIAN", 2), ("BLACK", 3), ("WHITE", 40))
        )

        screened = validate_success(api.screen_data_request(request["id"], disclosure))
        assert_request_counters(
            screened,
            cell_count=3,
            released_cell_count=1,
            suppressed_cell_count=2,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )

        cells = _cells_by_key(api, request["id"], disclosure)
        assert_cell(
            cells["ASIAN"], suppression_state=K.CELL_PRIMARY_SUPPRESSED, released_count=None
        )
        assert_cell(
            cells["BLACK"], suppression_state=K.CELL_PRIMARY_SUPPRESSED, released_count=None
        )
        assert_cell(cells["WHITE"], suppression_state=K.CELL_RELEASED, released_count=40)

        _rows, meta = validate_paginated(
            api.list_disclosure_cells(
                disclosure,
                request_id=request["id"],
                suppression_state=K.CELL_COMPLEMENTARY_SUPPRESSED,
            )
        )
        assert meta["total_count"] == 0

        released = validate_success(
            api.release_data_request(
                request["id"], disclosure, f.make_release_payload(TWO_SUPPRESSED_NOTE)
            )
        )
        assert_request_counters(released, released_cell_count=1, status=K.REQUEST_RELEASED)


class TestALonePrimaryWithNoCandidateStaysRecoverable:
    """A structural zero is released but can never be spent as a complementary victim."""

    def test_the_unmaskable_group_raises_residual_risk_and_blocks_the_external_release(
        self, api, disclosure
    ):
        """A cell in another dimension_group is never a candidate for this group's primary.

        PRD 3.9: "Within a group, the primaries are the cells the first pass suppressed, and the
        candidates are the cells the first pass released whose `raw_count` is strictly greater than
        0 — a structural zero is never a complementary candidate, because suppressing it would
        protect nothing."

        PRD 3.9: "If the group has no candidate at all, no second suppression is possible, and the
        request's `residual_disclosure_risk` is set to true to record that the release remains
        re-identifiable."

        PRD 3.9: "Both branches also carry one shared safety gate: a request whose
        `residual_disclosure_risk` is true may not be released at all when its `requester_type` is
        `EXTERNAL` or `MEDIA`, because the lone primary-suppressed cell that had no complementary
        candidate is recoverable by subtraction, and such an attempt is refused with
        `ERR_SMALL_CELL_DISCLOSURE`."

        Design: Corner/calculations/corner_calc_lone_primary_with_no_positive_candidate_flags_residual_risk
        """
        scenario = fx.frozen_cycle(api, record_count=33, checksum="c1d2e3f4a5b60136")
        request = fx.intake_request(
            api,
            scenario,
            requester_org=POLICY_INSTITUTE,
            requester_type=K.REQUESTER_EXTERNAL,
            requested_metric_key="HEADCOUNT_BY_RACE",
            avoidance_method=K.AVOIDANCE_SMALL_CELL_SUPPRESSION,
            min_cell_size=K.DEFAULT_MIN_CELL_SIZE,
        )
        fx.add_cells(api, scenario, "RACE_ETHNICITY", (("ASIAN", 3), ("TWO_OR_MORE", 0)))
        fx.add_cells(api, scenario, "GENDER", (("FEMALE", 30),))

        screened = validate_success(api.screen_data_request(request["id"], disclosure))
        assert_request_counters(
            screened,
            cell_count=3,
            released_cell_count=2,
            suppressed_cell_count=1,
            residual_disclosure_risk=True,
            status=K.REQUEST_SCREENED,
        )

        cells = _cells_by_key(api, request["id"], disclosure)
        assert_cell(
            cells["ASIAN"], suppression_state=K.CELL_PRIMARY_SUPPRESSED, released_count=None
        )
        assert_cell(cells["TWO_OR_MORE"], suppression_state=K.CELL_RELEASED, released_count=0)
        assert_cell(cells["FEMALE"], suppression_state=K.CELL_RELEASED, released_count=30)

        refused = api.release_data_request(
            request["id"], disclosure, f.make_release_payload(UNMASKED_NOTE)
        )
        validate_error(refused, ApiErrorId.SMALL_CELL_DISCLOSURE, 422)

        unchanged = validate_success(api.get_data_request(request["id"], disclosure))
        assert_request_counters(
            unchanged, status=K.REQUEST_SCREENED, residual_disclosure_risk=True
        )
        assert_null(unchanged["release_note"], "data_request.release_note")


class TestTheSameCrosstabUnderBothAvoidanceMethods:
    """One set of raw counts, two methods, two entirely different published answers."""

    @staticmethod
    def _twin_requests(api, disclosure, dimension_group, counts, checksum):
        """Two requests over identical cells: one suppressing, one rounding."""
        scenario = fx.frozen_cycle(
            api,
            record_count=12000,
            metrics=HEADCOUNT_METRICS_12000,
            checksum=checksum,
        )
        suppression = _open_request(
            api,
            scenario,
            disclosure,
            PRESS_BUREAU,
            K.REQUESTER_MEDIA,
            avoidance_method=K.AVOIDANCE_SMALL_CELL_SUPPRESSION,
            min_cell_size=K.DEFAULT_MIN_CELL_SIZE,
        )
        rounding = _open_request(
            api,
            scenario,
            disclosure,
            RESEARCH_CONSORTIUM,
            K.REQUESTER_INTERNAL,
            avoidance_method=K.AVOIDANCE_CONTROLLED_ROUNDING,
            min_cell_size=K.DEFAULT_MIN_CELL_SIZE,
        )
        for request in (suppression, rounding):
            fx.add_cells(api, scenario, dimension_group, counts, request=request)
        return suppression, rounding

    def test_the_race_crosstab_loses_two_cells_to_suppression_and_none_to_rounding(
        self, api, disclosure
    ):
        """The rounding request publishes the very cell the suppression request had to hide.

        PRD 3.9: "If the group has at least one candidate, the victim is the candidate with the
        smallest `raw_count`, with ties broken by `dimension_key` ascending; its
        `suppression_state` becomes `COMPLEMENTARY_SUPPRESSED` and its `released_count` is set to
        null."

        PRD 3.9: "A raw count of 3 is released as 5, 12 as 10, 20 as 20, 45 as 45, and 0 as 0."

        Design: Difficulty/dual_variant_calc/disclosure_small_cell_suppression_vs_controlled_rounding_variants
        """
        suppression, rounding = self._twin_requests(
            api, disclosure, "RACE_ETHNICITY", RACE_CROSSTAB, "a1b2c3d4e5f60002"
        )

        suppressed = validate_success(api.screen_data_request(suppression["id"], disclosure))
        assert_request_counters(
            suppressed,
            cell_count=5,
            released_cell_count=3,
            suppressed_cell_count=2,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )
        withheld = _cells_by_key(api, suppression["id"], disclosure)
        assert_cell(
            withheld["ASIAN"], suppression_state=K.CELL_PRIMARY_SUPPRESSED, released_count=None
        )
        assert_cell(
            withheld["BLACK"],
            suppression_state=K.CELL_COMPLEMENTARY_SUPPRESSED,
            released_count=None,
        )
        assert_cell(withheld["HISPANIC"], suppression_state=K.CELL_RELEASED, released_count=20)
        assert_cell(withheld["WHITE"], suppression_state=K.CELL_RELEASED, released_count=45)
        assert_cell(withheld["TWO_OR_MORE"], suppression_state=K.CELL_RELEASED, released_count=0)

        perturbed = validate_success(api.screen_data_request(rounding["id"], disclosure))
        assert_request_counters(
            perturbed,
            cell_count=5,
            released_cell_count=5,
            suppressed_cell_count=0,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )
        rounded = _cells_by_key(api, rounding["id"], disclosure)
        for key, released in (
            ("ASIAN", 5),
            ("BLACK", 10),
            ("HISPANIC", 20),
            ("WHITE", 45),
            ("TWO_OR_MORE", 0),
        ):
            assert_cell(rounded[key], suppression_state=K.CELL_RELEASED, released_count=released)
            assert_controlled_rounding(rounded[key])

    def test_a_small_cell_is_withheld_by_one_method_and_published_as_zero_by_the_other(
        self, api, disclosure
    ):
        """Rounding a raw 2 down to 0 publishes a category that suppression removed entirely.

        PRD 3.9: "A cell whose `raw_count` is strictly greater than 0 **and** strictly less than
        `min_cell_size` is a small cell: its `suppression_state` becomes `PRIMARY_SUPPRESSED` and
        its `released_count` is set to null."

        PRD 3.9: "Every cell of the request becomes `RELEASED`, and its `released_count` is its
        `raw_count` divided by 5, rounded half up to a whole number, multiplied by 5."

        Design: Difficulty/dual_variant_calc/disclosure_small_cell_suppression_vs_controlled_rounding_variants
        """
        suppression, rounding = self._twin_requests(
            api, disclosure, "AGE_BAND", AGE_CROSSTAB, "a1b2c3d4e5f60003"
        )

        suppressed = validate_success(api.screen_data_request(suppression["id"], disclosure))
        assert_request_counters(
            suppressed,
            cell_count=3,
            released_cell_count=1,
            suppressed_cell_count=2,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )
        withheld = _cells_by_key(api, suppression["id"], disclosure)
        assert_cell(
            withheld["A_18_19"],
            suppression_state=K.CELL_PRIMARY_SUPPRESSED,
            released_count=None,
            raw_count=2,
        )
        assert_cell(
            withheld["B_20_21"],
            suppression_state=K.CELL_COMPLEMENTARY_SUPPRESSED,
            released_count=None,
        )
        assert_cell(withheld["C_22_24"], suppression_state=K.CELL_RELEASED, released_count=20)

        perturbed = validate_success(api.screen_data_request(rounding["id"], disclosure))
        assert_request_counters(
            perturbed,
            cell_count=3,
            released_cell_count=3,
            suppressed_cell_count=0,
            residual_disclosure_risk=False,
            status=K.REQUEST_SCREENED,
        )
        rounded = _cells_by_key(api, rounding["id"], disclosure)
        assert_cell(
            rounded["A_18_19"], suppression_state=K.CELL_RELEASED, released_count=0, raw_count=2
        )
        assert_cell(rounded["B_20_21"], suppression_state=K.CELL_RELEASED, released_count=10)
        assert_cell(rounded["C_22_24"], suppression_state=K.CELL_RELEASED, released_count=20)
        for cell in rounded.values():
            assert_controlled_rounding(cell)
