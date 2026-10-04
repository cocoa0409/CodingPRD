"""Vendor briefings, briefing routing and the sales/research separation cascade."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_analyst,
    create_briefing,
    create_document,
    create_inclusion,
    create_sales_relationship,
    create_vendor,
    finalize_inclusion,
    get_success_data,
    make_vendor_rep_headers,
    set_clock,
    setup_document_with_inclusion,
    validate_error,
    validate_paginated,
)


def test_sales_relationship_cascade_revokes_briefings_and_reverts_inclusions():
    """PRD §3.8: "Second, every briefing for this analyst and vendor pair whose status
    is `REQUESTED`, `SCREENED` or `SCHEDULED` moves to `REVOKED_BY_SEPARATION` with
    `separation_check_result` `FAIL_SALES_RELATIONSHIP` and its `version` incremented.
    Third, every inclusion whose parent document's `lead_analyst_id` is this analyst,
    whose `vendor_id` is this vendor, and whose `inclusion_status` is `PROPOSED` or
    `UNDER_EVALUATION` is marked `lead_analyst_conflicted` true and reverted to
    `PROPOSED`. Fourth, the linked vendor's `active_sales_relationship_count` is
    incremented and its `briefing_eligible` recomputed."

    Design: Difficulty/transitive_cascade/sales_relationship_cascade_revokes_briefings_then_reverts_inclusions
    """
    set_clock("2026-09-01T00:00:00Z")
    # Briefing routing requires the analyst to list the briefing_topic in
    # topic_routes (PRD 3.8), so the fixture must declare MARKET_OUTLOOK.
    analyst = create_analyst(topic_routes=["MARKET_OUTLOOK"])
    vendor = create_vendor()
    document = create_document(analyst)
    inclusion = create_inclusion(document, vendor)
    briefing = create_briefing(
        vendor, briefing_topic="MARKET_OUTLOOK", requested_start_utc="2026-09-04T15:00:00Z"
    )
    assert briefing["status"] == "SCHEDULED"
    assert briefing["analyst_id"] == analyst["id"]

    relationship = create_sales_relationship(analyst, vendor)
    assert relationship["status"] == "ACTIVE"

    analyst_after = get_success_data(api_client.get_analyst(analyst["id"]))
    assert analyst_after["integrity_flag"] == "CONFLICT_REVIEW"
    assert analyst_after["conflicted_vendor_ids"] == [vendor["id"]]

    briefing_after = get_success_data(api_client.get_briefing(briefing["id"]))
    assert briefing_after["status"] == "REVOKED_BY_SEPARATION"
    assert briefing_after["separation_check_result"] == "FAIL_SALES_RELATIONSHIP"

    inclusion_after = get_success_data(api_client.get_inclusion(inclusion["id"]))
    assert inclusion_after["lead_analyst_conflicted"] is True
    assert inclusion_after["inclusion_status"] == "PROPOSED"

    vendor_after = get_success_data(api_client.get_vendor(vendor["id"]))
    assert vendor_after["active_sales_relationship_count"] == 1


def test_separation_cascade_reverts_only_the_open_placements():
    """PRD §3.8: "Third, every inclusion whose parent document's `lead_analyst_id` is
    this analyst, whose `vendor_id` is this vendor, and whose `inclusion_status` is
    `PROPOSED` or `UNDER_EVALUATION` is marked `lead_analyst_conflicted` true and
    reverted to `PROPOSED`."

    Design: Difficulty/transitive_cascade/sales_relationship_cascade_revokes_briefings_then_reverts_inclusions
    """
    set_clock("2026-09-01T00:00:00Z")
    analyst = create_analyst()
    vendor = create_vendor()

    settled = setup_document_with_inclusion(lead=analyst, vendor=vendor)
    finalize_inclusion(settled["inclusion"], "INCLUDE")

    open_document = create_document(analyst, title="Comparative Matrix: Data Platforms")
    open_inclusion = create_inclusion(open_document, vendor)

    create_sales_relationship(analyst, vendor)

    kept = get_success_data(api_client.get_inclusion(settled["inclusion"]["id"]))
    assert kept["inclusion_status"] == "INCLUDED", (
        "The cascade reverts only inclusions that are PROPOSED or UNDER_EVALUATION"
    )

    reverted = get_success_data(api_client.get_inclusion(open_inclusion["id"]))
    assert reverted["inclusion_status"] == "PROPOSED"
    assert reverted["lead_analyst_conflicted"] is True

    assert get_success_data(
        api_client.get_vendor(vendor["id"])
    )["active_sales_relationship_count"] == 1


def test_briefing_starting_exactly_one_buffer_after_the_previous_one_is_accepted():
    """PRD §3.8: "The slot is confirmed at creation when the requested window,
    expanded by a 15-minute buffer on both sides, does not overlap any other briefing
    of the assigned analyst that is `SCHEDULED` or `HELD`; when that buffer check fails
    the request is rejected with `ERR_BRIEFING_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/briefing_calendar_buffer_expanded_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    analyst = create_analyst(topic_routes=["MARKET_OUTLOOK"])
    vendor = create_vendor()
    first = create_briefing(
        vendor, briefing_topic="MARKET_OUTLOOK", requested_start_utc="2026-09-11T15:00:00Z"
    )
    assert first["status"] == "SCHEDULED"
    assert first["analyst_id"] == analyst["id"]

    second = create_briefing(
        vendor, briefing_topic="MARKET_OUTLOOK", requested_start_utc="2026-09-11T16:00:00Z"
    )
    assert second["status"] == "SCHEDULED", (
        "A briefing starting exactly 15 minutes after the previous one ends clears the buffer"
    )

    resp = api_client.create_briefing(
        {
            "vendor_id": vendor["id"],
            "briefing_topic": "MARKET_OUTLOOK",
            "requested_start_utc": "2026-09-11T15:50:00Z",
            "duration_minutes": 45,
        },
        make_vendor_rep_headers(vendor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BRIEFING_SLOT_CONFLICT)

    rows, meta = validate_paginated(
        api_client.list_briefings(
            TEST_USERS["research_director_headers"], params={"analyst_id": analyst["id"]}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2


def test_briefing_ending_one_buffer_before_the_next_one_is_accepted():
    """PRD §3.8: "The slot is confirmed at creation when the requested window,
    expanded by a 15-minute buffer on both sides, does not overlap any other briefing
    of the assigned analyst that is `SCHEDULED` or `HELD`; when that buffer check fails
    the request is rejected with `ERR_BRIEFING_SLOT_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/briefing_calendar_buffer_expanded_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    analyst = create_analyst(topic_routes=["MARKET_OUTLOOK"])
    vendor = create_vendor()
    create_briefing(
        vendor, briefing_topic="MARKET_OUTLOOK", requested_start_utc="2026-09-11T15:00:00Z"
    )

    earlier = create_briefing(
        vendor, briefing_topic="MARKET_OUTLOOK", requested_start_utc="2026-09-11T14:00:00Z"
    )
    assert earlier["status"] == "SCHEDULED", (
        "The earlier window ends exactly 15 minutes before the next one starts"
    )

    resp = api_client.create_briefing(
        {
            "vendor_id": vendor["id"],
            "briefing_topic": "MARKET_OUTLOOK",
            "requested_start_utc": "2026-09-11T14:05:00Z",
            "duration_minutes": 45,
        },
        make_vendor_rep_headers(vendor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BRIEFING_SLOT_CONFLICT)

    rows, _ = validate_paginated(
        api_client.list_briefings(
            TEST_USERS["research_director_headers"], params={"analyst_id": analyst["id"]}
        )
    )
    assert len(rows) == 2


def test_briefing_against_an_unknown_vendor_reports_vendor_not_found():
    """PRD §2.11: "A body foreign key that references a missing resource is reported
    the same way, using the error of the referenced entity."

    Design: Corner/entities/briefing_create_with_unknown_vendor_returns_vendor_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    create_analyst()

    resp = api_client.create_briefing(
        {
            "vendor_id": NON_EXISTENT_UUID,
            "briefing_topic": "MARKET_OUTLOOK",
            "requested_start_utc": "2026-09-25T15:00:00Z",
            "duration_minutes": 45,
        },
        make_vendor_rep_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_VENDOR_NOT_FOUND)

    rows, meta = validate_paginated(
        api_client.list_briefings(TEST_USERS["compliance_officer_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_briefing_is_refused_when_every_topic_eligible_analyst_is_conflicted():
    """PRD §3.8: "When the eligible pool is empty — every topic-eligible analyst is
    conflicted — the request is refused with `ERR_BRIEFING_SEPARATION_FAILED`
    (HTTP 403) and no briefing row is created."
    PRD §3.8: "A candidate must have analyst status `ACTIVE`, must list the
    `briefing_topic` in their `topic_routes`, and must have `integrity_flag` `CLEAR` —
    an analyst holding any active commercial tie is ineligible regardless of topic."

    Design: Corner/errors/briefing_with_only_a_conflicted_analyst_returns_briefing_separation_failed
    """
    set_clock("2026-09-01T00:00:00Z")
    analyst = create_analyst()
    vendor = create_vendor()
    create_sales_relationship(analyst, vendor)
    assert get_success_data(api_client.get_analyst(analyst["id"]))["integrity_flag"] == \
        "CONFLICT_REVIEW"

    resp = api_client.create_briefing(
        {
            "vendor_id": vendor["id"],
            "briefing_topic": "MARKET_OUTLOOK",
            "requested_start_utc": "2026-09-25T15:00:00Z",
            "duration_minutes": 45,
        },
        make_vendor_rep_headers(vendor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BRIEFING_SEPARATION_FAILED)

    rows, meta = validate_paginated(
        api_client.list_briefings(TEST_USERS["compliance_officer_headers"])
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_stale_analyst_version_blocks_the_second_sales_relationship():
    """PRD §2.12: "Creating a sales relationship requires `expected_analyst_version`;
    if it does not equal the analyst's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.8: "Commercial ties are registered separately, by a `SalesRep` or
    `ComplianceOfficer`, as a `SalesRelationship` naming the `analyst_id`, the
    `vendor_id`, a `relationship_type` of `SPONSORSHIP`, `PAID_ADVISORY` or
    `SPEAKING_FEE`, an `annual_value_cents` of at least 0, and the
    `expected_analyst_version` the client last observed for the analyst."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_analyst_version_on_the_second_sales_relationship
    """
    set_clock("2026-09-01T00:00:00Z")
    analyst = create_analyst()
    vendor = create_vendor()
    observed_version = analyst["version"]

    create_sales_relationship(analyst, vendor, relationship_type="SPONSORSHIP",
                              annual_value_cents=3_000_000)

    stale = api_client.create_sales_relationship(
        {
            "analyst_id": analyst["id"],
            "vendor_id": vendor["id"],
            "relationship_type": "SPEAKING_FEE",
            "annual_value_cents": 250_000,
            "expected_analyst_version": observed_version,
        },
        TEST_USERS["sales_rep_headers"],
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = get_success_data(api_client.get_analyst(analyst["id"]))
    create_sales_relationship(
        fresh, vendor, relationship_type="SPEAKING_FEE", annual_value_cents=250_000
    )

    rows, meta = validate_paginated(
        api_client.list_sales_relationships(
            TEST_USERS["compliance_officer_headers"], params={"analyst_id": analyst["id"]}
        )
    )
    assert len(rows) == 2
    assert meta["total_count"] == 2
    assert get_success_data(
        api_client.get_vendor(vendor["id"])
    )["active_sales_relationship_count"] == 2
