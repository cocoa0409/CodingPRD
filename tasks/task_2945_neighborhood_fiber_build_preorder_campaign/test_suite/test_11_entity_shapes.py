"""Entity shapes: created rows, server-assigned fields, defaults, listing and lookup failures."""

from test_helpers import (
    COORDINATOR,
    PM,
    ApiErrorId,
    CLOCK_EPOCH,
    UNKNOWN_BUILD_ZONE_ID,
    UNKNOWN_CAMPAIGN_ID,
    api_client,
    assert_account,
    assert_build_zone,
    assert_campaign,
    assert_cents,
    assert_envelope_meta,
    assert_error_body,
    assert_install_crew,
    assert_instant_equals,
    assert_ledger_entry,
    assert_page,
    assert_pct,
    assert_response_type,
    assert_total_count,
    build_zone_payload,
    campaign_payload,
    install_crew_payload,
    list_ledger_for_preorder,
    make_account,
    make_address,
    make_campaign,
    make_preorder,
    make_subscriber_headers,
    make_zone,
    preorder_payload,
    read_zone_version,
    service_address_payload,
    set_clock,
    set_serviceability,
    setup_campaign_with_zone,
    setup_serviceable_address,
    validate_error,
    validate_success,
)

PREREG_OPEN = "2026-08-01T00:00:00Z"
PREREG_CLOSE = "2026-09-30T23:59:00Z"


def test_campaign_creation_answers_201_with_every_declared_policy_field():
    """A brand-new campaign is a creation, so it answers 201 and echoes all its policy terms.

    PRD 4: "Endpoints that bring a new resource into existence answer with HTTP 201; every
    other successful call - reads, lists, and the transition and workflow endpoints that modify
    an existing resource - answers with HTTP 200."

    Design: Corner/entities/campaign_creation_returns_201_with_every_declared_field
    """
    set_clock()

    response = api_client.create_campaign(
        campaign_payload(
            max_deadline_extensions=2,
            extension_grant_days=30,
            claim_filing_window_days=45,
            restoration_sla_days=7,
            late_filing_factor=0.60,
        ),
        PM,
    )

    campaign = validate_success(response, 201)
    assert_response_type(response, "object")
    assert_envelope_meta(response)
    assert_campaign(campaign)
    assert campaign["name"] == "Fiberhood 2026", campaign["name"]
    assert campaign["city"] == "Aurora", campaign["city"]
    assert_pct(campaign["default_threshold_pct"], 10.00, "default_threshold_pct")
    assert_cents(campaign["deposit_amount_cents"], 1000, "deposit_amount_cents")
    assert campaign["max_deadline_extensions"] == 2, campaign["max_deadline_extensions"]
    assert campaign["extension_grant_days"] == 30, campaign["extension_grant_days"]
    assert campaign["claim_filing_window_days"] == 45, campaign["claim_filing_window_days"]
    assert campaign["restoration_sla_days"] == 7, campaign["restoration_sla_days"]
    assert_pct(campaign["late_filing_factor"], 0.60, "late_filing_factor")
    assert campaign["version"] == 1, campaign["version"]
    assert campaign["zone_count"] == 0, campaign["zone_count"]


def test_build_zone_retrieval_returns_the_stored_row_to_any_role():
    """A read is not a creation, so the zone comes back at 200 with its seeded opening state.

    PRD 3.1: "A newly carved zone starts with `campaign_status` `PREREG_OPEN` and
    `construction_status` `NOT_STARTED`, and its `prereg_deadline_at` is seeded from the
    campaign's `prereg_window_close_at`."

    Design: Corner/entities/build_zone_retrieval_returns_the_stored_row
    """
    base = setup_campaign_with_zone(
        zone_overrides={"household_count": 16, "threshold_pct": 12.5}
    )

    response = api_client.get_build_zone(base["zone"]["id"], COORDINATOR)

    zone = validate_success(response, 200)
    assert_response_type(response, "object")
    assert_build_zone(zone)
    assert zone["zone_code"] == "A1", zone["zone_code"]
    assert zone["household_count"] == 16, zone["household_count"]
    assert_pct(zone["threshold_pct"], 12.50, "threshold_pct")
    assert_instant_equals(zone["prereg_deadline_at"], PREREG_CLOSE, "prereg_deadline_at")
    assert zone["campaign_status"] == "PREREG_OPEN", zone["campaign_status"]
    assert zone["construction_status"] == "NOT_STARTED", zone["construction_status"]
    assert zone["readiness_posture"] == "BLOCKED", zone["readiness_posture"]


