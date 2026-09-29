"""Four peers, one partition of the work, and no actor who can walk an order alone."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DESIGNER_OWNERSHIP_REQUIRED,
    ERR_ROLE_NOT_PERMITTED,
)
from test_helpers.assertions import assert_page_meta
from test_helpers.fixtures import (
    accept_quote,
    book_consultation,
    build_quote,
    charter_territory,
    configure_opening,
    hire_designer,
    intake_lead,
    onboard_vendor,
    place_order,
    present_quote,
    read_consultation,
    read_territory,
    record_opening,
)
from test_helpers.test_users import (
    designer_headers,
    franchisee_headers,
    franchisor_headers,
    vendor_rep_headers,
)

ABSENT_QUOTE_ID = "11111111-1111-4111-8111-111111111111"

CORDED_VENDOR = {"base_lead_time_days": 10, "motorization_extra_days": 3,
                 "cutoff_hour_utc": 15, "remake_policy": "SHARED_50_50",
                 "concurrent_capacity": 5,
                 "supported_lift_systems": ["CORDED"]}


def test_the_four_roles_partition_the_work_in_both_directions(api):
    """Headquarters cannot measure, the owner cannot enrol a mill, and both refusals stick.

    "Four roles exist, and their names are spelled exactly `Franchisor`, `Franchisee`,
    `Designer` and `VendorRep`."

    "Brand headquarters charters territories, onboards manufacturers, drives the logical
    clock and reads every royalty ledger, but headquarters can never measure an opening,
    price a quote, install a blind or commission a motor."

    "Conversely a `Designer` runs the entire in-home workflow but cannot charter a
    territory, hire a colleague, or place a manufacturing order."

    "The Authorized Role(s) column names the roles permitted to invoke the endpoint at
    all; where a role is additionally restricted to resources it owns, that ownership rule
    is stated in Section 2.1 and in the relevant workflow of Section 3, and is enforced
    after existence has been established."

    Design: Corner/rbac/the_four_roles_are_peers_and_the_franchisor_is_not_a_superset
    """
    territory = charter_territory(api, postal_codes=["30301"])
    designer = hire_designer(api, territory)
    vendor = onboard_vendor(api, **CORDED_VENDOR)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, designer, lead)

    headquarters = franchisor_headers()
    owner = franchisee_headers(territory["id"])
    acting = designer_headers(designer["id"])
    dispatcher = vendor_rep_headers(vendor["id"])

    # Measuring is the designer's alone: neither peer above them may do it.
    validate_error(
        api.create_opening(f.opening_payload(consultation["id"],
                                             label="HQ tries to measure"),
                           headquarters),
        ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(
        api.create_opening(f.opening_payload(consultation["id"],
                                             label="Owner tries to measure"),
                           owner),
        ERR_ROLE_NOT_PERMITTED, 403)

    # The identical body from the right role lands, so the refusals were the role.
    measured = validate_success(
        api.create_opening(f.opening_payload(consultation["id"],
                                             label="Designer measures"),
                           acting), 201)
    assert measured["measure_status"] == "MEASURED"

    # Manufacturers are brand-level; the sample library is the franchisee's.
    validate_error(
        api.create_vendor(
            f.vendor_payload(name="Owner's own mill", base_lead_time_days=8,
                             motorization_extra_days=2, cutoff_hour_utc=12,
                             remake_policy="SHARED_50_50",
                             concurrent_capacity=3,
                             supported_lift_systems=["CORDED"]), owner),
        ERR_ROLE_NOT_PERMITTED, 403)
    validate_error(
        api.create_sample_kit(
            f.sample_kit_payload(territory["id"], kit_code="HQ-KIT",
                                 replacement_value_cents=50000),
            headquarters),
        ERR_ROLE_NOT_PERMITTED, 403)

    # The royalty-bearing territory read is closed to the designer who earns it.
    validate_error(api.get_territory(territory["id"], acting),
                   ERR_ROLE_NOT_PERMITTED, 403)

    # Role at priority 2 outranks existence at priority 3: no probing for prices.
    validate_error(api.get_quote(ABSENT_QUOTE_ID, dispatcher),
                   ERR_ROLE_NOT_PERMITTED, 403)

    validate_error(
        api.set_clock_raw({"current_utc": "2026-08-02T00:00:00.000Z"}, owner),
        ERR_ROLE_NOT_PERMITTED, 403)

    # Nothing any refusal attempted was written.
    assert read_consultation(api, designer,
                             consultation["id"])["measured_opening_count"] == 1
    kits, kit_meta = validate_paginated(
        api.list_sample_kits(owner, territory_id=territory["id"]))
    assert kits == []
    assert_page_meta(kit_meta, total_count=0, has_more=False)
    enrolled = validate_success(api.get_vendor(vendor["id"], headquarters))
    assert enrolled["name"] == "Ridgeline Shade Works"
    assert enrolled["base_lead_time_days"] == 10


def test_no_single_actor_can_walk_an_order_from_placed_to_received(api):
    """A designer's peer is refused on assignment, and ship and receive need two actors.

    "Every designer write is gated on being the assigned designer: the consultation being
    closed out, the consultation behind a sample check-out, the consultation behind an
    opening, the consultation behind a quote, and the install job being commissioned or
    signed off must all name this designer. A designer acting on somebody else's work is
    rejected with `ERR_DESIGNER_OWNERSHIP_REQUIRED` (HTTP 403)."

    "A manufacturer's dispatcher holds exactly one write in the whole API — reporting one
    of its own orders shipped — and may report only orders whose manufacturing vendor is
    itself."

    "Receipt is the point at which the vendor's production slot is released and the
    franchise's exposure falls: the vendor's `open_order_count` and the territory's
    `open_order_exposure_cents` are both re-derived downward, the latter by that order's
    `order_cost_cents`."

    Design: Corner/rbac/ownership_and_the_ship_receive_split_keep_two_actors_on_every_order
    """
    territory = charter_territory(api, postal_codes=["30301"])
    assigned = hire_designer(api, territory)
    colleague = hire_designer(api, territory, full_name="Marco Silva")
    vendor = onboard_vendor(api, **CORDED_VENDOR)
    lead = intake_lead(api, territory)
    consultation = book_consultation(api, assigned, lead)
    opening = configure_opening(
        api, assigned, record_opening(api, assigned, consultation, label="Den"),
        fabric_code="LT-SHEER", lift_system="CORDED")
    quote = build_quote(api, assigned, consultation)
    present_quote(api, assigned, quote)
    accept_quote(api, assigned, quote)
    order = place_order(api, territory, quote, [opening["id"]], vendor)
    assert order["order_cost_cents"] == 2083
    assert read_territory(api, territory)["open_order_exposure_cents"] == 2083

    peer = designer_headers(colleague["id"])
    owner = franchisee_headers(territory["id"])
    dispatcher = vendor_rep_headers(vendor["id"])

    # The right role on somebody else's appointment: priority 6, not priority 2.
    validate_error(
        api.create_opening(f.opening_payload(consultation["id"],
                                             label="Peer intrudes"), peer),
        ERR_DESIGNER_OWNERSHIP_REQUIRED, 403)
    validate_error(api.complete_consultation(consultation["id"], peer),
                   ERR_DESIGNER_OWNERSHIP_REQUIRED, 403)

    # The franchisee who paid for the order still cannot declare it shipped.
    validate_error(api.ship_vendor_order(order["id"], owner),
                   ERR_ROLE_NOT_PERMITTED, 403)
    shipped = validate_success(api.ship_vendor_order(order["id"], dispatcher))
    assert shipped["status"] == "SHIPPED"

    # And the vendor cannot sign for its own delivery.
    validate_error(api.receive_vendor_order(order["id"], dispatcher),
                   ERR_ROLE_NOT_PERMITTED, 403)
    received = validate_success(api.receive_vendor_order(order["id"], owner))
    assert received["status"] == "RECEIVED"
    assert received["order_cost_cents"] == 2083
    assert read_territory(api, territory)["open_order_exposure_cents"] == 0

    # The dispatcher sees what to make, never what it sold for.
    validate_error(api.get_quote(quote["id"], dispatcher),
                   ERR_ROLE_NOT_PERMITTED, 403)
    assert validate_success(
        api.get_vendor_order(order["id"], dispatcher))["id"] == order["id"]

    # A rejected peer write leaves no trace on the appointment it targeted.
    closed_out = read_consultation(api, assigned, consultation["id"])
    assert closed_out["measured_opening_count"] == 1
    assert closed_out["status"] == "SCHEDULED"
