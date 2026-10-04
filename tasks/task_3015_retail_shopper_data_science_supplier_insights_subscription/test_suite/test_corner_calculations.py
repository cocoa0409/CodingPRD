"""Calculation corners: segment criteria conjunction, matched-control pool
exhaustion, competitor-blind bucket suppression, and forecast supersession."""

from test_helpers import (
    account_with_contract,
    create_segment,
    create_study,
    get_success_data,
    ingest_households,
    start_study,
)
from test_helpers import factories
from test_helpers.test_users import TEST_USERS

SCIENTIST = TEST_USERS["insights_scientist_headers"]


def test_segment_size_applies_all_criteria(api):
    """Only the household satisfying category, frequency, monetary and region counts toward size.

    PRD: "The segment's `size` is the count of panel households that satisfy every supplied criterion, computed against the full panel at creation and recomputed at every submission."
    Design: Corner/calculations/segment_size_criteria_filtering
    """
    world = account_with_contract(api, name="Omega Olives", scope_category="SNACKS", scope_brands=["ACME"])
    ingest_households(api, [
        {"household_ref": "f1", "category_codes": ["SNACKS"], "frequency_12m": 10, "monetary_12m_cents": 5000, "region": "NW"},
        {"household_ref": "f2", "category_codes": ["SNACKS"], "frequency_12m": 2, "monetary_12m_cents": 5000, "region": "NW"},
        {"household_ref": "f3", "category_codes": ["SNACKS"], "frequency_12m": 10, "monetary_12m_cents": 100, "region": "NW"},
        {"household_ref": "f4", "category_codes": ["SNACKS"], "frequency_12m": 10, "monetary_12m_cents": 5000, "region": "SE"},
    ])
    segment = create_segment(
        api,
        world["contract"]["id"],
        world["analyst_headers"],
        segment_name="Filtered",
        min_frequency=5,
        min_monetary_cents=1000,
        region="NW",
    )
    assert segment["size"] == 1


EXHAUSTION_PANEL = [
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
        "household_ref": "T3",
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
]


def test_matched_control_pool_exhaustion_drops_treated(api):
    """Three treated against two controls yields two pairs; the third treated is dropped.

    PRD: "Treated households are processed in ascending `created_at` order; each selects the not-yet-chosen control of minimum distance, breaking ties by the control's ascending `created_at`; and each control is chosen at most once."
    PRD: "If the control pool empties before every treated household is matched, the remaining treated households are simply dropped from the pairing."
    Design: Corner/calculations/matched_control_pool_exhaustion_drops_treated
    """
    ingest_households(api, EXHAUSTION_PANEL)
    study = create_study(api)
    started = start_study(api, study["id"])
    pairs = started["matched_pairs"]
    assert len(pairs) == 2
    assert [(p["test_household_ref"], p["control_household_ref"]) for p in pairs] == [
        ("T1", "C1"),
        ("T2", "C2"),
    ]


def _competitor_blind_world(api):
    """TIER_PORTFOLIO contract, SNACKS scope over ACME; 20 own-brand + 19 rival-only households."""
    world = account_with_contract(
        api, name="Alpha Ale", tier="TIER_PORTFOLIO", scope_category="SNACKS", scope_brands=["ACME"]
    )
    own = [
        {
            "household_ref": f"o{i:02d}",
            "category_codes": ["SNACKS"],
            "brand_metrics": [{"brand_code": "ACME", "baseline_spend_cents": 100, "campaign_spend_cents": 100}],
        }
        for i in range(1, 21)
    ]
    rival = [
        {
            "household_ref": f"x{i:02d}",
            "category_codes": ["SNACKS"],
            "brand_metrics": [{"brand_code": "RIVAL", "baseline_spend_cents": 100, "campaign_spend_cents": 100}],
        }
        for i in range(1, 20)
    ]
    ingest_households(api, own + rival)
    return world


