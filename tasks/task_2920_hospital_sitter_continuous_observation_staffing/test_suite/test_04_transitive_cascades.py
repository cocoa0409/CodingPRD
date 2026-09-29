"""
Two multi-hop cascades where each link is caused by the previous link rather than
by the triggering call: an incident review walking the monitoring topology, and a
discharge walking the billing spine.
"""

from test_helpers import ObservationApiClient, instant, validate_success
from test_helpers.assertions import (
    assert_fields,
    assert_instant,
    assert_row_count,
    final_segment_rows,
    provisional_row,
)
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    COMPLETION_ORDER_DISCONTINUED,
    COST_POSTED,
    COST_REVERSED,
    DOC_PENDING,
    DOC_WAIVED,
    ENTRY_KIND_FINAL_SEGMENT,
    EVENT_INCIDENT_REVIEW,
    KIND_FALL_WITH_INJURY,
    MODALITY_ONE_TO_ONE_SITTER,
    MODALITY_VIDEO_MONITORING,
    ORDER_ACTIVE,
    ORDER_DISCONTINUED,
    PATIENT_DISCHARGED,
    POOL_INTERNAL_FLOAT,
    FEED_RELEASED,
    RELEASE_MODALITY_FORCED_TO_SITTER,
    RISK_ELOPEMENT,
    RISK_FALL,
    STAFF_AVAILABLE,
    STAFF_SUSPENDED,
    STATION_IDLE,
    SUSPENSION_INCIDENT_REVIEW_OPENED,
    UNIT_OPEN,
    VARIANT_ROLLING_EVENT_WEIGHTED,
    WATCH_COMPLETED,
    WATCH_ON_WATCH,
)
from test_helpers.fixtures import (
    advance_clock,
    assignment_cost_entries,
    make_assignment,
    make_feed,
    make_order,
    make_patient,
    make_safety_event,
    make_staff,
    make_station,
    make_unit,
    read_assignment,
    read_feed,
    read_order,
    read_patient,
    read_staff,
    read_station,
    read_unit,
    start_watch_at,
    unit_head,
)
from test_helpers.test_users import MANAGER, OFFICER_1, OFFICER_ONE


