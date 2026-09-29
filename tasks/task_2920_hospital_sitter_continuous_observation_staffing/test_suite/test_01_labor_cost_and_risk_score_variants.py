"""
The two dual-variant calculations of the observation contract: a watch's labor
cost read provisionally versus finally, and an order's elopement risk score read
at the admission baseline versus under the rolling event-weighted variant.
"""

from test_helpers import (
    HTTP_CREATED,
    ObservationApiClient,
    get_success_data,
    instant,
    validate_success,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_row_count,
    final_segment_rows,
    posted_total,
    provisional_row,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPLETION_SHIFT_END_NO_SUCCESSOR,
    COMPETENCY_ADVANCED,
    COST_POSTED,
    COST_REVERSED,
    DOC_WAIVED,
    ENTRY_KIND_FINAL_SEGMENT,
    ENTRY_KIND_PROVISIONAL,
    EVENT_CLOSED,
    KIND_ELOPEMENT_ATTEMPT,
    MODALITY_ONE_TO_ONE_SITTER,
    MODALITY_VIDEO_MONITORING,
    ORDER_ACTIVE,
    POOL_INTERNAL_FLOAT,
    RESOLUTION_CONTINUE_OBSERVATION,
    RISK_ELOPEMENT,
    RISK_FALL,
    VARIANT_ADMISSION_BASELINE,
    VARIANT_ROLLING_EVENT_WEIGHTED,
    WATCH_COMPLETED,
)
from test_helpers.factories import (
    close_event_payload,
    completion_payload,
    escalate_response_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    assignment_cost_entries,
    make_patient,
    make_safety_event,
    make_staff,
    make_unit,
    make_order,
    make_assignment,
    read_order,
    read_unit,
    start_watch_at,
    unit_cost_entries,
)
from test_helpers.test_users import (
    OFFICER_1,
    OFFICER_2,
    PROVIDER_1,
    make_sitter_headers,
)