def test_competitor_blind_bucket_below_minimum_suppresses(api):
    """A blinded bucket of nineteen is below the cell floor and suppresses the whole report.

    PRD: "Every reported cell is then tested against the minimum cell size of twenty (§2.9)."
    PRD: "The competitor side of a `COMPETITOR_BLIND` report is always this single blinded bucket; no per-competitor breakdown exists anywhere in the product."
    Design: Corner/calculations/competitor_blind_bucket_suppression
    """
    from test_helpers import create_report

    world = _competitor_blind_world(api)
    report = create_report(
        api, world["contract"]["id"], world["analyst_headers"], report_type="COMPETITOR_BLIND"
    )
    generated = get_success_data(api.generate_report(report["id"], world["analyst_headers"]))
    assert generated["status"] == "SUPPRESSED"
    assert generated["other_supplier_aggregate_households"] == 19


def test_competitor_blind_bucket_at_minimum_passes(api):
    """Growing the blinded bucket to exactly twenty lets the regenerated report report twenty.

    PRD: "The boundary is inclusive-pass: a count of exactly twenty passes, a count of nineteen is suppressed."
    PRD: "The competitor side of a `COMPETITOR_BLIND` report is always this single blinded bucket; no per-competitor breakdown exists anywhere in the product."
    Design: Corner/calculations/competitor_blind_bucket_suppression
    """
    from test_helpers import create_report

    world = _competitor_blind_world(api)
    report = create_report(
        api, world["contract"]["id"], world["analyst_headers"], report_type="COMPETITOR_BLIND"
    )
    first = get_success_data(api.generate_report(report["id"], world["analyst_headers"]))
    assert first["status"] == "SUPPRESSED"
    ingest_households(api, [
        {
            "household_ref": "x20",
            "category_codes": ["SNACKS"],
            "brand_metrics": [{"brand_code": "RIVAL", "baseline_spend_cents": 100, "campaign_spend_cents": 100}],
        }
    ])
    second = get_success_data(api.generate_report(report["id"], world["analyst_headers"]))
    assert second["status"] == "READY"
    assert second["other_supplier_aggregate_households"] == 20


def test_forecast_supersede_marks_prior(api):
    """A second forecast for the same product supersedes the first; one PUBLISHED and one SUPERSEDED remain.

    PRD: "the moment a forecast is created for a `product_ref` that already has a `PUBLISHED` forecast, the older forecast moves automatically to its terminal `SUPERSEDED` state."
    PRD: "Only one live forecast per product reference exists at any time."
    Design: Corner/calculations/forecast_supersede_marks_prior
    """
    world = account_with_contract(api, name="Beta Butter", tier="TIER_BRAND")
    first = get_success_data(api.create_forecast(
        factories.forecast_payload(
            world["contract"]["id"],
            product_ref="NEW-9",
            analogs=[{"analog_ref": "A1", "similarity_score": 1.0, "observed_week4_units": 50}],
            variant="SIMPLE_AVERAGE",
        ),
        SCIENTIST,
    ))
    assert first["status"] == "PUBLISHED"
    assert first["forecast_selected_units"] == 50
    second = get_success_data(api.create_forecast(
        factories.forecast_payload(
            world["contract"]["id"],
            product_ref="NEW-9",
            analogs=[{"analog_ref": "A2", "similarity_score": 1.0, "observed_week4_units": 70}],
            variant="SIMPLE_AVERAGE",
        ),
        SCIENTIST,
    ))
    assert second["forecast_selected_units"] == 70
    from test_helpers import validate_paginated

    rows, meta = validate_paginated(
        api.list_contract_forecasts(world["contract"]["id"], SCIENTIST)
    )
    assert meta["total_count"] == 2
    by_id = {f["id"]: f for f in rows}
    assert by_id[first["id"]]["status"] == "SUPERSEDED"
    assert by_id[second["id"]]["status"] == "PUBLISHED"
