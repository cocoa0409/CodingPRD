"""Endpoint behaviour: collection filters, the logical epoch, link writing and read models."""

from test_helpers import (
    OPERATORS,
    PLATFORM_ADMIN,
    VALET_OPS_MANAGER,
    api_client,
    assert_instants_equal,
    factories,
    fixtures,
    make_valet_headers,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Collection filters are independent equality filters
# --------------------------------------------------------------------------
def test_the_contract_collection_filters_by_status_and_by_property_separately():
    """Each filter narrows on its own field, and the enum array round-trips intact.

    PRD 2.3: "Contracts may be filtered by `property_id` and by `status`."

    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    in the `meta` object of the envelope, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` indicates
    whether rows remain beyond the current page."

    Design: Corner/endpoints/contract_listing_filters_by_property_and_status
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    cedar = fixtures.create_property(name="Cedar Ridge", unit_count=4)
    willow = fixtures.create_property(name="Willow Court", unit_count=6)
    draft = fixtures.draft_contract(cedar["id"])
    other = fixtures.draft_contract(
        willow["id"], service_night_days=["MON", "WED", "FRI"]
    )
    fixtures.activate_contract(other["id"])

    draft_rows, draft_meta = validate_paginated(
        api_client.list_contracts(PLATFORM_ADMIN, params={"status": "DRAFT"})
    )
    willow_rows, willow_meta = validate_paginated(
        api_client.list_contracts(PLATFORM_ADMIN, params={"property_id": willow["id"]})
    )

    assert draft_meta["total_count"] == 1
    assert draft_meta["has_more"] is False
    assert draft_meta["limit"] == 10, "the default page size is ten rows"
    assert draft_meta["offset"] == 0
    assert [row["id"] for row in draft_rows] == [draft["id"]]
    assert willow_meta["total_count"] == 1
    assert [row["id"] for row in willow_rows] == [other["id"]]
    assert willow_rows[0]["status"] == "ACTIVE"
    assert willow_rows[0]["service_night_days"] == ["MON", "WED", "FRI"]


# --------------------------------------------------------------------------
# Completing a route is not closing the night
# --------------------------------------------------------------------------
def test_completing_a_route_stamps_the_clock_and_leaves_the_night_in_progress():
    """The route reaches COMPLETED with its scans intact and the night keeps walking.

    PRD 3.5: "The route moves to `COMPLETED`, `completed_at` is stamped from the
    logical clock, and the night's `assigned_unit_coverage_count` is recomputed —
    completed routes remain inside the live sum."

    Design: Corner/endpoints/route_complete_stamps_completed_at_and_keeps_the_scan_count
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101, 102),
        resident_kwargs={
            101: {"move_in_date": "2026-08-01"},
            102: {"move_in_date": "2026-08-01"},
        },
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    route = fixtures.assign_route(night["id"], world["contractor"]["id"], 101, 104)
    fixtures.set_clock("2026-09-01T18:15:00Z")
    fixtures.accept_route(route["id"], world["contractor"]["id"])
    fixtures.set_clock("2026-09-01T19:00:00Z")
    for unit in (101, 102):
        fixtures.record_scan(
            route["id"], world["contractor"]["id"], world["residents"][unit]["id"]
        )
    fixtures.set_clock("2026-09-01T21:30:00Z")

    completed = validate_success(
        api_client.complete_route(
            route["id"], make_valet_headers(world["contractor"]["id"])
        )
    )

    assert completed["status"] == "COMPLETED"
    assert_instants_equal(
        completed["completed_at"], "2026-09-01T21:30:00.000Z", "completed_at"
    )
    assert_instants_equal(
        completed["accepted_at"], "2026-09-01T18:15:00.000Z", "accepted_at"
    )
    assert completed["scan_count"] == 2
    assert completed["unit_coverage_count"] == 4
    after = fixtures.read_night(night["id"])
    assert after["verification_status"] == "IN_PROGRESS"
    assert after["billing_status"] == "UNBILLED"
    assert after["assigned_unit_coverage_count"] == 4, (
        "a completed route stays inside the live coverage sum"
    )


# --------------------------------------------------------------------------
# The logical clock has a fixed starting position
# --------------------------------------------------------------------------
def test_the_clock_reads_the_fixed_epoch_before_any_client_repositions_it():
    """With no set call at all, every stamp comes from 2026-08-01T00:00:00Z.

    PRD 2.7: "Before any client repositions it, the logical clock reads exactly
    `2026-08-01T00:00:00Z`; it must not fall back to real time under any
    circumstance, including on a freshly started process."

    PRD 2.7: "Repositioning the clock is not a mutation of the domain: no entity is
    written, no `updated_at` is refreshed, and no `version` is incremented."

    Design: Corner/endpoints/logical_clock_reads_2026_08_01_before_any_set_call
    """
    prop = validate_success(
        api_client.create_property(
            {"name": "Cedar Ridge", "unit_count": 4, "market_code": "ATL"},
            PLATFORM_ADMIN,
        ),
        expected_status=201,
    )

    incident = validate_success(
        api_client.create_compactor_incident(
            prop["id"],
            factories.incident_payload("JAM", "ram jammed on a mattress"),
            VALET_OPS_MANAGER,
        ),
        expected_status=201,
    )

    assert_instants_equal(
        incident["reported_at"], "2026-08-01T00:00:00.000Z", "reported_at"
    )
    assert_instants_equal(
        incident["ack_deadline_at"], "2026-08-01T04:00:00.000Z", "ack_deadline_at"
    )
    assert_instants_equal(prop["created_at"], "2026-08-01T00:00:00.000Z", "created_at")

    moved = validate_success(
        api_client.set_clock(
            factories.clock_payload("2026-09-01T00:00:00Z"), PLATFORM_ADMIN
        )
    )

    assert_instants_equal(moved["current_utc"], "2026-09-01T00:00:00.000Z", "current_utc")
    unchanged = fixtures.read_property(prop["id"])
    assert unchanged["version"] == prop["version"]
    assert_instants_equal(unchanged["updated_at"], prop["updated_at"], "updated_at")
    assert_instants_equal(
        fixtures.read_incident(incident["id"])["reported_at"],
        "2026-08-01T00:00:00.000Z",
        "reported_at",
    )


