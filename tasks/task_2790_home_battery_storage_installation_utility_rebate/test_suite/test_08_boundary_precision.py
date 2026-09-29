"""
Two inclusive boundaries, one on a ratio and one on an instant.

A dispatch performance landing exactly on the shortfall floor is not a shortfall, and a
warranty registered exactly on its deadline is on time. Both boundaries are inclusive on
the favourable side, and both are one step away from the unfavourable outcome.
"""

from test_helpers import (
    UTILITY_REVIEWER_HEADERS,
    PerformanceStatus,
    WarrantyStatus,
    assert_cents,
    assert_instant_equals,
    assert_quantity,
    assert_stamped_from_clock,
    fixtures,
    get_success_data,
)

WINDOW_CLOSE = "2026-09-15T19:00:00Z"
WARRANTY_DEADLINE = "2026-09-09T17:00:00Z"


class TestRatioExactlyAtTheShortfallFloor:
    """A ratio of exactly 0.8000 pays in full and earns no bonus."""

    def _settled_at_the_floor(self, api):
        """A two-hour event delivering exactly 8 kWh against a 5 kW pledge."""
        project = fixtures.enrolled_project(api)
        fixtures.create_event(api, project)
        fixtures.call_into_event(api, project)
        fixtures.advance_clock(api, project, WINDOW_CLOSE)
        fixtures.report_delivery(api, project, 8.0)
        fixtures.settle_event(api, project)
        return project

    def test_a_ratio_of_exactly_the_floor_is_not_a_shortfall(self, api):
        """Eight kilowatt-hours over two hours is 4.00 kW against a 5.0 kW pledge.

        That is a performance ratio of exactly 0.8000, and the penalty predicate is strictly
        below the floor, so no penalty is taken and the household keeps the whole gross
        payment of 4.00 credited kilowatts at 850 cents each under the economic multiplier.

        PRD 3.9: "When the ratio is 0.80 or above, `shortfall_penalty_cents` is 0 — the boundary at exactly 0.80 is not a shortfall."
        PRD 3.9: "`performance_ratio` is `avg_delivered_kw` divided by `pledged_kw_snapshot`, rounded half up to four decimals."
        PRD 3.9: "The event multiplier is 12500 basis points when the event's `event_type` is `EMERGENCY` and 10000 basis points otherwise."

        Design: Difficulty/boundary_precision_check/byod_performance_ratio_exactly_at_shortfall_floor_incurs_no_penalty
        """
        project = self._settled_at_the_floor(api)

        performance = get_success_data(
            api.get_performance(project.performance_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_quantity(performance, "avg_delivered_kw", 4.00)
        assert_quantity(performance, "performance_ratio", 0.8000, decimals=4)
        assert_cents(performance, "shortfall_penalty_cents", 0)
        assert_cents(performance, "gross_payment_cents", 3400)
        assert performance["status"] == PerformanceStatus.SETTLED

    def test_the_same_ratio_sits_below_the_bonus_tier_and_earns_nothing_extra(self, api):
        """The floor for penalties and the floor for bonuses are different numbers.

        The season ratio after this single settlement is also 0.8000, which is below the lower
        bonus threshold of 0.85, so no bonus is added and the net payment is exactly the
        gross. The enrollment's season total records that same figure.

        PRD 3.9: "When that ratio is 0.95 or above the bonus is 1000 basis points; otherwise, when it is 0.85 or above the bonus is 500 basis points; otherwise there is no bonus."
        PRD 3.9: "`net_payment_cents` is `gross_payment_cents` minus `shortfall_penalty_cents` plus `bonus_cents`, floored at zero — a participation never owes the utility money."
        PRD 3.9: "The enrollment's `settled_event_count` is increased by one and its `performance_payment_cents_total` is increased by `net_payment_cents`; the event's `total_net_payment_cents` is increased by the same amount."

        Design: Difficulty/boundary_precision_check/byod_performance_ratio_exactly_at_shortfall_floor_incurs_no_penalty
        """
        project = self._settled_at_the_floor(api)

        performance = get_success_data(
            api.get_performance(project.performance_id, headers=UTILITY_REVIEWER_HEADERS)
        )
        assert_cents(performance, "bonus_cents", 0)
        assert_cents(performance, "net_payment_cents", 3400)
        enrollment = get_success_data(
            api.get_enrollment(project.enrollment_id, headers=project.installer_headers)
        )
        assert_quantity(enrollment, "season_compliance_ratio", 0.8000, decimals=4)
        assert_cents(enrollment, "performance_payment_cents_total", 3400)


class TestRegistrationExactlyOnTheDeadline:
    """A warranty registered on the deadline instant is covered, not void."""

    def _registered_on_the_deadline(self, api):
        """A bank commissioned at 17:00 and registered exactly thirty days later."""
        project = fixtures.commissioned_project(api)
        fixtures.advance_clock(api, project, WARRANTY_DEADLINE)
        fixtures.register_warranty(api, project, coverage_years=10)
        return project

    def test_registering_on_the_deadline_instant_activates_the_warranty(self, api):
        """Thirty days after commissioning, to the second, is still inside the window.

        The bank was commissioned at 2026-08-10T17:00:00Z, so its deadline falls on
        2026-09-09T17:00:00Z, and the registration is made at exactly that instant. The
        boundary is inclusive, so coverage is active and the supplied term is stored.

        PRD 3.6: "The deadline is `commissioned_at` plus 30 days and the boundary is **inclusive**: a registration landing exactly on `warranty_deadline_at` is on time and sets `warranty_status` to `ACTIVE`."
        PRD 3.6: "Registration stamps `warranty_registered_at` from the logical clock, stores the supplied term in `warranty_coverage_years` and the supplied serials in `serial_numbers`, and then decides coverage against the deadline."

        Design: Difficulty/boundary_precision_check/warranty_registration_exactly_at_deadline_stays_active
        """
        project = self._registered_on_the_deadline(api)

        system = fixtures.read_system(api, project)
        assert system["warranty_status"] == WarrantyStatus.ACTIVE
        assert_instant_equals(
            system["warranty_deadline_at"], WARRANTY_DEADLINE, "warranty_deadline_at"
        )
        assert_stamped_from_clock(system, "warranty_registered_at", WARRANTY_DEADLINE)
        assert system["warranty_coverage_years"] == 10

    def test_a_registration_on_the_deadline_is_not_counted_as_late(self, api):
        """The installer's lateness counter stays where the certification left it.

        Only a registration after the deadline instant voids coverage and counts against the
        installer, so a registration on the boundary leaves the counter at zero.

        PRD 3.6: "A registration landing after that instant sets `warranty_status` to `VOID` and increments the installer's `late_warranty_registration_count` by one."

        Design: Difficulty/boundary_precision_check/warranty_registration_exactly_at_deadline_stays_active
        """
        project = self._registered_on_the_deadline(api)

        installer = get_success_data(
            api.get_installer(project.installer_id, headers=project.installer_headers)
        )
        assert installer["late_warranty_registration_count"] == 0
