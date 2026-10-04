"""Corner-design section: calculations."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_region, make_config, make_source, make_series,
    submit_accepted_batch, submit_rejected_batch,
    create_batch_item_payload, create_condition_standard_payload,
    create_correction_payload, get_edition, ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def test_trailing_window_excludes_items_older_than_90_days(api):
    """PRD §3.4: "all items from ACCEPTED batches matching the series'
    (configuration_id, region_id) whose sale_date falls within the 90 days up
    to and including the server clock at edition creation" and "If the window
    is empty — no accepted items at all in the trailing 90 days — edition
    creation is rejected with ERR_INSUFFICIENT_DATA (HTTP 422)."

    The only accepted item is dated 2026-05-20, more than 90 days before the
    2026-09-01 clock, so the window is empty.

    Design: Corner/calculations/trailing_window_excludes_items_older_than_90_days
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-calc", year=2020)
    source = make_source(region["id"], source_type="DEALER",
                         external_key="src-calc", name="CALCD")
    submit_accepted_batch(source["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=2000000,
                                  sale_date="2026-05-20", mileage=10000),
    ], submission_ref="b-calc")
    series = make_series(config["id"], region["id"], external_key="ser-calc")

    res = api.create_valuation_edition(
        {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
        ADMIN)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_DATA.value)


def test_trailing_window_excludes_rejected_batch_items(api):
    """PRD §3.4: "If the window is empty — no accepted items at all in the
    trailing 90 days — edition creation is rejected with
    ERR_INSUFFICIENT_DATA (HTTP 422)." and the window holds only "items from
    ACCEPTED batches". A series whose only batch was REJECTED has an empty
    window.

    Design: Corner/calculations/trailing_window_excludes_rejected_batch_items
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-calc2", year=2020)
    source = make_source(region["id"], source_type="DEALER",
                         external_key="src-calc2", name="CALC2D")
    submit_rejected_batch(source["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=2000000,
                                  sale_date="2026-08-20", mileage=10000),
    ], submission_ref="b-calc2")
    series = make_series(config["id"], region["id"], external_key="ser-calc2")

    res = api.create_valuation_edition(
        {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
        ADMIN)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_DATA.value)


def test_condition_tier_constants_applied(api):
    """PRD §3.1: "The multipliers are a fixed catalog and the server enforces
    equality: EXCELLENT must be 1.10, GOOD must be 1.00, FAIR must be 0.85,
    and POOR must be 0.70. A creation whose multiplier deviates from the
    catalog value for its tier is rejected with ERR_INVALID_INPUT (HTTP
    400), as is any enum-membership or numeric-range violation on mutating
    endpoints — out-of-range years, out-of-range percentage adjustments,
    batch item arrays outside the allowed size, and similar shape failures
    all surface under the same error."

    Design: Corner/calculations/condition_tier_constants_applied
    """
    res = api.create_condition_standard(
        create_condition_standard_payload(
            tier="GOOD", description="Decent shape", multiplier=1.05),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_INPUT.value)


def test_tier_values_rounding_half_up(api):
    """PRD §3.4: "trade_in_cents is the reference times 0.87,
    private_party_cents is the reference times 0.95, and retail_cents is the
    reference times 1.08, each rounded half-up to whole cents."

    reference 2001000 -> private_party round_half_up(2001000*0.95) = 1900950;
    retail round_half_up(2001000*1.08) = 2161080.

    Design: Corner/calculations/tier_values_rounding_half_up
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-prec", year=2022)
    source = make_source(region["id"], source_type="DEALER",
                         external_key="src-prec", name="PRECD")
    submit_accepted_batch(source["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=2001000,
                                  sale_date="2026-08-20", mileage=10000),
    ], submission_ref="b-prec")
    series = make_series(config["id"], region["id"], external_key="ser-prec")

    edition = validate_success(api.create_valuation_edition(
        {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
        ADMIN), 201)
    assert edition["reference_price_cents"] == 2001000
    assert edition["private_party_cents"] == 1900950
    assert edition["retail_cents"] == 2161080


def test_correction_reconciles_latest_published_edition_only(api):
    """PRD §3.2: "The correction then recomputes, in place, the
    reference_price_cents and the three tier values of the latest PUBLISHED
    edition of each affected series; earlier editions are never touched,
    honoring historical retention." and "Once this recomputation lands, the
    correction's delta_applied flips to true."

    A single published edition computed from one item at 2000000 moves to
    reference 2400000 with trade_in round_half_up(2400000*0.87) = 2088000.

    Design: Corner/calculations/correction_reconciles_latest_published_edition_only
    """
    region = make_region(region_code="EAST")
    config = make_config(segment="SEDAN", external_key="cfg-corr", year=2021)
    source = make_source(region["id"], source_type="DEALER",
                         external_key="src-corr", name="CORRD")
    batch = submit_accepted_batch(source["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=2000000,
                                  sale_date="2026-08-20", mileage=10000),
    ], submission_ref="b-corr")
    series = make_series(config["id"], region["id"], external_key="ser-corr")
    edition = validate_success(api.create_valuation_edition(
        {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
        ADMIN), 201)
    published = validate_success(
        api.publish_valuation_edition(edition["id"], ADMIN), 200)
    version_before = published["version"]

    correction = validate_success(api.create_correction(
        create_correction_payload(batch["id"], corrected_price_cents=2400000),
        DATAOPS), 201)
    assert correction["delta_applied"] is True

    after = get_edition(edition["id"])
    assert after["reference_price_cents"] == 2400000
    assert after["trade_in_cents"] == 2088000
    assert after["version"] > version_before
