"""Difficulty tests — dual-variant calculations (queue A, rule `dual_variant_calc`).

Each test here translates exactly one instance of the difficulty index. The
asserted values are the ones the PRD's pinned arithmetic yields for the
instance's declared inputs in the modelled request, derived inclusively to the
cent and to the fourth decimal place.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    PLATFORM_ADMIN,
    TRANSACTION_COORDINATOR,
    create_region,
    create_lead_agent,
    create_client,
    create_closed_transaction,
    create_survey,
    assign_client,
    create_listing,
    set_clock,
)


@pytest.fixture(autouse=True)
def _clock():
    set_clock()


def test_listing_savings_pct_uses_the_flat_rate_over_the_traditional_baseline():
    """PRD §3.6: "The `gross_listing_fee_cents` is the platform's own commission at the flat rate, the `list_price_cents` multiplied by `list_fee_rate_pct`, rounded half-up to whole cents."
    PRD §3.6: "`savings_pct` expresses that saving as a proportion of the traditional baseline, rounded half-up to 4 decimal places."
    PRD §3.6: "The `traditional_listing_fee_cents` is the incumbent-brokerage baseline — the `list_price_cents` multiplied by the region's `traditional_commission_pct`, rounded half-up to whole cents — and it exists only to measure savings against."

    Design: Difficulty/dual_variant_calc/listing_savings_pct_base_and_provisional_vs_final
    """
    region = create_region(target_client_ratio=2.0, traditional_commission_pct=0.025)
    lead = create_lead_agent(region["id"])
    seller = create_client(
        full_name="Sara Seller", service_area_code="98101", need_kind="SELL",
    )
    assign_client(seller["id"])

    listing = create_listing(
        seller["id"], lead["id"], region["id"],
        list_price_cents=60_000_000,
        list_fee_rate_pct=0.0125,
        service_tier="FULL_SERVICE",
    )

    # gross = 60000000 * 0.0125 = 750000 exactly (flat-rate variant)
    assert listing["gross_listing_fee_cents"] == 750_000, listing
    # traditional = 60000000 * 0.025 = 1500000 exactly
    assert listing["traditional_listing_fee_cents"] == 1_500_000, listing
    # savings = 1500000 - 750000 = 750000
    assert listing["savings_amount_cents"] == 750_000, listing
    # savings_pct = 750000 / 1500000 = 0.5
    assert listing["savings_pct"] == pytest.approx(0.5, abs=1e-4), listing
    # with no referral in play the final fee equals the gross fee
    assert listing["final_listing_fee_cents"] == 750_000, listing


def test_listing_savings_pct_is_not_the_marginal_tier_roadmap_result():
    """PRD §3.6: "The listing also carries a forward-looking roadmap that is reported alongside the charged fee but is never the fee itself: it slices `list_price_cents` across the breaks at 50,000,000, 100,000,000 and 200,000,000 cents, applies the marginal rates 0.015, 0.0125 and 0.010 to the respective slices, rounds each slice's product half-up to whole cents, and sums them."
    PRD §3.6: "a provisional variant that divided the saving by the gross fee instead would report a materially different percentage, and the platform persists the baseline-denominated figure."

    Design: Difficulty/dual_variant_calc/listing_savings_pct_base_and_provisional_vs_final
    """
    region = create_region(target_client_ratio=2.0, traditional_commission_pct=0.025)
    lead = create_lead_agent(region["id"])
    seller = create_client(full_name="Sara Seller", service_area_code="98101", need_kind="SELL")
    assign_client(seller["id"])

    listing = create_listing(
        seller["id"], lead["id"], region["id"],
        list_price_cents=60_000_000,
        list_fee_rate_pct=0.0125,
        service_tier="FULL_SERVICE",
    )

    # The marginal-tier roadmap charges 50000000*0.015 + 10000000*0.0125 = 875000,
    # which would give savings 625000 and a proportion of 0.4167. The stored fee is
    # the flat-rate one, so neither of those is the persisted figure.
    assert listing["savings_amount_cents"] != 625_000, listing
    assert listing["savings_pct"] != pytest.approx(0.4167, abs=1e-4), listing
    assert listing["savings_pct"] == pytest.approx(0.5, abs=1e-4), listing


def test_penalty_blocked_survey_zeroes_the_csat_component_of_the_bonus():
    """PRD §3.9: "an answered survey with `bonus_eligible` false zeroes the customer-satisfaction component of that agent's bonus for the period".
    PRD §3.2: "plus 0.1 times the smaller of the region's `occupancy_pct` and 1.0".
    PRD §3.2: "is the rounded half-up mean, to two decimal places, of the `score` values from the agent's surveys whose `response_status` is `RESPONDED`".

    Design: Difficulty/dual_variant_calc/agent_bonus_csat_provisional_vs_final_weighting
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"], base_salary_cents=8_000_000)

    # Two close-and-score cycles immediately (surveys born RESPONDED with
    # bonus_eligible true); the third close, below, carries the penalised survey.
    for score in (5, 5):
        _client, tx = create_closed_transaction(region, lead)
        create_survey(tx["id"], lead["id"], score=score)

    # Third cycle: the survey is dispatched, ages through two ops runs, then is
    # answered late — a manual answer never earns bonus credit.
    _client, tx3 = create_closed_transaction(region, lead)
    survey3 = create_survey(tx3["id"], lead["id"])
    assert survey3["bonus_eligible"] is False
    get_success_data(api_client.run_region_ops(region["id"], PLATFORM_ADMIN))
    get_success_data(api_client.run_region_ops(region["id"], PLATFORM_ADMIN))
    answered = get_success_data(api_client.respond_survey(
        survey3["id"], {"score": 1}, TRANSACTION_COORDINATOR,
    ))
    assert answered["bonus_eligible"] is False, answered

    agent = get_success_data(api_client.get_agent(lead["id"], PLATFORM_ADMIN))

    # mean(5, 5, 1) = 3.6667 -> 3.67 at two decimal places
    assert agent["satisfaction_score"] == pytest.approx(3.67, abs=1e-2), agent
    # close_rate = 3 CLOSED / 3 non-CANCELLED = 1.0, csat zeroed by the penalty,
    # occupancy 0.0 (every client has closed and left the pipeline).
    assert agent["close_rate"] == pytest.approx(1.0, abs=1e-4), agent
    assert agent["bonus_pct"] == pytest.approx(0.2, abs=1e-4), agent
    # the unpenalised blend would add 0.15 * (3.67 / 5) and land on the 0.30 cap
    assert agent["bonus_pct"] != pytest.approx(0.30, abs=1e-4), agent


