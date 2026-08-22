"""Registration defaults and the reverse-reachability list channels."""

from test_helpers import (
    ADMIN,
    INTAKE,
    WAREHOUSE,
    agency_payload,
    client_payload,
    create_agency,
    create_approved_referral,
    create_client,
    create_referral,
    create_run,
    create_truck,
    create_volunteer,
    donation_item_payload,
    invite_crew,
    issue_voucher,
    make_case_manager_headers,
    make_volunteer_headers,
    prepare_offer_for_intake,
    set_clock,
    setup_allocated_voucher,
    triage_offer,
    validate_paginated,
    validate_success,
    voucher_line_payload,
)
from test_helpers import create_donation_offer as make_offer
from test_helpers.assertions import (
    assert_client,
    assert_crew_assignment,
    assert_partner_agency,
)


def test_agency_registration_stamps_quota_standing_and_version_defaults(api):
    """PRD §3.1: "A newly registered agency opens with `quota_used` at 0,
    `quota_epoch` at 1, `standing` at `GOOD`, and `no_show_credits_owed_cents`
    at 0."
    PRD §2.4: "`version` — an integer that starts at 1 when the row is created
    and increases by exactly 1 on every mutation of that row, including
    mutations applied indirectly as a side effect of an operation aimed at a
    different resource."

    Design: Corner/entities/corner_agency_creation_stamps_quota_and_standing_defaults
    """
    set_clock("2026-08-01T00:00:00Z")

    response = api.create_agency(
        agency_payload(name="Anchor Street Collective", county="NORTH",
                       quarterly_voucher_quota=4),
        ADMIN,
    )
    agency = validate_success(response, 201)

    assert_partner_agency(agency)
    assert agency["quota_used"] == 0, "a new agency opens with quota_used at 0"
    assert agency["quota_epoch"] == 1, "a new agency opens with quota_epoch at 1"
    assert agency["standing"] == "GOOD", "a new agency opens with standing GOOD"
    assert agency["no_show_credits_owed_cents"] == 0
    assert agency["version"] == 1, "version starts at 1 when the row is created"
    assert agency["quarterly_voucher_quota"] == 4
    assert agency["county"] == "NORTH"


def test_household_registration_defaults_has_infant_and_computed_fields(api):
    """PRD §3.1: "Households are registered by a `CaseManager`, who supplies the
    `agency_id` of their own agency, a `household_size` of at least 1 and at
    most 12, the `county` the household lives in, and an optional `has_infant`
    flag that defaults to false and means the household includes a child under
    24 months."
    PRD §3.1: "A newly registered household opens in `status` `ACTIVE` with
    `bed_bug_status` `CLEAR`, `bed_bug_confirmed_at` null, `no_show_strikes` at
    0, `delivery_ban_until` null, and `lifetime_vouchers_delivered` at 0."

    Design: Corner/entities/corner_client_has_infant_defaults_to_false_when_omitted
    """
    agency = create_agency(name="Brookfield Helpline", county="CENTRAL",
                           quarterly_voucher_quota=4)

    payload = client_payload(agency["id"], household_size=3, county="CENTRAL")
    payload.pop("has_infant")
    household = validate_success(
        api.create_client(payload, make_case_manager_headers(agency["id"])), 201
    )

    assert_client(household)
    assert household["has_infant"] is False, "has_infant defaults to false when omitted"
    assert household["status"] == "ACTIVE"
    assert household["bed_bug_status"] == "CLEAR"
    assert household["bed_bug_confirmed_at"] is None
    assert household["no_show_strikes"] == 0
    assert household["delivery_ban_until"] is None
    assert household["lifetime_vouchers_delivered"] == 0


