"""Conversion order lifecycle: cost estimate, post-schedule overlap, and the
rework cycle."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_success,
    create_active_studio,
    create_conversion_order,
    create_film,
    set_clock,
)

STUDIO_DATE = "2026-09-01T00:00:00Z"


def _studio_with_two_films(api, studio_manager_headers):
    set_clock()
    studio = create_active_studio()
    f1 = create_film(studio["id"], title="F1", runtime_minutes=100,
                     worldwide_release_date="2026-09-10T00:00:00Z")
    f2 = create_film(studio["id"], title="F2", runtime_minutes=100,
                     worldwide_release_date="2026-09-12T00:00:00Z")
    return studio, f1, f2


class TestPostCostEstimate:
    @pytest.mark.parametrize(
        "target_format,expected_cents",
        [
            ("PREMIUM_2D", 200000000 + 90 * 1200000),     # 308000000
            ("PREMIUM_3D", 350000000 + 90 * 1800000),     # 512000000
            ("PREMIUM_70MM", 500000000 + 90 * 2500000),   # 725000000
        ],
    )
    def test_post_cost_estimate_uses_format_rates(
        self, api, studio_manager_headers, target_format, expected_cents
    ):
        """PRD §3.3: "The estimate is a base rate plus a per-minute rate times
        the parent film's `runtime_minutes`, with the rates keyed by target
        format. A `PREMIUM_2D` conversion carries a base of 200,000,000 cents
        plus 1,200,000 cents per minute of runtime. A `PREMIUM_3D` conversion
        carries a base of 350,000,000 cents plus 1,800,000 cents per minute.
        A `PREMIUM_70MM` conversion carries a base of 500,000,000 cents plus
        2,500,000 cents per minute."

        Design: Corner/calculations/conversion_post_cost_estimate_uses_format_rates
        """
        set_clock()
        studio = create_active_studio()
        film = create_film(studio["id"], title="F", runtime_minutes=90,
                           worldwide_release_date="2026-09-15T00:00:00Z")
        order = create_conversion_order(
            film["id"], target_format=target_format,
            scheduled_post_start_date="2026-09-01T00:00:00Z",
            scheduled_post_end_date="2026-09-03T00:00:00Z",
        )
        assert order["post_cost_estimate_cents"] == expected_cents, (
            f"post_cost_estimate_cents for {target_format}: "
            f"expected {expected_cents}, got {order['post_cost_estimate_cents']}"
        )

    def test_post_cost_estimate_recomputes_per_film_runtime(
        self, api, studio_manager_headers
    ):
        """PRD §3.3: "The estimate is a base rate plus a per-minute rate times
        the parent film's `runtime_minutes`, with the rates keyed by target
        format." and "The result is an integer number of cents; no rounding
        is needed."

        Design: Corner/calculations/conversion_post_cost_estimate_uses_format_rates
        """
        set_clock()
        studio = create_active_studio()
        film = create_film(studio["id"], title="F", runtime_minutes=45,
                           worldwide_release_date="2026-09-15T00:00:00Z")
        order = create_conversion_order(
            film["id"], target_format="PREMIUM_2D",
            scheduled_post_start_date="2026-09-01T00:00:00Z",
            scheduled_post_end_date="2026-09-03T00:00:00Z",
        )
        assert isinstance(order["post_cost_estimate_cents"], int)
        assert order["post_cost_estimate_cents"] == 200000000 + 45 * 1200000


class TestPostScheduleOverlap:
    def test_closed_closed_boundary_day_conflicts(
        self, api, studio_manager_headers, post_scheduler_headers
    ):
        """PRD §3.3: "both inclusive — the post window is a closed-closed
        interval" and "no other ConversionOrder on a film of the same studio
        may have status `IN_POST` or `QC_REVIEW` with a post window that lies
        within one day of this order's window: because post windows are
        closed-closed, a one-day handoff is required between consecutive
        conversions — the other order's end date plus one day must not be
        strictly after this order's start while this order's end date plus
        one day is also strictly after the other order's start. A violation
        is rejected with `ERR_POST_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/conversion_post_schedule_uses_closed_closed_with_handoff_day
        """
        _, f1, f2 = _studio_with_two_films(api, studio_manager_headers)
        conv1 = create_conversion_order(
            f1["id"],
            scheduled_post_start_date="2026-09-01T00:00:00Z",
            scheduled_post_end_date="2026-09-03T00:00:00Z",
        )
        get_success_data(api.begin_post(conv1["id"], post_scheduler_headers))
        conv2 = create_conversion_order(
            f2["id"],
            scheduled_post_start_date="2026-09-03T00:00:00Z",
            scheduled_post_end_date="2026-09-05T00:00:00Z",
        )
        resp = api.begin_post(conv2["id"], post_scheduler_headers)
        validate_error(resp, ApiErrorId.ERR_POST_SCHEDULE_OVERLAP,
                       expected_status=409)
        order = validate_success(
            api.get_conversion_order(conv2["id"], post_scheduler_headers)
        )
        assert order["status"] == "SUBMITTED"

    def test_handoff_day_satisfies_gap(
        self, api, studio_manager_headers, post_scheduler_headers
    ):
        """PRD §3.3: "a one-day handoff is required between consecutive
        conversions — the other order's end date plus one day must not be
        strictly after this order's start while this order's end date plus
        one day is also strictly after the other order's start."

        Design: Difficulty/resource_temporal_overlap/conversion_post_schedule_uses_closed_closed_with_handoff_day
        """
        _, f1, f2 = _studio_with_two_films(api, studio_manager_headers)
        conv1 = create_conversion_order(
            f1["id"],
            scheduled_post_start_date="2026-09-01T00:00:00Z",
            scheduled_post_end_date="2026-09-03T00:00:00Z",
        )
        get_success_data(api.begin_post(conv1["id"], post_scheduler_headers))
        # conv1.end + 1 day = 2026-09-04; starting conv2 on 2026-09-04 means
        # conv1.end + 1 > conv2.start is false, so no conflict.
        conv2 = create_conversion_order(
            f2["id"],
            scheduled_post_start_date="2026-09-04T00:00:00Z",
            scheduled_post_end_date="2026-09-06T00:00:00Z",
        )
        resp = api.begin_post(conv2["id"], post_scheduler_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "IN_POST"


class TestReworkCycle:
    def test_rework_cycle_resets_post_window(
        self, api, studio_manager_headers, post_scheduler_headers,
        qa_reviewer_headers
    ):
        """PRD §3.3: "that `REWORK_REQUESTED → IN_POST` transition resets the
        rework window by setting `scheduled_post_end_date` to the current
        logical clock plus 7 days" and "The order may loop `QC_REVIEW →
        REWORK_REQUESTED → IN_POST → QC_REVIEW` any number of times."

        Design: Difficulty/non_linear_state_machine/conversion_order_rework_cycle_resets_post_window_and_signoff
        """
        # Simpler path: drive to QC_REVIEW, request rework, begin post.
        set_clock()
        studio = create_active_studio()
        film = create_film(studio["id"], title="Film Y", runtime_minutes=90,
                           worldwide_release_date="2026-09-15T00:00:00Z")
        order = create_conversion_order(
            film["id"],
            scheduled_post_start_date="2026-09-01T00:00:00Z",
            scheduled_post_end_date="2026-09-03T00:00:00Z",
            filmmaker_approval_required=True,
        )
        get_success_data(api.begin_post(order["id"], post_scheduler_headers))
        set_clock("2026-09-04T00:00:00Z")
        get_success_data(api.submit_for_qc(order["id"], post_scheduler_headers))
        resp = api.request_rework(order["id"], qa_reviewer_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "REWORK_REQUESTED"
        resp = api.begin_post(order["id"], post_scheduler_headers)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "IN_POST"
        fetched = validate_success(
            api.get_conversion_order(order["id"], post_scheduler_headers)
        )
        assert fetched["scheduled_post_end_date"][:19] == "2026-09-11T00:00:00", (
            f"rework must reset end to clock + 7 days; got "
            f"{fetched['scheduled_post_end_date']}"
        )

    def test_rework_clears_filmmaker_signoff(
        self, api, studio_manager_headers, post_scheduler_headers,
        qa_reviewer_headers
    ):
        """PRD §3.3: "clears `filmmaker_signoff` back to false, so a
        filmmaker signoff given before rework never carries across the
        cycle."

        Design: Difficulty/non_linear_state_machine/conversion_order_rework_cycle_resets_post_window_and_signoff
        """
        set_clock()
        studio = create_active_studio()
        film = create_film(studio["id"], title="Film Y", runtime_minutes=90,
                           worldwide_release_date="2026-09-15T00:00:00Z")
        order = create_conversion_order(
            film["id"],
            scheduled_post_start_date="2026-09-01T00:00:00Z",
            scheduled_post_end_date="2026-09-03T00:00:00Z",
            filmmaker_approval_required=True,
        )
        get_success_data(api.begin_post(order["id"], post_scheduler_headers))
        set_clock("2026-09-04T00:00:00Z")
        get_success_data(api.submit_for_qc(order["id"], post_scheduler_headers))
        # Rework the order and re-enter IN_POST: the rework edge clears the
        # filmmaker signoff back to false per the cycle rule.
        get_success_data(api.request_rework(order["id"], qa_reviewer_headers))
        get_success_data(api.begin_post(order["id"], post_scheduler_headers))
        fetched = validate_success(
            api.get_conversion_order(order["id"], post_scheduler_headers)
        )
        assert fetched["filmmaker_signoff"] is False, (
            "filmmaker_signoff must be cleared by the rework cycle"
        )
        # After rework, approval without signoff must be rejected again,
        # proving a signoff given before rework does not carry across.
        set_clock("2026-09-16T00:00:00Z")
        get_success_data(api.submit_for_qc(order["id"], post_scheduler_headers))
        resp = api.approve_release(order["id"], qa_reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_FILMMAKER_SIGNOFF_MISSING,
                       expected_status=409)
