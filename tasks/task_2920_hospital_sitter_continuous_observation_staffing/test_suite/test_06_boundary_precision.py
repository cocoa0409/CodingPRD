"""
Two thresholds walked from one side to the other: a risk score against the video
ceiling, and a safety event's age against the trailing discontinuation window.
"""

from test_helpers import (
    HTTP_CONFLICT,
    HTTP_UNPROCESSABLE,
    ObservationApiClient,
    instant,
    validate_error,
    validate_success,
)
from test_helpers.assertions import assert_fields, assert_instant, assert_row_count
from test_helpers.constants import (
    CLOCK_START,
    COMPETENCY_ADVANCED,
    DECISION_APPROVE,
    ERR_RECENT_SAFETY_EVENT_BLOCKS_DISCONTINUATION,
    ERR_VIDEO_MODALITY_NOT_PERMITTED,
    EVENT_CLOSED,
    FEED_ACTIVE,
    FEED_RELEASED,
    KIND_ELOPEMENT_ATTEMPT,
    MODALITY_ONE_TO_ONE_SITTER,
    MODALITY_VIDEO_MONITORING,
    ORDER_DISCONTINUATION_REVIEW,
    ORDER_DISCONTINUED,
    POOL_INTERNAL_FLOAT,
    RECOMMENDATION_DISCONTINUE,
    RESOLUTION_CONTINUE_OBSERVATION,
    RISK_ELOPEMENT,
    RISK_FALL,
    STATION_IDLE,
    VARIANT_ROLLING_EVENT_WEIGHTED,
)
from test_helpers.factories import (
    discontinuation_decision_payload,
    discontinuation_review_payload,
    feed_payload,
)
from test_helpers.fixtures import (
    advance_clock,
    close_event_on_order,
    make_order,
    make_patient,
    make_reassessment,
    make_staff,
    make_station,
    make_unit,
    order_feeds,
    read_event,
    read_order,
    read_station,
)
from test_helpers.test_users import (
    OFFICER_2,
    PROVIDER_1,
    PROVIDER_2,
    make_remote_observer_headers,
)


def _unit_l_video_order_on_a_console(api: ObservationApiClient) -> dict:
    """UNIT-L: a FALL + ELOPEMENT video order (baseline 4.0) and an idle console."""
    unit = make_unit(
        api,
        unit_code="UNIT-L",
        name="Telemetry Unit L",
        budget_cents=500000,
        video_monitoring_enabled=True,
    )
    patient = make_patient(
        api, unit["id"], mrn="MRN-9201", full_name="Pat Thirteen", age_years=60
    )
    observer = make_staff(
        api,
        unit["id"],
        full_name="Observer Ell",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL, RISK_ELOPEMENT],
        required_modality=MODALITY_VIDEO_MONITORING,
        clinical_rationale="Exit-seeking with unsteady gait",
    )
    station = make_station(api, observer["id"], station_label="CONSOLE-L1", declared_max_span=3)
    return {"unit": unit, "order": order, "observer": observer, "station": station}


def _close_one_elopement_attempt(api: ObservationApiClient, world: dict) -> dict:
    """Add one windowed ELOPEMENT_ATTEMPT worth 1.0 rolling point to the order."""
    return close_event_on_order(
        api,
        world["order"]["id"],
        KIND_ELOPEMENT_ATTEMPT,
        world["observer"]["id"],
        RESOLUTION_CONTINUE_OBSERVATION,
        closer_headers=OFFICER_2,
        as_remote_observer=True,
    )


def _admit_feed(api: ObservationApiClient, world: dict, start_hours: int, end_hours: int):
    return api.create_feed(
        feed_payload(
            world["station"]["id"],
            world["order"]["id"],
            instant(CLOCK_START, hours=start_hours),
            instant(CLOCK_START, hours=end_hours),
        ),
        make_remote_observer_headers(world["observer"]["id"]),
    )


