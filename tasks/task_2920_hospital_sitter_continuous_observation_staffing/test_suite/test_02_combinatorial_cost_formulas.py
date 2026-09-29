"""
The two combinatorial money formulas whose value depends on *where* the rounding
and the tier selection happen: per-segment rounding of realised labor, and the
coverage-surcharge tier keyed on the subtotal rather than on the charge total.
"""

from test_helpers import ObservationApiClient, get_success_data, validate_success
from test_helpers.assertions import (
    assert_fields,
    assert_row_count,
    final_segment_rows,
    posted_total,
    rows_where,
)
from test_helpers.constants import (
    COMPETENCY_ADVANCED,
    COMPETENCY_BASIC,
    COMPLETION_SHIFT_END_NO_SUCCESSOR,
    COST_POSTED,
    ENTRY_KIND_PROVISIONAL,
    MODALITY_ONE_TO_ONE_SITTER,
    POOL_AGENCY,
    POOL_INTERNAL_FLOAT,
    RISK_FALL,
    UNIT_OPEN,
)
from test_helpers.factories import completion_payload, cost_close_payload
from test_helpers.fixtures import (
    advance_clock,
    assignment_cost_entries,
    make_assignment,
    make_order,
    make_patient,
    make_staff,
    make_unit,
    read_unit,
    start_watch_at,
    unit_cost_entries,
)
from test_helpers.test_users import COORDINATOR, make_sitter_headers


def _unit_c_agency_watch(api: ObservationApiClient) -> dict:
    """
    UNIT-C: budget 200000 and OPEN, so the restricted-unit agency block never
    applies, with one AGENCY sitter at 2500 cents/hour on a 540-minute shift.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-C",
        name="Neuro Unit C",
        budget_cents=200000,
        video_monitoring_enabled=False,
    )
    patient = make_patient(api, unit["id"], mrn="MRN-3001", full_name="Pat Three", age_years=60)
    staff = make_staff(
        api,
        unit["id"],
        full_name="Agency Sitter",
        source_pool=POOL_AGENCY,
        hourly_rate_cents=2500,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Post-op delirium with fall risk",
    )
    assignment = make_assignment(
        api,
        order["id"],
        staff["id"],
        "2026-08-01T08:00:00Z",
        "2026-08-01T17:00:00Z",
        expected_order_version=order["version"],
    )
    return {"unit": unit, "staff": staff, "order": order, "assignment": assignment}


def _work_two_odd_segments(api: ObservationApiClient, world: dict) -> dict:
    """
    Work 08:00->10:08 (128 minutes) and 10:30->12:50 (140 minutes), with a
    22-minute break in between that is never billed.
    """
    sitter = make_sitter_headers(world["staff"]["id"])
    start_watch_at(api, world["assignment"]["id"], world["staff"]["id"], "2026-08-01T08:00:00Z")
    advance_clock(api, "2026-08-01T10:08:00Z")
    get_success_data(api.break_start(world["assignment"]["id"], sitter))
    advance_clock(api, "2026-08-01T10:30:00Z")
    get_success_data(api.break_end(world["assignment"]["id"], sitter))
    advance_clock(api, "2026-08-01T12:50:00Z")
    return validate_success(
        api.complete_watch(
            world["assignment"]["id"],
            completion_payload(COMPLETION_SHIFT_END_NO_SUCCESSOR),
            sitter,
        ),
        200,
    )


class TestPerSegmentRoundingOnAnAgencyWatch:
    """Rounding each segment first and summing afterwards, to the cent."""

    def test_each_segment_is_rounded_half_up_on_its_own(self, api: ObservationApiClient):
        """
        PRD 3.5: "That per-segment product is rounded half up to whole cents, and
        the rounded figure becomes that segment's `amount_cents`."

        At 2500 cents/hour and the AGENCY multiplier of 1.45, 128 minutes is
        7733.33... cents and 140 minutes is 8458.33... cents, so the two rows land
        on 7733 and 8458 while the 540-minute provisional was a single 32625-cent
        rounding.

        Design: Difficulty/combinatorial_formula/per_segment_rounding_beats_sum_then_round_on_agency_watch
        """
        world = _unit_c_agency_watch(api)
        assert_fields(
            world["assignment"],
            label="assignment",
            scheduled_minutes=540,
            provisional_cost_cents=32625,
        )

        _work_two_odd_segments(api, world)
        segments = final_segment_rows(assignment_cost_entries(api, world["assignment"]["id"]))
        assert_row_count(segments, 2, "FINAL_SEGMENT rows")
        assert_fields(
            segments[0],
            label="segment 1",
            segment_index=1,
            segment_minutes=128,
            amount_cents=7733,
            status=COST_POSTED,
            source_pool=POOL_AGENCY,
            night_differential_applied=False,
        )
        assert_fields(
            segments[1],
            label="segment 2",
            segment_index=2,
            segment_minutes=140,
            amount_cents=8458,
            status=COST_POSTED,
            source_pool=POOL_AGENCY,
            night_differential_applied=False,
        )

    def test_summing_the_rounded_segments_differs_from_rounding_the_sum(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.5: "Rounding each segment first and summing afterwards is the rule;
        summing the unrounded per-segment products and rounding once at the end is a
        different and explicitly wrong reading, and the two can differ by one or
        more cents."

        On this data the pinned reading gives 7733 + 8458 = 16191 while the rejected
        reading would give 16192, so the assignment's `final_cost_cents` and the
        unit's recomputed head both have to read 16191 exactly.

        Design: Difficulty/combinatorial_formula/per_segment_rounding_beats_sum_then_round_on_agency_watch
        """
        world = _unit_c_agency_watch(api)
        assignment = _work_two_odd_segments(api, world)

        assert_fields(
            assignment,
            label="assignment",
            final_cost_cents=16191,
            watched_minutes=268,
            watch_segment_count=2,
        )
        assert assignment["final_cost_cents"] != 16192, (
            "16192 is the sum-then-round reading the PRD explicitly rejects"
        )
        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit",
            observed_cost_to_date_cents=16191,
        )


