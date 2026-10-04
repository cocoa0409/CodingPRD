"""Research record creation, retrieval and publication."""


from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    build_verified_attribute,
    create_property,
    get_property,
    get_success_data,
    setup_provider_org,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_property_create_returns_every_declared_field_and_starts_draft_open(api):
    """PRD §3.1: "The record opens in the `DRAFT` research state with a `land_posture` of `OPEN` and an empty research dossier: `parent_property_id` is null because this is a root record, `attribute_verified_count`, `attribute_total_count` and `stale_source_count` all begin at zero, `completeness_pct` begins at 0.0, and `verified_sale_value_cents` begins at zero."

    Design: Corner/entities/property_create_returns_every_declared_field_and_starts_draft_open
    """
    provider = setup_provider_org()
    resp = api.create_property(
        {
            "market": "TX-DALLAS",
            "address_line": "1400 Ross Ave",
            "property_type": "OFFICE",
            "rentable_sqft": 120_000,
            "classification": "CLASS_A",
        },
        provider["creator_headers"],
    )
    data = validate_success(resp, 201)
    assert data["research_status"] == "DRAFT"
    assert data["land_posture"] == "OPEN"
    assert data["version"] == 1
    assert data["parent_property_id"] is None
    assert data["completeness_pct"] == 0.0
    assert data["attribute_total_count"] == 0
    assert data["attribute_verified_count"] == 0
    assert data["stale_source_count"] == 0
    assert data["verified_sale_value_cents"] == 0
    assert data["id"] and data["created_at"] and data["updated_at"]


def test_organization_get_returns_the_stored_tier_and_derived_counts(api):
    """PRD §2.8: "It also carries a `service_tier` drawn from `ENTERPRISE`, `MID_MARKET` or `SMB`; when the creating request omits that field it defaults to `ENTERPRISE`, and the tier feeds every fee rebase described in §3."

    Design: Corner/entities/organization_get_returns_the_stored_tier_and_derived_counts
    """
    org = get_success_data(api.create_organization(
        {"legal_name": "Meridian Advisory Partners", "org_type": "SUBSCRIBER",
         "home_market": "TX-DALLAS"},
        {"X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin"},
    ))
    snapshot = get_success_data(api.get_organization(org["id"], {
        "X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin",
    }))
    assert snapshot["legal_name"] == "Meridian Advisory Partners"
    assert snapshot["org_type"] == "SUBSCRIBER"
    assert snapshot["home_market"] == "TX-DALLAS"
    assert snapshot["service_tier"] == "ENTERPRISE"
    assert snapshot["status"] == "ACTIVE"
    assert snapshot["authorized_market_count"] == 0
    assert snapshot["active_contract_count"] == 0


def test_property_get_with_an_unknown_id_returns_property_not_found(api):
    """PRD §2.12: "The not-found identifiers are specific to the entity being resolved: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_USER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_ATTRIBUTE_NOT_FOUND`, `ERR_SOURCE_DOCUMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SEAT_NOT_FOUND` and `ERR_ENFORCEMENT_CASE_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/property_get_with_an_unknown_id_returns_property_not_found
    """
    provider = setup_provider_org()
    resp = api.get_property(NON_EXISTENT_UUID, provider["creator_headers"])
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND)
    assert resp.status_code == 404


