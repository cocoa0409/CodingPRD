"""Envelope, pagination, the logical clock, reverse lookups and the error shape.

PRD 2.2 wraps every answer in the same three-key envelope and PRD 2.3 fixes the
pagination contract; PRD 2.4 makes the logical clock the only source of "now",
and PRD 4 lists the reverse-lookup reads that navigate the flat topology.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    CONTRACT_ADMIN,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    RESERVATIONS_AGENT,
    REVENUE_MANAGER,
    SALES_MANAGER,
    AnalysisVariant,
    ApiErrorId,
    ChargeCategory,
    ContractStatus,
    LeadStatus,
    ReservationStatus,
    SpaceCode,
    assert_ancillary_charge,
    assert_block_night,
    assert_error_envelope,
    assert_lead,
    assert_no_pagination_meta,
    assert_pagination_meta,
    constants as C,
    factories as F,
    read_lead,
    reset_clock,
    seed_account,
    seed_ancillary_charge,
    seed_inventory_days,
    seed_lead,
    seed_open_master_block,
    seed_qualified_lead,
    seed_reservation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_object_reads_and_list_reads_wear_their_declared_envelopes(api):
    """An object read carries no window; a list read carries the default one.

    PRD 2.2 reserves the pagination figures for list endpoints, and PRD 2.3 fixes
    the defaults: limit "defaults to 10, its minimum accepted value is 1 and its
    maximum accepted value is 100", offset "defaults to 0 when omitted", with
    total_count counting "the number of rows matching the filters before the
    pagination window is applied". PRD 2.3 also refuses to be lenient about the
    bounds - "a limit outside the range 1 through 100, or a negative offset, is a
    malformed request and is rejected with ERR_INVALID_REQUEST (HTTP 400) rather
    than being silently clamped" - and PRD 2.8 routes that through priority 3, so
    a clamping implementation returns 200 where a 400 is required.

    Design: Corner/endpoints/envelope_and_pagination_shape_on_object_and_array_reads
    """
    reset_clock(api)
    account = seed_account(api)
    seed_inventory_days(api)

    object_response = api.get_account(account["id"], REVENUE_MANAGER)
    object_body = object_response.json()
    assert validate_success(object_response)["name"] == "Northwind Manufacturing"
    assert object_body["response_type"] == "object", (
        f"a single-entity read is an object read: {object_body['response_type']!r}"
    )
    assert object_body["meta"]["api_request_id"]
    assert object_body["meta"]["api_request_timestamp"]
    assert_no_pagination_meta(object_body)

    list_response = api.list_inventory_days(REVENUE_MANAGER)
    rows, meta = validate_paginated(list_response)
    assert list_response.json()["response_type"] == "array"
    assert_pagination_meta(meta, limit=10, offset=0, total_count=3, has_more=False)
    assert rows[0]["stay_date"] == "2026-11-09"

    validate_error(
        api.list_inventory_days(REVENUE_MANAGER, limit=0),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.list_inventory_days(REVENUE_MANAGER, limit=101),
        ApiErrorId.INVALID_REQUEST,
        400,
    )
    validate_error(
        api.list_inventory_days(REVENUE_MANAGER, offset=-1),
        ApiErrorId.INVALID_REQUEST,
        400,
    )


def test_the_lead_time_band_is_read_from_the_logical_clock_and_then_frozen(api):
    """Where the clock stands decides the band; moving it later decides nothing.

    PRD 2.4 states that "nothing in this service reads wall-clock time" and that
    "every deadline, expiry, cutoff, lead-time bucket, lapse test and damage tier
    is evaluated against a logical clock that the service owns", reporting the new
    position as current_utc. PRD 3.2 buys the top lead-time band at "180 days or
    more", and 2026-05-01 is 192 days before the 2026-11-09 arrival, so the
    identical enquiry earns 20 points instead of the 12 it earns from the startup
    default: 37 raw points scaled by the CORPORATE 1.20 is 44.4, which rounds half
    up to 44. The room-night value reads no clock and is unchanged. PRD 3.2 writes
    qualification_score onto the row, so unlike the account's incentive tier of
    PRD 3.1 it must not be re-derived when the clock later moves.

    Design: Corner/endpoints/the_clock_endpoint_moves_the_lead_time_scoring_tier
    """
    set_clock(api, "2026-05-01T00:00:00Z")
    account = seed_account(api)
    seed_inventory_days(api)
    lead = seed_lead(api, account["id"])

    early = validate_success(api.qualify_lead(lead["id"], SALES_MANAGER))

    assert_lead(
        early,
        status=LeadStatus.QUALIFIED,
        qualification_score=44,
        estimated_room_night_value_cents=206640,
    )

    moved = set_clock(api, C.CLOCK_DEFAULT)
    assert moved["current_utc"] == C.CLOCK_DEFAULT_MINTED, (
        f"the clock reports its new position, got {moved.get('current_utc')!r}"
    )
    assert_lead(read_lead(api, lead["id"]), qualification_score=44)


def test_each_reverse_lookup_returns_its_own_children_and_honours_its_filter(api):
    """Six child lists, each scoped to one parent and each narrowed by a filter.

    PRD 4 gives every child collection a reverse-lookup read off its parent, and
    PRD 2.3 says a filter that matches nothing "is an empty page, not an error",
    with total_count counting the matching rows before the window. The decoy
    organization and its own enquiry are what make the scoping visible: an
    implementation that ignores the parent id would report two leads. PRD 2.3
    makes the date window on the nightly grid half-open - "a from_date window
    bound that is inclusive and a to_date window bound that is exclusive" - so
    consecutive dates select exactly the first of them, and the charge list
    separates two categories against the same contract.

    Design: Corner/endpoints/reverse_lookup_endpoints_return_and_filter_their_children
    """
    world = seed_open_master_block(api)
    seed_reservation(
        api,
        world["master_block_id"],
        guest_name="Delegate One",
        arrival_date="2026-11-09",
        departure_date="2026-11-10",
    )
    seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
    )
    seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.AUDIOVISUAL,
        gross_amount_cents=200000,
    )
    decoy = seed_account(api, name="Decoy Logistics")
    seed_lead(api, decoy["id"], program_name="Decoy Program")

    leads, leads_meta = validate_paginated(
        api.list_account_leads(world["account_id"], SALES_MANAGER)
    )
    assert leads_meta["total_count"] == 1, (
        f"the decoy organization owns its own enquiry: {leads}"
    )
    assert_lead(leads[0], program_name="Northwind Sales Kickoff")
    _, new_only = validate_paginated(
        api.list_account_leads(world["account_id"], SALES_MANAGER, status=LeadStatus.NEW)
    )
    assert new_only["total_count"] == 0, "this organization's lead is long past NEW"

    _, historical = validate_paginated(
        api.list_lead_displacement_analyses(
            world["lead_id"],
            REVENUE_MANAGER,
            analysis_variant=AnalysisVariant.HISTORICAL_BASED,
        )
    )
    assert historical["total_count"] == 0, "the only study on file is forecast based"

    nights, nights_meta = validate_paginated(
        api.list_block_nights(
            world["master_block_id"],
            CONTRACT_ADMIN,
            from_date="2026-11-10",
            to_date="2026-11-11",
        )
    )
    assert nights_meta["total_count"] == 1, f"a half-open window of one day: {nights}"
    assert_block_night(nights[0], stay_date="2026-11-10", rooms_allotted=4)

    charges, charges_meta = validate_paginated(
        api.list_contract_ancillary_charges(
            world["contract_id"], ACCOUNTING_CLERK, category=ChargeCategory.BANQUET
        )
    )
    assert charges_meta["total_count"] == 1, f"two categories, one match: {charges}"
    assert_ancillary_charge(charges[0], net_amount_cents=450000)

    pending, pending_meta = validate_paginated(
        api.list_block_reservations(
            world["master_block_id"],
            RESERVATIONS_AGENT,
            status=ReservationStatus.PENDING,
        )
    )
    assert pending_meta["total_count"] == 1, f"one rooming-list entry: {pending}"
    assert pending[0]["guest_name"] == "Delegate One"
    _, cancelled = validate_paginated(
        api.list_block_reservations(
            world["master_block_id"],
            RESERVATIONS_AGENT,
            status=ReservationStatus.CANCELLED,
        )
    )
    assert cancelled["total_count"] == 0, "nobody has dropped out"

    signed, signed_meta = validate_paginated(
        api.list_contracts(
            CONTRACT_ADMIN, quote_id=world["quote_id"], status=ContractStatus.SIGNED
        )
    )
    assert signed_meta["total_count"] == 1, f"the quote produced one contract: {signed}"
    assert signed[0]["id"] == world["contract_id"]
    _, drafts = validate_paginated(
        api.list_contracts(CONTRACT_ADMIN, status=ContractStatus.DRAFT)
    )
    assert drafts["total_count"] == 0, "the contract has moved on from DRAFT"


def test_the_error_envelope_is_identical_from_four_hundred_to_four_twenty_two(api):
    """Six refusals across six status classes, one shape between them.

    PRD 2.2 gives a failure the same three keys as a success, with data narrowed
    to "exactly two fields: error_id ... and message, a human-readable sentence",
    and PRD 2.6 adds that "the message text is never asserted against by
    contract, but it must not be empty". PRD 2.8 supplies one instance of each
    class in its own priority order: a missing X-User-ID at priority 1, a role
    without the grant at priority 2, a malformed body at priority 3, an
    unresolvable id at priority 5, a step the row's status does not declare at
    priority 10, and a business rule at priority 7. An implementation that leaks a
    stack trace, an errors array or a bare string on any one of them breaks the
    uniformity the envelope promises.

    Design: Corner/errors/the_error_envelope_is_uniform_across_every_status_class
    """
    world = seed_qualified_lead(api)

    refusals = [
        (
            api.create_account(F.account_payload(name="No Badge"), NO_AUTH_HEADERS),
            ApiErrorId.UNAUTHENTICATED,
            401,
        ),
        (
            api.create_inventory_day(F.inventory_day_payload("2026-11-20"), SALES_MANAGER),
            ApiErrorId.UNAUTHORIZED,
            403,
        ),
        (
            api.create_account(
                F.account_payload(name="Bad Segment", market_segment="WHOLESALE"),
                SALES_MANAGER,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        ),
        (
            api.get_account(NON_EXISTENT_UUID, SALES_MANAGER),
            ApiErrorId.ACCOUNT_NOT_FOUND,
            404,
        ),
        (
            api.qualify_lead(world["lead_id"], SALES_MANAGER),
            ApiErrorId.LEAD_INVALID_STATE,
            409,
        ),
        (
            api.create_function_space_hold(
                F.function_space_hold_payload(
                    world["lead_id"],
                    space_code=SpaceCode.BOARDROOM,
                    start_at="2026-11-09T09:00:00Z",
                    end_at="2026-11-09T08:00:00Z",
                    attendee_count=12,
                ),
                SALES_MANAGER,
            ),
            ApiErrorId.INVALID_DATE_RANGE,
            422,
        ),
    ]

    for response, error_id, status in refusals:
        validate_error(response, error_id, status)
        assert_error_envelope(response.json())
