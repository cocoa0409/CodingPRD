"""Validation precedence, cross-entity gates and compensating invariants."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_distinct_user,
    build_verified_attribute,
    create_lease_comparable,
    create_listing,
    create_property,
    create_sale_transaction,
    ensure_researching,
    get_success_data,
    set_logical_clock,
    setup_listing_licensed_brokerage,
    setup_provider_org,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_authentication_check_precedes_the_existence_check(api):
    """PRD §2.14: "Authentication and request shape come first: a missing or empty `X-User-ID` or `X-User-Role` header surfaces as `ERR_UNAUTHENTICATED` (401), and a missing required field or a field that fails its declared type or enumeration surfaces as `ERR_INVALID_REQUEST` (400)."

    Design: Difficulty/priority_pair_validation_conflict/auth_outranks_existence_on_a_property_read
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    resp = api.get_property(NON_EXISTENT_UUID, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401


def test_a_well_formed_request_for_the_same_absent_property_reports_not_found(api):
    """PRD §2.14: "Existence follows, resolved left to right per §2.12, so a bad path identifier surfaces as its 404 not-found error ahead of any business rule."

    PRD §2.12: "The not-found identifiers are specific to the entity being resolved: `ERR_ORGANIZATION_NOT_FOUND`, `ERR_USER_NOT_FOUND`, `ERR_PROPERTY_NOT_FOUND`, `ERR_ATTRIBUTE_NOT_FOUND`, `ERR_SOURCE_DOCUMENT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_SEAT_NOT_FOUND` and `ERR_ENFORCEMENT_CASE_NOT_FOUND`, each carrying HTTP 404."

    Design: Difficulty/priority_pair_validation_conflict/auth_outranks_existence_on_a_property_read
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    provider = setup_provider_org()
    resp = api.get_property(NON_EXISTENT_UUID, provider["creator_headers"])
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND)
    assert resp.status_code == 404
    # The only difference from the unauthenticated call is the presence of the
    # auth headers, so the 401 observed there came from the auth gate.
    unauthenticated = api.get_property(NON_EXISTENT_UUID, {})
    assert unauthenticated.status_code == 401


def test_referential_integrity_outranks_the_fiscal_floor_on_a_sale(api):
    """PRD §2.14: "Referential integrity within the business model comes next, at HTTP 422: a subdivision originating from a property that is not `DRAFT` reports `ERR_SUBDIVISION_PARENT_INVALID`; an attribute whose `attribute_market` diverges from its property's `market` reports `ERR_ATTRIBUTE_MARKET_MISMATCH`; a lease whose `lease_end` is not strictly after its `lease_start` reports `ERR_LEASE_WINDOW_INVALID`; and a sale recorded on a property whose research state is neither `RESEARCHING` nor `VERIFIED` reports `ERR_SALE_PROPERTY_NOT_RESEARCHED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_outranks_fiscal_on_a_sale_transaction
    """
    set_logical_clock("2026-07-20T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="4100 Oak Lawn Ave",
        property_type="INDUSTRIAL", rentable_sqft=200_000, classification="CLASS_B",
    )
    resp = api.create_sale_transaction(
        prop["id"],
        {"buyer_name": "Cedar Point Capital", "close_date": "2026-07-01T00:00:00Z",
         "gross_sale_price_cents": 0},
        provider["creator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SALE_PROPERTY_NOT_RESEARCHED)
    assert resp.status_code == 422
    rows, meta = validate_paginated(
        api.list_sale_transactions(provider["creator_headers"], {"property_id": prop["id"]})
    )
    assert len(rows) == 0
    assert meta["total_count"] == 0


def test_the_fiscal_floor_fires_once_the_property_is_researched(api):
    """PRD §3.3: "A sale is recorded against a property with a `buyer_name`, a `close_date` and a `gross_sale_price_cents` that must be strictly positive — a non-positive price is refused with `ERR_SALE_PRICE_NOT_POSITIVE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_outranks_fiscal_on_a_sale_transaction
    """
    set_logical_clock("2026-07-20T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="4100 Oak Lawn Ave",
        property_type="INDUSTRIAL", rentable_sqft=200_000, classification="CLASS_B",
    )
    ensure_researching(prop["id"], provider["creator_headers"])
    resp = api.create_sale_transaction(
        prop["id"],
        {"buyer_name": "Cedar Point Capital", "close_date": "2026-07-01T00:00:00Z",
         "gross_sale_price_cents": 0},
        provider["creator_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SALE_PRICE_NOT_POSITIVE)
    assert resp.status_code == 409


def test_research_start_depends_on_the_acting_users_assigned_market(api):
    """PRD §2.5: "the API resolves the acting analyst's `assigned_market` as its defined address and rejects a scoped operation on a `Property` whose `market` differs from it with `ERR_PROPERTY_NOT_FOUND` and HTTP 404, exactly as though no such record existed."

    Design: Difficulty/cross_entity_state_dependency/research_start_depends_on_the_acting_users_assigned_market
    """
    set_logical_clock("2026-03-01T00:00:00Z")
    provider = setup_provider_org()
    nm_analyst, nm_headers = add_distinct_user(
        provider["org"]["id"], role="RESEARCH_ANALYST",
        full_name="Yusuf Adeyemi", assigned_market="NM-ALBUQUERQUE",
    )
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    resp = api.start_research(prop["id"], nm_headers)
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND)
    assert resp.status_code == 404
    assert get_success_data(
        api.get_property(prop["id"], provider["creator_headers"])
    )["research_status"] == "DRAFT"


def test_the_in_market_analyst_completes_the_same_research_start(api):
    """PRD §3.1: "Starting research explicitly advances `research_status` to `RESEARCHING`."

    Design: Difficulty/cross_entity_state_dependency/research_start_depends_on_the_acting_users_assigned_market
    """
    set_logical_clock("2026-03-01T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    started = validate_success(
        api.start_research(prop["id"], provider["creator_headers"]), 200
    )
    assert started["research_status"] == "RESEARCHING"
    assert started["version"] >= 2


def test_listing_publication_is_blocked_by_the_propertys_restricted_posture(api):
    """PRD §3.8: "The property's `land_posture` must be `OPEN` — a `FROZEN` property yields `ERR_PROPERTY_FROZEN` and a `RESTRICTED` one yields `ERR_PROPERTY_RESTRICTED`, both HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/listing_publication_depends_on_the_propertys_land_posture
    """
    set_logical_clock("2026-06-10T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    licensed = setup_listing_licensed_brokerage(markets=["TX-DALLAS"])
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    listing = create_listing(
        prop["id"], licensed["org"]["id"], licensed["publisher_headers"],
    )
    validate_success(
        api.report_market_escalations(
            {"markets": ["TX-DALLAS"], "reason_code": "LISTING_INTEGRITY_REVIEW"},
            provider["officer_headers"],
        ),
        200,
    )
    assert get_success_data(
        api.get_property(prop["id"], provider["creator_headers"])
    )["land_posture"] == "RESTRICTED"

    resp = api.publish_listing(listing["id"], licensed["publisher_headers"])
    validate_error(resp, ApiErrorId.ERR_PROPERTY_RESTRICTED)
    assert resp.status_code == 409
    assert get_success_data(
        api.get_listing(listing["id"], licensed["publisher_headers"])
    )["status"] == "DRAFT"


def test_listing_publication_is_blocked_outside_the_licensed_markets(api):
    """PRD §3.8: "The origin market must lie inside the publishing organization's licensed markets, or the request is refused with `ERR_UNAUTHORIZED_REDISTRIBUTION` (HTTP 409)."

    PRD §2.11: "A `THIRD_PARTY_LICENSED` source document may not be used to support an attribute or a listing in a market outside the acting organization's licensed markets; the rejection carries `ERR_UNAUTHORIZED_REDISTRIBUTION` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/listing_publication_depends_on_the_propertys_land_posture
    """
    set_logical_clock("2026-06-10T00:00:00Z")
    provider = setup_provider_org()
    out_of_market = setup_listing_licensed_brokerage(
        markets=["TX-AUSTIN"], org_name="Lone Star Listing Co", service_tier="SMB",
    )
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    listing = create_listing(
        prop["id"], out_of_market["org"]["id"], out_of_market["publisher_headers"],
    )
    resp = api.publish_listing(listing["id"], out_of_market["publisher_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_REDISTRIBUTION)
    assert resp.status_code == 409
    assert get_success_data(
        api.get_listing(listing["id"], out_of_market["publisher_headers"])
    )["status"] == "DRAFT"


def test_index_attribution_roll_adds_the_comparable_count(api):
    """PRD §3.5: "`attributed_records_delta` records how many records the run contributes to its market's attributed-record count; it is set to the run's `comp_count` when the run is created and is set to 0 when the run's attribution is removed."

    Design: Difficulty/compensating_invariant/index_attribution_roll_and_removal_conserve_attributed_records
    """
    set_logical_clock("2026-05-20T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    build_verified_attribute(
        provider, prop["id"], field_name="tenant_name", value="Harborline Logistics Inc",
        source_overrides={"obtained_at": "2026-05-10T00:00:00Z"},
    )
    validate_success(api.finalize_property(prop["id"], provider["creator_headers"]), 200)
    create_lease_comparable(
        prop["id"], provider["creator_headers"], lease_start="2026-06-01T00:00:00Z",
        lease_end="2027-06-01T00:00:00Z", effective_rent_psf=32.0,
    )
    create_lease_comparable(
        prop["id"], provider["creator_headers"], tenant_name="Fulcrum Interiors LLC",
        lease_start="2026-07-01T00:00:00Z", lease_end="2027-07-01T00:00:00Z",
        escalated_rent_psf=36.0, effective_rent_psf=30.0,
    )
    run = validate_success(
        api.create_index_run(
            {"market": "TX-DALLAS", "window_start": "2026-06-01T00:00:00Z",
             "window_end": "2027-06-01T00:00:00Z", "adjustment_mode": "UNADJUSTED"},
            provider["creator_headers"],
        ),
        201,
    )
    assert run["comp_count"] == 2
    assert run["attributed_records_delta"] == 2
    assert run["attribution_status"] == "ATTRIBUTED"


def test_index_attribution_removal_unwinds_the_run_without_touching_the_sale_total(api):
    """PRD §3.5: "A run's `attribution_status` is `ATTRIBUTED` while it contributes and `UNWOUND` once its records have been removed, and an attribution removal by a licensing or enforcement administrator is what performs that transition."

    PRD §3.5: "Removal never touches the historical index value; it only withdraws the run's contribution to the market's current count."

    Design: Difficulty/compensating_invariant/index_attribution_roll_and_removal_conserve_attributed_records
    """
    set_logical_clock("2026-05-20T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    build_verified_attribute(
        provider, prop["id"], field_name="tenant_name", value="Harborline Logistics Inc",
        source_overrides={"obtained_at": "2026-05-10T00:00:00Z"},
    )
    validate_success(api.finalize_property(prop["id"], provider["creator_headers"]), 200)
    create_lease_comparable(
        prop["id"], provider["creator_headers"], lease_start="2026-06-01T00:00:00Z",
        lease_end="2027-06-01T00:00:00Z", effective_rent_psf=32.0,
    )
    create_lease_comparable(
        prop["id"], provider["creator_headers"], tenant_name="Fulcrum Interiors LLC",
        lease_start="2026-07-01T00:00:00Z", lease_end="2027-07-01T00:00:00Z",
        escalated_rent_psf=36.0, effective_rent_psf=30.0,
    )
    run = validate_success(
        api.create_index_run(
            {"market": "TX-DALLAS", "window_start": "2026-06-01T00:00:00Z",
             "window_end": "2027-06-01T00:00:00Z", "adjustment_mode": "UNADJUSTED"},
            provider["creator_headers"],
        ),
        201,
    )
    create_sale_transaction(
        prop["id"], provider["creator_headers"], gross_sale_price_cents=5_000_000_000,
    )
    value_before = get_success_data(
        api.get_property(prop["id"], provider["creator_headers"])
    )["verified_sale_value_cents"]

    removed = validate_success(
        api.remove_attribution(run["id"], provider["officer_headers"]), 200
    )
    assert removed["attributed_records_delta"] == 0
    assert removed["attribution_status"] == "UNWOUND"
    assert removed["index_value"] == run["index_value"]
    # A second removal leaves the counter at zero rather than going negative.
    again = validate_success(
        api.remove_attribution(run["id"], provider["officer_headers"]), 200
    )
    assert again["attributed_records_delta"] == 0
    value_after = get_success_data(
        api.get_property(prop["id"], provider["creator_headers"])
    )["verified_sale_value_cents"]
    assert value_after == value_before == 0

def test_a_frozen_property_refuses_finalize_research_start_and_subdivision(api):
    """PRD §3.7: "The frozen property's discipline is strict: while it sits at `FROZEN`, finalize, the explicit start of research and subdivision are all refused with `ERR_PROPERTY_FROZEN` (HTTP 409)"

    PRD §3.4: "`FROZEN` blocks finalize, the start of research and subdivision."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_outranks_business_safety_on_a_frozen_property
    """
    set_logical_clock("2026-06-01T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    build_verified_attribute(
        provider, prop["id"], field_name="tenant_name", value="Harborline Logistics Inc",
        source_overrides={"obtained_at": "2026-05-20T00:00:00Z"},
    )
    validate_success(api.finalize_property(prop["id"], provider["creator_headers"]), 200)
    validate_success(
        api.report_market_escalations(
            {"markets": ["TX-DALLAS"], "reason_code": "SOURCE_INTEGRITY_REVIEW"},
            provider["officer_headers"],
        ),
        200,
    )
    snapshot = get_success_data(api.get_property(prop["id"], provider["creator_headers"]))
    assert snapshot["land_posture"] == "FROZEN"

    finalize_resp = api.finalize_property(prop["id"], provider["creator_headers"])
    validate_error(finalize_resp, ApiErrorId.ERR_PROPERTY_FROZEN)
    assert finalize_resp.status_code == 409

    start_resp = api.start_research(prop["id"], provider["creator_headers"])
    validate_error(start_resp, ApiErrorId.ERR_PROPERTY_FROZEN)
    assert start_resp.status_code == 409

    subdivide_resp = api.subdivide_property(
        prop["id"],
        {"market": "TX-DALLAS", "address_line": "1400 Ross Ave", "property_type": "OFFICE",
         "rentable_sqft": 40_000, "classification": "CLASS_A"},
        provider["creator_headers"],
    )
    validate_error(subdivide_resp, ApiErrorId.ERR_PROPERTY_FROZEN)
    assert subdivide_resp.status_code == 409


def test_the_frozen_gate_leaves_the_property_posture_unchanged(api):
    """PRD §3.7: "its `research_status` drops back to `RESEARCHING`, its `land_posture` becomes `FROZEN`, and every `PropertyAttribute` on it whose `proposed_status` is `PENDING` is reset to `NONE` with its `proposed_value` cleared."

    Design: Difficulty/priority_pair_validation_conflict/state_gate_outranks_business_safety_on_a_frozen_property
    """
    set_logical_clock("2026-06-01T00:00:00Z")
    provider = setup_provider_org(with_officer=True)
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="1400 Ross Ave",
        property_type="OFFICE", rentable_sqft=120_000, classification="CLASS_A",
    )
    build_verified_attribute(
        provider, prop["id"], field_name="tenant_name", value="Harborline Logistics Inc",
        source_overrides={"obtained_at": "2026-05-20T00:00:00Z"},
    )
    validate_success(api.finalize_property(prop["id"], provider["creator_headers"]), 200)
    validate_success(
        api.report_market_escalations(
            {"markets": ["TX-DALLAS"], "reason_code": "SOURCE_INTEGRITY_REVIEW"},
            provider["officer_headers"],
        ),
        200,
    )
    before = get_success_data(api.get_property(prop["id"], provider["creator_headers"]))
    api.start_research(prop["id"], provider["creator_headers"])
    after = get_success_data(api.get_property(prop["id"], provider["creator_headers"]))
    assert after["land_posture"] == "FROZEN"
    assert after["research_status"] == before["research_status"]
    assert after["version"] == before["version"]



def test_finalize_on_a_draft_property_first_moved_to_researching_reports_the_empty_set(api):
    """PRD §3.1: "A finalize attempted on a property whose `attribute_total_count` is zero is refused with `ERR_EMPTY_ATTRIBUTE_SET` (HTTP 409)"

    PRD §3.1: "Finalizing attempts to publish the record, and the two rules that guard publication are stated in §3.4."

    Design: Difficulty/priority_pair_validation_conflict/state_outranks_business_fiscal_on_finalize
    """
    set_logical_clock("2026-07-15T00:00:00Z")
    provider = setup_provider_org()
    prop = create_property(
        provider["creator_headers"], market="TX-DALLAS", address_line="2200 Bryan St",
        property_type="RETAIL", rentable_sqft=30_000, classification="CLASS_C",
    )
    validate_success(api.start_research(prop["id"], provider["creator_headers"]), 200)
    resp = api.finalize_property(prop["id"], provider["creator_headers"])
    validate_error(resp, ApiErrorId.ERR_EMPTY_ATTRIBUTE_SET)
    assert resp.status_code == 409
