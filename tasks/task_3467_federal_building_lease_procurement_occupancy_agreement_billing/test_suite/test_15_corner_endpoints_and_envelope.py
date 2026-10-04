"""Corner coverage: response envelope shapes, body-level FK existence, and
the succeeding-lease execution branch."""
from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, create_agency,
    create_offer_payload, get_success_data, set_clock,
    setup_expiring_lease_with_plan, validate_error, validate_paginated,
    validate_success, walk_requirement_to_soliciting,
)

ADMIN = TEST_USERS["gsa_admin_headers"]
OFFICER = TEST_USERS["gsa_leasing_officer_headers"]
LESSOR = TEST_USERS["lessor_rep_headers"]


def test_response_envelope_success_and_error_shapes(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/endpoints/response_envelope_success_and_error_shapes
    """
    agency = get_success_data(api.create_agency(
        {"bureau_code": "BUR-370", "name": "Forest Service"}, ADMIN))

    ok_resp = api.get_agency(agency["id"], ADMIN)
    ok_data = validate_success(ok_resp, 200)
    ok_body = ok_resp.json()
    assert ok_body["response_type"] == "object"
    assert isinstance(ok_body["meta"]["api_request_id"], str)
    assert isinstance(ok_body["meta"]["api_request_timestamp"], str)
    assert ok_data["id"] == agency["id"]

    err_resp = api.get_agency(NON_EXISTENT_UUID, ADMIN)
    validate_error(err_resp, ApiErrorId.ERR_NOT_FOUND)
    err_body = err_resp.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert err_body["data"]["message"]


def test_offer_create_with_unknown_building_returns_not_found(api):
    """PRD §2.8: "Requests that carry resource identifiers are validated left
    to right: path identifiers first, in path order, then identifiers
    referenced in the request body (for example `lease_id`, `building_id`, and
    `agency_id` when an occupancy agreement is created, `building_id` when an
    offer is created, or `reported_oa_id` when a service ticket is created).
    The first identifier that does not resolve to an existing resource rejects
    the request with `ERR_NOT_FOUND` (HTTP 404); later identifiers are not
    examined."

    Design: Corner/endpoints/offer_create_with_unknown_building_returns_not_found
    """
    agency = create_agency()
    set_clock("2026-10-01T00:00:00Z")
    req = walk_requirement_to_soliciting(agency)

    resp = api.create_offer(req["id"], create_offer_payload(
        NON_EXISTENT_UUID, lessor_name="Ghost Holdings"), LESSOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    offers, _ = validate_paginated(api.list_offers(
        OFFICER, params={"requirement_id": req["id"]}))
    assert offers == [], "no offer persisted"


def test_plan_execute_succeeding_lease_creates_successor(api):
    """PRD §3.9: "A `SUCCEEDING_LEASE` execution creates a new lease in
    `AWARDED` on the same building for the same agency, its `succeeds_lease_id`
    pointing back to the expiring lease, its rates and term taken from the
    stored `cost_params`, and its `leased_sf` carried over; the plan's
    `outcome_lease_id` records it."
    PRD §3.9: "When the current date passes an `EXPIRING` lease's `end_date`,
    the sweep moves it to `SUCCEEDED` if its `executed_option` is
    `SUCCEEDING_LEASE`, and to `EXPIRED` otherwise — including when no option
    was ever executed."

    Design: Corner/endpoints/plan_execute_succeeding_lease_creates_successor
    """
    bundle = setup_expiring_lease_with_plan(option="SUCCEEDING_LEASE")
    lease, building, plan = bundle["lease"], bundle["building"], bundle["plan"]

    executed = validate_success(api.execute_plan(plan["id"], OFFICER), 200)
    assert executed["status"] == "EXECUTED"
    new_lease_id = executed["outcome_lease_id"]
    assert new_lease_id is not None

    successors, _ = validate_paginated(api.list_leases(
        ADMIN, params={"succeeds_lease_id": lease["id"]}))
    assert successors[0]["id"] == new_lease_id, (
        "self-referential link via succeeds_lease_id")

    successor = validate_success(api.get_lease(new_lease_id, ADMIN), 200)
    assert successor["status"] == "AWARDED"
    assert successor["building_id"] == building["id"]
    assert successor["shell_rate_per_sf_yr_cents"] == 3200
    assert successor["term_months"] == 120, "succeeding_term_years 10 * 12"
    assert successor["leased_sf"] == 68300, "carried over"

    set_clock("2037-01-01T00:00:00Z")
    old_after = validate_success(api.get_lease(lease["id"], ADMIN), 200)
    assert old_after["executed_option"] == "SUCCEEDING_LEASE"
    assert old_after["status"] == "SUCCEEDED", "not EXPIRED"