def test_service_address_listing_paginates_with_total_count_and_has_more():
    """Two pages over three filtered rows: total_count counts the filtered population, not the page.

    PRD 2.3: "The `meta` block of a list response carries `limit` and `offset` echoing the
    effective values used, `total_count` giving the number of rows matching the filters before
    the page window is applied, and `has_more` indicating whether any matching row remains
    beyond this page."

    Design: Corner/entities/service_address_listing_paginates_with_total_count_and_has_more
    """
    base = setup_campaign_with_zone()
    zone_id = base["zone"]["id"]
    other_zone = make_zone(
        base["campaign"]["id"], name="Zone Bravo", zone_code="B1", household_count=10
    )
    first = make_address(zone_id, street_address="1 Elm St", distance_to_node_m=100)
    second = make_address(zone_id, street_address="2 Elm St", distance_to_node_m=105)
    third = make_address(zone_id, street_address="3 Elm St", distance_to_node_m=110)
    excluded = make_address(
        other_zone["id"], street_address="10 Oak Ave", distance_to_node_m=90
    )

    page_one = api_client.list_service_addresses(
        PM, params={"build_zone_id": zone_id, "limit": 2, "offset": 0}
    )

    rows, _ = assert_page(
        page_one, total_count=3, limit=2, offset=0, has_more=True, row_count=2
    )
    assert_response_type(page_one, "array")
    assert [row["id"] for row in rows] == [first["id"], second["id"]], rows
    assert excluded["id"] not in [row["id"] for row in rows]

    page_two = api_client.list_service_addresses(
        PM, params={"build_zone_id": zone_id, "limit": 2, "offset": 2}
    )
    tail, _ = assert_page(
        page_two, total_count=3, limit=2, offset=2, has_more=False, row_count=1
    )
    assert tail[0]["id"] == third["id"], tail


def test_get_build_zone_with_an_unknown_id_reports_the_zone_not_found():
    """A path identifier that resolves to nothing is a 404 carrying the usual envelope meta.

    PRD 2.10: "Every identifier embedded in the URL path resolves to an existing row."

    Design: Corner/entities/get_build_zone_with_unknown_id_returns_build_zone_not_found
    """
    set_clock()

    response = api_client.get_build_zone(UNKNOWN_BUILD_ZONE_ID, PM)

    validate_error(response, ApiErrorId.ERR_BUILD_ZONE_NOT_FOUND, 404)
    assert_response_type(response, "error")
    assert_error_body(response, ApiErrorId.ERR_BUILD_ZONE_NOT_FOUND)
    assert_envelope_meta(response)


def test_preorder_create_without_a_plan_tier_is_a_malformed_request():
    """A required field left out never reaches the deposit ladder; nothing is written.

    PRD 2.10: "Every required field is present and non-null, every enumerated field carries one
    of its declared values, every timestamp parses as an ISO 8601 UTC instant, every integer
    sits inside its declared range, and pagination stays inside its bounds."

    Design: Corner/entities/preorder_create_missing_required_plan_tier_returns_invalid_request
    """
    base = setup_serviceable_address()
    zone_id = base["zone"]["id"]
    account = base["account"]
    payload = preorder_payload(
        zone_id, base["address"]["id"], account["id"], read_zone_version(zone_id)
    )
    payload.pop("plan_tier")

    response = api_client.create_preorder(payload, make_subscriber_headers(account["id"]))

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert_total_count(
        api_client.list_preorders(PM, params={"service_address_id": base["address"]["id"]}),
        0,
    )
    assert_cents(
        validate_success(api_client.get_account(account["id"], PM))["deposit_held_cents"],
        0,
        "deposit_held_cents",
    )
    assert (
        validate_success(api_client.get_build_zone(zone_id, PM))[
            "provisional_qualifying_count"
        ]
        == 0
    )


