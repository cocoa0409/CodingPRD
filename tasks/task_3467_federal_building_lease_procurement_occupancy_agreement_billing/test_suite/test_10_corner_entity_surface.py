"""Corner coverage: entity creation defaults, field domains, not-found,
listing pagination, and occupancy-agreement tenancy structure."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, assert_agency, create_agency,
    create_leased_building, create_offer_payload, create_owned_building,
    create_requirement, get_success_data, set_clock, setup_commenced_lease,
    validate_error, validate_paginated, validate_success,
    walk_requirement_to_soliciting,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


def test_agency_create_returns_defaults(api):
    """PRD §3.1: "An agency is registered with a `bureau_code` — unique across
    all agencies — and a display `name`; its `status` is `ACTIVE` from
    creation, the only value that field takes."
    PRD §2.6: "`id` (string): a unique, server-minted identifier formatted as a
    UUID, with no type prefix."
    PRD §2.6: "`created_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits, set when the resource is created."
    PRD §2.6: "`version` (integer): a system-managed integer that increments by
    one on every mutation of the resource, including system-driven transitions,
    cascade effects, and computed-field recomputation."

    Design: Corner/entities/agency_create_returns_defaults
    """
    set_clock("2026-10-01T00:00:00Z")
    agency = validate_success(api.create_agency(
        {"bureau_code": "BUR-301", "name": "Forest Service"}, ADMIN), 201)
    assert_agency(agency)
    assert agency["status"] == "ACTIVE", "the default is applied at creation"
    assert agency["bureau_code"] == "BUR-301"
    assert agency["name"] == "Forest Service"


def test_agency_create_missing_required_bureau_code(api):
    """PRD §3.1: "An agency is registered with a `bureau_code` — unique across
    all agencies — and a display `name`; its `status` is `ACTIVE` from
    creation, the only value that field takes."
    PRD §2.10: "5. Request shape and field domains: required fields present,
    enums within their declared sets, numeric ranges respected,
    `special_needs` item shape, `measured_at` not in the future —
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/agency_create_missing_required_bureau_code
    """
    resp = api.create_agency({"name": "Forest Service"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_building_security_capability_out_of_range_rejected(api):
    """PRD §3.1: "`security_capability` (an integer from 1 to 5 expressing the
    highest facility security level the building can support)"
    PRD §2.10: "5. Request shape and field domains: required fields present,
    enums within their declared sets, numeric ranges respected,
    `special_needs` item shape, `measured_at` not in the future —
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/building_security_capability_out_of_range_rejected
    """
    resp = api.create_building(
        {"building_name": "X", "address": "1 A St", "region_code": "R9",
         "ownership_type": "FEDERALLY_OWNED", "security_capability": 6,
         "total_sf": 10000}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_requirement_create_applies_initial_state_and_defaults(api):
    """PRD §3.2: "A new requirement starts in `DRAFT`, with `delivery_method`
    set to `STANDARD` and `source_plan_id` null — both are only ever different
    when an expiration plan spawns the requirement (§3.9)."
    PRD §3.2: "Validation is the computational heart of requirement
    development and moves `SUBMITTED` to `VALIDATED`. Two calculations run at
    this moment."

    Design: Corner/entities/requirement_create_applies_initial_state_and_defaults
    """
    agency = create_agency()
    req = create_requirement(
        agency, title="Field Office", base_headcount=120,
        annual_growth_pct=0.01, target_occupancy_year=2030, sf_per_person=160,
        special_needs=[], region_code="R4", mission_points=10,
        population_points=8, size_points=6, criticality_points=6)
    assert req["status"] == "DRAFT"
    assert req["delivery_method"] == "STANDARD"
    assert req["source_plan_id"] is None
    assert req.get("projected_headcount") is None, (
        "projection happens only at validate")
    assert req.get("required_security_level") is None
    assert req.get("required_usable_sf") is None


def test_get_missing_agency_returns_not_found(api):
    """PRD §2.8: "The first identifier that does not resolve to an existing
    resource rejects the request with `ERR_NOT_FOUND` (HTTP 404); later
    identifiers are not examined."

    Design: Corner/entities/get_missing_agency_returns_not_found
    """
    resp = api.get_agency(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_offer_list_pagination_and_requirement_filter(api):
    """PRD §2.3: "List endpoints paginate through two query parameters.
    `limit` sets the maximum number of items returned; it defaults to 10, with
    a minimum of 1 and a maximum of 100. `offset` sets the number of items to
    skip and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/offer_list_pagination_and_requirement_filter
    """
    agency = create_agency()
    bld1 = create_leased_building(building_name="Metro Tower")
    bld2 = create_leased_building(building_name="Riverside Annex",
                                  address="200 River Rd")
    set_clock("2026-10-01T00:00:00Z")
    req = walk_requirement_to_soliciting(agency)
    off1 = get_success_data(api.create_offer(
        req["id"], create_offer_payload(bld1["id"]), LESSOR))
    off2 = get_success_data(api.create_offer(
        req["id"], create_offer_payload(
            bld2["id"], lessor_name="River Properties Inc",
            escalation_method="CPI_INDEXED", shell_rate_per_sf_yr_cents=3100,
            operating_rate_per_sf_yr_cents=880,
            base_year_tax_per_sf_yr_cents=410, ti_allowance_per_sf_cents=4500,
            free_rent_months=2), LESSOR))

    page1, meta1 = validate_paginated(api.list_offers(
        ADMIN, params={"requirement_id": req["id"], "limit": 1, "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(api.list_offers(
        ADMIN, params={"requirement_id": req["id"], "limit": 1, "offset": 1}))
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False

    assert page1[0]["id"] != page2[0]["id"]
    assert {page1[0]["id"], page2[0]["id"]} == {off1["id"], off2["id"]}


def test_oa_create_tenancy_ambiguity_rejected(api):
    """PRD §3.5: "Creation demands exactly one of `lease_id` or `building_id`:
    presenting both, or neither, is rejected with `ERR_OA_TENANCY_AMBIGUOUS`."

    Design: Corner/entities/oa_create_tenancy_ambiguity_rejected
    """
    bundle = setup_commenced_lease()
    agency, lease = bundle["agency"], bundle["lease"]
    owned = create_owned_building()

    both = api.create_oa(
        {"lease_id": lease["id"], "building_id": owned["id"],
         "agency_id": agency["id"], "assigned_sf": 1000,
         "start_date": "2027-01-01", "end_date": "2030-12-31"}, OFFICER)
    validate_error(both, ApiErrorId.ERR_OA_TENANCY_AMBIGUOUS)

    neither = api.create_oa(
        {"agency_id": agency["id"], "assigned_sf": 1000,
         "start_date": "2027-01-01", "end_date": "2030-12-31"}, OFFICER)
    validate_error(neither, ApiErrorId.ERR_OA_TENANCY_AMBIGUOUS)


def test_oa_create_on_leased_stock_building_rejected(api):
    """PRD §3.5: "A `building_id` agreement is only valid on a
    `FEDERALLY_OWNED` building — pointing one at leased stock fails with
    `ERR_BUILDING_NOT_OWNED`"

    Design: Corner/entities/oa_create_on_leased_stock_building_rejected
    """
    agency = create_agency()
    leased = create_leased_building()
    resp = api.create_oa(
        {"building_id": leased["id"], "agency_id": agency["id"],
         "assigned_sf": 1000, "start_date": "2027-01-01",
         "end_date": "2030-12-31",
         "shell_equivalent_rate_per_sf_yr_cents": 2800,
         "operating_rate_per_sf_yr_cents": 800}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_BUILDING_NOT_OWNED)


def test_owned_oa_missing_rate_inputs_rejected(api):
    """PRD §3.5: "A `building_id` agreement is only valid on a
    `FEDERALLY_OWNED` building — pointing one at leased stock fails with
    `ERR_BUILDING_NOT_OWNED` — and requires the market-rate inputs
    `shell_equivalent_rate_per_sf_yr_cents` and
    `operating_rate_per_sf_yr_cents`; an owned agreement missing either rate
    fails with `ERR_INVALID_REQUEST`, while on a leased agreement both are
    simply ignored."

    Design: Corner/entities/owned_oa_missing_rate_inputs_rejected
    """
    agency = create_agency(name="Park Service")
    owned = create_owned_building()
    resp = api.create_oa(
        {"building_id": owned["id"], "agency_id": agency["id"],
         "assigned_sf": 1000, "start_date": "2027-01-01",
         "end_date": "2030-12-31",
         "operating_rate_per_sf_yr_cents": 800}, OFFICER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