def _unit_a_watch(api: ObservationApiClient) -> dict:
    """
    UNIT-A: a 100000-cent budget, one FALL order on a 60-year-old, and one
    INTERNAL_FLOAT sitter at 3000 cents/hour scheduled 08:00Z -> 12:00Z.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-A",
        name="Medical Telemetry A",
        budget_cents=100000,
        video_monitoring_enabled=False,
    )
    patient = make_patient(api, unit["id"], mrn="MRN-1001", full_name="Pat One", age_years=60)
    staff = make_staff(
        api,
        unit["id"],
        full_name="Sitter One",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=3000,
        competency_level=COMPETENCY_ADVANCED,
        deescalation_cert_expires_on="2027-01-01T00:00:00Z",
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Unsteady gait, high fall risk",
    )
    assignment = make_assignment(
        api,
        order["id"],
        staff["id"],
        "2026-08-01T08:00:00Z",
        "2026-08-01T12:00:00Z",
        expected_order_version=order["version"],
    )
    return {
        "unit": unit,
        "patient": patient,
        "staff": staff,
        "order": order,
        "assignment": assignment,
    }


def _run_the_split_watch(api: ObservationApiClient, world: dict) -> None:
    """
    Work the watch 08:00->10:30, break 10:30->10:50, then 10:50->12:00 — a
    150-minute segment and a 70-minute segment with a 20-minute unbilled break.
    """
    sitter = make_sitter_headers(world["staff"]["id"])
    start_watch_at(api, world["assignment"]["id"], world["staff"]["id"], "2026-08-01T08:00:00Z")
    advance_clock(api, "2026-08-01T10:30:00Z")
    get_success_data(api.break_start(world["assignment"]["id"], sitter))
    advance_clock(api, "2026-08-01T10:50:00Z")
    get_success_data(api.break_end(world["assignment"]["id"], sitter))
    advance_clock(api, "2026-08-01T12:00:00Z")


class TestProvisionalVersusFinalLaborCost:
    """One watch, two labor-cost readings that deliberately disagree."""

    def test_provisional_variant_bills_the_whole_scheduled_window_in_one_rounding(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.4: "The result is rounded half up to whole cents **once**, over the
        whole window, and stored as `provisional_cost_cents`."

        3000 cents/hour over the 240 scheduled minutes at the INTERNAL_FLOAT
        multiplier of 1.00 is 12000 cents, posted as the assignment's PROVISIONAL
        ledger row before a single watch minute has been worked.

        Design: Difficulty/dual_variant_calc/assignment_labor_cost_provisional_vs_final_diverge_on_one_watch
        """
        world = _unit_a_watch(api)
        assignment = world["assignment"]

        assert_fields(
            assignment,
            label="assignment",
            scheduled_minutes=240,
            provisional_cost_cents=12000,
            final_cost_cents=None,
            watch_segment_count=0,
            watched_minutes=0,
        )

        rows = assignment_cost_entries(api, assignment["id"])
        assert_row_count(rows, 1, "ledger rows before the watch runs")
        assert_fields(
            rows[0],
            label="provisional row",
            entry_kind=ENTRY_KIND_PROVISIONAL,
            amount_cents=12000,
            status=COST_POSTED,
            night_differential_applied=False,
            segment_index=None,
            segment_minutes=None,
            source_pool=POOL_INTERNAL_FLOAT,
        )
        assert read_unit(api, world["unit"]["id"])["observed_cost_to_date_cents"] == 12000

    def test_final_variant_bills_only_realised_segment_minutes(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.5: "The assignment's `final_cost_cents` is then the **sum of the
        already-rounded per-segment amounts**."

        The same watch works 150 then 70 minutes around a 20-minute break, so the
        final figure is 7500 + 3500 = 11000 cents against a 12000-cent provisional:
        the two variants diverge on identical scheduling data because "break
        minutes are never billed".

        Design: Difficulty/dual_variant_calc/assignment_labor_cost_provisional_vs_final_diverge_on_one_watch
        """
        world = _unit_a_watch(api)
        _run_the_split_watch(api, world)

        response = api.complete_watch(
            world["assignment"]["id"],
            completion_payload(COMPLETION_SHIFT_END_NO_SUCCESSOR),
            make_sitter_headers(world["staff"]["id"]),
        )
        assignment = validate_success(response, 200)

        assert_fields(
            assignment,
            label="assignment",
            provisional_cost_cents=12000,
            final_cost_cents=11000,
            watch_segment_count=2,
            watched_minutes=220,
            watch_status=WATCH_COMPLETED,
            documentation_status=DOC_WAIVED,
        )

        rows = assignment_cost_entries(api, world["assignment"]["id"])
        assert_row_count(rows, 3, "ledger rows after completion")
        assert_fields(
            provisional_row(rows),
            label="provisional row",
            amount_cents=12000,
            status=COST_REVERSED,
        )
        segments = final_segment_rows(rows)
        assert_row_count(segments, 2, "FINAL_SEGMENT rows")
        assert_fields(
            segments[0],
            label="segment 1",
            entry_kind=ENTRY_KIND_FINAL_SEGMENT,
            segment_index=1,
            segment_minutes=150,
            amount_cents=7500,
            status=COST_POSTED,
            night_differential_applied=False,
        )
        assert_fields(
            segments[1],
            label="segment 2",
            entry_kind=ENTRY_KIND_FINAL_SEGMENT,
            segment_index=2,
            segment_minutes=70,
            amount_cents=3500,
            status=COST_POSTED,
            night_differential_applied=False,
        )

    def test_unit_ledger_settles_on_the_final_figure_not_the_provisional_one(
        self, api: ObservationApiClient
    ):
        """
        PRD 2.10: "A unit's `observed_cost_to_date_cents` is the sum of
        `amount_cents` across every `CostEntry` whose `unit_id` is that unit and
        whose `status` is `POSTED`."

        Once the provisional row is reversed, the only POSTED rows left are the two
        segment finals, so the head recomputes to 11000 rather than staying on the
        12000 the schedule reserved.

        Design: Difficulty/dual_variant_calc/assignment_labor_cost_provisional_vs_final_diverge_on_one_watch
        """
        world = _unit_a_watch(api)
        _run_the_split_watch(api, world)
        get_success_data(
            api.complete_watch(
                world["assignment"]["id"],
                completion_payload(COMPLETION_SHIFT_END_NO_SUCCESSOR),
                make_sitter_headers(world["staff"]["id"]),
            )
        )

        unit = read_unit(api, world["unit"]["id"])
        assert_fields(unit, label="unit", observed_cost_to_date_cents=11000)

        ledger = unit_cost_entries(api, world["unit"]["id"])
        assert posted_total(ledger) == 11000, (
            "the recomputed head must equal the sum over the POSTED rows"
        )
        assert read_order(api, world["order"]["id"])["coverage_gap_flag"] is True


def _unit_b_order_with_one_attempt(api: ObservationApiClient) -> dict:
    """
    UNIT-B: video monitoring enabled, an 80-year-old patient (the age adjustment is
    inclusive at 75) and one FALL + ELOPEMENT order written at the default clock,
    with one ELOPEMENT_ATTEMPT reported and escalated under it.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-B",
        name="Geriatric Unit B",
        budget_cents=100000,
        video_monitoring_enabled=True,
    )
    patient = make_patient(api, unit["id"], mrn="MRN-2001", full_name="Pat Two", age_years=80)
    staff = make_staff(
        api,
        unit["id"],
        full_name="Sitter Two",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    created = api.create_order(
        {
            "patient_id": patient["id"],
            "ordering_provider_user_id": PROVIDER_1["X-User-ID"],
            "risk_categories": [RISK_FALL, RISK_ELOPEMENT],
            "required_modality": MODALITY_VIDEO_MONITORING,
            "clinical_rationale": "Wandering with exit-seeking behaviour",
        },
        PROVIDER_1,
    )
    order = validate_success(created, HTTP_CREATED)
    return {"unit": unit, "patient": patient, "staff": staff, "order": order}


class TestAdmissionBaselineVersusRollingEventWeightedScore:
    """The same order data scored with and without its safety-event component."""

    def test_admission_baseline_variant_consults_no_safety_event(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.2: "At order creation the event component is fixed at exactly 0.0
        points. This is the **admission-baseline** reading of the score, and the
        field `risk_score_variant` records it as `ADMISSION_BASELINE`."

        FALL 1.5 + ELOPEMENT 2.5 + the 1.0 age adjustment for an 80-year-old is
        5.0, which selects the 12-hour tier and a due instant 12 hours after the
        creation clock.

        Design: Difficulty/dual_variant_calc/elopement_risk_score_admission_baseline_vs_rolling_event_weighted
        """
        world = _unit_b_order_with_one_attempt(api)

        assert_fields(
            world["order"],
            label="order at creation",
            elopement_risk_score=5.0,
            risk_score_variant=VARIANT_ADMISSION_BASELINE,
            reassessment_interval_hours=12,
            reassessment_count=0,
            status=ORDER_ACTIVE,
        )
        assert_instant(
            world["order"]["last_reassessed_at"], CLOCK_START, "order.last_reassessed_at"
        )
        assert_instant(
            world["order"]["next_reassessment_due_at"],
            instant(CLOCK_START, hours=12),
            "order.next_reassessment_due_at",
        )

    def test_rolling_event_weighted_variant_adds_the_trailing_attempt_component(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.3: "It contributes 1.0 point for each safety event on the order whose
        `event_kind` is `ELOPEMENT_ATTEMPT` or `AGGRESSION` and whose `occurred_at`
        falls at or after the instant 24 hours before the current logical clock"

        Closing that attempt re-scores the identical order under the rolling
        variant: 5.0 + 1.0 = 6.0, which lifts the cadence to the 8-hour tier. PRD
        3.8 pins that "a close never moves `last_reassessed_at`", so the due instant
        is recomputed from the unmoved creation instant.

        Design: Difficulty/dual_variant_calc/elopement_risk_score_admission_baseline_vs_rolling_event_weighted
        """
        world = _unit_b_order_with_one_attempt(api)
        event = make_safety_event(
            api,
            world["order"]["id"],
            KIND_ELOPEMENT_ATTEMPT,
            world["staff"]["id"],
            narrative="Patient attempted to leave the unit through the stairwell door",
        )
        get_success_data(
            api.escalate_response(
                event["id"],
                escalate_response_payload(["VERBAL_REDIRECTION", "FAMILY_PRESENCE"]),
                OFFICER_1,
            )
        )

        closed = validate_success(
            api.close_safety_event(
                event["id"],
                close_event_payload(RESOLUTION_CONTINUE_OBSERVATION),
                OFFICER_2,
            ),
            200,
        )
        assert closed["status"] == EVENT_CLOSED

        order = read_order(api, world["order"]["id"])
        assert_fields(
            order,
            label="order after the close",
            elopement_risk_score=6.0,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
            reassessment_interval_hours=8,
            status=ORDER_ACTIVE,
            reassessment_count=0,
        )
        assert_instant(
            order["last_reassessed_at"], CLOCK_START, "order.last_reassessed_at"
        )
        assert_instant(
            order["next_reassessment_due_at"],
            instant(CLOCK_START, hours=8),
            "order.next_reassessment_due_at",
        )