def test_property_create_missing_rentable_sqft_returns_invalid_request(api):
    """PRD §2.1: "A request whose payload omits a required input field, or whose field fails its declared type or enumeration constraint, is rejected with `ERR_INVALID_REQUEST` and carries HTTP status 400."

    Design: Corner/entities/property_create_missing_rentable_sqft_returns_invalid_request
    """
    provider = setup_provider_org()
    resp = api.create_property(
        {"market": "TX-DALLAS", "address_line": "1400 Ross Ave", "property_type": "OFFICE"},
        provider["creator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400
    listed, meta = validate_paginated(
        api.list_properties(provider["creator_headers"])
    )
    assert len(listed) == 0
    assert meta["total_count"] == 0


def test_property_create_violating_the_classification_enum_returns_invalid_request(api):
    """PRD §3.1: "A research cycle begins when a `ResearchAnalyst` registers a commercial building, supplying its `market`, its `address_line`, a `property_type` drawn from `OFFICE`, `RETAIL`, `INDUSTRIAL`, `MULTIFAMILY` or `HOSPITALITY`, a `rentable_sqft` figure that must be greater than zero, and an optional `classification` drawn from `CLASS_A`, `CLASS_B` or `CLASS_C`."

    Design: Corner/entities/property_create_violating_the_classification_enum_returns_invalid_request
    """
    provider = setup_provider_org()
    resp = api.create_property(
        {"market": "TX-DALLAS", "address_line": "1400 Ross Ave", "property_type": "OFFICE",
         "rentable_sqft": 120_000, "classification": "CLASS_D"},
        provider["creator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert resp.status_code == 400


def test_property_create_omitting_classification_defaults_to_class_b(api):
    """PRD §3.1: "When the caller omits `classification`, the record is created as `CLASS_B`."

    Design: Corner/entities/property_create_omitting_classification_defaults_to_class_b
    """
    provider = setup_provider_org()
    data = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="7500 N Central Expy",
        property_type="OFFICE", rentable_sqft=60_000,
    )
    assert "classification" in data
    assert data["classification"] == "CLASS_B"
    assert data["research_status"] == "DRAFT"


def test_user_get_with_an_unknown_id_returns_user_not_found(api):
    """PRD §2.12: "The not-found identifiers are specific to the entity being resolved: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_USER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_ATTRIBUTE_NOT_FOUND`, `ERR_SOURCE_DOCUMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SEAT_NOT_FOUND` and `ERR_ENFORCEMENT_CASE_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/user_get_with_an_unknown_id_returns_user_not_found
    """
    provider = setup_provider_org()
    resp = api.get_user(NON_EXISTENT_UUID, {
        "X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin",
    })
    validate_error(resp, ApiErrorId.ERR_USER_NOT_FOUND)
    assert resp.status_code == 404
    found = get_success_data(api.get_user(provider["creator"]["id"], {
        "X-User-ID": "ops-1", "X-User-Role": "PlatformAdmin",
    }))
    assert found["organization_id"] == provider["org"]["id"]


def test_finalize_from_draft_with_no_attributes_returns_empty_attribute_set(api):
    """PRD §3.1: "A finalize attempted on a property whose `attribute_total_count` is zero is refused with `ERR_EMPTY_ATTRIBUTE_SET` (HTTP 409), and a finalize attempted while any attribute on the property still sits in `PENDING` is refused with `ERR_ATTRIBUTES_UNRESOLVED` (HTTP 409)."

    Design: Corner/state_machines/finalize_from_draft_with_no_attributes_returns_empty_attribute_set
    """
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="2200 Bryan St",
        property_type="RETAIL", rentable_sqft=30_000, classification="CLASS_C",
    )
    resp = api.finalize_property(prop["id"], provider["creator_headers"])
    validate_error(resp, ApiErrorId.ERR_EMPTY_ATTRIBUTE_SET)
    assert resp.status_code == 409
    snapshot = get_property(prop["id"], provider["creator_headers"])
    assert snapshot["research_status"] == "DRAFT"
    assert snapshot["attribute_total_count"] == 0


def test_finalize_reaches_verified_from_either_entry_state(api):
    """PRD §3.1: "The path from `RESEARCHING` to `VERIFIED` runs through the same finalize operation as the `DRAFT` to `VERIFIED` path, and the two are distinguished only by which research state the record currently holds."

    Design: Corner/state_machines/finalize_reaches_verified_through_either_publication_edge
    """
    provider = setup_provider_org()

    first = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    build_verified_attribute(
        provider, first["id"], field_name="tenant_name", value="Harborline Logistics Inc",
        source_overrides={"obtained_at": "2026-08-25T00:00:00Z"},
    )
    direct = get_success_data(
        api.finalize_property(first["id"], provider["creator_headers"])
    )

    second = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="5000 Maple Ave",
        property_type="OFFICE", rentable_sqft=90_000, classification="CLASS_B",
    )
    get_success_data(api.start_research(second["id"], provider["creator_headers"]))
    build_verified_attribute(
        provider, second["id"], field_name="tenant_name", value="Fulcrum Interiors LLC",
        source_overrides={"obtained_at": "2026-08-25T00:00:00Z"},
    )
    after_researching = get_success_data(
        api.finalize_property(second["id"], provider["creator_headers"])
    )

    assert direct["research_status"] == "VERIFIED"
    assert after_researching["research_status"] == "VERIFIED"
    assert direct["attribute_verified_count"] == 1
    assert after_researching["attribute_verified_count"] == 1


def test_finalize_is_absent_from_the_verified_state(api):
    """PRD §3.1: "Both demand that the record hold the state the transition requires — a record in the wrong state is refused with `ERR_INVALID_STATE` (HTTP 409) — both demand that `land_posture` be `OPEN`, and both demand that the attribute set be non-empty."

    Design: Corner/state_machines/finalize_is_absent_from_the_verified_state
    """
    provider = setup_provider_org(with_officer=True)
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    build_verified_attribute(
        provider, prop["id"], field_name="tenant_name", value="Harborline Logistics Inc",
        source_overrides={"obtained_at": "2026-08-25T00:00:00Z"},
    )
    get_success_data(api.finalize_property(prop["id"], provider["creator_headers"]))

    resp = api.finalize_property(prop["id"], provider["creator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert resp.status_code == 409
    assert get_property(prop["id"], provider["creator_headers"])["research_status"] == "VERIFIED"

    # A market escalation is what moves a VERIFIED record out of that state.
    get_success_data(api.report_market_escalations(
        {"markets": ["TX-DALLAS"], "reason_code": "SOURCE_INTEGRITY_REVIEW"},
        provider["officer_headers"],
    ))
    frozen = get_property(prop["id"], provider["creator_headers"])
    assert frozen["research_status"] == "RESEARCHING"
    assert frozen["land_posture"] == "FROZEN"