class TestVideoGateIsStrictlyBelowSixPointZero:
    """Five point zero admits a feed; exactly six point zero does not."""

    def test_a_score_of_five_admits_the_feed_but_exactly_six_denies_it(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.2: "The score boundary is strict in a way the reassessment tiers are not —
        a score of 5.9 is permitted for video, and a score of exactly 6.0 is not."

        The same order is walked across the ceiling by accumulating attempt points:
        4.0 + 1.0 admits the feed, 4.0 + 2.0 lands exactly on the ceiling and is
        refused, which is only distinguishable from a `<=` reading at equality.

        Design: Difficulty/boundary_precision_check/video_gate_strict_less_than_six_point_zero_on_feed_admission
        """
        world = _unit_l_video_order_on_a_console(api)
        assert world["order"]["elopement_risk_score"] == 4.0

        _close_one_elopement_attempt(api, world)
        assert read_order(api, world["order"]["id"])["elopement_risk_score"] == 5.0
        admitted = validate_success(_admit_feed(api, world, 8, 12), 201)
        assert_fields(
            admitted, label="feed admitted at 5.0", status=FEED_ACTIVE, acuity_weight=3.0
        )
        validate_success(
            api.release_feed(
                admitted["id"], make_remote_observer_headers(world["observer"]["id"])
            )
        )

        _close_one_elopement_attempt(api, world)
        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order at the ceiling",
            elopement_risk_score=6.0,
            risk_score_variant=VARIANT_ROLLING_EVENT_WEIGHTED,
            reassessment_interval_hours=8,
        )
        validate_error(
            _admit_feed(api, world, 13, 17),
            ERR_VIDEO_MODALITY_NOT_PERMITTED,
            HTTP_UNPROCESSABLE,
        )

    def test_the_refused_admission_creates_no_feed_and_rewrites_no_modality(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.7: "The video modality gate of §3.2 is re-evaluated here against live data
        — unit `video_monitoring_enabled` true, `SELF_HARM` absent from the order's
        categories, and the order's `elopement_risk_score` strictly below 6.0 — with
        `ERR_VIDEO_MODALITY_NOT_PERMITTED` on failure."

        Re-evaluating the gate is a refusal, not a modality change: the order is
        still a VIDEO_MONITORING order, the console is back to its opening triple,
        and the only feed on the order is the released one.

        Design: Difficulty/boundary_precision_check/video_gate_strict_less_than_six_point_zero_on_feed_admission
        """
        world = _unit_l_video_order_on_a_console(api)
        _close_one_elopement_attempt(api, world)
        admitted = validate_success(_admit_feed(api, world, 8, 12), 201)
        validate_success(
            api.release_feed(
                admitted["id"], make_remote_observer_headers(world["observer"]["id"])
            )
        )
        _close_one_elopement_attempt(api, world)
        _admit_feed(api, world, 13, 17)

        feeds = order_feeds(api, world["order"]["id"])
        assert_row_count(feeds, 1, "feeds on the order")
        assert_fields(
            feeds[0],
            label="the only feed",
            id=admitted["id"],
            status=FEED_RELEASED,
        )
        assert_fields(
            read_station(api, world["station"]["id"]),
            label="console after the refusal",
            status=STATION_IDLE,
            active_feed_count=0,
            active_acuity_weight=0.0,
            effective_span_limit=3,
        )
        assert (
            read_order(api, world["order"]["id"])["required_modality"]
            == MODALITY_VIDEO_MONITORING
        )


def _unit_m_order_awaiting_a_decision(api: ObservationApiClient) -> dict:
    """
    UNIT-M: an order reassessed once, carrying one closed ELOPEMENT_ATTEMPT stamped at
    the startup clock, and sitting in DISCONTINUATION_REVIEW with a DISCONTINUE
    recommendation from its own ordering provider.
    """
    unit = make_unit(
        api,
        unit_code="UNIT-M",
        name="Rehab Unit M",
        budget_cents=500000,
        video_monitoring_enabled=False,
    )
    patient = make_patient(
        api, unit["id"], mrn="MRN-9301", full_name="Pat Fourteen", age_years=60
    )
    sitter = make_staff(
        api,
        unit["id"],
        full_name="Sitter Em",
        source_pool=POOL_INTERNAL_FLOAT,
        hourly_rate_cents=2000,
        competency_level=COMPETENCY_ADVANCED,
    )
    order = make_order(
        api,
        patient["id"],
        risk_categories=[RISK_FALL],
        required_modality=MODALITY_ONE_TO_ONE_SITTER,
        clinical_rationale="Impulsive transfers after sedation",
    )
    event = close_event_on_order(
        api,
        order["id"],
        KIND_ELOPEMENT_ATTEMPT,
        sitter["id"],
        RESOLUTION_CONTINUE_OBSERVATION,
        closer_headers=OFFICER_2,
    )
    make_reassessment(api, order["id"], [RISK_FALL])
    validate_success(
        api.open_discontinuation_review(
            order["id"], discontinuation_review_payload(RECOMMENDATION_DISCONTINUE), PROVIDER_1
        )
    )
    return {"unit": unit, "order": order, "event": event}


def _approve(api: ObservationApiClient, order_id: str, rationale: str):
    return api.decide_discontinuation(
        order_id, discontinuation_decision_payload(DECISION_APPROVE, rationale), PROVIDER_2
    )


class TestDiscontinuationSafetyWindowIsInclusiveAtTwentyFourHours:
    """An event exactly 24 hours old still blocks; one second later it does not."""

    def test_an_event_exactly_twenty_four_hours_old_still_blocks_the_approval(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.9: "The boundary is inclusive, so an event exactly 24 hours old still
        blocks the approval, and the rejection is
        `ERR_RECENT_SAFETY_EVENT_BLOCKS_DISCONTINUATION`."

        With `occurred_at` at the startup instant and the clock exactly 24 hours
        later, `occurred_at >= clock - 24h` holds at equality, so the order stays in
        review with its recommendation intact and nothing stamped.

        Design: Difficulty/boundary_precision_check/discontinuation_safety_window_inclusive_at_exactly_twenty_four_hours
        """
        world = _unit_m_order_awaiting_a_decision(api)
        advance_clock(api, instant(CLOCK_START, hours=24))

        validate_error(
            _approve(api, world["order"]["id"], "Attempt exactly 24h ago"),
            ERR_RECENT_SAFETY_EVENT_BLOCKS_DISCONTINUATION,
            HTTP_CONFLICT,
        )
        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order after the blocked decision",
            status=ORDER_DISCONTINUATION_REVIEW,
            discontinued_at=None,
            discontinuation_recommendation=RECOMMENDATION_DISCONTINUE,
        )

    def test_one_second_past_the_window_the_identical_approval_is_granted(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.9: "Clearing that gate advances the order `DISCONTINUATION_REVIEW →
        DISCONTINUED` and stamps `discontinued_at` from the logical clock, then
        cascades over everything the order was consuming."

        Only the clock differs between the refusal and the approval, and the event
        itself is never touched by either decision.

        Design: Difficulty/boundary_precision_check/discontinuation_safety_window_inclusive_at_exactly_twenty_four_hours
        """
        world = _unit_m_order_awaiting_a_decision(api)
        advance_clock(api, instant(CLOCK_START, hours=24))
        _approve(api, world["order"]["id"], "Attempt exactly 24h ago")

        advance_clock(api, instant(CLOCK_START, hours=24, seconds=1))
        approved = validate_success(
            _approve(api, world["order"]["id"], "Window now clear by one second")
        )
        assert approved["status"] == ORDER_DISCONTINUED
        assert_instant(
            approved["discontinued_at"],
            instant(CLOCK_START, hours=24, seconds=1),
            "order.discontinued_at",
        )

        event = read_event(api, world["event"]["id"])
        assert event["status"] == EVENT_CLOSED
        assert_instant(event["occurred_at"], CLOCK_START, "event.occurred_at")
        assert_fields(
            read_order(api, world["order"]["id"]),
            label="order after the approval",
            reassessment_count=1,
            elopement_risk_score=2.5,
        )

    def test_an_order_under_review_is_immune_to_both_clock_sweeps(
        self, api: ObservationApiClient
    ):
        """
        PRD 3.3: "Only orders in `ACTIVE` or `REASSESSMENT_DUE` are candidates — an
        order sitting in `ESCALATED` or `DISCONTINUATION_REVIEW` is immune to the
        sweep entirely, which is what makes an open discontinuation review safe from
        lapsing while it is being decided."

        The order's `next_reassessment_due_at` falls exactly on the first clock
        advance, which would otherwise be sufficient to mark it due, yet both
        advances report an untouched sweep.

        Design: Difficulty/boundary_precision_check/discontinuation_safety_window_inclusive_at_exactly_twenty_four_hours
        """
        world = _unit_m_order_awaiting_a_decision(api)
        assert_instant(
            read_order(api, world["order"]["id"])["next_reassessment_due_at"],
            instant(CLOCK_START, hours=24),
            "order.next_reassessment_due_at",
        )

        first = advance_clock(api, instant(CLOCK_START, hours=24))
        assert_fields(
            first,
            label="sweep at the due instant",
            orders_marked_reassessment_due=0,
            orders_lapsed=0,
        )
        _approve(api, world["order"]["id"], "Attempt exactly 24h ago")
        second = advance_clock(api, instant(CLOCK_START, hours=24, seconds=1))
        assert_fields(
            second,
            label="sweep one second later",
            orders_marked_reassessment_due=0,
            orders_lapsed=0,
        )
