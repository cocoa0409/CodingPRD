"""Inclusive boundaries, proved on the value itself and on its nearest neighbour.

A three-decimal exposure exactly at the safe harbor level, an instant exactly at
the cure deadline, and an integer exactly at the cure unit ceiling.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CURE_NOT_AVAILABLE,
    ERR_CURE_WINDOW_CLOSED,
)
from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_exposure,
    assert_instant,
    assert_margin,
    assert_posture,
    assert_status,
)
from test_helpers.constants import (
    CURE_UNIT_CEILING,
    DEFAULT_CLOCK,
    METHOD_MODELED,
    NOTICE_CURE_ELECTED,
    NOTICE_CURED_WITHIN_WINDOW,
    NOTICE_UNDER_EVALUATION,
    POSTURE_ENFORCEMENT_HOLD,
    RESULT_AT_OR_ABOVE,
    RESULT_BELOW,
    ROUTE_DERMAL,
)
from test_helpers.fixtures import (
    build_warned_product,
    elect_cure,
    evaluate_notice,
    make_assessment,
    make_bpa,
    make_notice,
    make_product,
    make_product_with_component,
    read_product,
    set_clock,
)
from test_helpers.test_users import REGULATORY_COUNSEL


CURE_DEADLINE = "2026-07-31T00:00:00Z"
ONE_SECOND_LATE = "2026-07-31T00:00:01Z"


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def linear_exposure_product(api):
    """One VERIFIED component whose DERMAL exposure is exactly uses_per_day times 0.5 ug.

    40.0 ppm x 0.25 g x 0.5 contact x 0.10 dermal = 0.5 ug per use, so
    uses_per_day 1.0 lands exactly on the 0.5 ug/day MADL and 0.998 lands one
    thousandth below it.
    """
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    base = make_product_with_component(
        api,
        chemical["id"],
        sku="SKU-BP1",
        product_overrides={"product_name": "Measuring Scoop", "annual_units": 50000},
    )
    base["chemical"] = chemical
    return base


@pytest.fixture
def twin_cure_elected_notices(api):
    """Two notices served 2026-06-01 on a fully warned product, both CURE_ELECTED.

    The whole bill of materials and the whole warning chain are written before
    either notice exists, because the first notice freezes the bill of
    materials, and the determination covers its one required channel so the
    cure-completion coverage precondition already holds.
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    chemical = make_bpa(api)
    bundle = build_warned_product(
        api,
        chemical["id"],
        sku="SKU-BP2",
        route=ROUTE_DERMAL,
        product_overrides={"product_name": "Picnic Tumbler", "annual_units": 50000},
    )
    product_id = bundle["product"]["id"]
    on_time = make_notice(
        api,
        product_id,
        chemical["id"],
        earliest_violation_date="2026-06-01T00:00:00Z",
        served_at="2026-06-01T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )
    late = make_notice(
        api,
        product_id,
        chemical["id"],
        earliest_violation_date="2026-06-01T00:00:00Z",
        served_at="2026-06-01T00:00:00Z",
        noticing_party_name="Delta Watch Alliance",
    )
    evaluate_notice(api, on_time["id"])
    on_time = elect_cure(api, on_time["id"])
    evaluate_notice(api, late["id"])
    late = elect_cure(api, late["id"])
    bundle["chemical"] = chemical
    bundle["on_time"] = on_time
    bundle["late"] = late
    return bundle


@pytest.fixture
def ceiling_and_over_ceiling_notices(api):
    """One product at exactly 100000 annual units and its twin at 100001, each noticed."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    at_ceiling = make_product(
        api,
        "SKU-BP3A",
        product_name="Ceiling Product",
        annual_units=CURE_UNIT_CEILING,
    )
    over_ceiling = make_product(
        api,
        "SKU-BP3B",
        product_name="Over Ceiling Product",
        annual_units=CURE_UNIT_CEILING + 1,
    )
    notice_at = make_notice(
        api,
        at_ceiling["id"],
        chemical["id"],
        earliest_violation_date="2026-07-01T00:00:00Z",
        served_at="2026-07-15T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )
    notice_over = make_notice(
        api,
        over_ceiling["id"],
        chemical["id"],
        earliest_violation_date="2026-07-01T00:00:00Z",
        served_at="2026-07-15T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )
    return {
        "chemical": chemical,
        "at_ceiling": at_ceiling,
        "over_ceiling": over_ceiling,
        "notice_at": notice_at,
        "notice_over": notice_over,
    }


def _read_notice(api, notice_id):
    return get_success_data(api.get_notice(notice_id, REGULATORY_COUNSEL))


def _complete_cure(api, notice_id):
    return api.notice_transition(
        notice_id, f.action_payload("COMPLETE_CURE"), REGULATORY_COUNSEL
    )


def _dermal_assessment(api, bundle, uses_per_day):
    return make_assessment(
        api,
        bundle["product"]["id"],
        bundle["chemical"]["id"],
        METHOD_MODELED,
        ROUTE_DERMAL,
        uses_per_day,
    )


# ─────────────────────────────────────────────────────────────────────────────
# The safe harbor comparison is inclusive
# ─────────────────────────────────────────────────────────────────────────────


class TestSafeHarborInclusiveComparison:
    def test_an_exposure_exactly_at_the_level_is_at_or_above(
        self, api, linear_exposure_product
    ):
        """0.500 ug/day against a 0.5 ug/day MADL is the adverse verdict, not the safe one.

        PRD: "The comparison is **inclusive**: an exposure exactly equal to the safe harbor level is `AT_OR_ABOVE_SAFE_HARBOR`, and it is the three-decimal `daily_exposure_ug` value that is compared, not any intermediate."

        Design: Difficulty/boundary_precision_check/exposure_exactly_at_safe_harbor_is_at_or_above
        """
        assessment = _dermal_assessment(api, linear_exposure_product, 1.0)
        assert_exposure(assessment["daily_exposure_ug"], 0.5)
        assert_margin(assessment["margin_ratio"], 1.0)
        assert assessment["result"] == RESULT_AT_OR_ABOVE

    def test_one_thousandth_below_the_level_is_below(
        self, api, linear_exposure_product
    ):
        """0.499 ug/day is strictly less than the level, so the verdict flips to BELOW.

        PRD: "Otherwise `margin_ratio` is `daily_exposure_ug` divided by `safe_harbor_level_ug_per_day`, rounded half up to four decimal places, and `result` is `AT_OR_ABOVE_SAFE_HARBOR` when `daily_exposure_ug` is greater than or equal to the level and `BELOW_SAFE_HARBOR` when it is strictly less."

        Design: Difficulty/boundary_precision_check/exposure_exactly_at_safe_harbor_is_at_or_above
        """
        assessment = _dermal_assessment(api, linear_exposure_product, 0.998)
        assert_assessment_verdict(assessment, 0.499, 0.998, RESULT_BELOW, 1)

    def test_the_two_verdicts_differ_on_one_thousandth_of_a_microgram(
        self, api, linear_exposure_product
    ):
        """Identical stored rows, a 0.001 ug/day gap, and opposite verdicts either side of it.

        PRD: "**The safe-harbor verdict.** Immediately after every daily-exposure evaluation the server compares the figure against the chemical's current safe harbor level and writes `margin_ratio` and `result`."

        Design: Difficulty/boundary_precision_check/exposure_exactly_at_safe_harbor_is_at_or_above
        """
        at_level = _dermal_assessment(api, linear_exposure_product, 1.0)
        below = _dermal_assessment(api, linear_exposure_product, 0.998)
        assert at_level["result"] == RESULT_AT_OR_ABOVE
        assert below["result"] == RESULT_BELOW
        assert at_level["daily_exposure_ug"] - below["daily_exposure_ug"] == (
            pytest.approx(0.001, abs=1e-6)
        )


# ─────────────────────────────────────────────────────────────────────────────
# The cure window is inclusive of the deadline instant
# ─────────────────────────────────────────────────────────────────────────────


class TestCureDeadlineInstant:
    def test_the_deadline_is_sixty_whole_days_after_service(
        self, api, twin_cure_elected_notices
    ):
        """Sixty times eighty-six thousand four hundred seconds from 2026-06-01 is 2026-07-31.

        PRD: "Intake computes `cure_deadline_at` as `served_at` plus a cure window of exactly sixty days, that is sixty times eighty-six thousand four hundred seconds, and the window is **inclusive** of that instant."

        Design: Difficulty/boundary_precision_check/complete_cure_at_exact_deadline_instant_then_one_second_later
        """
        bundle = twin_cure_elected_notices
        for notice in (bundle["on_time"], bundle["late"]):
            assert_instant(notice["cure_deadline_at"], CURE_DEADLINE, "cure_deadline_at")
            assert notice["cure_eligible"] is True
            assert_status(notice, NOTICE_CURE_ELECTED)

    def test_completing_the_cure_at_the_exact_deadline_is_inside_the_window(
        self, api, twin_cure_elected_notices
    ):
        """The instant equal to the deadline still cures, and it is stamped as the completion.

        PRD: "From `CURE_ELECTED`, completing the cure takes the notice to `CURED_WITHIN_WINDOW`, which requires that the current logical clock is at or before `cure_deadline_at` (the instant exactly equal to the deadline is still inside the window; one microsecond later the request is refused with `ERR_CURE_WINDOW_CLOSED`) and that the product now holds a determination in status `APPROVED` whose `covered_channel_count` equals the number of entries in its `required_channels` — the warning must actually be up on every required channel."

        Design: Difficulty/boundary_precision_check/complete_cure_at_exact_deadline_instant_then_one_second_later
        """
        bundle = twin_cure_elected_notices
        set_clock(api, CURE_DEADLINE)
        cured = get_success_data(_complete_cure(api, bundle["on_time"]["id"]))
        assert_status(cured, NOTICE_CURED_WITHIN_WINDOW)
        assert_instant(cured["cure_completed_at"], CURE_DEADLINE, "cure_completed_at")

    def test_one_second_after_the_deadline_the_window_is_closed(
        self, api, twin_cure_elected_notices
    ):
        """The twin notice differs only in the clock it is cured at, and it is refused.

        PRD: "**Layer 6 — temporal business rules.** In order: (1) a placement whose closed effective window intersects an existing window → `ERR_PLACEMENT_OVERLAP`; (2) a reformulation project whose half-open planned window intersects an existing one → `ERR_REFORMULATION_OVERLAP`; (3) cure completion requested after the cure deadline has passed → `ERR_CURE_WINDOW_CLOSED`; (4) a notice whose `earliest_violation_date` is later than its `served_at`, or whose `served_at` is later than the current logical clock → `ERR_INVALID_INTERVAL`; (5) warranty revocation while the warranty window still covers a live notice → `ERR_WARRANTY_IN_USE`."

        Design: Difficulty/boundary_precision_check/complete_cure_at_exact_deadline_instant_then_one_second_later
        """
        bundle = twin_cure_elected_notices
        set_clock(api, CURE_DEADLINE)
        get_success_data(_complete_cure(api, bundle["on_time"]["id"]))

        set_clock(api, ONE_SECOND_LATE)
        validate_error(
            _complete_cure(api, bundle["late"]["id"]), ERR_CURE_WINDOW_CLOSED, 409
        )
        unchanged = _read_notice(api, bundle["late"]["id"])
        assert_status(unchanged, NOTICE_CURE_ELECTED)
        assert unchanged["cure_completed_at"] is None

    def test_only_the_cured_notice_leaves_the_open_set(
        self, api, twin_cure_elected_notices
    ):
        """One notice cured, one still open, so the product stays on ENFORCEMENT_HOLD.

        PRD: "Completion stamps `cure_completed_at` with the current logical clock, then cascades: the product's `open_notice_count` decrements by 1, and because that count changed, `compliance_posture` is recomputed and leaves `ENFORCEMENT_HOLD` once the count reaches 0."

        Design: Difficulty/boundary_precision_check/complete_cure_at_exact_deadline_instant_then_one_second_later
        """
        bundle = twin_cure_elected_notices
        assert read_product(api, bundle["product"]["id"])["open_notice_count"] == 2

        set_clock(api, CURE_DEADLINE)
        get_success_data(_complete_cure(api, bundle["on_time"]["id"]))
        set_clock(api, ONE_SECOND_LATE)
        validate_error(
            _complete_cure(api, bundle["late"]["id"]), ERR_CURE_WINDOW_CLOSED, 409
        )

        product = read_product(api, bundle["product"]["id"])
        assert product["open_notice_count"] == 1
        assert_posture(product, POSTURE_ENFORCEMENT_HOLD)


# ─────────────────────────────────────────────────────────────────────────────
# The cure unit ceiling is inclusive
# ─────────────────────────────────────────────────────────────────────────────


class TestCureUnitCeiling:
    def test_exactly_one_hundred_thousand_units_is_still_eligible(
        self, api, ceiling_and_over_ceiling_notices
    ):
        """The bound is inclusive, so the product sitting exactly on it keeps its cure right.

        PRD: "Third, the product's `annual_units` must be at most one hundred thousand units, and this bound is inclusive, so a product selling exactly one hundred thousand units into California per year is still eligible."

        Design: Difficulty/boundary_precision_check/cure_eligibility_at_exact_annual_unit_ceiling_and_one_above
        """
        bundle = ceiling_and_over_ceiling_notices
        assert bundle["at_ceiling"]["annual_units"] == 100000
        assert_instant(
            bundle["notice_at"]["cure_deadline_at"],
            "2026-09-13T00:00:00Z",
            "cure_deadline_at",
        )

        evaluated = evaluate_notice(api, bundle["notice_at"]["id"])
        assert_status(evaluated, NOTICE_UNDER_EVALUATION)
        assert evaluated["cure_eligible"] is True

    def test_one_unit_above_the_ceiling_is_not_eligible(
        self, api, ceiling_and_over_ceiling_notices
    ):
        """100001 units fails the third condition, and one failed condition decides the flag.

        PRD: "**Cure eligibility.** The evaluation action takes the notice `RECEIVED → UNDER_EVALUATION` and computes `cure_eligible` from four conditions that must **all** hold."

        Design: Difficulty/boundary_precision_check/cure_eligibility_at_exact_annual_unit_ceiling_and_one_above
        """
        bundle = ceiling_and_over_ceiling_notices
        assert bundle["over_ceiling"]["annual_units"] == 100001

        evaluated = evaluate_notice(api, bundle["notice_over"]["id"])
        assert_status(evaluated, NOTICE_UNDER_EVALUATION)
        assert evaluated["cure_eligible"] is False

    def test_the_ceiling_notice_may_elect_the_cure(
        self, api, ceiling_and_over_ceiling_notices
    ):
        """A true eligibility flag makes ELECT_CURE a legal transition and sets the durable marker.

        PRD: "The first branch elects to cure, taking the notice `UNDER_EVALUATION → CURE_ELECTED`."

        Design: Difficulty/boundary_precision_check/cure_eligibility_at_exact_annual_unit_ceiling_and_one_above
        """
        bundle = ceiling_and_over_ceiling_notices
        evaluate_notice(api, bundle["notice_at"]["id"])
        elected = elect_cure(api, bundle["notice_at"]["id"])
        assert_status(elected, NOTICE_CURE_ELECTED)
        assert elected["cure_attempted"] is True

    def test_the_one_unit_heavier_twin_is_refused_and_does_not_move(
        self, api, ceiling_and_over_ceiling_notices
    ):
        """One extra unit turns the same request into ERR_CURE_NOT_AVAILABLE.

        PRD: "When `cure_eligible` is false or has not been computed yet, the request is refused with `ERR_CURE_NOT_AVAILABLE`."

        Design: Difficulty/boundary_precision_check/cure_eligibility_at_exact_annual_unit_ceiling_and_one_above
        """
        bundle = ceiling_and_over_ceiling_notices
        evaluate_notice(api, bundle["notice_over"]["id"])
        validate_error(
            api.notice_transition(
                bundle["notice_over"]["id"],
                f.action_payload("ELECT_CURE"),
                REGULATORY_COUNSEL,
            ),
            ERR_CURE_NOT_AVAILABLE,
            409,
        )
        unchanged = _read_notice(api, bundle["notice_over"]["id"])
        assert_status(unchanged, NOTICE_UNDER_EVALUATION)
        assert unchanged["cure_attempted"] is False
