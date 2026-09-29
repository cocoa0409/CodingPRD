"""Resource shapes, server-set defaults, windowed listings and the
request-shape rejections that create nothing."""

from test_helpers import (
    BSD_HEADERS,
    FDM_HEADERS,
    ApiErrorId,
    assert_brand,
    assert_common_fields,
    assert_error_envelope,
    assert_integer,
    assert_money,
    assert_object_envelope,
    assert_owner,
    assert_pagination_window,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated_list,
)

UNKNOWN_AGREEMENT_ID = "11111111-2222-3333-4444-555555555555"
UNKNOWN_PIP_ID = "99999999-8888-7777-6666-555555555555"


def test_publishing_a_brand_returns_every_declared_field_in_the_envelope(api):
    """PRD §2.2 and §3.1: a creation answers 201 with response_type 'object'
    and a meta block carrying the request identity, and the body echoes all
    eight submitted fields, the two counters at zero, and the server-generated
    identity and audit stamps.

    Design: Corner/entities/brand_create_returns_every_declared_field_in_the_success_envelope
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    response = api.create_brand(factories.build_solaris_brand_payload(), BSD_HEADERS)
    brand = assert_object_envelope(response, 201)

    assert brand["code"] == "SOLARIS"
    assert brand["name"] == "Solaris Collection"
    assert brand["tier"] == "UPSCALE"
    assert_money(brand["base_royalty_rate_pct"], 5.00, "base_royalty_rate_pct")
    assert_money(brand["marketing_fund_rate_pct"], 2.50, "marketing_fund_rate_pct")
    assert_money(brand["protected_radius_miles"], 5.00, "protected_radius_miles")
    assert_integer(brand["min_room_count"], 80, "min_room_count")
    assert_integer(brand["standard_term_years"], 20, "standard_term_years")
    assert_integer(brand["operating_unit_count"], 0, "operating_unit_count")
    assert_integer(brand["open_application_count"], 0, "open_application_count")
    assert_common_fields(brand, "brand")
    assert_brand(brand)


def test_reading_an_owner_back_reproduces_the_created_financial_profile(api):
    """PRD §3.2: an ownership entity read carries back the four submitted
    profile inputs unchanged alongside the two capacity variants the server
    derived from them, the initial PROSPECT status and revision zero.

    Design: Corner/entities/owner_read_back_matches_the_created_financial_profile
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    created = fixtures.create_strong_owner(api)
    owner = assert_object_envelope(api.get_owner(created["id"], FDM_HEADERS))

    assert owner["legal_name"] == "Harbor Point Hospitality LP"
    assert_money(owner["liquid_assets_amount"], 6_000_000.00, "liquid_assets_amount")
    assert_money(owner["net_worth_amount"], 18_000_000.00, "net_worth_amount")
    assert_integer(owner["credit_score"], 760, "credit_score")
    assert_integer(owner["existing_units_count"], 4, "existing_units_count")
    assert_money(owner["capacity_score_standalone"], 96.67, "capacity_score_standalone")
    assert_money(
        owner["capacity_score_portfolio_adjusted"], 100.00, "capacity_score_portfolio_adjusted"
    )
    assert owner["status"] == "PROSPECT"
    assert_integer(owner["financial_profile_revision"], 0, "financial_profile_revision")
    assert_owner(owner)


def test_application_listing_windows_three_rows_across_two_pages(api):
    """PRD §2.3: a listing reports total_count over everything matching the
    filters before the window is applied and sets has_more exactly when rows
    remain beyond it, ordering by created_at ascending - so three SUBMITTED
    applications come back as two pages of two and one.

    Design: Corner/entities/list_applications_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)
    owner = fixtures.create_strong_owner(api)
    ids = [
        fixtures.create_application(
            api, owner["id"], brand["id"], property_name=f"Harbor Point Hotel {index}"
        )["id"]
        for index in range(1, 4)
    ]

    params = {"brand_id": brand["id"], "status": "SUBMITTED", "limit": 2, "offset": 0}
    rows, meta = validate_paginated_list(api.list_applications(FDM_HEADERS, params))
    assert_pagination_window(meta, 2, 0, 3)
    assert [row["id"] for row in rows] == ids[:2], "rows must be ordered by created_at ascending"

    params["offset"] = 2
    rows, meta = validate_paginated_list(api.list_applications(FDM_HEADERS, params))
    assert_pagination_window(meta, 2, 2, 3)
    assert [row["id"] for row in rows] == ids[2:]

    read_brand = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(read_brand["open_application_count"], 3, "open_application_count")


def test_reading_an_agreement_that_does_not_exist_names_the_agreement_family(api):
    """PRD §2.9 and §5: an unresolvable path identifier answers 404 with the
    not-found error of that resource family and an error envelope carrying a
    non-empty message.

    Design: Corner/entities/get_agreement_with_unknown_uuid_returns_agreement_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    response = api.get_agreement(UNKNOWN_AGREEMENT_ID, FDM_HEADERS)
    validate_error(response, ApiErrorId.AGREEMENT_NOT_FOUND)
    assert response.status_code == 404

    data = assert_error_envelope(response)
    assert data["message"].strip(), "the error message must not be empty"


