"""Registry entity shape: declared defaults, derived zeros, system-stamped
fields, entity-specific not-found codes and the priority-4 schema gate.

Every test in this module translates exactly one non-stub instance of the
``entities`` section of SCAFFOLD_CORNER_DESIGN.yaml.  The logical clock is
pinned as the first server call of every test, and every precondition is built
from an empty database through PRD-declared endpoints only.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_center_hall,
    assert_error_envelope_shape,
    assert_hotel,
    assert_incentive_fund,
    assert_lodging_tax_receipt,
    assert_meeting_planner,
    assert_money_equals,
    assert_opportunity,
    assert_pagination_meta,
    assert_space_hold,
    assert_support_letter,
    fixtures,
    is_valid_uuid,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.types import (
    EngagementStatus,
    FundPosture,
    HallStatus,
    HoldPosture,
    HoldRank,
    LetterType,
    ParticipationStatus,
    PlannerTier,
    SalesStage,
    SpaceHoldStatus,
)

# The clock every chain in this module pins first.
CLOCK = "2026-08-01T00:00:00Z"

PLANNER_INPUT = {
    "org_name": "Continental Dental Assembly",
    "contact_email": "meetings@cda.org",
}

# A two-night convention arriving 2028-04-10: far enough past the pinned clock
# to clear the 180-day qualification lead time.
OPPORTUNITY_INPUT = {
    "event_name": "CDA Annual 2028",
    "arrival_date": "2028-04-10",
    "departure_date": "2028-04-12",
    "peak_rooms_requested": 1000,
    "total_room_nights_requested": 1800,
    "attendance_estimate": 8000,
    "exhibit_sqft_requested": 200_000,
    "rate_ceiling_amount": 219.00,
}

HALL_INPUT = {
    "name": "Grand Hall A",
    "exhibit_sqft": 250_000,
    "capacity_persons": 12_000,
    "turnaround_hours": 48,
}


def test_meeting_planner_creation_applies_every_declared_default(bureau_admin_headers):
    """Registering a planner with only org_name and contact_email materialises
    every derived counter at zero, tier TIER_C, engagement PROSPECT, a null
    last_touch_at and version 1 under a server-minted id.

    PRD: "A freshly registered planner starts with `engagement_status` `PROSPECT`, a `last_touch_at` of null, and every derived counter at zero: `definite_count`, `lost_count`, `lifetime_definite_room_nights`, `relationship_score_lifetime` and `relationship_score_rolling_24m` are all 0 at creation time except insofar as the migrated counters already feed the scores, and `tier` starts at `TIER_C` unless the migrated counters alone earn better." (PRD S3.1)
    PRD: "two optional counters may be supplied at registration: `legacy_definite_count` ... and `legacy_definite_room_nights` ... Both default to 0" (PRD S3.1); "Every resource in the system is identified by a server-minted UUID exposed as `id`. Identifiers carry no type prefix and clients never supply them on creation." (PRD S2.4)

    Design: Corner/entities/meeting_planner_creation_applies_every_declared_default
    """
    fixtures.set_clock(CLOCK)

    response = api_client.create_meeting_planner(dict(PLANNER_INPUT), bureau_admin_headers)
    planner = validate_success(response, expected_status=201)
    assert response.json()["response_type"] == "object"
    assert_meeting_planner(planner)

    assert planner["org_name"] == PLANNER_INPUT["org_name"]
    assert planner["contact_email"] == PLANNER_INPUT["contact_email"]

    assert planner["tier"] == PlannerTier.TIER_C.value
    assert planner["engagement_status"] == EngagementStatus.PROSPECT.value
    assert planner["relationship_score_lifetime"] == 0
    assert planner["relationship_score_rolling_24m"] == 0
    assert planner["last_touch_at"] is None

    for field in (
        "definite_count",
        "lost_count",
        "lifetime_definite_room_nights",
        "legacy_definite_count",
        "legacy_definite_room_nights",
    ):
        assert planner[field] == 0, f"{field} must default to 0, got {planner[field]!r}"

    assert planner["version"] == 1
    assert same_instant(planner["created_at"], CLOCK), (
        f"created_at must be stamped from the logical clock {CLOCK}, "
        f"got {planner['created_at']!r}"
    )
    assert is_valid_uuid(planner["id"]), "id must be a server-minted UUID"


def test_hotel_get_echoes_stored_inputs_and_zeroed_counters(
    bureau_admin_headers, sales_manager_headers
):
    """Reading a registered property echoes its stored inputs verbatim, defaults
    participation_status to PARTICIPATING and reports all three maintained
    aggregates at zero.

    PRD: "A `BureauAdmin` also registers each **hotel** in the citywide package with a property `name` of 1 to 120 characters, a `committable_rooms` figure of at least 1 ... and a `walk_distance_blocks` count of walking blocks from the convention center" (PRD S3.1)
    PRD: "A property's `participation_status` may be supplied at registration and defaults to `PARTICIPATING` ... Three aggregates on the property start at 0 and are maintained by the system: `committed_peak_rooms`, `committed_room_nights` and `pickup_room_nights`." (PRD S3.1)

    Design: Corner/entities/hotel_retrieval_returns_the_stored_row_unchanged
    """
    fixtures.set_clock(CLOCK)

    created = validate_success(
        api_client.create_hotel(
            {"name": "Harborview Grand", "committable_rooms": 600, "walk_distance_blocks": 2},
            bureau_admin_headers,
        ),
        expected_status=201,
    )

    response = api_client.get_hotel(created["id"], sales_manager_headers)
    hotel = validate_success(response, expected_status=200)
    assert response.json()["response_type"] == "object"
    assert_hotel(hotel)

    assert hotel["id"] == created["id"]
    assert hotel["name"] == "Harborview Grand"
    assert hotel["committable_rooms"] == 600
    assert hotel["walk_distance_blocks"] == 2
    assert hotel["participation_status"] == ParticipationStatus.PARTICIPATING.value

    assert hotel["committed_peak_rooms"] == 0
    assert hotel["committed_room_nights"] == 0
    assert hotel["pickup_room_nights"] == 0
    assert hotel["version"] == 1, "a retrieval is not a mutation and must not bump version"


def test_center_hall_listing_pages_with_total_count_and_has_more(
    bureau_admin_headers, center_scheduler_headers
):
    """Three registered halls page two-then-one: total_count stays 3, has_more
    flips from true to false, limit/offset echo the effective values and no hall
    is repeated or skipped across the two pages.

    PRD: "The `meta` block of a list response carries `limit` and `offset` echoing the effective values used, `total_count` giving the number of rows matching the filters before pagination is applied, and `has_more` set to true when rows remain beyond the current page." (PRD S2.3)
    PRD: "The `response_type` is either "object" for a single resource or "array" for a list of resources." (PRD S2.2)

    Design: Corner/entities/center_hall_listing_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock(CLOCK)

    halls = []
    for spec in (
        {"name": "Grand Hall A", "exhibit_sqft": 250_000, "capacity_persons": 12_000,
         "turnaround_hours": 48},
        {"name": "Grand Hall B", "exhibit_sqft": 180_000, "capacity_persons": 9_000,
         "turnaround_hours": 48},
        {"name": "Ballroom C", "exhibit_sqft": 40_000, "capacity_persons": 3_000,
         "turnaround_hours": 24},
    ):
        halls.append(
            validate_success(
                api_client.create_center_hall(spec, bureau_admin_headers),
                expected_status=201,
            )
        )

    first_response = api_client.list_center_halls(
        center_scheduler_headers, params={"limit": 2, "offset": 0}
    )
    page_one, meta_one = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert len(page_one) == 2, f"limit=2 must answer exactly 2 rows, got {len(page_one)}"
    assert_pagination_meta(meta_one, limit=2, offset=0, total_count=3, has_more=True)

    second_response = api_client.list_center_halls(
        center_scheduler_headers, params={"limit": 2, "offset": 2}
    )
    page_two, meta_two = validate_paginated(second_response)
    assert len(page_two) == 1, f"the tail page must answer 1 row, got {len(page_two)}"
    assert_pagination_meta(meta_two, limit=2, offset=2, total_count=3, has_more=False)

    for row in page_one + page_two:
        assert_center_hall(row)

    walked_ids = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(set(walked_ids)) == 3, (
        f"paging forward must walk three distinct halls, got {walked_ids}"
    )
    assert set(walked_ids) == {hall["id"] for hall in halls}
    walked_names = {row["name"] for row in page_one} | {row["name"] for row in page_two}
    assert walked_names == {"Grand Hall A", "Grand Hall B", "Ballroom C"}