def test_build_zone_omitted_options_fall_back_to_campaign_and_policy_defaults():
    """No threshold, no permit list and no bury cap supplied: all three come from policy.

    PRD 3.1: "`threshold_pct` defaults to the referenced campaign's `default_threshold_pct` and
    otherwise follows the same two-decimal, 0.01-to-100.00 rule."

    Design: Corner/entities/build_zone_defaults_threshold_from_campaign_and_bury_cap_to_two
    """
    set_clock()
    campaign = make_campaign(default_threshold_pct=12.5)

    response = api_client.create_build_zone(
        build_zone_payload(campaign["id"], household_count=10), PM
    )

    zone = validate_success(response, 201)
    assert_build_zone(zone)
    assert_pct(zone["threshold_pct"], 12.50, "threshold_pct")
    assert zone["required_permit_types"] == ["ROW"], zone["required_permit_types"]
    assert zone["max_concurrent_bury_ops"] == 2, zone["max_concurrent_bury_ops"]
    assert zone["extension_count"] == 0, zone["extension_count"]
    assert zone["cumulative_extension_days"] == 0, zone["cumulative_extension_days"]
    assert_cents(zone["make_ready_cost_cents"], 0, "make_ready_cost_cents")
    assert zone["outstanding_restoration_count"] == 0
    assert zone["final_qualifying_count"] is None
    assert zone["final_rate_pct"] is None
    assert zone["readiness_score"] is None
    assert zone["build_sequence_index"] is None
    assert zone["suspension_reason"] is None


def test_install_crew_omitted_capacity_parameters_default_to_thirty_and_four_eighty():
    """A crew registered with only a name and a type still gets a buffer and a working day.

    PRD 3.8: "`travel_buffer_minutes`, the trailing buffer appended to every one of this crew's
    windows for both conflict detection and capacity accounting, defaulting to 30 and
    constrained to between 0 and 240 inclusive"

    Design: Corner/entities/install_crew_defaults_buffer_thirty_and_capacity_four_eighty
    """
    set_clock()

    response = api_client.create_install_crew(
        install_crew_payload(name="Bury Crew 1", crew_type="BURY"), COORDINATOR
    )

    crew = validate_success(response, 201)
    assert_install_crew(crew)
    assert crew["travel_buffer_minutes"] == 30, crew["travel_buffer_minutes"]
    assert crew["daily_capacity_minutes"] == 480, crew["daily_capacity_minutes"]
    assert crew["booked_minutes_total"] == 0, crew["booked_minutes_total"]
    assert crew["scheduled_appointment_count"] == 0, crew["scheduled_appointment_count"]
    assert crew["version"] == 1, crew["version"]


def test_account_balances_open_at_zero_and_client_supplied_balances_are_ignored():
    """Both balances are ledger replays, so a client cannot seed them through the create body.

    PRD 2.8: "Every movement of money in this system is recorded as a `LedgerEntry`, and account
    balances are never incremented in place - they are recomputed by replaying the account's
    entries."

    Design: Corner/entities/account_deposit_held_cents_is_computed_and_ignores_client_input
    """
    set_clock()

    account = make_account(0, deposit_held_cents=999999, credit_balance_cents=888888)

    assert_account(account)
    assert_cents(account["deposit_held_cents"], 0, "deposit_held_cents")
    assert_cents(account["credit_balance_cents"], 0, "credit_balance_cents")
    assert_total_count(
        api_client.list_ledger_entries(PM, params={"account_id": account["id"]}), 0
    )


def test_campaign_identity_and_version_columns_are_minted_by_the_server():
    """The id is a server UUID and both system instants read the logical clock, not the wall clock.

    PRD 2.4: "Every resource in this system is identified by `id`, a server-minted UUID string."

    Design: Corner/entities/campaign_system_fields_are_server_assigned_and_input_is_ignored
    """
    set_clock()

    response = api_client.create_campaign(campaign_payload(), PM)

    campaign = validate_success(response, 201)
    assert_campaign(campaign)
    assert campaign["id"] != campaign["name"]
    assert campaign["id"] != PREREG_OPEN
    assert_instant_equals(campaign["created_at"], CLOCK_EPOCH, "created_at")
    assert_instant_equals(campaign["updated_at"], CLOCK_EPOCH, "updated_at")
    assert campaign["version"] == 1, campaign["version"]


