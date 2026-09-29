"""Immediate consistency: what a write's own response body already shows."""

from test_helpers import (
    assert_equals,
    assert_fields,
    assert_provider_counters,
    expect_ok,
)
from test_helpers.constants import NUMBER_1


class TestSweepResponseIsAlreadySettled:
    """The sweep body and the read that follows it agree on every counter."""

    def test_the_sweep_body_already_carries_the_post_cascade_counters(self, world):
        """Points, notice count, index and posture are settled inside the sweep response.

        PRD: "The sweep itself is a `Regulator`-only capability that takes a single `provider_id` and returns the refreshed provider row."

        Design: Corner/consistency_model/sweep_response_already_carries_every_recomputed_counter
        """
        world.set_clock("2026-08-01T00:00:00Z")
        provider = world.register_provider()
        notice = world.serve_notice(provider["id"], calling_number=NUMBER_1)
        world.set_clock("2026-08-06T00:00:00Z")

        swept = expect_ok(world.client.run_sweep(provider["id"], world.regulator))

        assert_provider_counters(
            swept,
            penalty_points=5,
            open_notice_count=0,
            sweep_index=1,
            overdue_traceback_count=0,
        )
        assert_equals(swept, "auth_posture", "SIGNING_SUSPENDED")

        read_back = expect_ok(
            world.client.get_provider(provider["id"], world.regulator)
        )

        assert_provider_counters(
            read_back, penalty_points=5, open_notice_count=0, sweep_index=1
        )
        assert_equals(read_back, "version", swept["version"])

        expired = world.read_notice(notice["id"])
        assert_fields(
            expired, state="EXPIRED_UNMITIGATED", penalty_points_assessed=5
        )

        assert_equals(read_back, "rmd_filing_status", "UNFILED")
        assert_provider_counters(read_back, outstanding_forfeiture_cents=0)