def test_application_missing_its_room_count_is_a_request_shape_failure(api):
    """PRD §2.9 band 5: a body missing a required field fails request-shape
    validation with 400 before anything is created, so the collection stays
    empty and the brand's open-application counter never moves.

    Design: Corner/entities/application_create_missing_required_room_count_returns_invalid_request
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)
    owner = fixtures.create_strong_owner(api)

    payload = factories.build_harbor_point_application_payload(owner["id"], brand["id"])
    payload.pop("room_count")
    response = api.create_application(payload, FDM_HEADERS)
    validate_error(response, ApiErrorId.INVALID_REQUEST)
    assert response.status_code == 400

    _, meta = validate_paginated_list(api.list_applications(FDM_HEADERS, {"brand_id": brand["id"]}))
    assert_integer(meta["total_count"], 0, "total_count")
    read_brand = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(read_brand["open_application_count"], 0, "open_application_count")


def test_registering_an_owner_defaults_the_status_and_the_profile_revision(api):
    """PRD §3.2: registration stamps status PROSPECT and
    financial_profile_revision zero without either being supplied, and both
    capacity variants are banded immediately - INSUFFICIENT for a thin
    portfolio.

    Design: Corner/entities/owner_create_defaults_status_to_prospect_and_revision_to_zero
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    response = api.create_owner(
        factories.build_owner_payload(
            legal_name="Cascade Thin Portfolio LLC",
            contact_email="thin@cascadethin.example",
            liquid_assets_amount=2_400_000.00,
            net_worth_amount=7_500_000.00,
            credit_score=680,
            existing_units_count=3,
        ),
        FDM_HEADERS,
    )
    owner = assert_object_envelope(response, 201)

    assert owner["status"] == "PROSPECT"
    assert_integer(owner["financial_profile_revision"], 0, "financial_profile_revision")
    assert owner["capacity_band_standalone"] == "INSUFFICIENT"
    assert owner["capacity_band_portfolio_adjusted"] == "INSUFFICIENT"


def test_registering_a_unit_ignores_a_submitted_status_and_stamps_operating(api):
    """PRD §3.1: registration stamps the unit's status as OPERATING and leaves
    status_reason null until the first status move, so a status supplied in the
    body is not an input - the unit is OPERATING and counts towards the brand.

    Design: Corner/entities/existing_unit_create_extra_field_status_is_ignored_input
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)
    response = api.create_existing_unit(
        factories.build_existing_unit_payload(
            brand["id"],
            unit_name="Solaris Lakeside",
            x_miles=1.20,
            y_miles=1.60,
            room_count=100,
            adr_amount=310.00,
            occupancy_pct=72.00,
            territory_start_date="2016-06-01",
            status="TERMINATED",
        ),
        BSD_HEADERS,
    )
    unit = assert_object_envelope(response, 201)

    assert unit["status"] == "OPERATING", (
        f"the submitted status must be ignored, got {unit['status']}"
    )
    assert unit["status_reason"] is None

    read_brand = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(read_brand["operating_unit_count"], 1, "operating_unit_count")


def test_publishing_a_second_brand_on_a_taken_code_is_refused(api):
    """PRD §3.1: a brand code is unique across the estate, so a second
    publication on a code another brand holds is refused with 409 and the
    incumbent brand is left exactly as it was.

    Design: Corner/entities/brand_create_with_a_code_another_brand_holds_is_rejected
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)

    response = api.create_brand(
        factories.build_brand_payload(
            code="SOLARIS",
            name="Solaris Collection Reserve",
            tier="LUXURY",
            base_royalty_rate_pct=6.00,
            marketing_fund_rate_pct=2.80,
            protected_radius_miles=6.00,
            min_room_count=90,
            standard_term_years=15,
        ),
        BSD_HEADERS,
    )
    validate_error(response, ApiErrorId.BRAND_CODE_TAKEN)
    assert response.status_code == 409

    incumbent = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert incumbent["name"] == "Solaris Collection"
    assert incumbent["tier"] == "UPSCALE"


