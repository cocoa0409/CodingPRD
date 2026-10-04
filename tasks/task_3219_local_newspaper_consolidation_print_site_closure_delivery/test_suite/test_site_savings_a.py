"""Difficulty queue A — dual_variant_calc on the site cost-avoidance domain.

The forward-looking figure annualizes the observed per-run mean across all thirty
window days; the chronological figure adds only each elapsed day's own observed
charge. The pair is compared rather than reconciled, and their absolute
difference is the divergence the closure audit pins.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_site,
    get_print_site,
    record_print_volume_response,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import (
    CLOCK_2026_09_30,
    FIXED_PRESS_AVOIDED_CENTS,
    SAVINGS_WINDOW_DAYS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]

OBSERVED_DAYS = 15
OBSERVED_CHARGE = 10000


@pytest.fixture
def site_with_half_run_window():
    """Hub + site KOT with 15 observed days at 10000 cents and no other records.

    Fifteen of the thirty window days carry a charge; the other fifteen never ran
    and were never recorded, so they add nothing to the chronological figure.
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    for day in range(1, OBSERVED_DAYS + 1):
        resp = record_print_volume_response(
            site["id"], f"2026-09-{day:02d}", OBSERVED_CHARGE)
        assert resp.status_code == 201, (
            f"recording 2026-09-{day:02d} failed: {resp.status_code} {resp.text}"
        )
    return hub, get_print_site(site["id"])


def test_forward_and_chronological_variants_diverge_by_the_pinned_amount(
        site_with_half_run_window):
    """PRD §3.1: "a window in which fifteen days were observed at 10,000 cents
    each and no other day carried a charge gives a flat daily rate of 150,000
    divided by 15, that is 10,000, an annualized figure of 180,000 plus 10,000
    times 30, that is 480,000.00, a realized figure of 180,000 plus 150,000, that
    is 330,000.00, and a divergence of exactly 150,000.00."

    Design: Difficulty/dual_variant_calc/site_savings_forward_vs_chronological
    """
    hub, site = site_with_half_run_window

    assert site["annualized_savings_cents"] == 480000.00, (
        f"expected 480000.00, got {site['annualized_savings_cents']}"
    )
    assert site["realized_savings_cents"] == 330000.00, (
        f"expected 330000.00, got {site['realized_savings_cents']}"
    )
    assert site["savings_divergence_cents"] == 150000.00, (
        f"expected 150000.00, got {site['savings_divergence_cents']}"
    )


def test_the_two_variants_are_not_interchangeable(site_with_half_run_window):
    """PRD §3.1: "Site closure economics are deliberately dual-variant, and the
    pair is compared against each other rather than reconciled."
    PRD §3.1: "The forward-looking figure assumes the whole window."

    Design: Difficulty/dual_variant_calc/site_savings_forward_vs_chronological
    """
    hub, site = site_with_half_run_window

    assert site["annualized_savings_cents"] != site["realized_savings_cents"], (
        "the forward-looking and chronological figures must differ"
    )
    assert site["annualized_savings_cents"] > site["realized_savings_cents"], (
        "annualizing a per-run mean across days that never ran projects a figure "
        "strictly higher than the days actually earned"
    )
    assert site["savings_divergence_cents"] == pytest.approx(
        abs(site["annualized_savings_cents"] - site["realized_savings_cents"]),
        abs=0.01,
    )


def test_chronological_variant_adds_only_the_days_that_ran(site_with_half_run_window):
    """PRD §3.1: "`realized_savings_cents` is the same fixed press cost avoided of
    1,800 dollars plus the sum of every window day's own `day_charge_cents` whose
    date is at or before the current logical date, rounded half up to two
    decimals — days that never ran add nothing."

    PRD §2.4: "Only the thirty contract-days immediately preceding the logical
    clock's current date enter the savings calculation".

    Design: Difficulty/dual_variant_calc/site_savings_forward_vs_chronological
    """
    hub, site = site_with_half_run_window

    expected_realized = FIXED_PRESS_AVOIDED_CENTS + OBSERVED_DAYS * OBSERVED_CHARGE
    expected_annualized = (
        FIXED_PRESS_AVOIDED_CENTS
        + (OBSERVED_CHARGE * OBSERVED_DAYS / OBSERVED_DAYS) * SAVINGS_WINDOW_DAYS
    )

    assert site["realized_savings_cents"] == pytest.approx(expected_realized, abs=0.01)
    assert site["annualized_savings_cents"] == pytest.approx(expected_annualized, abs=0.01)
    assert validate_success(api.get_print_site(site["id"], PRINT_OPS), 200)["id"] == site["id"]