def test_penalty_blocked_bonus_moves_the_whole_salary_commitment():
    """PRD §3.9: "A manually answered dispatch is never granted bonus credit — its `bonus_eligible` stays false whether it is answered from `DISPATCHED` or from `EXPIRED_DISPATCH`".
    PRD §3.2: "`salary_commitment_cents` is the sum of the `base_salary_cents`, the `bonus_cents`, the `benefits_cents` and the `expense_allowance_cents`".

    Design: Difficulty/dual_variant_calc/agent_bonus_csat_provisional_vs_final_weighting
    """
    region = create_region(target_client_ratio=2.0)
    lead = create_lead_agent(region["id"], base_salary_cents=8_000_000, benefits_cents=500_000)
    lead_id = lead["id"]

    for score in (5, 5):
        _client, tx = create_closed_transaction(region, lead)
        create_survey(tx["id"], lead_id, score=score)

    _client, tx3 = create_closed_transaction(region, lead)
    survey3 = create_survey(tx3["id"], lead_id)
    get_success_data(api_client.run_region_ops(region["id"], PLATFORM_ADMIN))
    get_success_data(api_client.run_region_ops(region["id"], PLATFORM_ADMIN))
    get_success_data(api_client.respond_survey(survey3["id"], {"score": 1}, TRANSACTION_COORDINATOR))

    agent = get_success_data(api_client.get_agent(lead_id, PLATFORM_ADMIN))

    # bonus_pct 0.2 on an 8000000-cent base => 1600000 cents
    assert agent["bonus_cents"] == 1_600_000, agent
    assert agent["salary_commitment_cents"] == 8_000_000 + 1_600_000 + 500_000, agent