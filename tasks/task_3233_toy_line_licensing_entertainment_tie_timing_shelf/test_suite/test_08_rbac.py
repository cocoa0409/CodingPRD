"""Role-based access control corners, including entity-backed ownership."""
from test_helpers import (
    ApiErrorId,
    BRAND,
    SAFETY,
    STUDIO,
    create_agreement,
    create_evergreen_line,
    create_property,
    create_retailer,
    create_shipment,
    create_sku,
    create_studio,
    fixtures,
    make_retailer_ops_headers,
    set_clock,
    setup_active_agreement,
    setup_evergreen_line_with_sku,
    setup_review_with_commitment,
    validate_error,
    validate_success,
)


def test_studio_rep_cannot_create_toy_line(api):
    """PRD §4: the `POST /toy-licensing/toy-lines` row authorizes only
    `BrandManager`.
    PRD §2.1: "A request whose role is not permitted for the operation — or that
    fails an entity-backed ownership check — is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/studio_rep_cannot_create_toy_line
    """
    set_clock("2026-10-01T00:00:00Z")
    studio = create_studio(name="S")
    prop = create_property(studio["id"], title="P", release_date="2027-01-01T00:00:00Z")
    agreement = create_agreement(prop["id"])

    resp = api.create_toy_line(
        {
            "name": "X",
            "brand_kind": "LICENSED",
            "property_id": prop["id"],
            "license_agreement_id": agreement["id"],
        },
        STUDIO,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_brand_manager_cannot_approve_own_amendment(api):
    """PRD §4: the `POST /toy-licensing/license-agreements/{id}/amendments/approve`
    row authorizes only `StudioRep`.
    PRD §2.1: "A request whose role is not permitted for the operation — or that
    fails an entity-backed ownership check — is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/brand_manager_cannot_approve_own_amendment
    """
    set_clock("2026-10-01T00:00:00Z")
    studio, prop, agreement = setup_active_agreement()
    validate_success(
        api.amend_license_agreement(
            agreement["id"],
            {
                "royalty_rate_pct": 0.15,
                "advance_guarantee_cents": 0,
                "end_date": "2029-12-31T00:00:00Z",
            },
            BRAND,
        )
    )

    resp = api.approve_amendment(agreement["id"], {}, BRAND)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    data = validate_success(api.get_license_agreement(agreement["id"], BRAND))
    assert data["status"] == "AMENDMENT_PENDING"


def test_retailer_ops_cannot_record_sale_for_other_retailer(api):
    """PRD §2.1: "In particular, a `RetailerOps` caller may record sales only on
    shipments whose host line review belongs to the retailer identified by
    `X-User-ID`, and may schedule line reviews only for that same retailer."

    Design: Corner/rbac/retailer_ops_cannot_record_sale_for_other_retailer
    """
    set_clock("2026-10-01T00:00:00Z")
    line, sku = setup_evergreen_line_with_sku(street="2026-09-01T00:00:00Z")
    retailer_a = create_retailer(name="A-Mart")
    retailer_b, review_b, commitment_b = setup_review_with_commitment(
        sku,
        retailer_name="B-Mart",
        committed_units=100,
        unit_price_cents=100,
        shelf_slots=2,
    )
    shipment_b = create_shipment(
        commitment_b["id"], planned_ship_date="2026-09-01T00:00:00Z", units=100
    )

    # RetailerOps acting as retailer A touches retailer B's shipment.
    resp = api.record_sale(
        shipment_b["id"], {"units_sold": 10}, make_retailer_ops_headers(retailer_a["id"])
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)

    shipment_data = validate_success(api.get_shipment(shipment_b["id"], BRAND))
    assert shipment_data["sold_units"] == 0


def test_safety_engineer_cannot_create_sku(api):
    """PRD §4: the `POST /toy-licensing/skus` row authorizes only `BrandManager`.
    PRD §2.1: "A request whose role is not permitted for the operation — or that
    fails an entity-backed ownership check — is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/safety_engineer_cannot_create_sku
    """
    line = create_evergreen_line(name="L")
    resp = api.create_sku(
        {
            "toy_line_id": line["id"],
            "name": "A",
            "age_grade_months": 36,
            "packaging_claims": ["BPA_FREE"],
            "moq_units": 1,
            "unit_cost_cents": 100,
            "tooling_cost_cents": 1000,
        },
        SAFETY,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
