"""
Calculation breadth: the reassessment tier boundaries, the cost-close waterfall's
input filters, the night-differential edge, half-up rounding on a half cent, and
the inclusive edge of the rolling event window.
"""

from test_helpers import (
    HTTP_CREATED,
    ObservationApiClient,
    validate_success,
)
from test_helpers.assertions import (
    assert_fields,
    assert_row_count,
    final_segment_rows,
    provisional_row,
    rows_where,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPLETION_SHIFT_END_NO_SUCCESSOR,
    COST_POSTED,
    COST_REVERSED,
    DOC_WAIVED,
    ENTRY_KIND_FINAL_SEGMENT,
    ENTRY_KIND_PROVISIONAL,
    EVENT_CLOSED,
    KIND_ELOPEMENT_ATTEMPT,
    ORDER_ACTIVE,
    ORDER_REASSESSMENT_DUE,
    POOL_AGENCY,
    RESOLUTION_CONTINUE_OBSERVATION,
    RISK_ELOPEMENT,
    RISK_FALL,
    RISK_SELF_HARM,
    STAFF_AVAILABLE,
    UNIT_OPEN,
    VARIANT_ADMISSION_BASELINE,
    VARIANT_ROLLING_EVENT_WEIGHTED,
    WATCH_COMPLETED,
)
from test_helpers.factories import (
    completion_payload,
    cost_close_payload,
    reassessment_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    assignment_cost_entries,
    close_event_on_order,
    make_assignment,
    make_order,
    make_patient,
    make_staff,
    make_unit,
    read_assignment,
    read_event,
    read_order,
    read_staff,
    read_unit,
    scheduled_watch,
    start_watch_at,
    unit_cost_entries,
    unit_head,
    unit_patient_order,
)
from test_helpers.test_users import (
    COORDINATOR,
    MANAGER,
    OFFICER_1,
    OFFICER_2,
    PROVIDER_1,
    make_sitter_headers,
)


class TestReassessmentCadenceTiers:
    """All four cadence tiers, two of them landing exactly on a boundary."""

    def test_four_orders_land_on_the_four_declared_interval_tiers(
        self, api: ObservationApiClient
    ) -> None:
        """
        Scores of exactly 8.0, 7.0, exactly 3.0 and 2.5 select the 4-, 8-, 12- and
        24-hour cadences respectively. The two exact hits pin both comparisons as
        inclusive, and each order's due instant is its creation instant advanced by its
        own interval.

        PRD 3.2: "The second derived figure is `reassessment_interval_hours`, which
        converts the score into a mandated reassessment cadence over four tiers, each
        boundary inclusive: a score of 8.0 or higher demands reassessment every 4 hours; a
        score below 8.0 but 6.0 or higher demands every 8 hours; a score below 6.0 but 3.0
        or higher demands every 12 hours; and anything below 3.0 falls to the default of
        every 24 hours."
        PRD 3.2: "Order creation stamps `last_reassessed_at` with the current logical clock
        and sets `next_reassessment_due_at` to that instant advanced by
        `reassessment_interval_hours` hours."

        Design: Corner/calculations/reassessment_interval_tiers_at_every_declared_boundary
        """
        unit = make_unit(api, unit_code="UNIT-C20", budget_cents=250000)
        elderly = make_patient(
            api, unit["id"], mrn="MRN-C2001", full_name="Tier Patient Four", age_years=76
        )
        seven = make_patient(
            api, unit["id"], mrn="MRN-C2002", full_name="Tier Patient Eight", age_years=60
        )
        three = make_patient(
            api, unit["id"], mrn="MRN-C2003", full_name="Tier Patient Twelve", age_years=60
        )
        low = make_patient(
            api,
            unit["id"],
            mrn="MRN-C2004",
            full_name="Tier Patient Twentyfour",
            age_years=60,
        )

        all_three = [RISK_FALL, RISK_ELOPEMENT, RISK_SELF_HARM]
        order_four = make_order(api, elderly["id"], risk_categories=all_three)
        order_eight = make_order(api, seven["id"], risk_categories=all_three)
        order_twelve = make_order(api, three["id"], risk_categories=[RISK_SELF_HARM])
        order_twentyfour = make_order(api, low["id"], risk_categories=[RISK_ELOPEMENT])

        expected = [
            (order_four, 8.0, 4, "2026-08-01T04:00:00.000Z"),
            (order_eight, 7.0, 8, "2026-08-01T08:00:00.000Z"),
            (order_twelve, 3.0, 12, "2026-08-01T12:00:00.000Z"),
            (order_twentyfour, 2.5, 24, "2026-08-02T00:00:00.000Z"),
        ]
        for order, score, interval, due_at in expected:
            assert_fields(
                read_order(api, order["id"]),
                label=f"order scoring {score}",
                elopement_risk_score=score,
                reassessment_interval_hours=interval,
                next_reassessment_due_at=due_at,
                last_reassessed_at=CLOCK_START,
                risk_score_variant=VARIANT_ADMISSION_BASELINE,
                status=ORDER_ACTIVE,
                reassessment_count=0,
            )


