"""Distributor performance scoring: dual provisional/final variants (PRD §3.9)."""
import pytest

from test_helpers import (
    TEST_USERS,
    setup_performance_score_scenario,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["brand_admin_headers"]


def test_performance_score_provisional_includes_unverified_submissions(api):
    """PRD §3.9: "The `performance_score_provisional` is the point-in-time reading:
    the arithmetic mean of the `score` values over the distributor's service visits
    whose `submitted_at` falls inside the window and whose `status` is `SUBMITTED` or
    `VERIFIED` — unverified submissions included — rounded half up to 2 decimal
    places, and 0 when no such visits exist."

    Visits 80 (VERIFIED), 100 (VERIFIED), 40 (SUBMITTED, unverified) -> the
    provisional mean includes the unverified 40: (80 + 100 + 40) / 3 = 73.33.

    Design: Difficulty/dual_variant_calc/distributor_performance_provisional_vs_final
    """
    ctx = setup_performance_score_scenario()
    data, _meta = validate_paginated(api.list_distributors(ADMIN))
    dist = next(d for d in data if d["id"] == ctx["distributor"]["id"])
    assert dist["performance_score_provisional"] == pytest.approx(73.33, abs=0.001), (
        f"provisional must include the unverified SUBMITTED visit: "
        f"expected 73.33, got {dist['performance_score_provisional']}"
    )


def test_performance_score_final_blends_verified_pulls_and_fill(api):
    """PRD §3.9: "The visit component is the arithmetic mean of `score` over the
    window's visits in `VERIFIED` status only, and 0 when there are none; it carries
    a weight of one half." and "The final score is the sum of the three weighted
    components, rounded half up to 2 decimal places."

    VERIFIED visits 80 and 100 -> visit component 90; pulls 3 on-time of 4 -> 75;
    order 18 of 20 units allocated -> fill 90; final = 0.5*90 + 0.3*75 + 0.2*90 = 85.5,
    which differs from the provisional 73.33 over the identical activity footprint.

    Design: Difficulty/dual_variant_calc/distributor_performance_provisional_vs_final
    """
    ctx = setup_performance_score_scenario()
    dist = validate_success(api.get_distributor(ctx["distributor"]["id"], ADMIN))
    assert dist["performance_score_final"] == pytest.approx(85.5, abs=0.001), (
        f"final must blend VERIFIED-only visits with pull/fill components: "
        f"expected 85.5, got {dist['performance_score_final']}"
    )
    assert dist["performance_score_provisional"] == pytest.approx(73.33, abs=0.001)
    assert dist["performance_score_provisional"] != dist["performance_score_final"], (
        "the two variants must diverge on the same data: the provisional mean "
        "includes the unverified SUBMITTED visit, the final excludes it"
    )