def test_application_with_an_affiliation_outside_the_vocabulary_is_refused(api):
    """PRD §2.12: an enumerated field accepts only the exact upper-case tokens
    the vocabulary declares, so an unrecognised affiliation is a request-shape
    failure with 400 and nothing is created.

    Design: Corner/entities/application_create_with_unknown_affiliation_returns_invalid_enum_error
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    brand = fixtures.create_solaris_brand(api)
    owner = fixtures.create_strong_owner(api)

    response = api.create_application(
        factories.build_harbor_point_application_payload(
            owner["id"], brand["id"], current_affiliation="BOUTIQUE"
        ),
        FDM_HEADERS,
    )
    validate_error(response, ApiErrorId.INVALID_REQUEST)
    assert response.status_code == 400

    read_brand = get_success_data(api.get_brand(brand["id"], BSD_HEADERS))
    assert_integer(read_brand["open_application_count"], 0, "open_application_count")


def test_adding_a_scope_line_under_an_unknown_plan_names_the_plan_family(api):
    """PRD §2.9: path identifiers are resolved outermost first and an
    unresolvable parent answers that family's not-found error, so a scope line
    filed under a plan that does not exist is a 404 on the plan.

    Design: Corner/entities/pip_item_create_under_an_unknown_plan_returns_not_found
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    response = api.create_pip_item(
        UNKNOWN_PIP_ID,
        factories.build_pip_item_payload(description="Guestroom soft goods"),
        BSD_HEADERS,
    )
    validate_error(response, ApiErrorId.PIP_NOT_FOUND)
    assert response.status_code == 404


def test_claim_naming_a_hotel_of_another_brand_is_refused_as_an_ineligible_claimant(api):
    """PRD §3.4: the aggrieved hotel must be OPERATING and carry the
    application's own brand_id, and a unit of another brand is refused with the
    same ineligible-claimant error - the unit itself stays OPERATING, and it
    was never in the impact input set either, which is scored over the
    application's brand alone.

    Design: Corner/entities/encroachment_claim_naming_a_unit_of_another_brand_is_rejected
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    conversion_brand = fixtures.create_solaris_brand(api)
    other_brand = fixtures.create_brand(api, code="POLARIS", name="Polaris Select", tier="MIDSCALE")
    other_unit = fixtures.create_existing_unit(
        api, other_brand["id"], unit_name="Polaris Lakeside",
        x_miles=1.20, y_miles=1.60, room_count=100, adr_amount=310.00, occupancy_pct=72.00,
    )
    owner = fixtures.create_strong_owner(api)
    application = fixtures.create_application(api, owner["id"], conversion_brand["id"])
    fixtures.start_review(api, application["id"])
    fixtures.set_clock(api, "2026-08-05T00:00:00Z")
    scored = fixtures.run_impact_analysis(api, application["id"])

    response = api.file_encroachment_claim(
        application["id"],
        factories.build_encroachment_claim_payload(
            other_unit["id"],
            claimed_revenue_loss_pct=8.00,
            narrative="Filed by a hotel of a different brand.",
        ),
        BSD_HEADERS,
    )
    validate_error(response, ApiErrorId.UNIT_NOT_OPERATING)
    assert response.status_code == 422

    read_unit_rows, _ = validate_paginated_list(
        api.list_brand_existing_units(other_brand["id"], BSD_HEADERS)
    )
    assert read_unit_rows[0]["status"] == "OPERATING", (
        "the refusal is about the brand mismatch, not the unit's own state"
    )
    assert_money(scored["preliminary_impact_score"], 0.00, "preliminary_impact_score")
    assert_integer(
        scored["impact_unit_count_preliminary"], 0, "impact_unit_count_preliminary"
    )

    _, meta = validate_paginated_list(
        api.list_encroachment_claims(BSD_HEADERS, {"application_id": application["id"]})
    )
    assert_integer(meta["total_count"], 0, "total_count")
