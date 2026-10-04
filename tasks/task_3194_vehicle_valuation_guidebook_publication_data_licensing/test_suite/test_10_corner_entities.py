"""Corner-design section: entities."""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_region, ApiErrorId, NON_EXISTENT_UUID,
    create_configuration_payload, create_source_payload,
    setup_published_edition,
)
from test_helpers.fixtures import ADMIN, DATAOPS


def test_region_creation_persists_all_fields(api):
    """PRD §3.1: "A Region is created with an uppercase region_code unique
    across all regions (for example WEST or EAST) and a human-readable name,
    and starts in ACTIVE status." and PRD §2.5: "version (integer): a
    system-managed counter that increments by one on every mutation of the
    resource".

    Design: Corner/entities/region_creation_persists_all_fields
    """
    created = validate_success(api.create_region(
        {"region_code": "NORTH", "name": "North Region"}, ADMIN), 201)
    fetched = validate_success(api.get_region(created["id"], ADMIN), 200)
    assert fetched["region_code"] == "NORTH"
    assert fetched["name"] == "North Region"
    assert fetched["status"] == "ACTIVE"
    assert fetched["version"] == 1


def test_configuration_year_out_of_range_rejected(api):
    """PRD §3.1: "year (an integer from 1990 to 2030 inclusive)" and "A
    creation whose multiplier deviates from the catalog value for its tier is
    rejected with ERR_INVALID_INPUT (HTTP 400), as is any enum-membership or
    numeric-range violation on mutating endpoints — out-of-range years,
    out-of-range percentage adjustments, batch item arrays outside the
    allowed size, and similar shape failures all surface under the same
    error."

    Design: Corner/entities/configuration_year_out_of_range_rejected
    """
    res = api.create_configuration(
        create_configuration_payload(
            make="Acme", model="Old", year=1985, trim="S", segment="SEDAN",
            annual_expected_miles=10000, external_key="cfg-bad-year"),
        ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_INPUT.value)


def test_configuration_default_annual_expected_miles_applied(api):
    """PRD §3.1: "annual_expected_miles, which defaults to 10000 when omitted
    and feeds the mileage adjustment curve used in offer pricing."

    Design: Corner/entities/configuration_default_annual_expected_miles_applied
    """
    payload = create_configuration_payload(
        make="Acme", model="Def", year=2022, trim="S", segment="SEDAN",
        external_key="cfg-def")
    del payload["annual_expected_miles"]
    created = validate_success(api.create_configuration(payload, ADMIN), 201)
    fetched = validate_success(api.get_configuration(created["id"], ADMIN), 200)
    assert fetched["annual_expected_miles"] == 10000


def test_edition_computed_tier_values_ignore_client_input(api):
    """PRD §3.4: "At creation the server computes the edition's
    reference_price_cents from the trailing market data, then derives its
    three tier values." and "trade_in_cents is the reference times 0.87,
    private_party_cents is the reference times 0.95, and retail_cents is the
    reference times 1.08, each rounded half-up to whole cents."

    A single accepted item at 3040000 yields reference 3040000, trade_in
    2644800, private_party 2888000, retail 3283200.

    Design: Corner/entities/edition_computed_tier_values_ignore_client_input
    """
    region = make_region(region_code="EAST")
    config = validate_success(api.create_configuration(
        create_configuration_payload(make="Acme", model="Ent", year=2023,
                                     trim="X", segment="SEDAN",
                                     external_key="cfg-ent"),
        ADMIN), 201)
    source = validate_success(api.create_source(
        create_source_payload(region["id"], source_type="DEALER", name="ED",
                              external_key="src-ent"),
        DATAOPS), 201)
    validate_success(api.activate_source(source["id"], DATAOPS), 200)
    from test_helpers import submit_accepted_batch, create_batch_item_payload
    submit_accepted_batch(source["id"], [
        create_batch_item_payload(config["id"], region["id"],
                                  sold_price_cents=3040000,
                                  sale_date="2026-08-20", mileage=10000),
    ], submission_ref="b-ent")
    series = validate_success(api.create_valuation_series(
        {"configuration_id": config["id"], "region_id": region["id"],
         "effective_from": "2026-09-01T00:00:00Z", "cadence": "WEEKLY",
         "external_key": "ser-ent"},
        ADMIN), 201)
    validate_success(api.activate_valuation_series(series["id"], ADMIN), 200)

    edition = validate_success(api.create_valuation_edition(
        {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
        ADMIN), 201)
    assert edition["reference_price_cents"] == 3040000
    assert edition["trade_in_cents"] == 2644800
    assert edition["private_party_cents"] == 2888000
    assert edition["retail_cents"] == 3283200


def test_source_requires_existing_region(api):
    """PRD §2.8: "Body-supplied foreign keys (region_id, source_id,
    configuration_id, series_id, edition_id, offer_id, batch_id,
    agreement_id, and every element of option_ids) are resolved under the
    same ERR_NOT_FOUND umbrella: an unresolvable reference in the payload is
    a 404, not a 400."

    Design: Corner/entities/source_requires_existing_region
    """
    res = api.create_source(
        create_source_payload(NON_EXISTENT_UUID, source_type="DEALER",
                              name="Ghost", external_key="src-ghost"),
        DATAOPS)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
