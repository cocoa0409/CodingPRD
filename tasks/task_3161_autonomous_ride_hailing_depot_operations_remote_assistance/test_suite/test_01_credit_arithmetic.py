"""Ride-credit provisioning: the territory pool and the per-ride credit.

The territory pool is provisioned from the demand curve at match time, and
both published figures floor their own division against the provision plus
a fixed denominator of 500, so they must be computed separately.
"""

from test_helpers import constants as c
from test_helpers.assertions import get_success_data, validate_success
from test_helpers.fixtures import (
    credit_stack,
    match_ride,
    read_territory,
    read_vehicle,
)
from test_helpers.test_users import FLEET


class TestTerritoryCreditProvisioning:
    """An ACTIVE territory provisions its pool from the demand curve."""

    def test_match_provisions_the_published_credit_literals(self, api):
        """Matching in an ACTIVE territory publishes the credit pair.

        PRD 2.10: "The signal's derived `effective_demand` is the greater of
        zero and the projected rides minus the manual-only rides; the zero floor
        matters because a curve can be entered with more manual-only demand than
        total demand, and it must not yield a negative figure."
        PRD 2.10: "Provision is ten times `effective_demand` when the territory
        is in any posture other than `RESTRICTED`."
        PRD 2.10: "The per-ride credit is 5,000,000 divided by that denominator,
        floored, and `total_credit_cents` is 5,000,000 multiplied by the provision
        and divided by the denominator, floored."
        PRD 3.4: "It also triggers the territory credit provisioning described in
        section 2.10: the territory's `total_credit_cents` is recomputed from the
        demand signal for the ride's window code, and the matched vehicle's
        `credit_cents` is credited."

        Design: Difficulty/dual_variant_calc/if_match_credit_open_vs_restricted_territory
        """
        stack = credit_stack(api, projected_rides=50, manual_only_rides=10)
        assert c.effective_demand(50, 10) == 40

        resp = match_ride(
            api,
            stack["territory"]["id"],
            stack["ride"]["id"],
            stack["pickup_location"]["id"],
            stack["vehicle"]["version"],
        )
        ride = validate_success(resp)

        assert ride["status"] == c.RIDE_MATCHED
        assert ride["vehicle_id"] == stack["vehicle"]["id"]

        territory = read_territory(api, stack["territory"]["id"])
        assert territory["total_credit_cents"] == c.total_credit_cents(40, c.POSTURE_ACTIVE)
        assert territory["total_credit_cents"] == 2_222_222, (
            f"expected the floored pool 2222222, got {territory['total_credit_cents']}"
        )

        vehicle = read_vehicle(api, stack["vehicle"]["id"])
        assert vehicle["credit_cents"] == c.credit_per_ride(40, c.POSTURE_ACTIVE)
        assert vehicle["credit_cents"] == 5_555, (
            f"expected the per-ride credit 5555, got {vehicle['credit_cents']}"
        )

    def test_match_credits_the_per_ride_amount_once(self, api):
        """The pool and the per-ride credit floor independently.

        PRD 2.10: "The per-ride credit is 5,000,000 divided by that denominator,
        floored, and `total_credit_cents` is 5,000,000 multiplied by the provision
        and divided by the denominator, floored."
        PRD 2.10: "Because each division floors independently, the two figures
        must be computed separately rather than one being derived from the other."

        Design: Difficulty/dual_variant_calc/if_match_credit_open_vs_restricted_territory
        """
        stack = credit_stack(
            api, projected_rides=50, manual_only_rides=10, idempotency_key="idem-credit-a2"
        )
        validate_success(
            match_ride(
                api,
                stack["territory"]["id"],
                stack["ride"]["id"],
                stack["pickup_location"]["id"],
                stack["vehicle"]["version"],
            )
        )

        signals = get_success_data(
            api.list_territory_demand_signals(stack["territory"]["id"], headers=FLEET)
        )
        assert signals[0]["effective_demand"] == 40

        territory = read_territory(api, stack["territory"]["id"])
        pool = territory["total_credit_cents"]
        assert pool == 2_222_222
        # The two literals are not derivable from one another: the pool is
        # provision * 5,000,000 / denominator while the per-ride credit is
        # 5,000,000 / denominator. Deriving the pool from the per-ride credit
        # would give 5555 * 400 == 2,222,000, a different figure.
        assert pool == 5_555 * 400 + 222
        assert pool != 5_555 * 400