class TestCostCloseWaterfall:
    """The charge is priced from a filtered slice of the ledger, not from the head."""

    def test_the_subtotal_drops_reversed_rows_and_rows_posted_on_the_bound(
        self, api: ObservationApiClient
    ) -> None:
        """
        Four PROVISIONAL rows sit on one unit: 19200 and 8000 posted at the startup clock
        with the second reversed by a void, 9600 posted an hour later, and 12000 posted at
        exactly the close bound. Only 19200 and 9600 survive both filters, so the subtotal
        is 28800, which alone selects the 0.04 tier and yields a 1152 surcharge and a 29952
        total. The live ledger head remains 40800, deliberately different from the subtotal,
        and no ledger row is touched.

        PRD 3.9: "Step one computes `subtotal_cents` as the exact integer sum of
        `amount_cents` over the unit's ledger rows whose `status` is `POSTED` and whose
        `posted_at` falls strictly before `close_through_utc`; the bound is strict, so a row
        posted at exactly `close_through_utc` is excluded, and rows in `status` `REVERSED`
        are excluded entirely — which is why a voided watch leaves no trace whatsoever in
        the charge."
        PRD 3.9: "Step two selects `coverage_surcharge_pct` from a tier keyed on
        `subtotal_cents` **alone**, over inclusive thresholds: a subtotal of 150000 cents or
        more takes 0.12, a subtotal below that but 60000 cents or more takes 0.08, a
        subtotal below that but 20000 cents or more takes 0.04, and anything below 20000
        cents takes 0.00."
        PRD 3.9: "The response returns `subtotal_cents`, `coverage_surcharge_pct`,
        `coverage_surcharge_cents` and `charge_total_cents`, together with the unit's
        resulting posture as `unit_status` and its resulting `version` as `unit_version`."
        PRD 3.9: "No ledger row is created, mutated or reversed by a cost close under any
        circumstances, and the unit's `version` advances by 1."

        Design: Corner/calculations/cost_close_subtotal_excludes_reversed_and_boundary_entries
        """
        unit = make_unit(api, unit_code="UNIT-C21", budget_cents=500000)
        rates = [2400, 1000, 1200, 1500]
        assignments = []
        for index, rate in enumerate(rates, start=1):
            patient = make_patient(
                api,
                unit["id"],
                mrn=f"MRN-C210{index}",
                full_name=f"Ledger Patient {index}",
            )
            staff = make_staff(
                api,
                unit["id"],
                full_name=f"Ledger Sitter {index}",
                hourly_rate_cents=rate,
            )
            order = make_order(api, patient["id"], risk_categories=[RISK_FALL])
            if index == 3:
                advance_clock(api, "2026-08-01T01:00:00Z")
            if index == 4:
                advance_clock(api, "2026-08-01T02:00:00Z")
            assignment = make_assignment(
                api,
                order["id"],
                staff["id"],
                "2026-08-01T08:00:00Z",
                "2026-08-01T16:00:00Z",
            )
            assignments.append(assignment)
            if index == 2:
                validate_success(api.void_assignment(assignment["id"], MANAGER))

        close = validate_success(
            api.cost_close(
                unit["id"], cost_close_payload("2026-08-01T02:00:00Z"), COORDINATOR
            )
        )

        assert_fields(
            close,
            label="cost close",
            subtotal_cents=28800,
            coverage_surcharge_cents=1152,
            charge_total_cents=29952,
            unit_status=UNIT_OPEN,
        )
        assert abs(float(close["coverage_surcharge_pct"]) - 0.04) < 1e-9, close
        after = read_unit(api, unit["id"])
        assert close["unit_version"] == after["version"], (close, after["version"])
        assert after["observed_cost_to_date_cents"] == 40800, after

        rows = unit_cost_entries(api, unit["id"])
        assert_row_count(rows, 4, "unit cost entries")
        expected_rows = [
            (assignments[0]["id"], 19200, COST_POSTED, CLOCK_START),
            (assignments[1]["id"], 8000, COST_REVERSED, CLOCK_START),
            (assignments[2]["id"], 9600, COST_POSTED, "2026-08-01T01:00:00.000Z"),
            (assignments[3]["id"], 12000, COST_POSTED, "2026-08-01T02:00:00.000Z"),
        ]
        for assignment_id, amount, status, posted_at in expected_rows:
            matches = rows_where(rows, assignment_id=assignment_id)
            assert_row_count(matches, 1, f"ledger rows for assignment {assignment_id}")
            assert_fields(
                matches[0],
                label=f"ledger row of {amount}",
                entry_kind=ENTRY_KIND_PROVISIONAL,
                amount_cents=amount,
                status=status,
                posted_at=posted_at,
            )