def _unit_g_video_order_with_console_and_watch(api: ObservationApiClient) -> dict:
    """
    UNIT-G: a video order monitored on a console by one observer and also watched at
    the bedside by a second, different sitter, with an injury event on the record.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-G",
        name="Neuro Unit G",
        budget_cents=100000,
        video_monitoring_enabled=True,
    )
    patient = make_patient(api, unit["id"], mrn="MRN-7001", full_name="Pat Eight", age_years=60)
    observer = make_staff(
        api,
        unit["id"],
        full_name="Observer Gee",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    sitter = make_staff(
        api,
        unit["id"],
        full_name="Sitter Gee",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2400,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL, RISK_ELOPEMENT],
        required_modality=MODALITY_VIDEO_MONITORING,
        clinical_rationale="Wandering with unsteady gait; remote observation acceptable",
    )
    station = make_station(api, observer["id"], station_label="CONSOLE-G1", declared_max_span=2)
    feed = make_feed(
        api,
        station["id"],
        order["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=12),
        observer["id"],
    )
    assignment = make_assignment(
        api,
        order["id"],
        sitter["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=16),
        expected_order_version=order["version"],
    )
    advance_clock(api, instant(CLOCK_START, hours=8))
    start_watch_at(api, assignment["id"], sitter["id"], instant(CLOCK_START, hours=8))
    event = make_safety_event(
        api,
        order["id"],
        KIND_FALL_WITH_INJURY,
        sitter["id"],
        narrative="Unwitnessed fall from chair, forehead laceration",
        assignment_id=assignment["id"],
    )
    return {
        "unit": unit,
        "observer": observer,
        "sitter": sitter,
        "order": order,
        "station": station,
        "feed": feed,
        "assignment": assignment,
        "event": event,
    }


class TestIncidentReviewCascadesFourHopsDeep:
    """Modality -> feed -> station -> observer, each hop caused by the one before."""

    def test_forcing_the_sitter_modality_releases_the_feed_idles_the_console_and_frees_its_observer(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.8: "Second, because the order's modality has left `VIDEO_MONITORING`,
        every feed on that order whose `status` is `ACTIVE` is released with
        `release_reason` `MODALITY_FORCED_TO_SITTER`, processed in ascending
        `created_at`. Third, because those feeds left `ACTIVE`, each affected console
        recomputes `active_feed_count`, `active_acuity_weight` and
        `effective_span_limit`, and any console whose `active_feed_count` reaches 0
        transitions `ACTIVE_MONITORING → IDLE`. Fourth, because a console became `IDLE`,
        its observer transitions `ON_ASSIGNMENT → AVAILABLE`."

        Design: Difficulty/transitive_cascade/incident_review_modality_to_feed_to_station_to_observer_depth_four
        """
        world = _unit_g_video_order_with_console_and_watch(api)
        assert world["order"]["required_modality"] == MODALITY_VIDEO_MONITORING
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="console before the review",
            active_feed_count=1,
            active_acuity_weight=3.0,
            effective_span_limit=2,
        )

        reviewed = validate_success(api.open_incident_review(world["event"]["id"], OFFICER_1))
        assert_fields(
            reviewed,
            label="reviewed event",
            status=EVENT_INCIDENT_REVIEW,
            review_opened_by_user_id=OFFICER_ONE,
        )

        assert (
            read_order(api, world["order"]["id"])["required_modality"]
            == MODALITY_ONE_TO_ONE_SITTER
        ), "hop 1 rewrites the order's modality"

        feed = read_feed(api, world["feed"]["id"])
        assert_fields(
            feed,
            label="hop 2 feed",
            status=FEED_RELEASED,
            release_reason=RELEASE_MODALITY_FORCED_TO_SITTER,
        )
        assert_instant(feed["released_at"], instant(CLOCK_START, hours=8), "feed.released_at")

        assert_fields(
            read_station(api, world["station"]["id"]),
            label="hop 3 console",
            status=STATION_IDLE,
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=2,
        )

        assert_fields(
            read_staff(api, world["observer"]["id"]),
            label="hop 4 console observer",
            status=STAFF_AVAILABLE,
            suspension_reason=None,
        )

    def test_the_named_sitter_is_suspended_after_the_hops_and_not_confused_with_the_observer(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.8: "Finally, and strictly **after** all four cascade hops, if the event
        named an `assignment_id` then the observer who was keeping that watch
        transitions to `SUSPENDED` with `suspension_reason` `INCIDENT_REVIEW_OPENED`."

        The two staff rows resolve to opposite outcomes in the same request: the
        console observer freed by hop 4 is AVAILABLE, while the bedside sitter named
        by the event is SUSPENDED. Neither the watch dimension nor the ledger is
        touched, because the cascade "posts no ledger row".

        Design: Difficulty/transitive_cascade/incident_review_modality_to_feed_to_station_to_observer_depth_four
        """
        world = _unit_g_video_order_with_console_and_watch(api)
        validate_success(api.open_incident_review(world["event"]["id"], OFFICER_1))

        assert_fields(
            read_staff(api, world["sitter"]["id"]),
            label="the sitter named by the event",
            status=STAFF_SUSPENDED,
            suspension_reason=SUSPENSION_INCIDENT_REVIEW_OPENED,
        )
        assert read_staff(api, world["observer"]["id"])["status"] == STAFF_AVAILABLE

        assert_fields(
            read_assignment(api, world["assignment"]["id"]),
            label="the sitter's watch",
            watch_status=WATCH_ON_WATCH,
            documentation_status=DOC_PENDING,
        )
        assert unit_head(api, world["unit"]["id"]) == 19200, (
            "only the PROVISIONAL entry stands; the cascade posts nothing"
        )

    def test_the_review_rescores_the_order_without_moving_its_reassessment_stamp(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.8: "Alongside the cascade the order's `elopement_risk_score` is recomputed
        under the rolling event-weighted reading, and `reassessment_interval_hours` is
        recomputed from the new score with `next_reassessment_due_at` reset to
        `last_reassessed_at` advanced by that interval — note that `last_reassessed_at`
        itself is not moved, because opening a review is not a reassessment."

        A FALL_WITH_INJURY contributes all-time points and never escalates the
        order, so the score rises 4.0 -> 6.0, the cadence tightens to 8 hours, the
        due instant is recomputed off the unmoved stamp, and the status stays ACTIVE.

        Design: Difficulty/transitive_cascade/incident_review_modality_to_feed_to_station_to_observer_depth_four
        """
        world = _unit_g_video_order_with_console_and_watch(api)
        assert_fields(
            world["order"],
            label="order at admission",
            elopement_risk_score=4.0,
            reassessment_interval_hours=12,
        )

        validate_success(api.open_incident_review(world["event"]["id"], OFFICER_1))

        order = read_order(api, world["order"]["id"])
        assert_fields(
            order,
            label="order after the review opened",
            status=ORDER_ACTIVE,
            elopement_risk_score=6.0,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
            reassessment_interval_hours=8,
        )
        assert_instant(order["last_reassessed_at"], CLOCK_START, "order.last_reassessed_at")
        assert_instant(
            order["next_reassessment_due_at"],
            instant(CLOCK_START, hours=8),
            "order.next_reassessment_due_at",
        )


def _unit_h_live_watch(api: ObservationApiClient) -> dict:
    """UNIT-H: one live watch at 2400 cents/hour, three billable hours old."""
    unit = make_unit(
        api,
        unit_code="UNIT-H",
        name="Med-Surg Unit H",
        budget_cents=100000,
        video_monitoring_enabled=False,
    )
    patient = make_patient(api, unit["id"], mrn="MRN-8001", full_name="Pat Nine", age_years=60)
    sitter = make_staff(
        api,
        unit["id"],
        full_name="Sitter Aitch",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2400,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Post-operative delirium with fall risk",
    )
    assignment = make_assignment(
        api,
        order["id"],
        sitter["id"],
        instant(CLOCK_START, hours=8),
        instant(CLOCK_START, hours=16),
        expected_order_version=order["version"],
    )
    advance_clock(api, instant(CLOCK_START, hours=8))
    start_watch_at(api, assignment["id"], sitter["id"], instant(CLOCK_START, hours=8))
    advance_clock(api, instant(CLOCK_START, hours=11))
    return {
        "unit": unit,
        "patient": patient,
        "sitter": sitter,
        "order": order,
        "assignment": assignment,
    }


class TestDischargeCascadesDownTheBillingSpine:
    """Patient -> order -> watch -> ledger, then a budget re-check that does nothing."""

    def test_the_discharge_discontinues_the_order_completes_the_watch_and_settles_the_ledger(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.9: "In the second hop, because each of those orders became
        `DISCONTINUED`, its assignments in `watch_status` `ON_WATCH` or `ON_BREAK`
        transition to `COMPLETED` with `completion_reason` `ORDER_DISCONTINUED` and
        `documentation_status` `PENDING → WAIVED`, while its assignments in
        `SCHEDULED` transition to `VOIDED`."

        The third hop closes the open segment at the clock the discharge ran on, so
        exactly 180 whole minutes are billed at 2400 cents an hour while the
        provisional row is reversed rather than rewritten.

        Design: Difficulty/transitive_cascade/patient_discharge_order_to_assignment_to_ledger_depth_three
        """
        world = _unit_h_live_watch(api)
        validate_success(api.discharge_patient(world["patient"]["id"], MANAGER))

        patient = read_patient(api, world["patient"]["id"])
        assert patient["status"] == PATIENT_DISCHARGED
        assert_instant(
            patient["discharged_at"], instant(CLOCK_START, hours=11), "patient.discharged_at"
        )

        order = read_order(api, world["order"]["id"])
        assert order["status"] == ORDER_DISCONTINUED, "hop 1 terminates the order"
        assert_instant(
            order["discontinued_at"], instant(CLOCK_START, hours=11), "order.discontinued_at"
        )

        assignment = read_assignment(api, world["assignment"]["id"])
        assert_fields(
            assignment,
            label="hop 2 watch",
            watch_status=WATCH_COMPLETED,
            completion_reason=COMPLETION_ORDER_DISCONTINUED,
            documentation_status=DOC_WAIVED,
            final_cost_cents=7200,
            watch_segment_count=1,
            watched_minutes=180,
        )

        rows = assignment_cost_entries(api, world["assignment"]["id"])
        assert_row_count(rows, 2, "ledger rows for the swept-up watch")
        reversed_row = provisional_row(rows)
        assert_fields(
            reversed_row,
            label="hop 3 reversed provisional",
            amount_cents=19200,
            status=COST_REVERSED,
        )
        assert_instant(
            reversed_row["reversed_at"], instant(CLOCK_START, hours=11), "entry.reversed_at"
        )
        finals = final_segment_rows(rows)
        assert_row_count(finals, 1, "posted final segment rows")
        final_row = finals[0]
        assert_fields(
            final_row,
            label="hop 3 final segment",
            entry_kind=ENTRY_KIND_FINAL_SEGMENT,
            status=COST_POSTED,
            amount_cents=7200,
            segment_index=1,
            segment_minutes=180,
            night_differential_applied=False,
        )
        assert unit_head(api, world["unit"]["id"]) == 7200

    def test_the_fourth_hop_re_evaluates_the_budget_and_visibly_declines_to_restrict(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.9: "In the fourth hop, because the unit's ledger head has moved, the
        unit re-evaluates its budget and transitions `OPEN → RESTRICTED` with
        `restriction_reason` `BUDGET_THRESHOLD_REACHED` when the head has reached or
        passed `observation_cost_budget_cents`."

        The recomputed head of 7200 is far below the 100000 budget, so the
        re-evaluation leaves the unit OPEN — an outcome only observable because hop 3
        really did rewrite the head down from 19200. The order's `coverage_gap_flag`
        also stays false, because a system sweep is not SHIFT_END_NO_SUCCESSOR.

        Design: Difficulty/transitive_cascade/patient_discharge_order_to_assignment_to_ledger_depth_three
        """
        world = _unit_h_live_watch(api)
        assert unit_head(api, world["unit"]["id"]) == 19200

        validate_success(api.discharge_patient(world["patient"]["id"], MANAGER))

        assert_fields(
            read_unit(api, world["unit"]["id"]),
            label="unit after the cascade",
            observed_cost_to_date_cents=7200,
            status=UNIT_OPEN,
            restriction_reason=None,
        )
        assert read_order(api, world["order"]["id"])["coverage_gap_flag"] is False
        assert read_staff(api, world["sitter"]["id"])["status"] == STAFF_AVAILABLE