def test_referral_listing_pages_with_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` block of a list response carries `limit` (the
    effective page size), `offset` (the effective starting position),
    `total_count` (the number of matching rows before the page window is
    applied), and `has_more` (true when rows remain beyond the current page)."
    PRD §3.2: "Referrals may be listed with optional filters on `client_id`,
    `agency_id` and `status`."

    Design: Corner/entities/corner_referral_listing_paginates_with_total_count_and_has_more
    """
    agency = create_agency(name="Fairmount Family Bridge", county="CENTRAL",
                           quarterly_voucher_quota=5)
    for size, category in ((2, "BED"), (3, "SOFA"), (4, "CRIB")):
        household = create_client(agency["id"], household_size=size, county="CENTRAL")
        create_referral(agency["id"], household["id"],
                        requested_categories=[category])

    first_page, first_meta = validate_paginated(
        api.list_referrals(ADMIN, {"agency_id": agency["id"], "limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"limit 2 must return 2 rows, got {len(first_page)}"
    assert first_meta["total_count"] == 3, "total_count counts rows before the window"
    assert first_meta["has_more"] is True, "rows remain beyond the first page"

    second_page, second_meta = validate_paginated(
        api.list_referrals(ADMIN, {"agency_id": agency["id"], "limit": 2, "offset": 2})
    )
    assert len(second_page) == 1, f"offset 2 must return the last row, got {len(second_page)}"
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False, "no rows remain beyond the second page"

    for row in first_page + second_page:
        assert row["agency_id"] == agency["id"], "the agency filter must scope the list"


def test_voucher_listing_filtered_by_referral_returns_only_that_referrals_voucher(api):
    """PRD §3.3: "Vouchers may be listed with optional filters on `referral_id`,
    `status` and `fee_status`; a voucher's lines and its booked stops are each
    readable as their own collections, filterable by `status`."

    Design: Corner/endpoints/corner_vouchers_filtered_list_scopes_to_one_referral
    """
    agency = create_agency(name="Silverbirch Aid", county="CENTRAL",
                           quarterly_voucher_quota=5)
    household_one = create_client(agency["id"], household_size=2, county="CENTRAL")
    household_two = create_client(agency["id"], household_size=5, county="CENTRAL")

    referral_one = create_approved_referral(agency["id"], household_one["id"],
                                            requested_categories=["BED"])
    voucher_one = issue_voucher(agency["id"], referral_one["id"],
                                [voucher_line_payload("BED", 1, "B")])
    referral_two = create_approved_referral(agency["id"], household_two["id"],
                                            requested_categories=["SOFA"])
    voucher_two = issue_voucher(agency["id"], referral_two["id"],
                                [voucher_line_payload("SOFA", 1, "C")])

    rows, meta = validate_paginated(
        api.list_vouchers(ADMIN, {"referral_id": referral_one["id"]})
    )
    assert len(rows) == 1, f"expected only referral one's voucher, got {len(rows)}"
    assert meta["total_count"] == 1
    assert rows[0]["id"] == voucher_one["id"]
    assert all(row["id"] != voucher_two["id"] for row in rows), (
        "the other referral's voucher must not appear under this filter"
    )

    lines, _ = validate_paginated(api.list_voucher_lines(voucher_one["id"], ADMIN))
    assert len(lines) == 1
    assert lines[0]["category"] == "BED"


def test_donation_offer_listing_filtered_by_assigned_truck(api):
    """PRD §3.4: "Offers may be listed with optional filters on `status`,
    `truck_id` and `pickup_county`, and an offer's pieces may be listed filtered
    by `decision`."
    PRD §3.4: "**Booking the pickup** moves a triaged offer `TRIAGED →
    PICKUP_SCHEDULED` by naming the `truck_id` that will collect it, which
    writes that value onto the offer and bumps the offer's `version`."

    Design: Corner/endpoints/corner_donation_offers_filtered_by_assigned_truck
    """
    set_clock("2026-08-04T09:00:00Z")
    truck_one = create_truck(label="BOX-51", capacity_cubic_feet=600,
                             home_county="CENTRAL", crew_minimum=1)
    truck_two = create_truck(label="BOX-52", capacity_cubic_feet=600,
                             home_county="NORTH", crew_minimum=1)

    prepared = prepare_offer_for_intake(
        truck_one["id"], [donation_item_payload("DRESSER", "B", False, 20.0)],
        window_start="2026-08-05T10:00:00Z", window_end="2026-08-05T12:00:00Z",
        donor_name="Boyd Alvarez", donor_phone="555-0811",
    )
    offer_scheduled = prepared["offer"]

    offer_unscheduled = make_offer(
        [donation_item_payload("TABLE_SET", "B", False, 20.0)],
        donor_name="Cleo Nakamura", donor_phone="555-0812",
        pickup_window_start="2026-08-05T14:00:00Z",
        pickup_window_end="2026-08-05T16:00:00Z",
    )
    offer_unscheduled = triage_offer(offer_unscheduled["id"])

    rows, _ = validate_paginated(
        api.list_donation_offers(INTAKE, {"truck_id": truck_one["id"]})
    )
    assert len(rows) == 1, f"only the offer booked onto truck one, got {len(rows)}"
    assert rows[0]["id"] == offer_scheduled["id"]

    empty_rows, empty_meta = validate_paginated(
        api.list_donation_offers(INTAKE, {"truck_id": truck_two["id"]})
    )
    assert empty_rows == [], "no offer is booked onto the second truck"
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    assert offer_unscheduled["truck_id"] is None, (
        "an offer that was never scheduled keeps truck_id null"
    )
    assert offer_unscheduled["status"] == "TRIAGED"


def test_inventory_listing_filters_compose_on_status_and_category(api):
    """PRD §3.5: "Warehouse stock may be read one unit at a time or listed with
    optional filters on `status`, `category`, `condition`, `donation_item_id`
    and `reserved_for_voucher_line_id`."
    PRD §3.6: "Each taken unit moves `AVAILABLE → RESERVED`, records the line in
    its `reserved_for_voucher_line_id`, raises the line's `quantity_allocated`
    by 1, and has its `version` bumped."

    Design: Corner/endpoints/corner_inventory_list_filters_compose_on_status_and_category
    """
    set_clock("2026-08-04T09:00:00Z")
    setup_allocated_voucher(
        lines=[voucher_line_payload("BED", 1, "B")],
        offer_items=[
            donation_item_payload("BED", "B", False, 30.0),
            donation_item_payload("BED", "B", False, 30.0),
            donation_item_payload("DRESSER", "B", False, 20.0),
        ],
        truck_label="BOX-50", agency_name="Thistledown Services",
    )

    available_beds, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE", "category": "BED"})
    )
    assert len(available_beds) == 1, (
        f"one BED stays AVAILABLE after the round, got {len(available_beds)}"
    )
    assert available_beds[0]["category"] == "BED"
    assert available_beds[0]["status"] == "AVAILABLE"

    all_available, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE"})
    )
    assert len(all_available) == 2, (
        f"one BED and one DRESSER remain AVAILABLE, got {len(all_available)}"
    )
    assert sorted(unit["category"] for unit in all_available) == ["BED", "DRESSER"]

    reserved_beds, _ = validate_paginated(
        api.list_inventory_items(WAREHOUSE, {"status": "RESERVED", "category": "BED"})
    )
    assert len(reserved_beds) == 1
    assert reserved_beds[0]["reserved_for_voucher_line_id"] is not None, (
        "a reserved unit records the line it is held for"
    )

    body = api.list_inventory_items(WAREHOUSE, {"status": "AVAILABLE"}).json()
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert isinstance(body["meta"].get("api_request_timestamp"), str)


def test_volunteer_crew_assignment_subresource_scopes_to_that_volunteer(api):
    """PRD §2.5: "The same discipline applies to the stops of a voucher, the
    items of a donation offer, the stops and crew of a delivery run, and the
    crew assignments of a volunteer."
    PRD §4: "List every crew assignment held by this volunteer"
    PRD §3.7: "Runs may be listed with optional filters on `truck_id`, `status`,
    `service_date` and `rescheduled_from_run_id`, and a run's stops and its crew
    are each readable as their own collections filterable by `status`."

    Design: Corner/endpoints/corner_volunteer_crew_assignments_subresource_scopes_to_that_volunteer
    """
    set_clock("2026-08-04T09:00:00Z")
    truck = create_truck(label="BOX-53", capacity_cubic_feet=600,
                         home_county="CENTRAL", crew_minimum=2)
    volunteer_a = create_volunteer(name="Dara Okonkwo", county="CENTRAL",
                                   lift_certified=True)
    volunteer_b = create_volunteer(name="Esme Lindgren", county="CENTRAL",
                                   lift_certified=False)
    run = create_run(truck["id"], service_date="2026-08-05",
                     window_start="2026-08-05T09:00:00Z",
                     window_end="2026-08-05T17:00:00Z", county="CENTRAL")
    assignment_a = invite_crew(run["id"], volunteer_a["id"], "DRIVER")
    assignment_b = invite_crew(run["id"], volunteer_b["id"], "LIFTER")

    own_rows, _ = validate_paginated(
        api.list_volunteer_crew_assignments(
            volunteer_a["id"], make_volunteer_headers(volunteer_a["id"])
        )
    )
    assert len(own_rows) == 1, (
        f"the sub-resource lists only this volunteer's assignments, got {len(own_rows)}"
    )
    assert own_rows[0]["id"] == assignment_a["id"]
    assert_crew_assignment(own_rows[0])

    crew_rows, _ = validate_paginated(api.list_run_crew(run["id"], ADMIN))
    assert len(crew_rows) == 2, "the run's own crew collection holds both invitations"
    assert {row["volunteer_id"] for row in crew_rows} == {
        volunteer_a["id"], volunteer_b["id"]
    }

    invited_b = next(row for row in crew_rows if row["id"] == assignment_b["id"])
    assert invited_b["role_on_crew"] == "LIFTER"

    run_now = validate_success(api.get_delivery_run(run["id"], ADMIN))
    assert run_now["confirmed_crew_count"] == 0
    assert run_now["status"] == "PLANNED"