# --------------------------------------------------------------------------
# One scan write, three links
# --------------------------------------------------------------------------
def test_a_scan_writes_three_links_from_two_inputs():
    """The path gives the route, the body gives the resident, the route gives the night.

    PRD 3.5: "On success the scan is persisted with `scanned_at` stamped from the
    logical clock and with `service_night_id` copied down from the route it belongs
    to — deliberately denormalised so that night-level aggregates and queries never
    have to traverse the route."

    Design: Corner/endpoints/scan_links_the_route_and_the_resident_and_denormalises_the_night
    """
    world = fixtures.build_scan_ready_night(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        service_date="2026-09-01",
    )
    fixtures.set_clock("2026-09-01T19:00:00Z")

    scan = validate_success(
        api_client.record_scan(
            world["route"]["id"],
            factories.scan_payload(
                world["residents"][101]["id"], "SERVICED", "TRASH_BIN"
            ),
            make_valet_headers(world["contractor"]["id"]),
        ),
        expected_status=201,
    )

    assert scan["route_assignment_id"] == world["route"]["id"]
    assert scan["resident_id"] == world["residents"][101]["id"]
    assert scan["service_night_id"] == world["night"]["id"]
    assert_instants_equal(scan["scanned_at"], "2026-09-01T19:00:00.000Z", "scanned_at")
    assert scan["void_reason"] is None
    assert scan["non_compliance_type"] is None
    assert scan["tag_status"] == "NONE"
    assert scan["offense_ordinal"] == 0
    by_night = fixtures.list_scans({"service_night_id": world["night"]["id"]})
    assert [row["id"] for row in by_night] == [scan["id"]], (
        "the denormalised night link is queryable"
    )


# --------------------------------------------------------------------------
# The read model re-presents the whole waterfall
# --------------------------------------------------------------------------
def test_reading_a_draft_statement_re_presents_every_waterfall_field():
    """Gross minus credit minus share equals net in the read model too.

    PRD 3.8: "**Step four — the net due.** `net_due_from_property_cents` is
    `gross_passthrough_cents` minus `missed_service_credit_cents` minus
    `property_revenue_share_cents`. This step is exact integer subtraction with no
    rounding at all."

    PRD 3.8: "A successful draft is born `DRAFT` with `variant` `PROVISIONAL`,
    `created_by_user_id` set to the drafting operator's `X-User-ID`,
    `issued_by_user_id` null, and `void_reason` null"

    Design: Corner/endpoints/statement_read_returns_the_whole_settlement_waterfall
    """
    world = fixtures.build_active_community(
        name="Cedar Ridge",
        unit_count=4,
        resident_units=(101,),
        resident_kwargs={101: {"move_in_date": "2026-08-01"}},
        contract={
            "per_unit_monthly_fee_cents": 3495,
            "property_revenue_share_bps": 1500,
            "sla_missed_threshold_bps": 1000,
        },
        with_contractor=False,
    )
    night = fixtures.schedule_night(world["contract"]["id"], "2026-09-01")
    fixtures.close_night(night["id"])
    draft = fixtures.draft_statement(world["contract"]["id"], "2026-09")

    read_back = validate_success(
        api_client.get_statement(draft["id"], PLATFORM_ADMIN)
    )

    assert read_back["variant"] == "PROVISIONAL"
    assert read_back["status"] == "DRAFT"
    assert read_back["billing_period"] == "2026-09"
    assert read_back["gross_passthrough_cents"] == 13980
    assert read_back["scheduled_night_count"] == 1
    assert float(read_back["missed_equivalent_nights"]) == 1.0
    assert read_back["missed_service_bps"] == 10000
    assert read_back["sla_credit_rate_bps"] == 1200
    assert read_back["missed_service_credit_cents"] == 1678
    assert read_back["property_revenue_share_cents"] == 1845
    assert read_back["net_due_from_property_cents"] == 10457
    assert (
        read_back["gross_passthrough_cents"]
        - read_back["missed_service_credit_cents"]
        - read_back["property_revenue_share_cents"]
        == read_back["net_due_from_property_cents"]
    )
    assert read_back["issued_by_user_id"] is None
    assert read_back["created_by_user_id"] == OPERATORS["ANALYST_DRAFTER"]
    assert read_back["void_reason"] is None
