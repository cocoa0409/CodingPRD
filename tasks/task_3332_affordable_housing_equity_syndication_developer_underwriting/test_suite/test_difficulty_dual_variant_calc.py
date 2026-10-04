"""Depth: one calculation with two variants evaluated on the same row.

Every test here pins a number that follows from the PRD's own arithmetic, not
from any worked example: the preliminary and final equity variants, and the
priced and realized fund yields.
"""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    read_fund,
    read_project,
    setup_canonical_scenario,
    setup_committed_project,
    validate_success,
)

AM_HEADERS_KEY = "asset_manager_headers"


def _finalize(project):
    """PUT the project with underwriting_action=FINALIZE against its live version."""
    from test_helpers import finalize_underwriting

    return finalize_underwriting(project)


def _record_delivery(project_id, allocation_id, cents, headers):
    return get_success_data(
        api_client.record_allocation_delivery(
            project_id, allocation_id, cents, headers
        )
    )


def test_preliminary_equity_ignores_the_credit_award(asset_manager_headers):
    """PRD §3.4: "A quality uplift is then computed as that base multiplied by
    the `market_study_absorption_score` and by 0.10, rounded half-up to a whole
    cent. The `preliminary_equity_cents` is the base minus the quality uplift."
    PRD §3.4: "A new project starts at `UNDERWRITING` with `underwriting_stage`
    `PRELIMINARY`, and creation immediately computes `preliminary_equity_cents`
    and `underwritten_equity_cents`."

    Base = 1234567890 - 700000000 = 534567890; uplift = round(534567890 * 0.83
    * 0.10) = round(44369134.87) = 44369135; equity = 534567890 - 44369135 =
    490198755.

    Design: Difficulty/dual_variant_calc/underwriting_equity_preliminary_vs_final_on_same_project
    """
    scenario = setup_canonical_scenario(
        with_subscription=True,
        pay_in_full=True,
        with_project=True,
        with_allocation=True,
    )
    project = read_project(scenario.project["id"])

    assert project["underwriting_stage"] == "PRELIMINARY"
    assert project["preliminary_equity_cents"] == 490198755, (
        "preliminary equity must be the budget gap net of the quality uplift"
    )
    assert project["underwritten_equity_cents"] == 490198755
    assert project["final_equity_cents"] is None


def test_final_equity_caps_at_priced_credit_value_less_sponsor_uplift(
    asset_manager_headers,
):
    """PRD §3.4: "The `final_equity_cents` is the lesser of the final base and
    the credit value, minus the sponsor uplift."
    PRD §3.4: "The `underwritten_equity_cents` is always `final_equity_cents`
    when the stage is `FINAL` and `preliminary_equity_cents` otherwise."

    Credit value = round(912345678 * 0.9123) = 832332962; final base = 534567890;
    sponsor uplift = round(534567890 * 96 / 10000.0) = round(5131851.744) =
    5131852; final equity = 534567890 - 5131852 = 529436038.

    Design: Difficulty/dual_variant_calc/underwriting_equity_preliminary_vs_final_on_same_project
    """
    scenario = setup_canonical_scenario(
        with_subscription=True,
        pay_in_full=True,
        with_project=True,
        with_allocation=True,
    )
    before = read_project(scenario.project["id"])
    assert before["preliminary_equity_cents"] == 490198755

    project = _finalize(scenario.project)

    assert project["underwriting_stage"] == "FINAL"
    assert project["final_equity_cents"] == 529436038, (
        "final equity must cap the budget gap at the priced credit award and "
        "subtract the capped sponsor-experience uplift"
    )
    assert project["underwritten_equity_cents"] == 529436038
    assert project["preliminary_equity_cents"] == 490198755, (
        "the preliminary variant is retained on the row and is not overwritten "
        "by finalization"
    )
    assert (
        project["final_equity_cents"] - project["preliminary_equity_cents"]
        == 39237283
    )


def test_priced_yield_reads_awarded_credits_against_subscribed_equity(
    asset_manager_headers,
):
    """PRD §3.3: "The `priced_yield_pct` is the `awarded_credits_total_cents`
    minus the `subscribed_equity_cents`, divided by the `subscribed_equity_cents`,
    expressed to 6 decimal places; when `subscribed_equity_cents` is zero the
    yield is zero."

    awarded total = 912345678, subscribed equity = 460000000, so the yield is
    452345678 / 460000000 = 0.983360.

    Design: Difficulty/dual_variant_calc/fund_yield_priced_vs_realized_divergence_on_same_fund
    """
    scenario = setup_committed_project()
    _record_delivery(
        scenario.project["id"],
        scenario.allocation["id"],
        450000000,
        asset_manager_headers,
    )

    fund = read_fund(scenario.fund["id"])

    assert fund["awarded_credits_total_cents"] == 912345678
    assert fund["subscribed_equity_cents"] == 460000000
    assert fund["priced_yield_pct"] == pytest.approx(0.983360, abs=1e-6), (
        "priced yield must divide awarded credit dollars by subscribed equity"
    )


def test_realized_yield_reads_delivered_credits_against_funded_equity(
    asset_manager_headers,
):
    """PRD §3.3: "The `realized_yield_pct` is the `delivered_credits_total_cents`
    minus the `funded_equity_cents`, divided by the `funded_equity_cents`, to 6
    decimal places, and zero when the funded equity is zero."
    PRD §3.3: "A fund that under-delivers credits therefore reports a realized
    yield far below its priced yield even when the price per credit dollar has
    not moved at all."

    delivered total = 450000000, funded equity = 460000000, so the yield is
    -10000000 / 460000000 = -0.021739.

    Design: Difficulty/dual_variant_calc/fund_yield_priced_vs_realized_divergence_on_same_fund
    """
    scenario = setup_committed_project()
    _record_delivery(
        scenario.project["id"],
        scenario.allocation["id"],
        450000000,
        asset_manager_headers,
    )

    fund = read_fund(scenario.fund["id"])

    assert fund["delivered_credits_total_cents"] == 450000000
    assert fund["funded_equity_cents"] == 460000000
    assert fund["realized_yield_pct"] == pytest.approx(-0.021739, abs=1e-6), (
        "realized yield must divide delivered credit dollars by funded equity"
    )
    assert fund["realized_yield_pct"] != fund["priced_yield_pct"], (
        "the two variants are computed from different bases and must diverge"
    )
