"""The introduction protocol's cyclic stage machine and its two accumulators."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_success
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money


class TestProtocolRegressesThenReadvances:
    """HOWDY to PARTIAL_CONTACT to HOWDY to PARTIAL_CONTACT, driven by observations."""

    def test_three_calm_sessions_advance_out_of_howdy(self, api):
        """The third calm observation advances the stage and resets both counters.

        PRD: "Advancement is considered only when the accumulator is still below
        6 points, and then requires two things at once: `sessions_at_stage`,
        counting this observation, must have reached at least 3, and the last two
        observations recorded at this stage — this one included — must both be
        `CALM`."

        Design: Difficulty/non_linear_state_machine/introduction_protocol_regresses_then_readvances
        """
        world = fx.world_with_protocol(api)
        opened = world.read_protocol()
        assert opened["stage"] == "HOWDY"
        assert opened["sessions_at_stage"] == 0
        assert opened["regression_count"] == 0
        assert_money(opened["aggression_score_total"], 0.00,
                     "aggression_score_total")
        first = fx.observe(world, "CALM", observed_on="2026-10-02")
        assert first["stage"] == "HOWDY"
        assert first["sessions_at_stage"] == 1
        second = fx.observe(world, "CALM", observed_on="2026-10-03")
        assert second["stage"] == "HOWDY"
        assert second["sessions_at_stage"] == 2
        third = fx.observe(world, "CALM", observed_on="2026-10-04")
        assert third["stage"] == "PARTIAL_CONTACT"
        assert third["sessions_at_stage"] == 0
        assert third["observation_count"] == 3
        assert third["regression_count"] == 0

    def test_three_minor_aggressions_regress_the_protocol_one_stage(self, api):
        """A six-point stage accumulator drops PARTIAL_CONTACT back to HOWDY.

        PRD: "If the stage accumulator has reached 6 points or more, the protocol
        regresses one stage — `FULL_CONTACT` back to `PARTIAL_CONTACT`, or
        `PARTIAL_CONTACT` back to `HOWDY` — incrementing `regression_count` by 1
        and resetting both stage counters."

        Design: Difficulty/non_linear_state_machine/introduction_protocol_regresses_then_readvances
        """
        world = fx.world_with_protocol(api)
        fx.advance_one_stage(world)
        fourth = fx.observe(world, "MINOR_AGGRESSION", observed_on="2026-10-05")
        assert fourth["stage"] == "PARTIAL_CONTACT"
        assert fourth["sessions_at_stage"] == 1
        fifth = fx.observe(world, "MINOR_AGGRESSION", observed_on="2026-10-06")
        assert fifth["stage"] == "PARTIAL_CONTACT"
        assert fifth["sessions_at_stage"] == 2
        sixth = fx.observe(world, "MINOR_AGGRESSION", observed_on="2026-10-07")
        assert sixth["stage"] == "HOWDY"
        assert sixth["regression_count"] == 1
        assert sixth["sessions_at_stage"] == 0
        assert sixth["observation_count"] == 6
        assert_money(sixth["aggression_score_total"], 6.00,
                     "aggression_score_total")

    def test_the_cycle_readvances_with_the_lifetime_total_intact(self, api):
        """Nine observations end back at PARTIAL_CONTACT with one regression spent.

        PRD: "`aggression_score_total` is the sum of points over every
        observation ever recorded and is likewise never reset; it is stored to two
        decimal places for envelope consistency although its value is always a
        whole number."

        Design: Difficulty/non_linear_state_machine/introduction_protocol_regresses_then_readvances
        """
        world = fx.world_with_protocol(api)
        fx.advance_one_stage(world)
        for day in ("2026-10-05", "2026-10-06", "2026-10-07"):
            fx.observe(world, "MINOR_AGGRESSION", observed_on=day)
        seventh = fx.observe(world, "CALM", observed_on="2026-10-08")
        assert seventh["stage"] == "HOWDY"
        eighth = fx.observe(world, "CALM", observed_on="2026-10-09")
        assert eighth["stage"] == "HOWDY"
        ninth = fx.observe(world, "CALM", observed_on="2026-10-10")
        assert ninth["stage"] == "PARTIAL_CONTACT"
        assert ninth["regression_count"] == 1
        assert ninth["observation_count"] == 9
        assert ninth["sessions_at_stage"] == 0
        assert_money(ninth["aggression_score_total"], 6.00,
                     "aggression_score_total")
        assert world.read_animal(world.m1_id)["location_status"] == "INTRODUCING"

    def test_the_protocol_version_increments_on_every_observation(self, api):
        """Each of the nine observations bumps the protocol's version by one.

        PRD: "The protocol's `version` increments by 1 on every recorded
        observation, whether or not the stage changed."

        Design: Difficulty/non_linear_state_machine/introduction_protocol_regresses_then_readvances
        """
        world = fx.world_with_protocol(api)
        opening_version = world.read_protocol()["version"]
        levels = ["CALM"] * 3 + ["MINOR_AGGRESSION"] * 3 + ["CALM"] * 3
        for index, level in enumerate(levels):
            data = fx.observe(world, level,
                              observed_on=f"2026-10-{2 + index:02d}")
            assert data["version"] == opening_version + index + 1
        assert world.read_protocol()["stage"] == "PARTIAL_CONTACT"

    def test_a_single_severe_aggression_neither_regresses_nor_advances(self, api):
        """Five points is below the six-point threshold, so the stage holds.

        PRD: "Note also that a single `SEVERE_AGGRESSION` observation is worth 5
        points and does not on its own reach the six-point threshold, while three
        `MINOR_AGGRESSION` observations at one stage total 6 and do."

        Design: Difficulty/non_linear_state_machine/introduction_protocol_regresses_then_readvances
        """
        world = fx.world_with_protocol(api)
        fx.advance_one_stage(world)
        data = fx.observe(world, "SEVERE_AGGRESSION", observed_on="2026-10-05")
        assert data["stage"] == "PARTIAL_CONTACT"
        assert data["regression_count"] == 0
        assert data["sessions_at_stage"] == 1
        assert_money(data["aggression_score_total"], 5.00,
                     "aggression_score_total")
