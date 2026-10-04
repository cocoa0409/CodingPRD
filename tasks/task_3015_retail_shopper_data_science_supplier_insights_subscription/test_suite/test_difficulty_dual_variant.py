"""Dual-variant calculations: incrementality lift and new-item forecasts.

Both calculations compute two figures from the same inputs and expose both;
the incrementality study distinguishes raw from bias-corrected lift, and the
forecast distinguishes unweighted from similarity-weighted projections.
"""

import pytest

from test_helpers import (
    create_account,
    create_contract,
    create_study,
    get_success_data,
    ingest_households,
    read_study,
    set_clock,
    start_study,
)
from test_helpers import factories
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]
SCIENTIST = TEST_USERS["insights_scientist_headers"]

# Treated households exposed to ACME with campaign spend 24000 and baseline
# 22000; controls unexposed with campaign 20000 and baseline 20000.
MATCH_PANEL = [
    {
        "household_ref": "T1",
        "category_codes": ["SNACKS"],
        "recency_days": 5,
        "frequency_12m": 10,
        "monetary_12m_cents": 24000,
        "exposed_brands": ["ACME"],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 22000, "campaign_spend_cents": 24000}],
    },
    {
        "household_ref": "T2",
        "category_codes": ["SNACKS"],
        "recency_days": 5,
        "frequency_12m": 10,
        "monetary_12m_cents": 24000,
        "exposed_brands": ["ACME"],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 22000, "campaign_spend_cents": 24000}],
    },
    {
        "household_ref": "C1",
        "category_codes": ["SNACKS"],
        "recency_days": 6,
        "frequency_12m": 10,
        "monetary_12m_cents": 23000,
        "exposed_brands": [],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 20000, "campaign_spend_cents": 20000}],
    },
    {
        "household_ref": "C2",
        "category_codes": ["SNACKS"],
        "recency_days": 4,
        "frequency_12m": 12,
        "monetary_12m_cents": 23000,
        "exposed_brands": [],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 20000, "campaign_spend_cents": 20000}],
    },
    {
        "household_ref": "C3",
        "category_codes": ["SNACKS"],
        "recency_days": 6,
        "frequency_12m": 8,
        "monetary_12m_cents": 25000,
        "exposed_brands": [],
        "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 20000, "campaign_spend_cents": 20000}],
    },
]

FORECAST_ANALOGS = [
    {"analog_ref": "A1", "similarity_score": 0.9, "observed_week4_units": 100},
    {"analog_ref": "A2", "similarity_score": 0.6, "observed_week4_units": 140},
    {"analog_ref": "A3", "similarity_score": 0.3, "observed_week4_units": 80},
]


def _study_in_analysis(api):
    """Panel + started study, clock advanced to window_end so the read lands in ANALYSIS."""
    ingest_households(api, MATCH_PANEL)
    study = create_study(api)
    start_study(api, study["id"])
    set_clock(api, "2026-09-10T00:00:00Z")
    return study


def test_incrementality_lift_variants_raw_and_bias_corrected(api):
    """One matched panel yields a raw lift of 20.0 and a bias-corrected lift of 15.0.

    PRD: "The `provisional_lift_pct` is the raw lift: the difference of the test and control averages, divided by the control average, expressed as a percentage."
    PRD: "The `final_lift_pct` applies a bias correction for baseline divergence: the correction is one-half of the gap between the treated households' mean `baseline_spend_cents` and the controls' mean `baseline_spend_cents` for the brand; that correction is subtracted from the spend difference before dividing by the control average and converting to a percentage."
    Design: Difficulty/dual_variant_calc/incrementality_provisional_vs_final_lift
    """
    study = _study_in_analysis(api)
    observed = read_study(api, study["id"])
    assert observed["status"] == "ANALYSIS"
    assert observed["test_avg_spend_cents"] == 24000
    assert observed["control_avg_spend_cents"] == 20000
    assert observed["provisional_lift_pct"] == pytest.approx(20.0, abs=0.01)
    assert observed["final_lift_pct"] == pytest.approx(15.0, abs=0.01)


