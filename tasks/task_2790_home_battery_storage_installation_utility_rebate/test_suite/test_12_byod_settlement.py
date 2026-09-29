"""
When the bonus tier is chosen, relative to when the season ratio is updated.

Settlement folds a participation into the season accumulators and only then reads the bonus
tier from them. The two events here are built so that the pre-update ratio and the
post-update ratio fall in different tiers, which makes the ordering observable in cents.
"""

from test_helpers import (
    UTILITY_REVIEWER_HEADERS,
    EventType,
    assert_cents,
    assert_quantity,
    fixtures,
    get_success_data,
)

FIRST_WINDOW_CLOSE = "2026-09-15T19:00:00Z"
SECOND_EVENT = dict(
    window_start="2026-09-20T16:00:00Z",
    window_end="2026-09-20T19:00:00Z",
    event_type=EventType.EMERGENCY,
    target_kw=600,
    payment_rate_cents_per_kw=1200,
)
SECOND_WINDOW_CLOSE = "2026-09-20T19:00:00Z"


class TestBonusTierReadAfterTheSeasonUpdate:
    """The second event's bonus depends on the ratio it has just changed."""

    def _two_events_the_second_awaiting_settlement(self, api):
        """A season at 0.9000 after one event, with a perfect second event reported."""
        project = fixtures.enrolled_project(api)

        fixtures.create_event(api, project)
        fixtures.call_into_event(api, project)
        first_performance_id = project.performance_id
        fixtures.advance_clock(api, project, FIRST_WINDOW_CLOSE)
        fixtures.report_delivery(api, project, 9.0)
        fixtures.settle_event(api, project)

        fixtures.create_event(api, project, **SECOND_EVENT)
        fixtures.call_into_event(api, project)
        fixtures.advance_clock(api, project, SECOND_WINDOW_CLOSE)
        fixtures.report_delivery(api, project, 15.0)
        return project, first_performance_id

    def test_the_bonus_uses_the_ratio_that_includes_the_event_being_settled(self, api):
        """Fifteen kilowatt-hours over three hours meets the pledge exactly.

        Credited capacity is 5.00 kW, so the emergency multiplier pays a gross of 7500 cents
        with no shortfall. Folding this event in lifts the season ratio from 0.9000 to 0.9500,
        which is the upper bonus tier and pays 750 cents; had the tier been read from the
        pre-event ratio of 0.9000 the lower tier would have paid 375.

        PRD 3.9: "This ordering is normative and non-negotiable: the tier is read from the `season_compliance_ratio` that already includes the participation being settled, never from the pre-event ratio."
        PRD 3.9: "`bonus_cents` is `gross_payment_cents` multiplied by the chosen basis-point figure, divided by 10000, rounded half up to a whole number of cents."

        Design: Difficulty/combinatorial_formula/byod_bonus_tier_read_from_post_update_season_ratio
        """
        project, _ = self._two_events_the_second_awaiting_settlement(api)

        fixtures.settle_event(api, project)

        performance = get_success_data(
            api.get_performance(project.performance_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(performance, "avg_delivered_kw", 5.00)
        assert_quantity(performance, "performance_ratio", 1.0000, decimals=4)
        assert_cents(performance, "gross_payment_cents", 7500)
        assert_cents(performance, "shortfall_penalty_cents", 0)
        assert_cents(performance, "bonus_cents", 750)
        assert performance["bonus_cents"] != 375
        assert_cents(performance, "net_payment_cents", 8250)

    def test_the_season_accumulators_span_both_events_in_settlement_order(self, api):
        """Each event's bonus was chosen from the ratio as it stood at its own settlement.

        The first event delivered 4.50 credited kilowatts against the 5.0 kW pledge, a ratio of
        0.9000 that earned the lower tier and paid 4016 cents. The second event, settled
        afterwards, took the upper tier and paid 8250. The enrollment's season total is the sum
        of the two, and the second event's own total is its single net payment.

        PRD 3.9: "The enrollment's `season_compliance_ratio` is then recomputed as `cumulative_credited_kw` divided by `cumulative_pledged_kw`, rounded half up to four decimals."
        PRD 3.9: "The enrollment accumulators span every settled participation of that enrollment across all events of the season, in settlement order."

        Design: Difficulty/combinatorial_formula/byod_bonus_tier_read_from_post_update_season_ratio
        """
        project, first_performance_id = self._two_events_the_second_awaiting_settlement(api)

        settled_event = fixtures.settle_event(api, project)

        first = get_success_data(
            api.get_performance(first_performance_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_cents(first, "net_payment_cents", 4016)
        enrollment = get_success_data(
            api.get_enrollment(project.enrollment_id, headers=project.installer_headers)
        )
        assert_quantity(enrollment, "season_compliance_ratio", 0.9500, decimals=4)
        assert enrollment["settled_event_count"] == 2
        assert_cents(enrollment, "performance_payment_cents_total", 12266)
        assert_cents(settled_event, "total_net_payment_cents", 8250)