class TestFinalSegmentCosting:
    """The night differential edge and half-up rounding of a per-segment product."""

    def test_a_segment_starting_exactly_at_twenty_three_hundred_is_a_night_segment(
        self, api: ObservationApiClient
    ) -> None:
        """
        A watch scheduled 23:00Z to 07:00Z bills 16000 provisionally with no differential
        at all. The single realised segment starts at exactly 23:00Z, which is the
        inclusive edge of the night band, so its 120 minutes bill 2000 * 2 * 1.15 == 4600
        and the row records that the differential was applied.

        PRD 3.5: "A segment qualifies as a night segment purely by the UTC hour-of-day of
        the instant it *started*: the segment is a night segment when that hour is 23 or
        later, or earlier than 7 — in other words, segments beginning anywhere from 23:00
        through 06:59 UTC."
        PRD 3.4: "No night differential is applied in this variant and no break time is
        deducted from it."
        PRD 3.5: "The `night_differential_applied` flag on each ledger row records whether
        that row was multiplied by the differential."

        Design: Corner/calculations/night_differential_applies_to_a_segment_starting_exactly_at_23_00
        """
        world = scheduled_watch(
            api,
            unit_code="UNIT-C22",
            mrn="MRN-C2201",
            budget_cents=250000,
            risk_categories=[RISK_FALL],
            shift_start_at="2026-08-01T23:00:00Z",
            shift_end_at="2026-08-02T07:00:00Z",
            staff_name="Night Sitter",
        )
        assert read_assignment(api, world["assignment"]["id"])[
            "provisional_cost_cents"
        ] == 16000
        start_watch_at(
            api,
            world["assignment"]["id"],
            world["staff"]["id"],
            "2026-08-01T23:00:00Z",
        )
        swept = advance_clock(api, "2026-08-02T01:00:00Z")
        assert swept["orders_marked_reassessment_due"] == 1, swept

        validate_success(
            api.complete_watch(
                world["assignment"]["id"],
                completion_payload(COMPLETION_SHIFT_END_NO_SUCCESSOR),
                make_sitter_headers(world["staff"]["id"]),
            )
        )

        rows = assignment_cost_entries(api, world["assignment"]["id"])
        assert_row_count(rows, 2, "assignment cost entries")
        assert_fields(
            provisional_row(rows),
            label="provisional row",
            amount_cents=16000,
            status=COST_REVERSED,
            reversed_at="2026-08-02T01:00:00.000Z",
            night_differential_applied=False,
        )
        finals = final_segment_rows(rows)
        assert_row_count(finals, 1, "posted final segment rows")
        assert_fields(
            finals[0],
            label="final segment row",
            entry_kind=ENTRY_KIND_FINAL_SEGMENT,
            amount_cents=4600,
            status=COST_POSTED,
            segment_index=1,
            segment_minutes=120,
            night_differential_applied=True,
        )
        assert_fields(
            read_assignment(api, world["assignment"]["id"]),
            label="assignment",
            watch_status=WATCH_COMPLETED,
            completion_reason=COMPLETION_SHIFT_END_NO_SUCCESSOR,
            documentation_status=DOC_WAIVED,
            final_cost_cents=4600,
            watch_segment_count=1,
            watched_minutes=120,
        )
        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit",
            observed_cost_to_date_cents=4600,
            status=UNIT_OPEN,
        )
        assert read_order(api, world["order"]["id"])["coverage_gap_flag"] is True
        assert_fields(
            read_staff(api, world["staff"]["id"]),
            label="sitter",
            status=STAFF_AVAILABLE,
            total_watch_minutes=120,
        )

    def test_an_agency_segment_landing_on_a_half_cent_rounds_half_up(
        self, api: ObservationApiClient
    ) -> None:
        """
        Six realised minutes at 2500 cents an hour on the agency multiplier come to
        2500 * (6/60) * 1.45 == 362.5 exactly. Rounding half up gives 363, and the unit's
        ledger head makes the difference from a truncating or banker's reading visible.

        PRD 3.5: "For a segment, the whole minutes it lasted are divided by 60 and
        multiplied by the observer's `hourly_rate_cents`, then by the pool multiplier (1.00
        for `INTERNAL_FLOAT`, 1.45 for `AGENCY`, 0.00 for `VOLUNTEER`), then by the night
        differential of 1.15 when that segment qualifies as a night segment and by 1.00 when
        it does not."
        PRD 3.5: "That per-segment product is rounded half up to whole cents, and the
        rounded figure becomes that segment's `amount_cents`."
        PRD 2.7: "Wherever a labor computation produces a fractional cent, the result is
        rounded half up to a whole cent — that is, a value whose fractional part is exactly
        one half rounds away from zero to the next whole cent."

        Design: Corner/calculations/agency_segment_cost_rounds_half_up_on_a_half_cent
        """
        world = scheduled_watch(
            api,
            unit_code="UNIT-C23",
            mrn="MRN-C2301",
            budget_cents=250000,
            risk_categories=[RISK_FALL],
            hourly_rate_cents=2500,
            source_pool=POOL_AGENCY,
            staff_name="Agency Sitter",
        )
        start_watch_at(
            api,
            world["assignment"]["id"],
            world["staff"]["id"],
            "2026-08-01T08:00:00Z",
        )
        advance_clock(api, "2026-08-01T08:06:00Z")

        validate_success(
            api.complete_watch(
                world["assignment"]["id"],
                completion_payload(COMPLETION_SHIFT_END_NO_SUCCESSOR),
                make_sitter_headers(world["staff"]["id"]),
            )
        )

        rows = assignment_cost_entries(api, world["assignment"]["id"])
        finals = final_segment_rows(rows)
        assert_row_count(finals, 1, "posted final segment rows")
        assert_fields(
            finals[0],
            label="final segment row",
            amount_cents=363,
            status=COST_POSTED,
            segment_index=1,
            segment_minutes=6,
            night_differential_applied=False,
            source_pool=POOL_AGENCY,
        )
        assert_fields(
            provisional_row(rows),
            label="provisional row",
            amount_cents=29000,
            status=COST_REVERSED,
        )
        assert_fields(
            read_assignment(api, world["assignment"]["id"]),
            label="assignment",
            provisional_cost_cents=29000,
            final_cost_cents=363,
            watched_minutes=6,
        )
        assert unit_head(api, world["unit"]["id"]) == 363
        assert read_staff(api, world["staff"]["id"])["total_watch_minutes"] == 6