def _unit_d_two_provisionals(api: ObservationApiClient) -> dict:
    """
    UNIT-D: two FALL orders on two patients, staffed by two INTERNAL_FLOAT sitters
    at 2900 over 720 minutes and 2320 over 600 minutes, so the ledger carries
    PROVISIONAL rows of 34800 and 23200 both posted at the default clock.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-D",
        name="Behavioral Unit D",
        budget_cents=200000,
        video_monitoring_enabled=False,
    )
    patient_four = make_patient(
        api, unit["id"], mrn="MRN-4001", full_name="Pat Four", age_years=60
    )
    patient_five = make_patient(
        api, unit["id"], mrn="MRN-4002", full_name="Pat Five", age_years=60
    )
    sitter_four = make_staff(
        api,
        unit["id"],
        full_name="Sitter Four",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2900,
        competency_level=COMPETENCY_BASIC,
    )
    sitter_five = make_staff(
        api,
        unit["id"],
        full_name="Sitter Five",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2320,
        competency_level=COMPETENCY_BASIC,
    )
    order_four = make_order(
        api,
        patient_four["id"],
        risk_categories=[RISK_FALL],
        clinical_rationale="Fall risk after syncope",
    )
    order_five = make_order(
        api,
        patient_five["id"],
        risk_categories=[RISK_FALL],
        clinical_rationale="Fall risk after hip fracture",
    )
    assignment_four = make_assignment(
        api,
        order_four["id"],
        sitter_four["id"],
        "2026-08-01T00:00:00Z",
        "2026-08-01T12:00:00Z",
        expected_order_version=order_four["version"],
    )
    assignment_five = make_assignment(
        api,
        order_five["id"],
        sitter_five["id"],
        "2026-08-02T00:00:00Z",
        "2026-08-02T10:00:00Z",
        expected_order_version=order_five["version"],
    )
    return {
        "unit": unit,
        "assignment_four": assignment_four,
        "assignment_five": assignment_five,
    }


class TestCoverageSurchargeTierKeyedOnTheSubtotal:
    """The pinned evaluation order that breaks the tier's apparent circularity."""

    def test_tier_is_selected_from_the_subtotal_alone(self, api: ObservationApiClient):
        """
        PRD 3.9: "Step two selects `coverage_surcharge_pct` from a tier keyed on
        `subtotal_cents` **alone**, over inclusive thresholds"

        34800 + 23200 is a subtotal of 58000, which sits in the 20000-or-more tier
        at 0.04 and yields a 2320-cent surcharge and a 60320-cent total. Keying the
        tier on the resulting total would reach the 60000 threshold and return 62640,
        which is the circular reading the PRD rejects.

        Design: Difficulty/combinatorial_formula/cost_close_surcharge_tier_keyed_on_subtotal_not_on_total
        """
        world = _unit_d_two_provisionals(api)
        assert_fields(
            world["assignment_four"], label="a4", provisional_cost_cents=34800
        )
        assert_fields(
            world["assignment_five"], label="a5", provisional_cost_cents=23200
        )
        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit",
            observed_cost_to_date_cents=58000,
        )

        result = validate_success(
            api.cost_close(
                world["unit"]["id"],
                cost_close_payload("2026-08-03T00:00:00Z"),
                COORDINATOR,
            ),
            200,
        )
        assert_fields(
            result,
            label="cost close",
            subtotal_cents=58000,
            coverage_surcharge_pct=0.04,
            coverage_surcharge_cents=2320,
            charge_total_cents=60320,
            unit_status=UNIT_OPEN,
        )
        assert result["charge_total_cents"] != 62640, (
            "62640 is the tier-keyed-on-the-total reading the PRD rejects"
        )

    def test_cost_close_leaves_the_ledger_completely_untouched(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.9: "No ledger row is created, mutated or reversed by a cost close under
        any circumstances, and the unit's `version` advances by 1."

        After pricing a period that includes both provisionals, the unit still holds
        exactly the two POSTED rows it held before, and none of the four charge
        figures is persisted on the unit.

        Design: Difficulty/combinatorial_formula/cost_close_surcharge_tier_keyed_on_subtotal_not_on_total
        """
        world = _unit_d_two_provisionals(api)
        before = unit_cost_entries(api, world["unit"]["id"])
        assert_row_count(before, 2, "ledger rows before the close")

        get_success_data(
            api.cost_close(
                world["unit"]["id"],
                cost_close_payload("2026-08-03T00:00:00Z"),
                COORDINATOR,
            )
        )

        after = unit_cost_entries(api, world["unit"]["id"])
        assert_row_count(after, 2, "ledger rows after the close")
        assert_row_count(
            rows_where(after, status=COST_POSTED), 2, "POSTED rows after the close"
        )
        assert_row_count(
            rows_where(after, entry_kind=ENTRY_KIND_PROVISIONAL),
            2,
            "PROVISIONAL rows after the close",
        )
        assert posted_total(after) == 58000
        assert sorted(row["amount_cents"] for row in after) == [23200, 34800]

        unit = read_unit(api, world["unit"]["id"])
        assert_fields(unit, label="unit", observed_cost_to_date_cents=58000, status=UNIT_OPEN)
        for figure in (
            "subtotal_cents",
            "coverage_surcharge_pct",
            "coverage_surcharge_cents",
            "charge_total_cents",
        ):
            assert figure not in unit, (
                f"{figure} must not be persisted on the unit; got {unit.get(figure)!r}"
            )
