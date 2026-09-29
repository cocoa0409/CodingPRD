"""Studbook lateness scoring: the surcharge tier is keyed on capped base points."""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_success
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.test_users import make_admin_headers

FILING_CLOCK = "2026-07-15T09:00:00Z"


def _filing_world(api):
    """One institution and one programme, with the clock parked before filing."""
    api.set_clock("2026-07-01T00:00:00Z", make_admin_headers())
    world = fx.base_world(api, publish=False)
    world.set_clock(FILING_CLOCK)
    return world


def _file(world, reporting_period_end, submission_type="BIRTH"):
    return validate_success(
        world.api.create_studbook_submission(
            f.studbook_submission_payload(
                world.program_id, world.sender_id,
                submission_type=submission_type,
                reporting_period_end=reporting_period_end,
            ),
            world.sender,
        ),
        201,
    )


class TestStudbookSurchargeTier:
    """The multiplier comes from base_points alone, after the twenty-point cap."""

    def test_fifteen_days_late_earns_the_one_tenth_tier(self, api):
        """7.50 base points sit in the 3-to-8 band, so the surcharge is 0.75.

        PRD: "The `surcharge_multiplier` is then selected **from `base_points`
        alone and never re-evaluated afterwards**: four tenths where
        `base_points` has reached 15 or more, one quarter where it has reached 8
        but not 15, one tenth where it has reached 3 but not 8, and zero below 3."

        Design: Difficulty/combinatorial_formula/studbook_surcharge_tier_keyed_on_base_points_only
        """
        world = _filing_world(api)
        data = _file(world, "2026-05-31")
        assert data["submitted_on"].startswith("2026-07-15")
        assert data["days_late"] == 15
        assert_money(data["base_points"], 7.50, "base_points")
        assert_money(data["surcharge_multiplier"], 0.10, "surcharge_multiplier")
        assert_money(data["surcharge_points"], 0.75, "surcharge_points")
        assert_money(data["total_compliance_points"], 8.25,
                     "total_compliance_points")
        assert float(data["total_compliance_points"]) != 9.38
        assert data["status"] == "SUBMITTED"

    def test_filing_posts_nothing_to_the_institution_balance(self, api):
        """The four lateness figures stay on the submission until review.

        PRD: "None of those four figures is posted anywhere at filing time."

        Design: Difficulty/combinatorial_formula/studbook_surcharge_tier_keyed_on_base_points_only
        """
        world = _filing_world(api)
        _file(world, "2026-05-31")
        assert_money(
            world.read_institution(world.sender_id)["compliance_points_balance"],
            0.00, "compliance_points_balance",
        )
        assert world.read_institution(world.sender_id)["accreditation_status"] == \
            "ACCREDITED"

    def test_forty_days_late_caps_the_base_at_twenty_before_the_surcharge(self, api):
        """20.00 base points draw a four-tenths surcharge and total 28.00.

        PRD: "A filing forty days past the deadline therefore earns 20.00 base
        points after the cap, a four-tenths surcharge of 8.00 points, and 28.00
        total compliance points."

        Design: Difficulty/combinatorial_formula/studbook_surcharge_tier_keyed_on_base_points_only
        """
        world = _filing_world(api)
        data = _file(world, "2026-05-06")
        assert data["days_late"] == 40
        assert_money(data["base_points"], 20.00, "base_points")
        assert_money(data["surcharge_multiplier"], 0.40, "surcharge_multiplier")
        assert_money(data["surcharge_points"], 8.00, "surcharge_points")
        assert_money(data["total_compliance_points"], 28.00,
                     "total_compliance_points")

    def test_fifty_days_late_scores_the_same_as_forty_because_of_the_cap(self, api):
        """The cap binds before the surcharge, so 50 days also totals 28.00.

        PRD: "`base_points` is `days_late` multiplied by half a point per day,
        rounded half up to two decimal places, and then **capped at 20 points**;
        the cap is applied before anything else happens, not after."

        Design: Difficulty/combinatorial_formula/studbook_surcharge_tier_keyed_on_base_points_only
        """
        world = _filing_world(api)
        data = _file(world, "2026-04-26")
        assert data["days_late"] == 50
        assert_money(data["base_points"], 20.00, "base_points")
        assert_money(data["total_compliance_points"], 28.00,
                     "total_compliance_points")
        assert float(data["total_compliance_points"]) != 35.00

    def test_an_early_filing_is_never_negative_and_draws_no_surcharge(self, api):
        """A filing five days before the deadline scores zero on all four figures.

        PRD: "`days_late` is the whole days by which `submitted_on` falls after
        that deadline, or 0 when the filing was on time or early — it is never
        negative."

        Design: Difficulty/combinatorial_formula/studbook_surcharge_tier_keyed_on_base_points_only
        """
        world = _filing_world(api)
        data = _file(world, "2026-06-20")
        assert data["days_late"] == 0
        assert_money(data["base_points"], 0.00, "base_points")
        assert_money(data["surcharge_multiplier"], 0.00, "surcharge_multiplier")
        assert_money(data["surcharge_points"], 0.00, "surcharge_points")
        assert_money(data["total_compliance_points"], 0.00,
                     "total_compliance_points")