class TestCreditInputs:
    """Every input of the three-input credit function moves the literal."""

    def test_demand_change_moves_both_credit_literals(self, api):
        """A second demand input resolves a different, equally exact pair.

        PRD 2.10: "Provision is ten times `effective_demand` when the territory
        is in any posture other than `RESTRICTED`."
        PRD 2.10: "The per-ride credit is 5,000,000 divided by that denominator,
        floored, and `total_credit_cents` is 5,000,000 multiplied by the provision
        and divided by the denominator, floored."

        Design: Difficulty/combinatorial_formula/if_match_credit_multi_input_threshold
        """
        stack = credit_stack(
            api, projected_rides=60, manual_only_rides=10, idempotency_key="idem-credit-b1"
        )
        assert c.effective_demand(60, 10) == 50

        validate_success(
            match_ride(
                api,
                stack["territory"]["id"],
                stack["ride"]["id"],
                stack["pickup_location"]["id"],
                stack["vehicle"]["version"],
            )
        )
        territory = read_territory(api, stack["territory"]["id"])
        assert territory["total_credit_cents"] == c.total_credit_cents(50, c.POSTURE_ACTIVE)
        assert territory["total_credit_cents"] == 2_500_000, (
            f"expected 2500000 for provision 500, got {territory['total_credit_cents']}"
        )

    def test_effective_demand_floors_at_zero(self, api):
        """More manual-only demand than total demand floors the curve at zero.

        PRD 2.10: "The signal's derived `effective_demand` is the greater of
        zero and the projected rides minus the manual-only rides; the zero floor
        matters because a curve can be entered with more manual-only demand than
        total demand, and it must not yield a negative figure."

        Design: Difficulty/combinatorial_formula/if_match_credit_multi_input_threshold
        """
        stack = credit_stack(
            api, projected_rides=10, manual_only_rides=25, idempotency_key="idem-credit-b2"
        )
        validate_success(
            match_ride(
                api,
                stack["territory"]["id"],
                stack["ride"]["id"],
                stack["pickup_location"]["id"],
                stack["vehicle"]["version"],
            )
        )
        signals = get_success_data(
            api.list_territory_demand_signals(stack["territory"]["id"], headers=FLEET)
        )
        assert signals[0]["effective_demand"] == 0, "the curve must not yield a negative figure"

        territory = read_territory(api, stack["territory"]["id"])
        assert territory["total_credit_cents"] == 0


class TestPerRideCreditLiteral:
    """The per-ride credit is pinned against a second demand input."""

    def test_per_ride_credit_literal_for_demand_thirty(self, api):
        """With effective demand 30 the per-ride credit resolves to 6250.

        PRD 2.10: "Provision is ten times `effective_demand` when the territory
        is in any posture other than `RESTRICTED`."
        PRD 2.10: "The per-ride credit is 5,000,000 divided by that denominator,
        floored, and `total_credit_cents` is 5,000,000 multiplied by the provision
        and divided by the denominator, floored."

        Design: Corner/calculations/if_match_credit_per_ride_literal_open_territory
        """
        stack = credit_stack(
            api, projected_rides=40, manual_only_rides=10, idempotency_key="idem-credit-c1"
        )
        assert c.effective_demand(40, 10) == 30
        validate_success(
            match_ride(
                api,
                stack["territory"]["id"],
                stack["ride"]["id"],
                stack["pickup_location"]["id"],
                stack["vehicle"]["version"],
            )
        )
        vehicle = read_vehicle(api, stack["vehicle"]["id"])
        assert vehicle["credit_cents"] == 6_250, (
            f"expected floor(5000000/800) == 6250, got {vehicle['credit_cents']}"
        )

    def test_pool_literal_for_demand_thirty(self, api):
        """The same curve resolves the territory pool to 1875000.

        PRD 2.10: "The per-ride credit is 5,000,000 divided by that denominator,
        floored, and `total_credit_cents` is 5,000,000 multiplied by the provision
        and divided by the denominator, floored."

        Design: Corner/calculations/if_match_credit_per_ride_literal_open_territory
        """
        stack = credit_stack(
            api, projected_rides=40, manual_only_rides=10, idempotency_key="idem-credit-c2"
        )
        validate_success(
            match_ride(
                api,
                stack["territory"]["id"],
                stack["ride"]["id"],
                stack["pickup_location"]["id"],
                stack["vehicle"]["version"],
            )
        )
        territory = read_territory(api, stack["territory"]["id"])
        assert territory["total_credit_cents"] == 1_875_000, (
            f"expected floor(5000000*300/800) == 1875000, got {territory['total_credit_cents']}"
        )