def test_incrementality_final_lift_strictly_smaller_than_provisional(api):
    """A positive baseline gap makes the adjusted figure strictly smaller than the raw one.

    PRD: "The final lift is therefore strictly smaller than the provisional lift whenever the treated group was already out-spending the controls at baseline."
    PRD: "Both lift figures are stored rounded half-up to two decimal places."
    Design: Difficulty/dual_variant_calc/incrementality_provisional_vs_final_lift
    """
    study = _study_in_analysis(api)
    observed = read_study(api, study["id"])
    assert observed["final_lift_pct"] < observed["provisional_lift_pct"]
    # Rounded half-up to two decimals: 15.0 and 20.0 exactly on this fixture.
    assert round(observed["provisional_lift_pct"], 2) == observed["provisional_lift_pct"]
    assert round(observed["final_lift_pct"], 2) == observed["final_lift_pct"]


def test_forecast_simple_average_variant_selects_unweighted_mean(api):
    """The SIMPLE_AVERAGE variant selects the unweighted mean of 106.67 while both projections are stored.

    PRD: "`forecast_simple_avg_units` is the unweighted mean of the analogs' `observed_week4_units`, ignoring similarity entirely."
    PRD: "`forecast_weighted_units` is the similarity-weighted mean: each analog's `observed_week4_units` weighted by its `similarity_score`, summed, and divided by the sum of the similarity scores — shifting the projection toward closer analogs."
    PRD: "The `forecast_selected_units` field holds whichever projection the `variant` selects: the simple average for `SIMPLE_AVERAGE`, the weighted figure for `SIMILARITY_WEIGHTED`."
    Design: Difficulty/dual_variant_calc/forecast_simple_vs_similarity_weighted
    """
    account = create_account(api, name="Acme Foods", region="NW")
    contract = create_contract(api, account["id"], tier="TIER_PORTFOLIO")
    resp = api.create_forecast(
        factories.forecast_payload(contract["id"], product_ref="NEW-1", analogs=FORECAST_ANALOGS, variant="SIMPLE_AVERAGE"),
        SCIENTIST,
    )
    forecast = get_success_data(resp)
    assert forecast["forecast_simple_avg_units"] == pytest.approx(106.67, abs=0.005)
    assert forecast["forecast_weighted_units"] == pytest.approx(110.0, abs=0.005)
    assert forecast["forecast_selected_units"] == pytest.approx(106.67, abs=0.005)
    assert forecast["status"] == "PUBLISHED"


def test_forecast_similarity_weighted_variant_selects_weighted_mean(api):
    """The SIMILARITY_WEIGHTED variant selects the 110.0 weighted figure over the 106.67 simple mean.

    PRD: "Two projections are always computed and stored."
    PRD: "The `forecast_selected_units` field holds whichever projection the `variant` selects: the simple average for `SIMPLE_AVERAGE`, the weighted figure for `SIMILARITY_WEIGHTED`."
    Design: Difficulty/dual_variant_calc/forecast_simple_vs_similarity_weighted
    """
    account = create_account(api, name="Acme Foods", region="NW")
    contract = create_contract(api, account["id"], tier="TIER_PORTFOLIO")
    resp = api.create_forecast(
        factories.forecast_payload(contract["id"], product_ref="NEW-2", analogs=FORECAST_ANALOGS, variant="SIMILARITY_WEIGHTED"),
        SCIENTIST,
    )
    forecast = get_success_data(resp)
    assert forecast["forecast_simple_avg_units"] == pytest.approx(106.67, abs=0.005)
    assert forecast["forecast_weighted_units"] == pytest.approx(110.0, abs=0.005)
    assert forecast["forecast_selected_units"] == pytest.approx(110.0, abs=0.005)
