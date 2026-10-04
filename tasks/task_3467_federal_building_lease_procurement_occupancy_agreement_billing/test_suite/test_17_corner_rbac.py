"""Corner coverage: role-based access control — exclusive denials, the
entity-backed agency scope rule, and the shared read surface (PRD §2.1, §4)."""
from test_helpers import (
    ApiErrorId, TEST_USERS, create_agency, create_leased_building,
    create_offer_payload, create_requirement, generate_bill,
    get_success_data, make_agency_manager_headers, set_clock,
    setup_active_leased_oa, submit_requirement, validate_error,
    validate_paginated, validate_success, walk_requirement_to_soliciting,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
PM = TEST_USERS["gsa_property_manager_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


def test_lessor_cannot_register_building(api):
    """PRD §2.1: "Each endpoint admits a fixed list of roles (see §4); a caller
    whose role is not on that list is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §4: "| POST | `/leasing/buildings` | Register a federally owned or
    leased-stock building | GSAAdmin |"

    Design: Corner/rbac/lessor_cannot_register_building
    """
    resp = api.create_building(
        {"building_name": "X", "address": "1 A St", "region_code": "R9",
         "ownership_type": "FEDERALLY_OWNED", "security_capability": 3,
         "total_sf": 10000}, LESSOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_agency_manager_cannot_validate_requirement(api):
    """PRD §2.1: "Each endpoint admits a fixed list of roles (see §4); a caller
    whose role is not on that list is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §4: "| POST | `/leasing/space-requirements/{id}/validate` | Validate a
    `SUBMITTED` requirement; computes projection, security level, and required
    square footage | GSALeasingOfficer |"

    The owning agency cannot self-validate even on its own requirement.

    Design: Corner/rbac/agency_manager_cannot_validate_requirement
    """
    agency = create_agency()
    set_clock("2026-10-01T00:00:00Z")
    req = create_requirement(
        agency, title="Field Office", base_headcount=120,
        annual_growth_pct=0.01, target_occupancy_year=2030, sf_per_person=160,
        special_needs=[], region_code="R4", mission_points=10,
        population_points=8, size_points=6, criticality_points=6)
    submit_requirement(req, agency)

    resp = api.validate_requirement(
        req["id"], make_agency_manager_headers(agency["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    after = validate_success(api.get_space_requirement(req["id"], OFFICER), 200)
    assert after["status"] == "SUBMITTED"


def test_property_manager_cannot_award_lease(api):
    """PRD §2.1: "Each endpoint admits a fixed list of roles (see §4); a caller
    whose role is not on that list is rejected with `ERR_FORBIDDEN_FOR_ROLE`
    (HTTP 403)."
    PRD §4: "| POST | `/leasing/offers/{id}/select` | Award the lease to this
    offer; creates the lease and rejects sibling offers | GSALeasingOfficer |"

    Design: Corner/rbac/property_manager_cannot_award_lease
    """
    agency = create_agency()
    building = create_leased_building()
    set_clock("2026-10-01T00:00:00Z")
    req = walk_requirement_to_soliciting(agency)
    offer = get_success_data(api.create_offer(
        req["id"], create_offer_payload(building["id"]), LESSOR))
    get_success_data(api.evaluate_offer(offer["id"], OFFICER))

    resp = api.select_offer(offer["id"], PM)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    after = validate_success(api.get_offer(offer["id"], OFFICER), 200)
    assert after["status"] == "UNDER_EVALUATION"
    req_after = validate_success(api.get_space_requirement(req["id"], OFFICER), 200)
    assert req_after["status"] == "SOLICITING"


def test_agency_manager_paying_other_agencys_bill_denied(api):
    """PRD §2.1: "When `X-User-Role` is `AgencyManager`, `X-User-ID` is the
    `id` of the acting `Agency`; ownership checks on any resource that
    references an `Agency` compare the resource's `agency_id` field to
    `X-User-ID`, and a mismatch is rejected with `ERR_AGENCY_SCOPE_VIOLATION`
    (HTTP 403)."

    Agency B paying agency A's bill is scope-denied and leaves no trace; the
    identical payment by agency A succeeds.

    Design: Corner/rbac/agency_manager_paying_other_agencys_bill_denied
    """
    bundle = setup_active_leased_oa(tax_year=None)
    oa, agency_a = bundle["oa"], bundle["agency"]
    agency_b = create_agency(name="Park Service")
    bill = generate_bill(oa, "2027-04")

    resp = api.pay_bill(bill["id"], {"amount_cents": 1000},
                        make_agency_manager_headers(agency_b["id"]))
    validate_error(resp, ApiErrorId.ERR_AGENCY_SCOPE_VIOLATION)
    bills, _ = validate_paginated(api.list_bills(oa["id"], ADMIN))
    assert bills[0]["amount_paid_cents"] == 0, "scope-denied payment left no trace"

    paid = validate_success(api.pay_bill(
        bill["id"], {"amount_cents": 1000},
        make_agency_manager_headers(agency_a["id"])), 200)
    assert paid["status"] == "PARTIALLY_PAID"
    assert paid["amount_paid_cents"] == 1000


def test_lessor_shared_get_building_allowed(api):
    """PRD §4: "| GET | `/leasing/buildings/{id}` | Get one building, including
    computed `available_sf` | GSAAdmin, GSALeasingOfficer, GSAPropertyManager,
    AgencyManager, LessorRep |"

    The read surface is shared by all five roles.

    Design: Corner/rbac/lessor_shared_get_building_allowed
    """
    building = create_leased_building()
    data = validate_success(api.get_building(building["id"], LESSOR), 200)
    assert data["id"] == building["id"]
