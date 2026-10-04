"""Premium quoting: pinned rounding orders, coverage limits, validation order."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    activate_classification,
    bind_quote,
    create_property,
    create_quote,
    get_success_data,
    premium_quote_payload,
    publish_classification,
    setup_classification_review,
    setup_classified_community,
    validate_error,
    validate_success,
)

INSURER = TEST_USERS["insurer_headers"]


def _ratington(api):
    """Community graded class 5 (adjusted 55.14, modifier 0.85), EFFECTIVE,
    with a property insured for 200,000,000 cents within both radii."""
    ctx = setup_classification_review(
        api, name="Ratington", population=20000, area_sq_miles=12, rural_area_pct=10,
        needed_fire_flow_gpm=1500, storage_capacity_gal=0,
        supply_works_capacity_gpm=1500, daily_consumption_gpm=400,
        dept_data={
            "career_on_duty_per_shift": 3, "volunteers_on_duty_avg": 0,
            "training_hours_per_firefighter_annual": 240, "training_facility_level": "A",
            "live_fire_training": True, "coverage_pct_within_5mi": 50,
        },
        apparatus=[{"kind": "ENGINE", "pump_capacity_gpm": 1800}],
        hydrant_count=1,
        flow_tests=[{"measured_flow_gpm": 700, "outcome": "certified"}],
        comms={"operators_on_duty_min": 2, "avg_alarm_to_dispatch_seconds": 120,
               "redundant_circuits": False, "backup_power": False},
    )
    assert ctx["sheet"]["adjusted_total_points"] == pytest.approx(55.14, abs=0.005)
    assert ctx["sheet"]["base_class"] == 5
    classification = publish_classification(api, ctx["cycle"]["id"], ctx["sheet"]["id"])
    activate_classification(api, classification["id"])
    prop = create_property(
        api, ctx["community"]["id"], address="10 Oak St",
        distance_to_nearest_hydrant_ft=500, distance_to_nearest_station_road_miles=2.0,
        construction_type="MASONRY", insured_value_cents=200000000,
    )
    return ctx, prop


def test_provisional_premium_rounds_once_at_the_end(api):
    """PRD §3.8: "its `provisional_premium_cents` is computed in one shot:
    the exact annual premium — `coverage_amount_cents` times `base_rate_bp`
    times the pinned modifier, divided by 10000 — is multiplied by
    `term_months`, divided by 12, and the result rounded half-up to a whole
    cent." 25,000,000 x 333 bp x 0.85 x 7/12 rounds to 412,781.

    Design: Difficulty/combinatorial_formula/premium_rounding_order_provisional_vs_final
    """
    _, prop = _ratington(api)
    quote = create_quote(
        api, prop["id"], coverage_amount_cents=25000000, base_rate_bp=333,
        term_months=7, coverage_start_date="2027-01-01", coverage_end_date="2027-07-31",
    )
    assert quote["status"] == "QUOTED"
    assert quote["provisional_premium_cents"] == 412781
    assert quote["final_premium_cents"] is None


def test_final_premium_rounds_per_month_then_multiplies(api):
    """PRD §3.8: "A successful bind computes `final_premium_cents` under a
    different, pinned rounding order: the exact annual premium is divided by
    12 and rounded half-up to a whole cent per month, and that monthly figure
    is then multiplied by `term_months`." Monthly 58,969 x 7 = 412,783, a
    2-cent delta against the round-at-end variant.

    Design: Difficulty/combinatorial_formula/premium_rounding_order_provisional_vs_final
    """
    ctx, prop = _ratington(api)
    quote = create_quote(
        api, prop["id"], coverage_amount_cents=25000000, base_rate_bp=333,
        term_months=7, coverage_start_date="2027-01-01", coverage_end_date="2027-07-31",
    )
    bound = bind_quote(api, ctx["community"]["id"], quote["id"])
    assert bound["status"] == "BOUND"
    assert bound["final_premium_cents"] == 412783
    assert bound["final_premium_cents"] - bound["provisional_premium_cents"] == 2


def _cap_city(api):
    """EFFECTIVE class-10 community with a property insured 100,000,000."""
    ctx = setup_classified_community(api, name="Prio Two")
    prop = create_property(
        api, ctx["community"]["id"], address="7 Ash St",
        distance_to_nearest_hydrant_ft=300, distance_to_nearest_station_road_miles=1.0,
        construction_type="FRAME", insured_value_cents=100000000,
    )
    return ctx, prop


def test_temporal_priority_beats_fiscal_on_quote_create(api):
    """PRD §2.11: "then temporal rules, then structural payload constraints,
    and finally fiscal limits" — a window that ends before it starts
    (temporal) outranks coverage above 150% (fiscal), so the rejection is
    `ERR_COVERAGE_PERIOD_INVALID`. PRD §3.8: "The coverage start must not
    precede the logical clock date and the end must not precede the start".

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_beats_fiscal_on_quote_create
    """
    ctx, prop = _cap_city(api)
    resp = api.create_premium_quote(
        premium_quote_payload(
            prop["id"], coverage_amount_cents=200000000,
            coverage_start_date="2027-06-01", coverage_end_date="2027-01-01",
        ),
        INSURER,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_PERIOD_INVALID)
    quotes = get_success_data(api.list_premium_quotes(INSURER, params={"property_id": prop["id"]}))
    assert quotes == [], "no PremiumQuote may be created"


def test_fiscal_violation_alone_returns_coverage_exceeds_value(api):
    """PRD §3.8: "Coverage may not exceed 150% of the property's
    `insured_value_cents`, with exactly 150% permitted; excess is rejected
    with `ERR_COVERAGE_EXCEEDS_VALUE` (HTTP 422)." With a valid window the
    fiscal rung is the one that fires.

    Design: Difficulty/priority_pair_validation_conflict/temporal_priority_beats_fiscal_on_quote_create
    """
    ctx, prop = _cap_city(api)
    resp = api.create_premium_quote(
        premium_quote_payload(prop["id"], coverage_amount_cents=200000000),
        INSURER,
    )
    validate_error(resp, ApiErrorId.ERR_COVERAGE_EXCEEDS_VALUE)


def test_premium_quote_get_not_found_returns_404(api):
    """PRD §2.11: "the first identifier that matches nothing produces that
    resource type's own 404 — respectively … `ERR_QUOTE_NOT_FOUND`".

    Design: Corner/entities/premium_quote_get_not_found_returns_404
    """
    resp = api.get_premium_quote(NON_EXISTENT_UUID, INSURER)
    validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_FOUND)


def test_coverage_exact_150pct_allowed_above_rejected(api):
    """PRD §3.8: "Coverage may not exceed 150% of the property's
    `insured_value_cents`, with exactly 150% permitted; excess is rejected
    with `ERR_COVERAGE_EXCEEDS_VALUE` (HTTP 422)."

    Design: Corner/validations/coverage_exact_150pct_allowed_above_rejected
    """
    ctx = setup_classified_community(api, name="Cap City")
    prop = create_property(
        api, ctx["community"]["id"], address="5 Oak St",
        distance_to_nearest_hydrant_ft=300, distance_to_nearest_station_road_miles=1.0,
        construction_type="FRAME", insured_value_cents=200000000,
    )
    resp_ok = api.create_premium_quote(
        premium_quote_payload(prop["id"], coverage_amount_cents=300000000), INSURER
    )
    validate_success(resp_ok, 201)
    resp_over = api.create_premium_quote(
        premium_quote_payload(prop["id"], coverage_amount_cents=300000001), INSURER
    )
    validate_error(resp_over, ApiErrorId.ERR_COVERAGE_EXCEEDS_VALUE)