class TestRollingEventWindowEdge:
    """The windowed component of the rolling score at and just past 24 hours."""

    def test_an_attempt_exactly_twenty_four_hours_old_still_counts_but_a_second_later_does_not(
        self, api: ObservationApiClient
    ) -> None:
        """
        One ELOPEMENT_ATTEMPT occurred at the startup clock on a FALL-only order, so the
        rolling reading is 1.5 plus 1.0 for the attempt. Reassessed at exactly 24 hours
        later the attempt is still inside the inclusive window and the score holds at 2.5;
        one second later the same event has fallen out and the score drops to 1.5, with no
        other input having changed and the event itself untouched.

        PRD 3.3: "It contributes 1.0 point for each safety event on the order whose
        `event_kind` is `ELOPEMENT_ATTEMPT` or `AGGRESSION` and whose `occurred_at` falls at
        or after the instant 24 hours before the current logical clock — the boundary is
        inclusive, so an attempt exactly 24 hours old still counts — plus 2.0 points for
        each safety event on the order whose `event_kind` is `FALL_WITH_INJURY` or
        `SELF_HARM_ATTEMPT`, counted over all time with no window at all."
        PRD 3.3: "That record carries the `order_id` it belongs to, the acting provider's
        identity in `performed_by_user_id`, the `risk_categories_after` as submitted, the
        order's `elopement_risk_score` immediately before the reassessment in `score_before`,
        the score immediately after it in `score_after`, the resulting cadence in
        `interval_hours_after`, and the logical-clock instant of the reassessment in
        `reassessed_at`."

        Design: Corner/calculations/attempt_event_window_is_inclusive_at_exactly_twenty_four_hours
        """
        world = unit_patient_order(
            api,
            unit_code="UNIT-C24",
            mrn="MRN-C2401",
            budget_cents=250000,
            risk_categories=[RISK_FALL],
        )
        sitter = make_staff(api, world["unit"]["id"], full_name="Window Sitter")
        event = close_event_on_order(
            api,
            world["order"]["id"],
            KIND_ELOPEMENT_ATTEMPT,
            sitter["id"],
            RESOLUTION_CONTINUE_OBSERVATION,
            opener_headers=OFFICER_1,
            closer_headers=OFFICER_2,
        )
        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order after the event closed",
            elopement_risk_score=2.5,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
            status=ORDER_ACTIVE,
        )

        swept = advance_clock(api, "2026-08-02T00:00:00Z")
        assert swept["orders_marked_reassessment_due"] == 1, swept
        assert (
            read_order(api, world["order"]["id"])["status"] == ORDER_REASSESSMENT_DUE
        )

        first = validate_success(
            api.create_reassessment(
                world["order"]["id"], reassessment_payload([RISK_FALL]), PROVIDER_1
            ),
            expected_status=HTTP_CREATED,
        )
        assert_fields(
            first,
            label="reassessment at exactly 24 hours",
            score_before=2.5,
            score_after=2.5,
            interval_hours_after=24,
            reassessed_at="2026-08-02T00:00:00.000Z",
        )
        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order after the first reassessment",
            status=ORDER_ACTIVE,
            elopement_risk_score=2.5,
            last_reassessed_at="2026-08-02T00:00:00.000Z",
            next_reassessment_due_at="2026-08-03T00:00:00.000Z",
        )

        advance_clock(api, "2026-08-02T00:00:01Z")
        second = validate_success(
            api.create_reassessment(
                world["order"]["id"], reassessment_payload([RISK_FALL]), PROVIDER_1
            ),
            expected_status=HTTP_CREATED,
        )
        assert_fields(
            second,
            label="reassessment one second later",
            score_before=2.5,
            score_after=1.5,
            interval_hours_after=24,
        )
        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order after the second reassessment",
            elopement_risk_score=1.5,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
            reassessment_count=2,
        )
        assert_fields(
            read_event(api, event["id"]),
            label="safety event",
            status=EVENT_CLOSED,
            occurred_at=CLOCK_START,
        )
