"""Five peer roles with no hierarchy: each role's exclusive operations refused to its
peers, each shared operation accepted from every role on its own list, and the two
entity-backed identities checked for presence, resolution and ownership in turn.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import api_client
from test_helpers.constants import ANCHOR_MONDAY
from test_helpers.fixtures import (
    CATALOG_SPEC_COFFEE_ONLY,
    create_account,
    create_asset,
    create_route,
    evaluate_posture,
    place_asset_at_site,
    propose_adjustment,
    read_account,
    read_adjustment,
    read_placement,
    read_site,
    read_visit,
    read_work_order,
    recompute_attachment,
    schedule_visit,
    set_market_index,
    setup_placed_site,
    setup_second_site,
    setup_work_order,
)
from test_helpers.test_users import (
    TEST_USERS,
    make_customer_contact_headers,
    make_route_technician_headers,
)

PA = TEST_USERS["program_admin_headers"]
AM = TEST_USERS["account_manager_headers"]
BS = TEST_USERS["billing_specialist_headers"]

RENTAL_TERMS = {
    "terms_type": "RENTAL",
    "minimum_purchase_cents": 60000,
    "min_term_months": 12,
}


def _count(response) -> int:
    """The honest row count behind a listing page."""
    _rows, meta = validate_paginated(response)
    return meta["total_count"]


def test_every_roles_exclusive_operation_is_refused_to_each_of_its_peers():
    """Eight calls, each an operation reserved to one role and attempted by another,
    every one of them a 403 that writes nothing — and the last of them, an unknown
    adjustment invoked by the wrong role, answers with the authorization failure rather
    than the missing row.

    "If the acting role does not appear on the endpoint's authorized-role list in §4, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    "When a single request could fail several checks, the outcome is not a matter of
    implementation taste. Checks are evaluated in a fixed global order, and the **first**
    failing check determines the response."

    Design: Corner/rbac/corner_each_roles_exclusive_operation_is_unauthorized_for_every_peer
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
        **RENTAL_TERMS,
    )
    account_id = base["account"]["id"]
    site_id = base["site"]["id"]
    route_id = base["route"]["id"]
    placement_id = base["placement"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]
    visit = schedule_visit(site_id)
    account_version = read_account(account_id)["version"]

    # The route network belongs to the ProgramAdmin, not to the AccountManager.
    validate_error(
        api_client.create_route(
            f.create_route_payload(name="Pirate route", service_day="TUE"), AM
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    # Break rooms belong to the AccountManager, not to the BillingSpecialist.
    validate_error(
        api_client.create_site(
            f.create_site_payload(account_id, route_id, site_name="Billing's own site"),
            BS,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    # Invoice assembly belongs to the BillingSpecialist, not to the ProgramAdmin.
    validate_error(
        api_client.create_invoice(
            f.create_invoice_payload(
                account_id,
                "2026-08-01T00:00:00Z",
                "2026-08-31T23:59:59Z",
                account_version,
            ),
            PA,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    # Retrieval belongs to the AccountManager, not to the technician on the route.
    validate_error(
        api_client.retrieve_placement(
            placement_id,
            f.retrieve_placement_payload("SERVICEABLE"),
            make_route_technician_headers(route_id),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    # Price proposals belong to the BillingSpecialist, not to the customer's signer.
    validate_error(
        api_client.create_price_adjustment(
            f.create_price_adjustment_payload(
                account_id, effective_at="2026-08-15T00:00:00Z"
            ),
            make_customer_contact_headers(account_id),
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    # Reporting a stop belongs to the RouteTechnician, not to the AccountManager.
    validate_error(
        api_client.complete_visit(
            visit["id"],
            f.complete_visit_payload([f.delivered_line(coffee_id, 0)]),
            AM,
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    # Commitment evaluation belongs to the BillingSpecialist.
    validate_error(
        api_client.evaluate_placement_compliance(placement_id, {}, AM),
        "ERR_UNAUTHORIZED",
        403,
    )
    # Role authorization is checked above path-identifier resolution.
    unknown_target = validate_error(
        api_client.respond_price_adjustment(
            NON_EXISTENT_UUID, f.respond_payload("ACCEPT"), PA
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    assert unknown_target["error_id"] != "ERR_ADJUSTMENT_NOT_FOUND", (
        "authorization is decided before the identifier is resolved"
    )

    assert _count(api_client.list_routes(PA, params={"limit": 100})) == 1
    assert _count(api_client.list_sites(AM, params={"account_id": account_id})) == 1
    assert _count(api_client.list_invoices(BS, params={"account_id": account_id})) == 0
    assert (
        _count(api_client.list_price_adjustments(BS, params={"account_id": account_id}))
        == 0
    )
    assert read_placement(placement_id)["placement_status"] == "ACTIVE"
    assert read_visit(visit["id"])["visit_status"] == "SCHEDULED"


def test_a_shared_operation_is_accepted_from_every_role_on_its_own_list():
    """The posture recompute, the attachment recompute, work-order creation and stop
    scheduling are each shared between two roles, and each is exercised from both — while
    the market write, shared between a different pair, still refuses the account manager.

    "An `AccountManager` or `BillingSpecialist` may also recompute a site's posture
    directly, without waiting for a visit."

    "A `RouteTechnician` or a `ProgramAdmin` opens one against a placed brewer by
    supplying the `asset_id` and a `wo_type` of `PREVENTIVE` (the scheduled check),
    `DESCALE` (which clears the descale clock), or `REPAIR` (corrective work)."

    Design: Corner/rbac/corner_shared_operations_accept_either_declared_role
    """
    base = setup_placed_site(
        clock=ANCHOR_MONDAY,
        serial_number="URN30-0001",
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
        **RENTAL_TERMS,
    )
    account_id = base["account"]["id"]
    first_room = base["site"]
    route_id = base["route"]["id"]
    second_room = setup_second_site(base)
    second_asset = create_asset(base["model"]["id"], serial_number="URN30-0002")
    place_asset_at_site(second_room, second_asset["id"], **RENTAL_TERMS)
    planned_version = read_site(first_room["id"])["version"]

    by_manager = evaluate_posture(first_room["id"], headers=AM)
    assert by_manager["escalation_score"] == 0.0
    assert by_manager["service_posture"] == "ACTIVE"
    assert by_manager["version"] == planned_version
    by_billing = evaluate_posture(first_room["id"], headers=BS)
    assert by_billing["escalation_score"] == 0.0
    assert by_billing["service_posture"] == "ACTIVE"
    assert by_billing["version"] == planned_version

    assert recompute_attachment(account_id, headers=AM)["allied_attachment_bps"] == 0
    assert recompute_attachment(account_id, headers=BS)["allied_attachment_bps"] == 0

    by_technician = validate_success(
        api_client.create_work_order(
            f.create_work_order_payload(base["asset"]["id"], "REPAIR"),
            make_route_technician_headers(route_id),
        ),
        201,
    )
    assert by_technician["wo_status"] == "OPEN"
    assert by_technician["site_id"] == first_room["id"]
    by_admin = validate_success(
        api_client.create_work_order(
            f.create_work_order_payload(second_asset["id"], "REPAIR"), PA
        ),
        201,
    )
    assert by_admin["wo_status"] == "OPEN"
    assert by_admin["site_id"] == second_room["id"], (
        "the admin carries no route scoping, and the site still comes from the asset"
    )

    manager_stop = validate_success(
        api_client.create_visit(f.create_visit_payload(first_room["id"]), AM), 201
    )
    assert manager_stop["visit_status"] == "SCHEDULED"
    admin_stop = validate_success(
        api_client.create_visit(
            f.create_visit_payload(
                second_room["id"],
                window_start="2026-08-03T11:00:00Z",
                window_end="2026-08-03T11:45:00Z",
            ),
            PA,
        ),
        201,
    )
    moved = validate_success(
        api_client.reschedule_visit(
            admin_stop["id"],
            f.reschedule_visit_payload(
                "2026-08-03T13:00:00Z", "2026-08-03T13:45:00Z"
            ),
            PA,
        ),
        200,
    )
    assert moved["window_start"] == "2026-08-03T13:00:00Z"

    set_market_index(2100000, headers=BS)
    set_market_index(2200000, headers=PA)
    validate_error(
        api_client.set_green_index(f.set_green_index_payload(2300000), AM),
        "ERR_UNAUTHORIZED",
        403,
    )
    quoted = propose_adjustment(account_id, effective_at="2026-09-01T00:00:00Z")
    assert quoted["index_current_micros"] == 2200000, "the refused write stored nothing"
    assert quoted["movement_bps"] == 1000


def test_an_entity_backed_identity_is_checked_for_presence_resolution_then_ownership():
    """The same two endpoints are attacked three ways each: no identity header at all, a
    header that resolves to no row, and a header naming a real but foreign row. Only the
    owning identity is admitted, so the header is the sole difference between the refusal
    and the success.

    "For these two entity-backed roles the identifier must actually resolve — a
    `RouteTechnician` whose `X-User-ID` matches no existing route, or a `CustomerContact`
    whose `X-User-ID` matches no existing account, is rejected with
    `ERR_UNKNOWN_ACTOR_IDENTITY` (HTTP 401)."

    "A `RouteTechnician` may only act on a service visit whose route matches its own
    `X-User-ID`, and on a maintenance work order whose site sits on the route matching
    its own `X-User-ID`; a violation of either yields `ERR_ACTOR_NOT_ON_ROUTE` (HTTP
    403)."

    Design: Corner/rbac/corner_entity_backed_identity_headers_that_do_not_resolve_or_do_not_own_the_row_are_rejected
    """
    base = setup_work_order(
        clock=ANCHOR_MONDAY,
        serial_number="URN30-0001",
        with_loaner_asset=False,
        catalog_spec=CATALOG_SPEC_COFFEE_ONLY,
        **RENTAL_TERMS,
    )
    own_account_id = base["account"]["id"]
    own_route_id = base["route"]["id"]
    work_order_id = base["work_order"]["id"]
    coffee_id = base["products"]["COFFEE"]["id"]
    visit = schedule_visit(base["site"]["id"])
    assert visit["route_id"] == own_route_id

    foreign_route = create_route(name="Uptown Monday Route", service_day="MON")
    foreign_account = create_account(legal_name="Southgate Partners LLC")
    set_market_index(2400000, headers=BS)
    proposal = propose_adjustment(own_account_id, effective_at="2026-09-01T00:00:00Z")
    assert proposal["adj_status"] == "PROPOSED"

    line_payload = f.append_visit_line_payload(coffee_id, 20)
    validate_error(
        api_client.append_visit_line(
            visit["id"], line_payload, {"X-User-Role": "RouteTechnician"}
        ),
        "ERR_MISSING_AUTH_HEADERS",
        401,
    )
    validate_error(
        api_client.append_visit_line(
            visit["id"], line_payload, TEST_USERS["route_technician_headers"]
        ),
        "ERR_UNKNOWN_ACTOR_IDENTITY",
        401,
    )
    validate_error(
        api_client.append_visit_line(
            visit["id"], line_payload, make_route_technician_headers(foreign_route["id"])
        ),
        "ERR_ACTOR_NOT_ON_ROUTE",
        403,
    )
    validate_error(
        api_client.advance_work_order(
            work_order_id,
            f.advance_work_order_payload("IN_PROGRESS"),
            make_route_technician_headers(foreign_route["id"]),
        ),
        "ERR_ACTOR_NOT_ON_ROUTE",
        403,
    )
    assert read_work_order(work_order_id)["wo_status"] == "OPEN"
    assert read_visit(visit["id"])["lines"] == []

    # "Appending a requested line to a service visit is **not** a resource
    # creation — it mutates the visit's `lines` array and returns the visit with
    # 200 OK."
    accepted_line = validate_success(
        api_client.append_visit_line(
            visit["id"], line_payload, make_route_technician_headers(own_route_id)
        ),
        200,
    )
    assert len(accepted_line["lines"]) == 1, "the body was fine all along"
    assert accepted_line["lines"][0]["requested_units"] == 20

    accept_payload = f.respond_payload("ACCEPT")
    validate_error(
        api_client.respond_price_adjustment(
            proposal["id"], accept_payload, TEST_USERS["customer_contact_headers"]
        ),
        "ERR_UNKNOWN_ACTOR_IDENTITY",
        401,
    )
    validate_error(
        api_client.respond_price_adjustment(
            proposal["id"],
            accept_payload,
            make_customer_contact_headers(foreign_account["id"]),
        ),
        "ERR_ACTOR_NOT_ACCOUNT_CONTACT",
        403,
    )
    assert read_adjustment(proposal["id"])["adj_status"] == "PROPOSED"

    settled = validate_success(
        api_client.respond_price_adjustment(
            proposal["id"],
            accept_payload,
            make_customer_contact_headers(own_account_id),
        ),
        200,
    )
    assert settled["adj_status"] == "ACCEPTED"
