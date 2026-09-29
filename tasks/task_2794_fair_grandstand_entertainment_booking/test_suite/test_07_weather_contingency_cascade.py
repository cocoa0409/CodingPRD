"""A severe-weather cancellation and the chain it runs down the booking: the
production advance is cancelled, its rider lines are voided, its cost ledgers and
the booking's recoupable production cost fall to zero, the confirmed sponsorship
is cancelled against a make-good credit, and the stage hold is released.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.api_client import api_client
from test_helpers.assertions import (
    assert_contingency_action,
    assert_production_advance,
    assert_stage_posture,
)
from test_helpers.factories import build_contingency_action_payload
from test_helpers.test_users import FAIR_OPERATIONS_DIRECTOR_HEADERS

# The hospitality line the artist agreed to repay out of its own earnings.
RECOUPABLE_RIDER_COST_CENTS = 120_000
# A supporting sponsor buying signage on a show with no price tiers earns no
# premium at all, so the fee it is priced at is the base fee it bought.
CONFIRMED_ACTIVATION_FEE_CENTS = 1_000_000


def _weather_exposed_show():
    """A held show whose advance carries an approved recoupable hospitality line
    and whose sponsorship pool carries one confirmed signage package.

    The seed staging line is deliberately left unruled, so the advance is still
    in review when the weather call is made, and no price tier is ever built, so
    there are no sold units to refund.
    """
    world = fixtures.setup_base_world(
        edition_overrides={"name": "Weather Cascade Fair"}
    )
    scenario = fixtures.setup_accepted_booking(world)

    hospitality = fixtures.add_rider_item(
        scenario["advance"]["id"],
        category="HOSPITALITY",
        description="Dressing room hospitality buyout",
        requested_cost_cents=RECOUPABLE_RIDER_COST_CENTS,
        is_critical=False,
        artist_recoupable=True,
    )
    fixtures.rule_rider_item(hospitality["id"], "APPROVED")

    sponsor = fixtures.create_sponsor(
        name="Valley Mutual", category="FINANCIAL", exclusivity_tier="SUPPORTING"
    )
    activation = fixtures.create_activation(
        sponsor["id"],
        scenario["booking"]["id"],
        rights="SIGNAGE",
        base_fee_cents=CONFIRMED_ACTIVATION_FEE_CENTS,
        exclusivity_category="FINANCIAL",
    )
    fixtures.confirm_activation(activation["id"])

    scenario["hospitality_rider_item"] = hospitality
    scenario["sponsor"] = sponsor
    scenario["activation"] = fixtures.get_activation(activation["id"])
    scenario["advance"] = fixtures.get_advance(scenario["advance"]["id"])
    scenario["booking"] = fixtures.get_booking(scenario["booking"]["id"])
    return scenario


def _call_off_the_show(booking_id):
    """Record the severe-weather cancellation, echoing the booking version read a
    moment ago because the cascades move that version constantly.
    """
    payload = build_contingency_action_payload(
        fixtures.booking_version(booking_id),
        action_type="CANCEL",
        reason_code="SEVERE_WEATHER",
        refund_policy="FULL_REFUND",
    )
    return validate_success(
        api_client.create_contingency_action(
            booking_id, payload, FAIR_OPERATIONS_DIRECTOR_HEADERS
        ),
        expected_status=201,
    )


class TestSevereWeatherCancellationCascade:
    """One weather decision, followed down every hop it forces."""

    def test_approved_recoupable_line_reaches_the_booking_before_the_weather_call(self):
        """An approved hospitality line the artist agreed to repay is summed into
        the advance's recoupable cost, and the booking's recoupable production cost
        mirrors that figure while the show is still alive.

        "A change to `recoupable_rider_cost_cents` propagates one hop further: the booking's `recoupable_production_cost_cents` mirrors it"

        Design: Difficulty/transitive_cascade/weather_cancellation_voids_riders_and_zeroes_recoupment
        """
        scenario = _weather_exposed_show()

        advance = scenario["advance"]
        assert_production_advance(advance)
        assert advance["status"] == "ADVANCE_IN_REVIEW"
        assert advance["approved_rider_cost_cents"] == RECOUPABLE_RIDER_COST_CENTS
        assert advance["recoupable_rider_cost_cents"] == RECOUPABLE_RIDER_COST_CENTS
        assert (
            scenario["booking"]["recoupable_production_cost_cents"]
            == RECOUPABLE_RIDER_COST_CENTS
        )

    def test_cancellation_cancels_the_advance_and_voids_every_rider_line(self):
        """The severe-weather cancellation kills the show, cancels the production
        advance beneath it and voids both rider lines — the ruled hospitality line
        and the seed staging line still waiting on a decision.

        "The booking's production advance moves to `ADVANCE_CANCELLED`; every rider line of that advance whose status is `REQUESTED`, `APPROVED`, `SUBSTITUTED` or `DENIED` becomes `VOIDED` with its `approved_cost_cents` set to 0"

        Design: Difficulty/transitive_cascade/weather_cancellation_voids_riders_and_zeroes_recoupment
        """
        scenario = _weather_exposed_show()

        _call_off_the_show(scenario["booking"]["id"])

        booking = fixtures.get_booking(scenario["booking"]["id"])
        assert booking["booking_status"] == "CANCELLED"

        advance = fixtures.get_advance(scenario["advance"]["id"])
        assert advance["status"] == "ADVANCE_CANCELLED"
        assert advance["blocked_reason_code"] is None

        hospitality = fixtures.get_rider_item(
            scenario["hospitality_rider_item"]["id"]
        )
        assert hospitality["status"] == "VOIDED"
        assert hospitality["approved_cost_cents"] == 0

        seed = fixtures.get_rider_item(scenario["seed_rider_item"]["id"])
        assert seed["status"] == "VOIDED"

    def test_cancellation_zeroes_the_advance_ledgers_and_the_booking_recoupment(self):
        """With every rider line voided the advance's three cost ledgers recompute
        to nothing, and the booking's recoupable production cost follows them down
        from the figure it carried a moment earlier.

        "the advance's `approved_rider_cost_cents`, `recoupable_rider_cost_cents` and `denied_item_count` therefore all recompute to 0"

        Design: Difficulty/transitive_cascade/weather_cancellation_voids_riders_and_zeroes_recoupment
        """
        scenario = _weather_exposed_show()
        assert (
            scenario["booking"]["recoupable_production_cost_cents"]
            == RECOUPABLE_RIDER_COST_CENTS
        )

        _call_off_the_show(scenario["booking"]["id"])

        advance = fixtures.get_advance(scenario["advance"]["id"])
        assert advance["approved_rider_cost_cents"] == 0
        assert advance["recoupable_rider_cost_cents"] == 0
        assert advance["denied_item_count"] == 0

        booking = fixtures.get_booking(scenario["booking"]["id"])
        assert booking["recoupable_production_cost_cents"] == 0

    def test_cancellation_credits_the_sponsor_and_empties_the_show_pool(self):
        """The confirmed signage package is cancelled with the fair owing the
        sponsor a make-good credit for the rights it will not deliver, and the
        show's sponsorship revenue is recomputed to nothing.

        "Every sponsorship activation on the booking whose status is `PROPOSED` or `CONFIRMED` becomes `CANCELLED` with its `make_good_credit_cents` set to its `net_fee_cents`"

        Design: Difficulty/transitive_cascade/weather_cancellation_voids_riders_and_zeroes_recoupment
        """
        scenario = _weather_exposed_show()
        assert (
            scenario["booking"]["sponsorship_revenue_cents"]
            == CONFIRMED_ACTIVATION_FEE_CENTS
        )

        _call_off_the_show(scenario["booking"]["id"])

        activation = fixtures.get_activation(scenario["activation"]["id"])
        assert activation["status"] == "CANCELLED"
        assert activation["make_good_credit_cents"] == CONFIRMED_ACTIVATION_FEE_CENTS

        booking = fixtures.get_booking(scenario["booking"]["id"])
        assert booking["sponsorship_revenue_cents"] == 0

    def test_zero_refund_liability_closes_the_box_office_in_the_same_request(self):
        """The show was never scaled, so there is nothing to refund: the decision is
        taken before any doors instant exists, its liability computes to nothing and
        the box-office dimension closes out immediately rather than sitting in
        refunding.

        "when the computed `refund_liability_cents` is 0, nothing is owed to patrons, so the box-office dimension closes immediately"

        Design: Difficulty/transitive_cascade/weather_cancellation_voids_riders_and_zeroes_recoupment
        """
        scenario = _weather_exposed_show()

        action = _call_off_the_show(scenario["booking"]["id"])

        assert_contingency_action(action)
        assert action["action_type"] == "CANCEL"
        assert action["reason_code"] == "SEVERE_WEATHER"
        assert action["pre_doors"] is True
        assert action["refund_liability_cents"] == 0

        booking = fixtures.get_booking(scenario["booking"]["id"])
        assert booking["ticketing_status"] == "REFUNDED"
        assert booking["refund_liability_cents"] == 0

    def test_cancelled_show_releases_the_stage_hold_it_occupied(self):
        """A cancelled show stops occupying its slot, so the stage's held-show count
        drops back to nothing and the stage advertises itself as open again.

        "The stage's `held_show_count` falls by one, flipping `booking_posture` back to `OPEN` once the count sits below `slot_soft_cap`"

        Design: Difficulty/transitive_cascade/weather_cancellation_voids_riders_and_zeroes_recoupment
        """
        scenario = _weather_exposed_show()
        assert fixtures.get_stage(scenario["stage"]["id"])["held_show_count"] == 1

        _call_off_the_show(scenario["booking"]["id"])

        stage = fixtures.get_stage(scenario["stage"]["id"])
        assert stage["held_show_count"] == 0
        assert stage["booking_posture"] == "OPEN"
        assert_stage_posture(stage)
