"""Founding a season: halls, sections, the collective agreement and the catalogue reads."""

from test_helpers import (
    ARTISTIC_ADMIN,
    BOX_OFFICE,
    ORCHESTRA_MANAGER,
    ApiErrorId,
    add_engagement,
    assert_concert,
    assert_patron,
    assert_seat_section,
    assert_union_agreement,
    assert_venue,
    build_world,
    create_balcony_section,
    create_concert,
    create_musician,
    create_patron,
    create_section,
    create_service,
    create_venue,
    inventory_for,
    read_concert,
    read_patron,
    read_service,
    read_venue,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_concert_opens_all_three_status_dimensions(api):
    """PRD 3.2: "On creation the concert takes its three opening statuses —
    `programming_status` of `DRAFT`, `sale_status` of `UNANNOUNCED`,
    `performance_status` of `SCHEDULED` — a `readiness_posture` of `READY`, a
    `substitution_count` of 0, a `gross_ticket_revenue_cents` of 0, and the
    `section_inventory` snapshot described in §2.9."
    PRD 2.9: "At creation the held and sold counts are zero, `available_count`
    equals `capacity`, `fill_bp` is 0 and `demand_band` is `LOW`."
    PRD 2.4: "`version` is an integer that starts at 1 on creation and increments
    by one on every mutation of the resource."

    Design: Corner/entities/create_concert_returns_201_with_all_three_status_dimensions
    """
    set_clock("2026-09-01T00:00:00Z")
    season = validate_success(
        api.create_season(
            {
                "name": "2027 Season",
                "fiscal_year": 2027,
                "renewal_deadline_utc": "2026-10-01T00:00:00Z",
                "base_ticket_price_cents": 6000,
            },
            ARTISTIC_ADMIN,
        ),
        201,
    )
    venue = validate_success(
        api.create_venue({"name": "Grand Hall", "changeover_buffer_minutes": 60},
                         ARTISTIC_ADMIN),
        201,
    )
    section = validate_success(
        api.create_section(
            {
                "venue_id": venue["id"],
                "name": "ORCHESTRA",
                "capacity": 100,
                "price_multiplier_bp": 15000,
                "donor_priority_rank": 1,
            },
            ARTISTIC_ADMIN,
        ),
        201,
    )

    response = api.create_concert(
        {
            "season_id": season["id"],
            "venue_id": venue["id"],
            "title": "Opening Night",
            "performance_start_utc": "2026-11-05T19:30:00Z",
            "performance_end_utc": "2026-11-05T21:30:00Z",
            "program_minutes": 105,
        },
        ARTISTIC_ADMIN,
    )
    concert = validate_success(response, 201)
    assert_concert(concert)

    assert concert["programming_status"] == "DRAFT"
    assert concert["sale_status"] == "UNANNOUNCED"
    assert concert["performance_status"] == "SCHEDULED"
    assert concert["readiness_posture"] == "READY"
    assert concert["substitution_count"] == 0
    assert concert["gross_ticket_revenue_cents"] == 0
    assert concert["version"] == 1, "a freshly created resource is at version 1"

    assert len(concert["section_inventory"]) == 1
    element = inventory_for(concert, section["id"])
    assert element["capacity"] == 100
    assert element["held_count"] == 0
    assert element["sold_count"] == 0
    assert element["available_count"] == 100
    assert element["fill_bp"] == 0
    assert element["demand_band"] == "LOW"


def test_section_added_after_a_concert_is_not_retrofitted_onto_it(api):
    """PRD 2.9: "Adding a section to a hall afterwards does not retro-fit an
    inventory element onto concerts created earlier."
    PRD 2.9: "A hall also publishes `total_capacity`, the sum of `capacity` over
    the seating sections registered inside it, which grows as each section is added."

    Design: Corner/entities/section_inventory_is_snapshotted_and_not_retrofitted
    """
    set_clock("2026-09-01T00:00:00Z")
    world = build_world(
        clock=None,
        with_union=False,
        venue_overrides={"name": "Grand Hall"},
        section_specs=[{"_balcony": True}],
        concert_count=1,
        titles=["Early Concert"],
        program_indexes=[],
    )
    balcony = world.section

    orchestra = create_section(world.venue["id"], name="ORCHESTRA", capacity=100,
                               price_multiplier_bp=15000, donor_priority_rank=1)
    late_concert = create_concert(
        world.season["id"], world.venue["id"], title="Late Concert",
        performance_start_utc="2026-12-05T19:30:00Z",
        performance_end_utc="2026-12-05T21:30:00Z",
    )

    early = read_concert(world.concert["id"])
    assert len(early["section_inventory"]) == 1, (
        "the earlier concert must keep the single-section snapshot it was created with"
    )
    assert early["section_inventory"][0]["seat_section_id"] == balcony["id"]

    late = read_concert(late_concert["id"])
    assert len(late["section_inventory"]) == 2
    assert {e["seat_section_id"] for e in late["section_inventory"]} == {
        balcony["id"], orchestra["id"],
    }

    assert read_venue(world.venue["id"])["total_capacity"] == 150


def test_optional_fields_fall_back_to_their_declared_defaults(api):
    """PRD 3.1: "A **Venue** carries only a `name` and an optional
    `changeover_buffer_minutes`, the stage-turnaround interval described in §2.8,
    which defaults to 60 minutes and must not be negative."
    PRD 3.1: "The optional `min_renewal_priority_score` sets the minimum priority
    score a patron must reach in order to renew a package seated here; it defaults
    to 0 and must not be negative."
    PRD 3.1: "`max_service_minutes` — the worked minutes included in scale, above
    which overtime begins — defaults to 150 minutes, or two and a half hours, and
    must be at least 1."
    PRD 3.1: "One optional field, `loyalty_discount_bp`, sets the base loyalty
    discount in basis points granted to renewing subscribers; it defaults to 500
    basis points — five percent — and may be set anywhere from 0 to 2000 basis
    points inclusive."

    Design: Corner/entities/venue_and_union_defaults_applied_when_omitted
    """
    set_clock("2026-09-01T00:00:00Z")
    season = validate_success(
        api.create_season(
            {
                "name": "2027 Season",
                "fiscal_year": 2027,
                "renewal_deadline_utc": "2026-10-01T00:00:00Z",
                "base_ticket_price_cents": 6000,
            },
            ARTISTIC_ADMIN,
        ),
        201,
    )
    assert season["loyalty_discount_bp"] == 500

    venue = validate_success(
        api.create_venue({"name": "Bare Hall"}, ARTISTIC_ADMIN), 201
    )
    assert_venue(venue)
    assert venue["changeover_buffer_minutes"] == 60

    section = validate_success(
        api.create_section(
            {
                "venue_id": venue["id"],
                "name": "ORCHESTRA",
                "capacity": 100,
                "price_multiplier_bp": 15000,
                "donor_priority_rank": 1,
            },
            ARTISTIC_ADMIN,
        ),
        201,
    )
    assert_seat_section(section)
    assert section["min_renewal_priority_score"] == 0

    agreement = validate_success(
        api.create_union_agreement(
            {"season_id": season["id"], "scale_service_fee_cents": 20000},
            ORCHESTRA_MANAGER,
        ),
        201,
    )
    assert_union_agreement(agreement)
    assert agreement["max_service_minutes"] == 150
    assert agreement["overtime_rate_cents_per_minute"] == 400
    assert agreement["min_rest_minutes_between_services"] == 90
    assert agreement["max_services_per_day"] == 2
    assert agreement["doubling_premium_bp"] == 1250
    assert agreement["mandatory_break_minutes"] == 20
    assert agreement["principal_premium_bp"] == 2000


def test_new_patron_ledgers_start_at_zero_with_a_seniority_only_score(api):
    """PRD 3.4: "A new patron opens with a `donor_level` of `NONE`, with
    `lifetime_donation_cents`, `consecutive_renewal_years`, `credit_balance_cents`
    and `lifetime_cash_in_cents` all at zero, and with a `renewal_priority_score`
    computed from seniority alone."
    PRD 3.4: "The score is then the patron's `consecutive_renewal_years` multiplied
    by 100, plus the points their `donor_level` carries — 0 for `NONE`, 50 for
    `FRIEND`, 150 for `SUSTAINER`, 400 for `BENEFACTOR` and 900 for `LAUREATE` —
    plus seniority in years multiplied by 10."

    Design: Corner/entities/patron_system_fields_start_at_zero_and_are_server_owned
    """
    set_clock("2026-09-01T00:00:00Z", BOX_OFFICE)
    patron = validate_success(
        api.create_patron(
            {
                "full_name": "Noel Vance",
                "email": "noel-fields@patron.test",
                "subscriber_since_year": 2018,
            },
            BOX_OFFICE,
        ),
        201,
    )
    assert_patron(patron)
    assert patron["donor_level"] == "NONE"
    assert patron["lifetime_donation_cents"] == 0
    assert patron["credit_balance_cents"] == 0
    assert patron["lifetime_cash_in_cents"] == 0
    assert patron["consecutive_renewal_years"] == 0
    assert patron["renewal_priority_score"] == 80, (
        "seniority alone: the 2026 clock year less 2018, times 10"
    )
    assert patron["version"] == 1


def test_venue_total_capacity_is_the_sum_of_its_sections(api):
    """PRD 3.1: "Registering a section adds its `capacity` to the hall's
    `total_capacity`, but — as noted in §2.9 — it does not retro-fit an inventory
    element onto concerts that already exist."

    Design: Corner/entities/venue_total_capacity_is_computed_from_sections
    """
    set_clock("2026-09-01T00:00:00Z")
    venue = create_venue(name="Grand Hall", changeover_buffer_minutes=60)
    assert read_venue(venue["id"])["total_capacity"] == 0

    create_section(venue["id"], name="ORCHESTRA", capacity=100,
                   price_multiplier_bp=15000, donor_priority_rank=1)
    assert read_venue(venue["id"])["total_capacity"] == 100

    create_balcony_section(venue["id"])
    assert read_venue(venue["id"])["total_capacity"] == 150

    data, meta = validate_paginated(
        api.list_sections(ARTISTIC_ADMIN, params={"venue_id": venue["id"]})
    )
    assert meta["total_count"] == 2
    assert len(data) == 2


def test_concert_listing_reports_pagination_meta(api):
    """PRD 2.3: "`limit` caps the number of items returned; when it is not supplied
    it defaults to 10, its minimum accepted value is 1 and its maximum accepted
    value is 100."
    PRD 2.3: "List responses carry the four pagination fields inside the `meta`
    object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/concert_list_pagination_reports_total_count_and_has_more
    """
    world = build_world(concert_count=3, program_indexes=[])

    first_page = api.list_concerts(
        ARTISTIC_ADMIN, params={"season_id": world.season["id"], "limit": 2, "offset": 0}
    )
    data, meta = validate_paginated(first_page)
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert first_page.json()["response_type"] == "array"

    second_page = api.list_concerts(
        ARTISTIC_ADMIN, params={"season_id": world.season["id"], "limit": 2, "offset": 2}
    )
    data, meta = validate_paginated(second_page)
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert second_page.json()["response_type"] == "array"


def test_engagement_listing_resolves_service_and_musician_directions(api):
    """PRD 3.3: "The engagement opens in `CONFIRMED` with `provisional_pay_cents`
    and `final_pay_cents` null and `overtime_minutes` at 0, and it increments the
    service's `confirmed_engagement_count` by one."

    Design: Corner/entities/engagement_junction_resolves_both_directions
    """
    world = build_world()
    service_a = create_service(
        world.concert["id"], world.venue["id"],
        scheduled_start_utc="2026-11-04T14:00:00Z",
        scheduled_end_utc="2026-11-04T16:00:00Z",
        minimum_complement=0, break_minutes=20,
    )
    service_b = create_service(
        world.concert["id"], world.venue["id"], service_type="DRESS_REHEARSAL",
        scheduled_start_utc="2026-11-05T14:00:00Z",
        scheduled_end_utc="2026-11-05T16:00:00Z",
        minimum_complement=0, break_minutes=20,
    )
    player_one = create_musician(full_name="Pia Solberg", instrument="VIOLIN")
    player_two = create_musician(full_name="Tomas Reiner", instrument="CELLO")

    add_engagement(service_a["id"], player_one["id"])
    add_engagement(service_a["id"], player_two["id"])
    add_engagement(service_b["id"], player_one["id"])

    _, meta = validate_paginated(
        api.list_engagements(ORCHESTRA_MANAGER, params={"service_id": service_a["id"]})
    )
    assert meta["total_count"] == 2, "service A carries both players"

    _, meta = validate_paginated(
        api.list_engagements(ORCHESTRA_MANAGER, params={"musician_id": player_one["id"]})
    )
    assert meta["total_count"] == 2, "player one plays both services"

    _, meta = validate_paginated(
        api.list_engagements(ORCHESTRA_MANAGER, params={"musician_id": player_two["id"]})
    )
    assert meta["total_count"] == 1

    assert read_service(service_a["id"])["confirmed_engagement_count"] == 2


def test_create_concert_without_program_minutes_is_rejected(api):
    """PRD 2.6: "Required fields are present, enum-typed fields carry a value from
    their declared set, integer fields fall inside their declared ranges,
    `scheduled_end_utc` is strictly after `scheduled_start_utc`, `actual_end_utc`
    is strictly after `actual_start_utc`, and a patron's `email` is unique across
    all patrons. Any violation yields `ERR_INVALID_REQUEST` with HTTP 422."
    PRD 3.2: "and `program_minutes`, the total printed programme duration in
    minutes, which must be at least 1."

    Design: Corner/entities/create_concert_missing_required_field_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z")
    world = build_world(clock=None, with_union=False, concert_count=0,
                        program_indexes=[])

    response = api.create_concert(
        {
            "season_id": world.season["id"],
            "venue_id": world.venue["id"],
            "title": "Nameless",
            "performance_start_utc": "2026-11-05T19:30:00Z",
            "performance_end_utc": "2026-11-05T21:30:00Z",
        },
        ARTISTIC_ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    _, meta = validate_paginated(
        api.list_concerts(ARTISTIC_ADMIN, params={"season_id": world.season["id"]})
    )
    assert meta["total_count"] == 0, "the rejected request must create nothing"


def test_service_with_non_increasing_schedule_is_rejected(api):
    """PRD 2.6: "Required fields are present, enum-typed fields carry a value from
    their declared set, integer fields fall inside their declared ranges,
    `scheduled_end_utc` is strictly after `scheduled_start_utc`, `actual_end_utc`
    is strictly after `actual_start_utc`, and a patron's `email` is unique across
    all patrons. Any violation yields `ERR_INVALID_REQUEST` with HTTP 422."

    Design: Corner/entities/create_service_with_non_increasing_times_returns_invalid_request
    """
    world = build_world()

    response = api.create_rehearsal(
        {
            "concert_id": world.concert["id"],
            "venue_id": world.venue["id"],
            "service_type": "REHEARSAL",
            "scheduled_start_utc": "2026-11-04T14:00:00Z",
            "scheduled_end_utc": "2026-11-04T14:00:00Z",
            "minimum_complement": 0,
            "break_minutes": 0,
        },
        ORCHESTRA_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    _, meta = validate_paginated(
        api.list_rehearsals(ORCHESTRA_MANAGER,
                            params={"concert_id": world.concert["id"]})
    )
    assert meta["total_count"] == 0


def test_duplicate_patron_email_is_rejected(api):
    """PRD 3.4: "A `BoxOfficeAgent` registers a **Patron** with a `full_name` and an
    `email` that must be unique across all patrons — a duplicate address is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/duplicate_patron_email_returns_invalid_request
    """
    set_clock("2026-09-01T00:00:00Z", BOX_OFFICE)
    first = create_patron(full_name="Noel Vance", email="noel-dup@patron.test")

    response = api.create_patron(
        {"full_name": "Noel Vance Junior", "email": "noel-dup@patron.test"},
        BOX_OFFICE,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    assert read_patron(first["id"])["full_name"] == "Noel Vance"


def test_second_union_agreement_for_a_season_is_refused(api):
    """PRD 3.1: "Exactly one agreement may exist per season; a second registration
    against a season that already has one is refused with
    `ERR_UNION_AGREEMENT_DUPLICATE`."

    Design: Corner/state_machines/duplicate_union_agreement_returns_duplicate_error
    """
    set_clock("2026-09-01T00:00:00Z", ORCHESTRA_MANAGER)
    world = build_world(clock=None, concert_count=0, program_indexes=[])

    response = api.create_union_agreement(
        {"season_id": world.season["id"], "scale_service_fee_cents": 25000},
        ORCHESTRA_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_UNION_AGREEMENT_DUPLICATE.value, 409)

    data, meta = validate_paginated(
        api.list_union_agreements(ORCHESTRA_MANAGER,
                                  params={"season_id": world.season["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["scale_service_fee_cents"] == 20000


def test_concerts_can_be_filtered_by_sale_status(api):
    """PRD 3.5: "When it succeeds, every concert of the season whose
    `programming_status` is `PROGRAMMED` or `LOCKED` and whose `sale_status` is
    still `UNANNOUNCED` moves to `RENEWAL_ONLY`, processed in ascending order of
    `performance_start_utc` with ties broken by ascending `created_at`. Concerts
    still in `DRAFT` programming are left `UNANNOUNCED`."

    Design: Corner/endpoints/filter_concerts_by_sale_status
    """
    world = build_world(concert_count=2, program_indexes=[0],
                        advance_to="RENEWAL_WINDOW")
    programmed, still_draft = world.concerts

    data, meta = validate_paginated(
        api.list_concerts(
            ARTISTIC_ADMIN,
            params={"season_id": world.season["id"], "sale_status": "RENEWAL_ONLY"},
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == programmed["id"]

    data, meta = validate_paginated(
        api.list_concerts(
            ARTISTIC_ADMIN,
            params={"season_id": world.season["id"], "sale_status": "UNANNOUNCED"},
        )
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == still_draft["id"]
