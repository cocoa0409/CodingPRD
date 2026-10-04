"""Site evaluation scoring, quoting, and payback computations (PRD §3.1)."""
import pytest

from test_helpers import (
    STORE_BETA,
    STORE_DELTA,
    create_site_evaluation,
    create_site_evaluation_payload,
    create_store,
    validate_success,
)


def test_demographic_led_score_quote_and_verdict(api, placement_manager_headers):
    """PRD §3.1: "Identical inputs can therefore produce different verdicts
    under the two variants: a store with demographic 80, velocity 90,
    footprint score 50, and competitor density 20 scores 66.50 under
    `DEMOGRAPHIC_LED` but 71.00 under `VELOCITY_LED`."
    PRD §3.1: "The `install_quote_cents` is the all-in placement capex in whole
    cents: a unit cost of 325000 cents for a `STANDARD` chiller or 218000 cents
    for a `COMPACT`, plus a flat installation fee of 45000 cents, plus the
    footprint component (the `allocated_sqft` times 1250 cents per square foot,
    rounded half up to whole cents), plus the distance component (the store's
    `distance_miles_from_plant` times 925 cents per mile, rounded half up to
    whole cents)."

    Design: Difficulty/dual_variant_calc/site_score_demographic_vs_velocity_divergence
    """
    store = create_store()  # Store Alpha: demo 80, velocity 90, competitor 20, distance 10
    resp = api.create_site_evaluation(
        store["id"],
        create_site_evaluation_payload(model_variant="DEMOGRAPHIC_LED"),
        placement_manager_headers,
    )
    data = validate_success(resp, expected_status=201)
    assert data["footprint_score"] == 50, "min(100, round_half_up(100*16/32)) == 50"
    assert data["composite_score"] == pytest.approx(66.50, abs=0.005)
    # PRD formula for (STANDARD, 16 sqft, 10 miles): 325000+45000+20000+9250.
    assert data["install_quote_cents"] == 399250
    assert data["payback_months"] == pytest.approx(2.56, abs=0.005)
    assert data["verdict"] == "ELIGIBLE"


def test_velocity_led_diverges_on_identical_inputs(api, placement_manager_headers):
    """PRD §3.1: "Under `VELOCITY_LED`, the same inputs are weighted 0.20, 0.55,
    0.15, and 0.10 respectively."
    PRD §3.1: "Identical inputs can therefore produce different verdicts under
    the two variants: a store with demographic 80, velocity 90, footprint score
    50, and competitor density 20 scores 66.50 under `DEMOGRAPHIC_LED` but
    71.00 under `VELOCITY_LED`."

    Design: Difficulty/dual_variant_calc/site_score_demographic_vs_velocity_divergence
    """
    store = create_store()
    demo = validate_success(
        api.create_site_evaluation(store["id"], create_site_evaluation_payload(model_variant="DEMOGRAPHIC_LED"),
                                   placement_manager_headers),
        expected_status=201,
    )
    vel = validate_success(
        api.create_site_evaluation(store["id"], create_site_evaluation_payload(model_variant="VELOCITY_LED"),
                                   placement_manager_headers),
        expected_status=201,
    )
    assert vel["composite_score"] == pytest.approx(71.00, abs=0.005)
    assert demo["composite_score"] == pytest.approx(66.50, abs=0.005)
    assert demo["composite_score"] != vel["composite_score"], "variants must diverge on identical inputs"
    # Quote and payback do not depend on the scoring variant.
    assert vel["install_quote_cents"] == 399250 == demo["install_quote_cents"]
    assert vel["payback_months"] == pytest.approx(2.56, abs=0.005)
    assert vel["verdict"] == "ELIGIBLE"


def test_velocity_led_score_literal_check(api, placement_manager_headers):
    """PRD §3.1: "The computed `footprint_score` is the smaller of 100 and the
    value of 100 times `allocated_sqft` divided by 32 — the reference footprint
    — rounded half up."
    PRD §3.1: "a store with demographic 80, velocity 90, footprint score 50,
    and competitor density 20 scores 66.50 under `DEMOGRAPHIC_LED` but 71.00
    under `VELOCITY_LED`."

    Design: Corner/calculations/velocity_led_score_literal_check
    """
    store = create_store()
    data = validate_success(
        api.create_site_evaluation(store["id"], create_site_evaluation_payload(model_variant="VELOCITY_LED"),
                                   placement_manager_headers),
        expected_status=201,
    )
    assert data["footprint_score"] == 50
    assert data["composite_score"] == pytest.approx(71.00, abs=0.005)
    assert data["verdict"] == "ELIGIBLE"