def test_service_address_rejects_a_dwelling_type_outside_its_declared_values():
    """DUPLEX is not one of the two declared dwelling types, so the create never lands.

    PRD 2.10: "every enumerated field carries one of its declared values, every timestamp parses
    as an ISO 8601 UTC instant"

    Design: Corner/entities/service_address_rejects_unknown_dwelling_type_enum_value
    """
    base = setup_campaign_with_zone()
    zone_id = base["zone"]["id"]

    response = api_client.create_service_address(
        service_address_payload(
            zone_id, street_address="4 Elm St", dwelling_type="DUPLEX", unit_count=2
        ),
        PM,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)
    assert_total_count(
        api_client.list_service_addresses(PM, params={"build_zone_id": zone_id}), 0
    )


def test_a_ledger_entry_carries_no_version_and_no_updated_at():
    """The deposit hold is discoverable only through the list filter, and it is not a versioned row.

    PRD 2.4: "Ledger rows are immutable and append-only, so they carry `id` and `created_at` and
    nothing else from that set"

    Design: Corner/entities/ledger_entry_is_immutable_with_no_version_and_no_write_endpoint
    """
    base = setup_serviceable_address()
    preorder = make_preorder(
        base["zone"]["id"], base["address"]["id"], base["account"]["id"]
    )

    entries, listing = list_ledger_for_preorder(preorder["id"])

    assert_total_count(listing, 1)
    assert len(entries) == 1, entries
    entry = entries[0]
    assert entry["entry_type"] == "DEPOSIT_HELD", entry["entry_type"]
    assert_cents(entry["amount_cents"], 1000, "amount_cents")
    assert_ledger_entry(entry)
    assert entry["damage_claim_id"] is None, entry["damage_claim_id"]

    reread = validate_success(api_client.get_ledger_entry(entry["id"], PM))
    assert_ledger_entry(reread)
    assert reread["id"] == entry["id"], (entry["id"], reread["id"])
    assert_instant_equals(reread["created_at"], entry["created_at"], "created_at")


def test_a_preorder_naming_an_address_from_another_zone_is_a_linkage_mismatch():
    """The address sits in Zone Bravo while the sign-up names Zone Alpha, so the two disagree.

    PRD 2.10: "on a preorder sign-up, the referenced address's `build_zone_id` equals the
    supplied `build_zone_id`"

    Design: Corner/entities/preorder_with_address_from_another_zone_returns_linkage_mismatch
    """
    base = setup_campaign_with_zone()
    alpha_id = base["zone"]["id"]
    bravo = make_zone(
        base["campaign"]["id"], name="Zone Bravo", zone_code="B1", household_count=10
    )
    address = make_address(bravo["id"], street_address="10 Oak Ave", distance_to_node_m=90)
    set_serviceability(address["id"], "SERVICEABLE")
    account = make_account(0)

    response = api_client.create_preorder(
        preorder_payload(
            alpha_id, address["id"], account["id"], read_zone_version(alpha_id)
        ),
        make_subscriber_headers(account["id"]),
    )

    validate_error(response, ApiErrorId.ERR_ADDRESS_LINKAGE_MISMATCH, 422)
    for zone_id in (alpha_id, bravo["id"]):
        zone = validate_success(api_client.get_build_zone(zone_id, PM))
        assert zone["provisional_qualifying_count"] == 0, zone
    assert_cents(
        validate_success(api_client.get_account(account["id"], PM))["deposit_held_cents"],
        0,
        "deposit_held_cents",
    )


def test_carving_a_zone_under_an_unknown_campaign_reports_the_campaign_not_found():
    """The body's foreign key resolves to nothing, so no zone is carved at all.

    PRD 2.10: "Every foreign-key identifier supplied in a request body or as a query filter
    resolves to an existing row."

    Design: Corner/entities/build_zone_create_under_unknown_campaign_returns_campaign_not_found
    """
    set_clock()

    response = api_client.create_build_zone(
        build_zone_payload(
            UNKNOWN_CAMPAIGN_ID, name="Zone Ghost", zone_code="G1", household_count=10
        ),
        PM,
    )

    validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND, 404)
    assert_total_count(api_client.list_build_zones(PM), 0)
