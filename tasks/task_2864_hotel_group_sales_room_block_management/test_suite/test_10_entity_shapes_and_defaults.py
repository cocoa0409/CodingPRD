"""Resource shape: declared defaults, computed fields and system-minted values.

PRD 2.5 gives every resource an id, a created_at, an updated_at and a version
that starts at 1; PRD 3.1 and PRD 3.2 fix which fields a client supplies, which
the service defaults, and which stay null until an operation computes them.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    REVENUE_MANAGER,
    SALES_MANAGER,
    SALES_MANAGER_ALT,
    SALES_MANAGER_ALT_ID,
    ACCOUNTING_CLERK,
    CONTRACT_ADMIN,
    RESERVATIONS_AGENT,
    ApiErrorId,
    LeadStatus,
    MarketSegment,
    assert_group_account,
    assert_lead,
    assert_minted_instant,
    assert_no_pagination_meta,
    assert_pagination_meta,
    constants as C,
    factories as F,
    is_valid_uuid,
    read_lead,
    seed_account,
    seed_calendar_and_package,
    seed_inventory_days,
    seed_lead,
    seed_qualified_lead,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_new_account_materialises_every_declared_default(api):
    """Creating an account from its three required fields fills in the rest.

    PRD 3.1 defaults credit_hold to false, starts repeat_group_count and
    lifetime_actualized_room_nights at 0 with last_completed_departure_date null,
    and seeds rebooking_incentive_pct at the lowest band of 0.01; PRD 2.5 starts
    version at 1. Leaving the computed columns absent until the first completed
    programme, or starting version at 0, breaks the contract.

    Design: Corner/entities/account_creation_returns_declared_defaults_and_version_one
    """
    created = validate_success(
        api.create_account(F.account_payload(), SALES_MANAGER), 201
    )

    assert_group_account(
        created,
        name="Northwind Manufacturing",
        market_segment=MarketSegment.CORPORATE,
        billing_contact_email="ap@northwind.example",
        credit_hold=False,
        repeat_group_count=0,
        lifetime_actualized_room_nights=0,
        last_completed_departure_date=None,
        rebooking_incentive_pct=0.01,
        version=1,
    )


def test_reading_an_account_neither_changes_it_nor_paginates(api):
    """A read is a read: same values, same version, no list metadata.

    PRD 2.5 advances version only on a mutation, so fetching the row must report
    exactly what the create reported - including the derived incentive tier - and
    leave version at 1. PRD 2.2 reserves the pagination figures for list reads.

    Design: Corner/entities/account_get_returns_the_stored_row_unchanged
    """
    created = seed_account(api)

    response = api.get_account(created["id"], REVENUE_MANAGER)
    fetched = validate_success(response)

    assert_group_account(
        fetched,
        name="Northwind Manufacturing",
        market_segment=MarketSegment.CORPORATE,
        rebooking_incentive_pct=0.01,
        version=1,
    )
    assert fetched == created, (
        f"the stored row must come back unchanged: {created} then {fetched}"
    )
    assert_no_pagination_meta(response.json())


def test_the_inventory_calendar_pages_over_the_whole_filtered_set(api):
    """total_count counts the set, not the page, and has_more tracks the tail.

    PRD 2.3 returns limit, offset, total_count and has_more on every list read
    and orders inventory days by stay_date ascending, so a two-row page over
    three days reports three and more to come, and the offset-2 page reports
    three and nothing further.

    Design: Corner/entities/inventory_day_list_paginates_with_total_count_and_has_more
    """
    seed_inventory_days(api)

    first_page, first_meta = validate_paginated(
        api.list_inventory_days(REVENUE_MANAGER, limit=2, offset=0)
    )
    assert_pagination_meta(
        first_meta, total_count=3, has_more=True, limit=2, offset=0
    )
    assert [row["stay_date"] for row in first_page] == ["2026-11-09", "2026-11-10"]

    last_page, last_meta = validate_paginated(
        api.list_inventory_days(REVENUE_MANAGER, limit=2, offset=2)
    )
    assert_pagination_meta(
        last_meta, total_count=3, has_more=False, limit=2, offset=2
    )
    assert [row["stay_date"] for row in last_page] == ["2026-11-11"]


def test_each_entity_family_answers_an_unknown_id_with_its_own_error(api):
    """Eleven families, eleven distinct 404s.

    PRD 2.8 resolves path ids at priority 4 and the error catalogue of PRD 2.2
    gives each family its own identifier, so a shared ERR_NOT_FOUND - or a 500
    from an unguarded lookup - is wrong for every one of them.

    Design: Corner/entities/unknown_path_ids_return_the_entity_specific_not_found_error
    """
    missing = NON_EXISTENT_UUID
    cases = (
        (api.get_account(missing, SALES_MANAGER), ApiErrorId.ACCOUNT_NOT_FOUND),
        (api.get_lead(missing, SALES_MANAGER), ApiErrorId.LEAD_NOT_FOUND),
        (api.get_package(missing, SALES_MANAGER), ApiErrorId.PACKAGE_NOT_FOUND),
        (
            api.get_displacement_analysis(missing, REVENUE_MANAGER),
            ApiErrorId.ANALYSIS_NOT_FOUND,
        ),
        (api.get_rate_quote(missing, SALES_MANAGER), ApiErrorId.QUOTE_NOT_FOUND),
        (api.get_contract(missing, CONTRACT_ADMIN), ApiErrorId.CONTRACT_NOT_FOUND),
        (api.get_room_block(missing, RESERVATIONS_AGENT), ApiErrorId.BLOCK_NOT_FOUND),
        (
            api.get_reservation(missing, RESERVATIONS_AGENT),
            ApiErrorId.RESERVATION_NOT_FOUND,
        ),
        (
            api.get_ancillary_charge(missing, ACCOUNTING_CLERK),
            ApiErrorId.CHARGE_NOT_FOUND,
        ),
        (
            api.get_reconciliation(missing, ACCOUNTING_CLERK),
            ApiErrorId.RECONCILIATION_NOT_FOUND,
        ),
        (
            api.get_function_space_hold(missing, SALES_MANAGER),
            ApiErrorId.HOLD_NOT_FOUND,
        ),
    )

    for response, expected in cases:
        validate_error(response, expected, 404)


def test_an_unresolvable_body_reference_is_a_not_found_before_anything_else(api):
    """A dangling foreign key in the body answers like a dangling path id.

    PRD 2.8 resolves referenced entities at priority 6, ahead of the version
    guard at priority 8 and every state rule below it, so a quote naming an
    unknown lead is ERR_LEAD_NOT_FOUND even though it carries a perfectly good
    expected_lead_version. None of the five refused writes may persist a row.

    Design: Corner/entities/body_foreign_keys_that_do_not_resolve_are_rejected_as_not_found
    """
    world = seed_qualified_lead(api)

    validate_error(
        api.create_lead(
            F.lead_payload(NON_EXISTENT_UUID, program_name="Ghost Account Program"),
            SALES_MANAGER,
        ),
        ApiErrorId.ACCOUNT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_rate_quote(
            F.rate_quote_payload(
                NON_EXISTENT_UUID, world["package_id"], world["lead_version"]
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.LEAD_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_rate_quote(
            F.rate_quote_payload(
                world["lead_id"], NON_EXISTENT_UUID, world["lead_version"]
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.PACKAGE_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_reservation(
            F.reservation_payload(NON_EXISTENT_UUID), RESERVATIONS_AGENT
        ),
        ApiErrorId.BLOCK_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_ancillary_charge(
            F.ancillary_charge_payload(NON_EXISTENT_UUID), ACCOUNTING_CLERK
        ),
        ApiErrorId.CONTRACT_NOT_FOUND,
        404,
    )

    _, lead_meta = validate_paginated(
        api.list_account_leads(world["account_id"], SALES_MANAGER)
    )
    assert lead_meta["total_count"] == 1, "only the pre-existing lead may survive"
    _, quote_meta = validate_paginated(api.list_rate_quotes(SALES_MANAGER))
    assert quote_meta["total_count"] == 0, "no refused quote may persist"


def test_a_lead_without_its_peak_room_count_is_rejected_unconverted(api):
    """A required integer must be present and must be an integer.

    PRD 3.2 needs peak_rooms for the peak-size component of the score, and PRD
    2.8 rejects a malformed body at priority 3 with ERR_INVALID_REQUEST, so
    omitting the field cannot become a silent zero and the string "4" cannot be
    coerced into a room count. Neither attempt may leave a lead behind.

    Design: Corner/entities/lead_create_with_missing_required_peak_rooms_is_rejected
    """
    account = seed_account(api)

    absent = F.lead_payload(account["id"], program_name="Missing Peak")
    absent.pop("peak_rooms")
    validate_error(
        api.create_lead(absent, SALES_MANAGER), ApiErrorId.INVALID_REQUEST, 400
    )

    stringly = F.lead_payload(account["id"], program_name="Stringly Typed")
    stringly["peak_rooms"] = "4"
    validate_error(
        api.create_lead(stringly, SALES_MANAGER), ApiErrorId.INVALID_REQUEST, 400
    )

    _, meta = validate_paginated(
        api.list_account_leads(account["id"], SALES_MANAGER)
    )
    assert meta["total_count"] == 0, "a rejected create must persist nothing"


def test_closed_enums_and_numeric_ranges_are_both_request_shape_rules(api):
    """An unknown enum member and an out-of-range fraction are the same failure.

    PRD 3.1 closes market_segment over the four segments that have a scoring
    multiplier, so LEISURE has no meaning and cannot be defaulted to 1.0, and it
    bounds max_discount_stack_pct above by 1. PRD 2.8 answers both at priority 3
    with a 400 rather than treating them as business rules.

    Design: Corner/entities/account_create_with_invalid_enum_market_segment_is_rejected
    """
    validate_error(
        api.create_account(
            F.account_payload(
                name="Sunseeker Tours",
                market_segment="LEISURE",
                billing_contact_email="ap@sunseeker.example",
            ),
            SALES_MANAGER,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_package(
            F.package_payload(name="Impossible Cap", max_discount_stack_pct=1.5),
            REVENUE_MANAGER,
        ),
        ApiErrorId.INVALID_REQUEST,
        400,
    )


def test_qualification_is_what_computes_the_score_and_the_room_night_value(api):
    """Both computed columns are null until qualification writes them.

    PRD 3.2 leaves qualification_score and estimated_room_night_value_cents null
    on a new lead while deriving nights_count from the half-open stay range - 3,
    not 4 - and then writes 29 raw points scaled by the CORPORATE 1.20 to 35, and
    a room-night value of 17220 cents times 12 room nights. Qualification is a
    single mutation, so version goes from 1 to 2.

    Design: Corner/entities/lead_qualify_writes_both_computed_fields_and_leaves_inputs_alone
    """
    world = seed_calendar_and_package(api)
    created = seed_lead(api, world["account_id"])

    assert_lead(
        read_lead(api, created["id"]),
        status=LeadStatus.NEW,
        qualification_score=None,
        estimated_room_night_value_cents=None,
        nights_count=3,
        peak_rooms=4,
        total_requested_room_nights=12,
        version=1,
    )

    qualified = validate_success(api.qualify_lead(created["id"], SALES_MANAGER))

    assert_lead(
        qualified,
        status=LeadStatus.QUALIFIED,
        qualification_score=35,
        estimated_room_night_value_cents=206640,
        nights_count=3,
        peak_rooms=4,
        total_requested_room_nights=12,
        version=2,
    )


def test_identifiers_timestamps_and_the_owner_are_all_server_minted(api):
    """The client supplies none of the system fields.

    PRD 2.5 mints a bare UUID with no type prefix and renders both instants from
    the logical clock with exactly three fractional digits, identical on a
    freshly created row; PRD 3.2 stamps owner_user_id from the X-User-ID header,
    never from the body. PRD 2.2 wraps the row in an object envelope carrying the
    request id and timestamp.

    Design: Corner/entities/account_system_fields_are_server_minted
    """
    account = seed_account(api)

    response = api.create_lead(
        F.lead_payload(account["id"], program_name="Header Owner Program"),
        SALES_MANAGER_ALT,
    )
    lead = validate_success(response, 201)

    assert is_valid_uuid(lead["id"]) and len(lead["id"]) == 36, (
        f"the id must be a bare 36-character UUID, got {lead['id']!r}"
    )
    assert_lead(lead, owner_user_id=SALES_MANAGER_ALT_ID)
    assert_minted_instant(lead["created_at"], "Lead.created_at")
    assert lead["created_at"] == C.CLOCK_DEFAULT_MINTED, (
        f"created_at must render the logical clock, got {lead['created_at']!r}"
    )
    assert lead["updated_at"] == lead["created_at"], (
        "a freshly created row has not been updated since it was created"
    )

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"]
    assert body["meta"]["api_request_timestamp"]