def test_install_quote_compact_components_literal(api, placement_manager_headers):
    """PRD §3.1: "Each component is rounded to whole cents individually, round
    half up, before the four components are summed."

    Design: Corner/calculations/install_quote_compact_components_literal
    """
    store = create_store(payload=STORE_DELTA)  # distance 7 miles
    data = validate_success(
        api.create_site_evaluation(
            store["id"],
            create_site_evaluation_payload(chiller_model="COMPACT", forecast_weekly_units=120, allocated_sqft=10),
            placement_manager_headers,
        ),
        expected_status=201,
    )
    # 218000 + 45000 + round(10*1250) + round(7*925) = 281975
    assert data["install_quote_cents"] == 281975


def test_payback_rounding_order_pinned_at_291600(api, placement_manager_headers):
    """PRD §3.1: "Carrying fractional monthly units into the margin
    multiplication is non-conformant: at a cost of 291600 cents and 10.4
    forecast weekly units, the pinned order yields 36.00 months, while the
    unrounded variant would yield 35.95."

    Design: Difficulty/combinatorial_formula/payback_rounding_order_pinned
    """
    store = create_store(payload=STORE_BETA)  # demo 90, velocity 80, competitor 10, distance 12
    data = validate_success(
        api.create_site_evaluation(
            store["id"],
            create_site_evaluation_payload(chiller_model="COMPACT", forecast_weekly_units=10.4, allocated_sqft=14),
            placement_manager_headers,
        ),
        expected_status=201,
    )
    assert data["install_quote_cents"] == 291600, "218000 + 45000 + 17500 + 11100"
    assert data["composite_score"] == pytest.approx(68.30, abs=0.005)
    # Pinned order: round_half_up(10.4*13/3) = 45 first; 45*180 = 8100; 291600/8100 = 36.00.
    assert data["payback_months"] == pytest.approx(36.00, abs=0.005)


def test_payback_rounding_order_keeps_verdict_eligible(api, placement_manager_headers):
    """PRD §3.1: "The evaluation's `verdict` is `ELIGIBLE` when the
    `composite_score` is at least 60.0 and `payback_months` is at most 36.0 —
    both boundaries inclusive — and `INELIGIBLE` otherwise."

    Design: Difficulty/combinatorial_formula/payback_rounding_order_pinned
    """
    store = create_store(payload=STORE_BETA)
    data = validate_success(
        api.create_site_evaluation(
            store["id"],
            create_site_evaluation_payload(chiller_model="COMPACT", forecast_weekly_units=10.4, allocated_sqft=14),
            placement_manager_headers,
        ),
        expected_status=201,
    )
    assert data["payback_months"] == pytest.approx(36.00, abs=0.005)
    assert data["verdict"] == "ELIGIBLE", "36.00 <= 36.0 inclusive must be ELIGIBLE (the unpinned 35.95 hides the boundary)"


def test_payback_exactly_36_is_eligible(api, placement_manager_headers):
    """PRD §3.1: "The evaluation's `verdict` is `ELIGIBLE` when the
    `composite_score` is at least 60.0 and `payback_months` is at most 36.0 —
    both boundaries inclusive — and `INELIGIBLE` otherwise."

    Design: Difficulty/boundary_precision_check/payback_exactly_36_eligible
    """
    store = create_store(payload=STORE_BETA)
    data = validate_success(
        api.create_site_evaluation(
            store["id"],
            create_site_evaluation_payload(chiller_model="COMPACT", forecast_weekly_units=10.4, allocated_sqft=14),
            placement_manager_headers,
        ),
        expected_status=201,
    )
    assert data["payback_months"] == pytest.approx(36.00, abs=0.005), "boundary value exactly at the cap"
    assert data["verdict"] == "ELIGIBLE"


def test_payback_just_over_36_is_ineligible(api, placement_manager_headers):
    """PRD §3.1: "The evaluation's `verdict` is `ELIGIBLE` when the
    `composite_score` is at least 60.0 and `payback_months` is at most 36.0 —
    both boundaries inclusive — and `INELIGIBLE` otherwise."
    PRD §3.1: "Weekly units are converted to monthly units by multiplying by 13
    and dividing by 3, rounding half up to a whole number of units first; that
    integer is multiplied by the unit margin of 180 cents to obtain monthly
    margin; and `payback_months` is the `install_quote_cents` divided by the
    monthly margin, rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/payback_exactly_36_eligible
    """
    store = create_store(payload=STORE_BETA)
    data = validate_success(
        api.create_site_evaluation(
            store["id"],
            create_site_evaluation_payload(chiller_model="COMPACT", forecast_weekly_units=10.2, allocated_sqft=14),
            placement_manager_headers,
        ),
        expected_status=201,
    )
    # round_half_up(10.2*13/3) = 44 -> margin 7920 -> 291600/7920 = 36.82
    assert data["install_quote_cents"] == 291600
    assert data["composite_score"] == pytest.approx(68.30, abs=0.005)
    assert data["payback_months"] == pytest.approx(36.82, abs=0.005)
    assert data["verdict"] == "INELIGIBLE", "only the payback gate flips the verdict"