def test_opportunity_get_unknown_id_returns_opportunity_not_found(
    sales_manager_headers
):
    """A syntactically valid but unknown opportunity id answers the
    entity-specific 404 ERR_OPPORTUNITY_NOT_FOUND in the error envelope.

    PRD: "Each resource kind has its own dedicated not-found code, all carrying HTTP 404: `ERR_PLANNER_NOT_FOUND`, `ERR_HOTEL_NOT_FOUND`, `ERR_HALL_NOT_FOUND`, `ERR_OPPORTUNITY_NOT_FOUND` ..." (PRD S2.7)
    PRD: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`." / "`response_type": "error"`" with data carrying `error_id` and `message` (PRD S2.2)

    Design: Corner/entities/opportunity_get_with_unknown_id_returns_opportunity_not_found
    """
    fixtures.set_clock(CLOCK)

    response = api_client.get_opportunity(NON_EXISTENT_UUID, sales_manager_headers)
    validate_error(
        response, ApiErrorId.ERR_OPPORTUNITY_NOT_FOUND.value, expected_status=404
    )
    assert_error_envelope_shape(response)


def test_opportunity_create_missing_rate_ceiling_returns_validation(
    sales_manager_headers
):
    """Omitting rate_ceiling_amount fails the priority-4 schema gate with
    ERR_VALIDATION (400) and leaves no opportunity row behind.

    PRD: "Request-body schema conformance — `ERR_VALIDATION`, 400, on every endpoint. This covers required fields being present ..." (PRD S2.7 rule 4)
    PRD: "Alongside them the lead carries a `rate_ceiling_amount`, a strictly positive currency amount with two decimals that no hotel may exceed in its nightly rate for this block." (PRD S3.2)

    Design: Corner/entities/opportunity_creation_missing_required_field_returns_validation
    """
    fixtures.set_clock(CLOCK)
    planner = fixtures.register_planner(**PLANNER_INPUT)

    payload = dict(OPPORTUNITY_INPUT, planner_id=planner["id"])
    payload.pop("rate_ceiling_amount")

    response = api_client.create_opportunity(payload, sales_manager_headers)
    validate_error(response, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    _, meta = validate_paginated(api_client.list_opportunities(sales_manager_headers))
    assert meta["total_count"] == 0, (
        f"a rejected creation must not persist a row, got total_count {meta['total_count']}"
    )


def test_center_hall_omitted_optionals_take_declared_defaults(center_scheduler_headers):
    """Omitting turnaround_hours and hall_status yields the declared 48-hour
    buffer and AVAILABLE status, with confirmed_hold_count starting at 0.

    PRD: "a `turnaround_hours` figure of at least 0 that defaults to 48 and expresses how long the hall needs between one event's move-out and the next event's move-in. A hall's `hall_status` defaults to `AVAILABLE` ... The hall's `confirmed_hold_count` starts at 0" (PRD S3.1)
    PRD: "Exhibit space is registered as **center halls**, which either a `BureauAdmin` or a `CenterScheduler` may create." (PRD S3.1)

    Design: Corner/entities/center_hall_omitted_optional_inputs_take_declared_defaults
    """
    fixtures.set_clock(CLOCK)

    response = api_client.create_center_hall(
        {"name": "Grand Hall A", "exhibit_sqft": 250_000, "capacity_persons": 12_000},
        center_scheduler_headers,
    )
    hall = validate_success(response, expected_status=201)
    assert_center_hall(hall)

    assert hall["turnaround_hours"] == 48, (
        f"the omitted turnaround must default to 48, got {hall['turnaround_hours']!r}"
    )
    assert hall["hall_status"] == HallStatus.AVAILABLE.value
    assert hall["confirmed_hold_count"] == 0
    assert hall["exhibit_sqft"] == 250_000
    assert hall["capacity_persons"] == 12_000


def test_opportunity_event_nights_from_half_open_range(sales_manager_headers):
    """A lead arriving 2028-04-10 and departing 2028-04-12 carries event_nights 2
    over the half-open range, and is born LEAD / NONE with every derived
    aggregate at zero and definite_at and lost_reason null.

    PRD: "The block occupies the half-open range from `arrival_date` up to but **not including** `departure_date`, so the departure night is not an occupied night, and the server derives `event_nights` as the whole number of days from `arrival_date` to `departure_date`. A three-night convention arriving on the 10th therefore departs on the 13th." (PRD S3.2)
    PRD: "A new lead is born in `sales_stage` `LEAD` with `hold_posture` `NONE`, and every derived aggregate on it starts at zero: `committed_peak_rooms`, `block_coverage_pct`, `citywide_cutoff_days_before_arrival`, `cutoff_alignment_spread_days`, `definite_room_nights` and `attrition_settlement_amount` are all 0, while `definite_at` and `lost_reason` are null." (PRD S3.2)

    Design: Corner/entities/opportunity_event_nights_computed_from_the_half_open_date_range
    """
    fixtures.set_clock(CLOCK)
    planner = fixtures.register_planner(**PLANNER_INPUT)

    response = api_client.create_opportunity(
        dict(OPPORTUNITY_INPUT, planner_id=planner["id"]), sales_manager_headers
    )
    opportunity = validate_success(response, expected_status=201)
    assert_opportunity(opportunity)

    assert opportunity["event_nights"] == 2, (
        "2028-04-10 -> 2028-04-12 is two occupied nights over the half-open range, "
        f"got {opportunity['event_nights']!r}"
    )
    assert opportunity["sales_stage"] == SalesStage.LEAD.value
    assert opportunity["hold_posture"] == HoldPosture.NONE.value

    assert_money_equals(
        opportunity["block_coverage_pct"], 0.00, "Opportunity.block_coverage_pct"
    )
    assert opportunity["committed_peak_rooms"] == 0
    assert opportunity["citywide_cutoff_days_before_arrival"] == 0
    assert opportunity["cutoff_alignment_spread_days"] == 0
    assert opportunity["definite_room_nights"] == 0
    assert_money_equals(
        opportunity["attrition_settlement_amount"],
        0.00,
        "Opportunity.attrition_settlement_amount",
    )
    assert opportunity["definite_at"] is None
    assert opportunity["lost_reason"] is None


def test_space_hold_expires_at_stamped_from_clock_plus_ninety_days(
    center_scheduler_headers
):
    """A FIRST-rank hold's expires_at is a system field stamped at 90 days after
    the logical clock -- 2026-08-01 becomes 2026-10-30 and a clock moved to
    2026-09-01 becomes 2026-11-30 -- with challenge_deadline and release_reason
    still null.

    PRD: "A `FIRST`-rank hold has its `expires_at` stamped at 90 days after the current logical clock -- a full quarter for the bureau to convert the lead." (PRD S3.3)
    PRD: "Otherwise the hold is created in status `HELD`, with `hold_rank` set to `FIRST` when the blocking set was empty ... Neither rank sets `challenge_deadline`, which stays null until a challenge is actually raised, and `release_reason` and `challenged_by_space_hold_id` likewise stay null." (PRD S3.3)

    Design: Corner/entities/space_hold_expiry_is_system_stamped_from_the_clock
    """
    fixtures.set_clock(CLOCK)
    planner = fixtures.register_planner(**PLANNER_INPUT)
    hall_a = fixtures.register_hall(**HALL_INPUT)
    lead_a = fixtures.create_lead(planner["id"], **OPPORTUNITY_INPUT)
    fixtures.qualify_lead(lead_a["id"])

    response = api_client.create_space_hold(
        {
            "opportunity_id": lead_a["id"],
            "center_hall_id": hall_a["id"],
            "move_in_start": "2028-04-08T00:00:00Z",
            "move_out_end": "2028-04-13T00:00:00Z",
        },
        center_scheduler_headers,
    )
    hold_a = validate_success(response, expected_status=201)
    assert_space_hold(hold_a)

    assert hold_a["hold_rank"] == HoldRank.FIRST.value
    assert hold_a["status"] == SpaceHoldStatus.HELD.value
    assert same_instant(hold_a["expires_at"], "2026-10-30T00:00:00Z"), (
        "expires_at must be the clock plus the 90-day first-hold life, "
        f"got {hold_a['expires_at']!r}"
    )
    assert hold_a["challenge_deadline"] is None
    assert hold_a["release_reason"] is None
    assert hold_a.get("challenged_by_space_hold_id") is None

    # Moving the clock before the call moves the stamp: no request field can.
    fixtures.set_clock("2026-09-01T00:00:00Z")
    hall_b = fixtures.register_hall(**dict(HALL_INPUT, name="Grand Hall B"))
    lead_b = fixtures.create_lead(planner["id"], **OPPORTUNITY_INPUT)
    fixtures.qualify_lead(lead_b["id"])

    hold_b = validate_success(
        api_client.create_space_hold(
            {
                "opportunity_id": lead_b["id"],
                "center_hall_id": hall_b["id"],
                "move_in_start": "2028-04-08T00:00:00Z",
                "move_out_end": "2028-04-13T00:00:00Z",
            },
            center_scheduler_headers,
        ),
        expected_status=201,
    )
    assert hold_b["hold_rank"] == HoldRank.FIRST.value
    assert same_instant(hold_b["expires_at"], "2026-11-30T00:00:00Z"), (
        "a hold placed a month later expires a month later, "
        f"got {hold_b['expires_at']!r}"
    )


def test_support_letter_is_append_only_and_moves_parent_type_count(
    sales_manager_headers
):
    """A support letter is an append-only event record -- id and created_at with
    no updated_at and no version -- whose received_at is stamped from the clock,
    is readable back through its parent's sub-collection, and moves the parent
    package's distinct-type counter to 1.

    PRD: "Its `received_at` is stamped from the logical clock; being an immutable event record, a letter carries `id` and `created_at` but no `updated_at` and no `version`." (PRD S3.7)
    PRD: "after each attachment the package's `support_letter_type_count` is recomputed as the number of **distinct** `letter_type` values attached to it" (PRD S3.7); "Five resource kinds are deliberately append-only records of a single event and therefore carry only `id` and `created_at` ... support letters ..." (PRD S2.4)

    Design: Corner/entities/support_letter_is_immutable_and_carries_no_version
    """
    fixtures.set_clock(CLOCK)
    planner = fixtures.register_planner(**PLANNER_INPUT)
    lead = fixtures.create_lead(planner["id"], **OPPORTUNITY_INPUT)
    qualified = fixtures.qualify_lead(lead["id"])

    bid = validate_success(
        api_client.create_bid_package(
            {
                "opportunity_id": lead["id"],
                "expected_opportunity_version": qualified["version"],
            },
            sales_manager_headers,
        ),
        expected_status=201,
    )

    response = api_client.create_support_letter(
        bid["id"],
        {"organization_name": "Office of the Mayor", "letter_type": LetterType.MAYOR.value},
        sales_manager_headers,
    )
    letter = validate_success(response, expected_status=201)
    assert_support_letter(letter)

    assert letter["bid_package_id"] == bid["id"]
    assert letter["organization_name"] == "Office of the Mayor"
    assert letter["letter_type"] == LetterType.MAYOR.value
    assert same_instant(letter["received_at"], CLOCK), (
        f"received_at is stamped from the logical clock, got {letter['received_at']!r}"
    )
    assert "version" not in letter, "an immutable letter must expose no version"
    assert "updated_at" not in letter, "an immutable letter must expose no updated_at"

    listed, meta = validate_paginated(
        api_client.list_support_letters(bid["id"], sales_manager_headers)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in listed] == [letter["id"]]
    assert "version" not in listed[0] and "updated_at" not in listed[0]

    parent = validate_success(
        api_client.get_bid_package(bid["id"], sales_manager_headers), expected_status=200
    )
    assert parent["support_letter_type_count"] == 1, (
        "the parent's distinct-type counter moves even though the child is immutable, "
        f"got {parent['support_letter_type_count']!r}"
    )


def test_support_letter_under_unknown_bid_package_returns_bid_not_found(
    sales_manager_headers
):
    """Posting a letter under an unknown bid package id resolves the parent path
    segment first and answers 404 ERR_BID_PACKAGE_NOT_FOUND rather than creating
    an orphan row.

    PRD: "Path identifiers are resolved strictly left to right, and resolution completes before any body field is examined." (PRD S2.7)
    PRD: "Each resource kind has its own dedicated not-found code, all carrying HTTP 404: ... `ERR_BID_PACKAGE_NOT_FOUND` ..." (PRD S2.7)

    Design: Corner/entities/support_letter_against_unknown_bid_package_returns_bid_not_found
    """
    fixtures.set_clock(CLOCK)

    response = api_client.create_support_letter(
        NON_EXISTENT_UUID,
        {"organization_name": "Office of the Mayor", "letter_type": LetterType.MAYOR.value},
        sales_manager_headers,
    )
    validate_error(
        response, ApiErrorId.ERR_BID_PACKAGE_NOT_FOUND.value, expected_status=404
    )


def test_opportunity_unknown_planner_fk_returns_planner_not_found(sales_manager_headers):
    """A body foreign key that dangles is refused with the referenced kind's own
    404 code, ERR_PLANNER_NOT_FOUND, and no lead is created.

    PRD: "The same codes are reused for foreign keys supplied in a request body: `planner_id`, `supersedes_opportunity_id`, `opportunity_id`, `center_hall_id`, `hotel_id`, `bid_package_id`, `fund_id`, `challenging_space_hold_id` and `room_block_commitment_id` must all resolve to live rows, and a dangling reference returns the not-found code of the referenced kind." (PRD S2.7)
    PRD: "Every foreign key in the body resolving — the matching 404 code, on every creation that carries a foreign key." (PRD S2.7 rule 6)

    Design: Corner/entities/opportunity_with_unknown_planner_fk_returns_planner_not_found
    """
    fixtures.set_clock(CLOCK)

    payload = dict(
        OPPORTUNITY_INPUT,
        planner_id=NON_EXISTENT_UUID,
        event_name="Phantom Congress",
        peak_rooms_requested=100,
        total_room_nights_requested=200,
        attendance_estimate=500,
        exhibit_sqft_requested=1000,
        rate_ceiling_amount=199.00,
    )

    response = api_client.create_opportunity(payload, sales_manager_headers)
    validate_error(
        response, ApiErrorId.ERR_PLANNER_NOT_FOUND.value, expected_status=404
    )

    _, meta = validate_paginated(api_client.list_opportunities(sales_manager_headers))
    assert meta["total_count"] == 0, (
        f"a dangling planner reference must create nothing, got {meta['total_count']}"
    )


def test_opportunity_reversed_dates_and_bad_enum_fail_validation(
    sales_manager_headers, services_manager_headers, center_scheduler_headers
):
    """The priority-4 schema gate refuses all three shape violations with
    ERR_VALIDATION (400): an arrival on or after departure, an undeclared enum
    member, and an integer below its declared range.

    PRD: "Request-body schema conformance — `ERR_VALIDATION`, 400, on every endpoint. This covers required fields being present, enum values being declared members, dates being `YYYY-MM-DD` ... integers falling inside their declared ranges, `arrival_date` being strictly earlier than `departure_date` ..." (PRD S2.7 rule 4)
    PRD: "its `category`, which is one of `HOUSING`, `TRANSPORTATION` or `VOLUNTEER`" (PRD S3.9); "an `exhibit_sqft` of rentable exhibit square footage of at least 1" (PRD S3.1)

    Design: Corner/entities/opportunity_reversed_dates_and_bad_enum_fail_type_constraints
    """
    fixtures.set_clock(CLOCK)
    planner = fixtures.register_planner(**PLANNER_INPUT)

    reversed_dates = api_client.create_opportunity(
        dict(
            OPPORTUNITY_INPUT,
            planner_id=planner["id"],
            event_name="Backwards Congress",
            arrival_date="2028-04-12",
            departure_date="2028-04-10",
            peak_rooms_requested=100,
            total_room_nights_requested=200,
            attendance_estimate=500,
            exhibit_sqft_requested=1000,
            rate_ceiling_amount=199.00,
        ),
        sales_manager_headers,
    )
    validate_error(reversed_dates, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    # A lead exists but is only in LEAD stage: the schema gate at priority 4
    # still beats the stage gate at priority 9, so the undeclared category wins.
    lead = fixtures.create_lead(planner["id"], **OPPORTUNITY_INPUT)
    bad_enum = api_client.create_servicing_order(
        {
            "opportunity_id": lead["id"],
            "category": "CATERING",
            "requested_units": 10,
            "window_start": "2028-04-09T00:00:00Z",
            "window_end": "2028-04-13T00:00:00Z",
        },
        services_manager_headers,
    )
    validate_error(bad_enum, ApiErrorId.ERR_VALIDATION.value, expected_status=400)

    out_of_range = api_client.create_center_hall(
        {"name": "Grand Hall A", "exhibit_sqft": 0, "capacity_persons": 12_000,
         "turnaround_hours": 48},
        center_scheduler_headers,
    )
    validate_error(out_of_range, ApiErrorId.ERR_VALIDATION.value, expected_status=400)


def test_lodging_tax_receipts_scoped_to_their_own_fund(
    bureau_admin_headers, board_analyst_headers
):
    """Receipts are children of exactly one fund: fund FY2028's list carries only
    its own two rows, and each fund's budget_amount and lodging_tax_receipts_total
    move only for its own receipts (503400.00 / 3400.00 versus 100500.00 / 500.00).

    PRD: "Posting a receipt raises both `lodging_tax_receipts_total` and `budget_amount` by the receipt `amount`, recomputes `uncommitted_amount` from the conservation identity, re-derives `posture`, and bumps the fund's `version` by one" (PRD S3.1)
    PRD: "`budget_amount` equals `uncommitted_amount` plus `committed_amount` plus `disbursed_amount`." (PRD S2.10)

    Design: Corner/entities/lodging_tax_receipts_are_listed_scoped_to_their_own_fund
    """
    fixtures.set_clock(CLOCK)

    fund_a = validate_success(
        api_client.create_incentive_fund(
            {"fiscal_year": 2028, "budget_amount": 500_000.00}, bureau_admin_headers
        ),
        expected_status=201,
    )
    fund_b = validate_success(
        api_client.create_incentive_fund(
            {"fiscal_year": 2029, "budget_amount": 100_000.00}, bureau_admin_headers
        ),
        expected_status=201,
    )

    receipts_a = []
    for amount in (3000.00, 400.00):
        row = validate_success(
            api_client.create_lodging_tax_receipt(
                fund_a["id"], {"amount": amount, "received_at": CLOCK}, bureau_admin_headers
            ),
            expected_status=201,
        )
        assert_lodging_tax_receipt(row)
        assert row["fund_id"] == fund_a["id"]
        receipts_a.append(row)

    receipt_b = validate_success(
        api_client.create_lodging_tax_receipt(
            fund_b["id"], {"amount": 500.00, "received_at": CLOCK}, bureau_admin_headers
        ),
        expected_status=201,
    )

    listed, meta = validate_paginated(
        api_client.list_lodging_tax_receipts(fund_a["id"], board_analyst_headers)
    )
    assert meta["total_count"] == 2, (
        f"fund FY2028 owns exactly two receipts, got total_count {meta['total_count']}"
    )
    listed_ids = {row["id"] for row in listed}
    assert listed_ids == {receipts_a[0]["id"], receipts_a[1]["id"]}
    assert receipt_b["id"] not in listed_ids, "another fund's receipt must never be listed here"
    for row in listed:
        assert_lodging_tax_receipt(row)
        assert row["fund_id"] == fund_a["id"]
        assert float(row["amount"]) in (3000.00, 400.00)
    assert_money_equals(
        sum(float(row["amount"]) for row in listed), 3400.00, "fund A listed receipt sum"
    )

    read_a = validate_success(
        api_client.get_incentive_fund(fund_a["id"], board_analyst_headers),
        expected_status=200,
    )
    assert_incentive_fund(read_a)
    assert_money_equals(read_a["lodging_tax_receipts_total"], 3400.00, "fund A receipts total")
    assert_money_equals(read_a["budget_amount"], 503_400.00, "fund A budget")
    assert_money_equals(read_a["uncommitted_amount"], 503_400.00, "fund A uncommitted")
    assert_money_equals(read_a["committed_amount"], 0.00, "fund A committed")
    assert_money_equals(read_a["disbursed_amount"], 0.00, "fund A disbursed")
    assert read_a["posture"] == FundPosture.OPEN.value

    read_b = validate_success(
        api_client.get_incentive_fund(fund_b["id"], board_analyst_headers),
        expected_status=200,
    )
    assert_incentive_fund(read_b)
    assert_money_equals(read_b["lodging_tax_receipts_total"], 500.00, "fund B receipts total")
    assert_money_equals(read_b["budget_amount"], 100_500.00, "fund B budget")
    assert_money_equals(read_b["uncommitted_amount"], 100_500.00, "fund B uncommitted")
