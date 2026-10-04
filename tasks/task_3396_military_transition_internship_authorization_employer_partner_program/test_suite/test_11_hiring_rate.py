"""The employer hiring rate: two variants that legitimately diverge over
identical underlying data, and the zero-denominator read."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, assert_instant, assert_two_dp, fixtures, worlds
from test_helpers.test_users import PROGRAM_OFFICE_HEADERS


def test_hiring_rate_cohort_variant_buckets_by_separation(api):
    """PRD §3.7: "Under `COHORT`, the caller must supply `cohort_start_date` and
    `cohort_end_date` — omitting either is `ERR_VALIDATION` — and completions are
    bucketed by the member's `separation_date` falling within that caller-supplied
    window, both bounds inclusive."
    PRD §3.7: "In either variant, `completed_count` is the number of in-window
    completions and `converted_count` is the number of those completions having a
    conversion record with `hired` true; `hiring_rate_pct` is 100 times
    `converted_count` divided by `completed_count`, rounded half-up to 2 decimal
    places, and an empty denominator yields exactly 0.00."

    Both completed matches' members separate inside [2027-01-01, 2027-01-31]; only
    the first has a hired conversion, so the cohort rate is 50.00.

    Design: Difficulty/dual_variant_calc/hiring_rate_cohort_vs_rolling_diverge
    """
    ns = worlds.setup_hiring_rate_world(api)
    data = validate_success(
        api.get_hiring_rate(
            ns.employer["id"], PROGRAM_OFFICE_HEADERS,
            params={"variant": "COHORT", "cohort_start_date": "2027-01-01", "cohort_end_date": "2027-01-31"},
        )
    )
    assert data["completed_count"] == 2
    assert data["converted_count"] == 1
    assert_two_dp(data["hiring_rate_pct"], 50.00, "hiring_rate_pct")


def test_hiring_rate_rolling_variant_buckets_by_completed_at(api):
    """PRD §3.7: "Under `ROLLING`, the default when `variant` is omitted,
    completions are bucketed by the match's `completed_at` date falling within the
    trailing 90-day window (`ROLLING_HIRING_WINDOW_DAYS`) ending at the logical
    clock date, both bounds inclusive."
    PRD §3.7: "The two variants legitimately diverge on identical underlying data
    because they bucket the same completions on different dates over different
    windows."

    With the clock at 2027-03-10 the window is [2026-12-10, 2027-03-10]: only the
    second match's completed_at (2026-12-15) lands inside, and it has no hired
    conversion — rate 0.00, diverging from the cohort read of the same data.

    Design: Difficulty/dual_variant_calc/hiring_rate_cohort_vs_rolling_diverge
    """
    ns = worlds.setup_hiring_rate_world(api)
    data = validate_success(api.get_hiring_rate(ns.employer["id"], PROGRAM_OFFICE_HEADERS, params={"variant": "ROLLING"}))
    assert_instant(data["window_start_date"], "2026-12-10", "rolling window_start_date")
    assert_instant(data["window_end_date"], "2027-03-10", "rolling window_end_date")
    assert data["completed_count"] == 1
    assert data["converted_count"] == 0
    assert_two_dp(data["hiring_rate_pct"], 0.00, "hiring_rate_pct")


def test_hiring_rate_zero_denominator_and_cohort_params(api):
    """PRD §3.7: "In either variant, `completed_count` is the number of in-window
    completions and `converted_count` is the number of those completions having a
    conversion record with `hired` true; `hiring_rate_pct` is 100 times
    `converted_count` divided by `completed_count`, rounded half-up to 2 decimal
    places, and an empty denominator yields exactly 0.00."
    PRD §3.7: "Under `ROLLING`, the default when `variant` is omitted, completions
    are bucketed by the match's `completed_at` date falling within the trailing
    90-day window (`ROLLING_HIRING_WINDOW_DAYS`) ending at the logical clock date,
    both bounds inclusive."
    PRD §3.7: "Under `COHORT`, the caller must supply `cohort_start_date` and
    `cohort_end_date` — omitting either is `ERR_VALIDATION` — and completions are
    bucketed by the member's `separation_date` falling within that caller-supplied
    window, both bounds inclusive."

    Design: Corner/calculations/hiring_rate_zero_denominator_and_cohort_params
    """
    employer = fixtures.create_authorized_employer(api)

    default_read = validate_success(api.get_hiring_rate(employer["id"], PROGRAM_OFFICE_HEADERS))
    assert default_read["variant"] == "ROLLING"
    assert default_read["completed_count"] == 0
    assert_two_dp(default_read["hiring_rate_pct"], 0.00, "hiring_rate_pct")

    missing_dates = api.get_hiring_rate(employer["id"], PROGRAM_OFFICE_HEADERS, params={"variant": "COHORT"})
    validate_error(missing_dates, ApiErrorId.ERR_VALIDATION)

    cohort = validate_success(
        api.get_hiring_rate(
            employer["id"], PROGRAM_OFFICE_HEADERS,
            params={"variant": "COHORT", "cohort_start_date": "2027-01-01", "cohort_end_date": "2027-01-31"},
        )
    )
    assert_instant(cohort["window_start_date"], "2027-01-01", "cohort window_start_date")
    assert cohort["completed_count"] == 0
    assert cohort["converted_count"] == 0
    assert_two_dp(cohort["hiring_rate_pct"], 0.00, "hiring_rate_pct")
