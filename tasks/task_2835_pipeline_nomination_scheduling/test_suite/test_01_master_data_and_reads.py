"""Master data creation, server-minted defaults, and the plain read surface.

These tests cover the carrier's reference data — terminals, product grades,
segments, shippers and the immutable historical movement ledger — together with
the server-minted defaults a brand-new nomination cycle and nomination carry,
the not-found and body-reference refusals of the ladder, and the paginated and
single-resource read shapes.

Every test builds its own network from scratch: the database is empty when the
test starts and the logical clock reads the instant it reads before any call.
"""

from test_helpers import (
    ADMIN,
    SCHEDULER,
    UNKNOWN_CYCLE_ID,
    ApiErrorId,
    add_canonical_alpha_history,
    add_shipper,
    assert_capacity_conservation,
    assert_cycle,
    assert_envelope_is_error,
    assert_envelope_is_object,
    assert_millisecond_timestamp,
    assert_nomination,
    assert_product_grade,
    assert_shipping_history_record,
    assert_terminal,
    create_cycle_payload,
    create_nomination_payload,
    create_product_grade_payload,
    create_segment_payload,
    create_shipping_history_payload,
    create_terminal_payload,
    make_shipper_headers,
    refresh_cycle,
    reset_clock,
    setup_cycle_with_nomination,
    setup_multi_shipper_cycle,
    setup_network,
    setup_open_cycle,
    transmix_grade_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# A syntactically valid UUID that names no terminal, used for the body-reference
# resolution rank of the refusal ladder.
UNKNOWN_TERMINAL_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


# --------------------------------------------------------------- the terminals


def test_terminal_registration_echoes_declared_fields_at_version_one(api):
    """PRD 3.1: "Registering a tank terminal takes a `terminal_code` that must be
    unique across all terminals, a `name`, a `role_kind` of `ORIGIN`,
    `DESTINATION` or `BOTH` declaring whether the terminal may originate
    movements, receive them, or do both, a `shell_capacity_bbl` strictly greater
    than zero giving total tankage, and a `min_operating_inventory_bbl` of zero
    or more giving the floor that must remain in tank after any injection debit."
    PRD 3.1: "A newly registered terminal starts with `inventory_bbl` of 0 and
    `version` of 1."
    PRD 4: "Creating a brand-new resource returns HTTP **201**; every other
    successful call — state transitions, adjustments, reschedules and reads alike
    — returns HTTP **200**."

    Design: Corner/entities/terminal_creation_returns_all_declared_fields_at_version_one
    """
    reset_clock()

    response = api.create_terminal(
        create_terminal_payload(
            terminal_code="HOU",
            name="Houston Origin",
            role_kind="ORIGIN",
            shell_capacity_bbl=500000,
            min_operating_inventory_bbl=10000,
            injection_bays=2,
        ),
        ADMIN,
    )
    origin = validate_success(response, 201)

    assert_envelope_is_object(response.json())
    assert_terminal(origin)
    assert origin["terminal_code"] == "HOU", "the terminal echoes its code"
    assert origin["name"] == "Houston Origin", "the terminal echoes its name"
    assert origin["role_kind"] == "ORIGIN", "the terminal echoes its role kind"
    assert float(origin["shell_capacity_bbl"]) == 500000, "total tankage is echoed"
    assert float(origin["min_operating_inventory_bbl"]) == 10000, (
        "the operating floor is echoed"
    )
    assert int(origin["injection_bays"]) == 2, "the declared bay count is echoed"
    assert float(origin["inventory_bbl"]) == 0, (
        "a newly registered terminal holds no barrels"
    )
    assert origin["version"] == 1, "a newly registered terminal is at version 1"
    assert "_" not in origin["id"], "the id is a bare UUID with no type prefix"


def test_terminal_injection_bays_defaults_to_one_when_omitted(api):
    """PRD 3.1: "An optional `injection_bays` states how many batches may occupy
    overlapping injection windows at that terminal; it must be at least 1 and
    defaults to 1 when omitted."

    Design: Corner/entities/terminal_injection_bays_defaults_to_one_when_omitted
    """
    reset_clock()

    payload = create_terminal_payload(
        terminal_code="NAS",
        name="Nashville Delivery",
        role_kind="DESTINATION",
        shell_capacity_bbl=400000,
        min_operating_inventory_bbl=5000,
    )
    payload.pop("injection_bays")

    destination = validate_success(api.create_terminal(payload, ADMIN), 201)

    assert_terminal(destination)
    assert int(destination["injection_bays"]) == 1, (
        "an omitted injection_bays defaults to one bay, never to zero or null"
    )
    assert float(destination["inventory_bbl"]) == 0, "the tank starts empty"
    assert destination["role_kind"] == "DESTINATION", "the role kind is echoed"


def test_terminal_registration_without_shell_capacity_rejected(api):
    """PRD 3.1: "Registering a tank terminal takes a `terminal_code` that must be
    unique across all terminals, a `name`, a `role_kind` of `ORIGIN`,
    `DESTINATION` or `BOTH` declaring whether the terminal may originate
    movements, receive them, or do both, a `shell_capacity_bbl` strictly greater
    than zero giving total tankage, and a `min_operating_inventory_bbl` of zero
    or more giving the floor that must remain in tank after any injection debit."
    PRD 2.5: "Required body fields present; every enum value a member of its
    declared set; volumes and rates strictly greater than zero where positivity
    is required; `window_end` after `window_start`; `effective_to`, when
    supplied, after `effective_from`; `sequence_rank` between 1 and 9 inclusive;
    `capacity_derate_pct` inside the range 0 through 1 inclusive; and every
    supplied instant parsing as ISO 8601 UTC. Any failure yields
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/terminal_creation_missing_required_shell_capacity_rejected
    """
    reset_clock()

    payload = create_terminal_payload(
        terminal_code="HOU",
        name="Houston Origin",
        role_kind="ORIGIN",
        min_operating_inventory_bbl=10000,
    )
    payload.pop("shell_capacity_bbl")
    payload.pop("injection_bays")

    response = api.create_terminal(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert_envelope_is_error(response.json())

    rows, meta = validate_paginated(api.list_terminals(ADMIN, params={"limit": 10}))
    assert meta["total_count"] == 0, "no terminal is registered by a refused request"
    assert rows == [], "the terminal collection stays empty"


def test_terminal_registration_with_undeclared_role_kind_rejected(api):
    """PRD 3.1: "Registering a tank terminal takes a `terminal_code` that must be
    unique across all terminals, a `name`, a `role_kind` of `ORIGIN`,
    `DESTINATION` or `BOTH` declaring whether the terminal may originate
    movements, receive them, or do both, a `shell_capacity_bbl` strictly greater
    than zero giving total tankage, and a `min_operating_inventory_bbl` of zero
    or more giving the floor that must remain in tank after any injection debit."
    PRD 2.5: "Required body fields present; every enum value a member of its
    declared set; volumes and rates strictly greater than zero where positivity
    is required; `window_end` after `window_start`; `effective_to`, when
    supplied, after `effective_from`; `sequence_rank` between 1 and 9 inclusive;
    `capacity_derate_pct` inside the range 0 through 1 inclusive; and every
    supplied instant parsing as ISO 8601 UTC. Any failure yields
    `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/terminal_creation_with_invalid_enum_role_kind_rejected
    """
    reset_clock()

    payload = create_terminal_payload(
        terminal_code="HOU",
        name="Houston Origin",
        role_kind="TRANSSHIP",
        shell_capacity_bbl=500000,
        min_operating_inventory_bbl=10000,
    )
    payload.pop("injection_bays")

    response = api.create_terminal(payload, ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(api.list_terminals(ADMIN, params={"limit": 10}))
    assert meta["total_count"] == 0, (
        "an undeclared role kind is refused rather than stored as free text"
    )
    assert rows == [], "the terminal collection stays empty"


# ---------------------------------------------------------- the grade vocabulary


def test_product_grade_transmix_flag_defaults_to_false(api):
    """PRD 3.1: "A boolean `is_transmix_grade`, defaulting to false, marks a grade
    as the interface slop cut rather than a shippable product."
    PRD 3.1: "Each grade carries a unique `grade_code` — `JET`, `ULSD`, `CBOB` and
    `TRANSMIX` are typical — a human-readable `name`, and a `sequence_rank`
    between 1 and 9 inclusive where rank 1 is the cleanest, lightest product and
    higher ranks are progressively dirtier."

    Design: Corner/entities/product_grade_is_transmix_grade_defaults_to_false_when_omitted
    """
    reset_clock()

    shippable_payload = create_product_grade_payload(
        grade_code="ULSD",
        name="Ultra Low Sulfur Diesel",
        sequence_rank=3,
        max_sulfur_ppm=15,
        max_rvp_psi=12,
    )
    assert "is_transmix_grade" not in shippable_payload, (
        "the shippable grade is filed without the slop flag"
    )
    ulsd = validate_success(api.create_product_grade(shippable_payload, ADMIN), 201)

    slop = validate_success(
        api.create_product_grade(
            transmix_grade_payload(
                grade_code="TRANSMIX",
                name="Interface Transmix",
                sequence_rank=9,
                max_sulfur_ppm=5000,
                max_rvp_psi=20,
            ),
            ADMIN,
        ),
        201,
    )

    assert_product_grade(ulsd)
    assert_product_grade(slop)
    assert ulsd["is_transmix_grade"] is False, (
        "a grade filed without the flag is a shippable product, not the slop cut"
    )
    assert int(ulsd["sequence_rank"]) == 3, "the diesel rank is echoed"
    assert slop["is_transmix_grade"] is True, (
        "the flag is honoured when the filing declares it, never inferred from rank"
    )
    assert int(slop["sequence_rank"]) == 9, "the slop rank is echoed"


# ------------------------------------------------ the immutable history ledger


def test_historical_movement_record_carries_no_version_or_updated_at(api):
    """PRD 2.4: "The one exception is the historical movement record: it is an
    immutable audit row, it has no update operation, and it carries only `id` and
    `created_at` — both `updated_at` and `version` are absent from its
    representation."
    PRD 3.1: "Each row names the `shipper_id` whose movement it records, the
    `segment_id` the movement ran on, the `cycle_code` of the historical cycle it
    summarises, an `actual_shipped_bbl` of zero or more giving the barrels
    actually delivered for that shipper in that cycle, a `cycle_end_at` instant at
    which the historical cycle's shipping window ended, and a `record_status` of
    either `FINAL` or `PROVISIONAL`."
    PRD 2.4: "Every instant the service stores or returns uses that same
    rendering, and every instant a client supplies must parse as ISO 8601 UTC or
    the request is refused with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/shipping_history_record_is_immutable_and_carries_no_version
    """
    ctx = setup_network(grades=("ULSD",))
    alpha = add_shipper(ctx, "ALPHA")

    created = validate_success(
        api.create_shipping_history(
            create_shipping_history_payload(
                alpha["id"],
                ctx["segment"]["id"],
                cycle_code="2026-06",
                actual_shipped_bbl=30000,
                cycle_end_at="2026-06-30T00:00:00Z",
                record_status="FINAL",
            ),
            ADMIN,
        ),
        201,
    )

    read_back = validate_success(api.get_shipping_history(created["id"], SCHEDULER), 200)

    for row in (created, read_back):
        assert_shipping_history_record(row)
        assert "version" not in row, (
            "the historical movement record carries no version at all"
        )
        assert "updated_at" not in row, (
            "the historical movement record carries no updated_at at all"
        )
        assert "id" in row and "created_at" in row, (
            "the record still carries its id and created_at"
        )
        assert float(row["actual_shipped_bbl"]) == 30000.00, (
            "the barrels actually delivered are echoed"
        )
        assert row["record_status"] == "FINAL", "the record status is echoed"
        assert row["shipper_id"] == alpha["id"], "the row names the shipper it records"
        assert row["segment_id"] == ctx["segment"]["id"], (
            "the row names the segment the movement ran on"
        )
        assert row["cycle_code"] == "2026-06", "the historical cycle code is echoed"
        assert row["cycle_end_at"] == "2026-06-30T00:00:00.000Z", (
            "the stored instant is rendered with exactly three fractional digits"
        )
        assert_millisecond_timestamp(row["cycle_end_at"], "cycle_end_at")


# ----------------------------------------------- body references and path reads


def test_segment_with_unknown_origin_terminal_reference_rejected(api):
    """PRD 2.5: "Every foreign key supplied in a request body resolves to an
    existing row — `shipper_id`, `grade_id`, `segment_id`, `origin_terminal_id`,
    `destination_terminal_id`, `linefill_grade_id`, `cycle_id`, `nomination_id`,
    `supersedes_nomination_id`, `tariff_id` and `terminal_id` alike. An
    unresolvable reference yields `ERR_REFERENCE_NOT_FOUND` (404)."
    PRD 3.1: "Its `origin_terminal_id` must name a terminal whose `role_kind` is
    `ORIGIN` or `BOTH`, and its `destination_terminal_id` must name a terminal
    whose `role_kind` is `DESTINATION` or `BOTH`."

    Design: Corner/entities/segment_creation_with_unknown_terminal_reference_rejected
    """
    reset_clock()

    destination = validate_success(
        api.create_terminal(
            create_terminal_payload(
                terminal_code="NAS",
                name="Nashville Delivery",
                role_kind="DESTINATION",
                shell_capacity_bbl=400000,
                min_operating_inventory_bbl=5000,
                injection_bays=1,
            ),
            ADMIN,
        ),
        201,
    )
    ulsd = validate_success(
        api.create_product_grade(create_product_grade_payload(), ADMIN), 201
    )

    response = api.create_segment(
        create_segment_payload(
            UNKNOWN_TERMINAL_ID,
            destination["id"],
            ulsd["id"],
            segment_code="HOU-NAS",
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value, 404)
    assert_envelope_is_error(response.json())

    rows, meta = validate_paginated(api.list_segments(ADMIN, params={"limit": 10}))
    assert meta["total_count"] == 0, (
        "an unresolvable origin terminal creates no segment, even though the "
        "destination terminal and the linefill grade both resolve"
    )
    assert rows == [], "the segment collection stays empty"


def test_unknown_cycle_read_reports_cycle_not_found(api):
    """PRD 2.5: "A missing nomination cycle yields `ERR_CYCLE_NOT_FOUND` (404) on
    the single-cycle read and on every cycle action; a missing nomination yields
    `ERR_NOMINATION_NOT_FOUND` (404) on the single-nomination read and every
    nomination action; a missing batch ticket yields `ERR_BATCH_TICKET_NOT_FOUND`
    (404) on the single-ticket read and every ticket action; a missing maintenance
    event yields `ERR_MAINTENANCE_EVENT_NOT_FOUND` (404) on the single-event read
    and every event action; a missing settlement yields
    `ERR_SETTLEMENT_NOT_FOUND` (404) on the single-settlement read and every
    settlement action."

    Design: Corner/entities/unknown_cycle_id_read_returns_cycle_not_found
    """
    reset_clock()

    response = api.get_cycle(UNKNOWN_CYCLE_ID, SCHEDULER)
    validate_error(response, ApiErrorId.ERR_CYCLE_NOT_FOUND.value, 404)
    assert_envelope_is_error(response.json())


# ----------------------------------------- server-minted cycle and nomination


def test_new_cycle_opens_with_server_minted_system_fields(api):
    """PRD 3.3: "A new cycle's `status` is `OPEN`, its `schedule_version` is 0, its
    `nominated_total_bbl`, `allocated_total_bbl`, `unallocated_capacity_bbl` and
    `total_transmix_bbl` are all 0, its `effective_capacity_bbl` and
    `derate_pct_applied` are 0, its `proration_factor`, `schedule_published_at`,
    `schedule_published_by_user_id` and `settled_at` are null, and its `version`
    is 1."
    PRD 3.4: "Three occasions recompute effective capacity: a close, a proration,
    and any change to the segment's `derate_pct` caused by a maintenance
    transition."

    Design: Corner/entities/cycle_system_fields_are_server_generated_at_creation
    """
    ctx = setup_network(grades=("ULSD",))

    response = api.create_cycle(
        create_cycle_payload(
            ctx["segment"]["id"],
            cycle_code="2026-09",
            window_open_at="2026-08-01T00:00:00Z",
            window_close_at="2026-08-20T00:00:00Z",
            ship_start_at="2026-09-01T00:00:00Z",
            ship_end_at="2026-09-30T00:00:00Z",
        ),
        SCHEDULER,
    )
    cycle = validate_success(response, 201)

    assert_envelope_is_object(response.json())
    assert_cycle(cycle)
    assert cycle["status"] == "OPEN", "a freshly opened cycle is collecting"
    assert cycle["version"] == 1, "the cycle row is at version 1"
    assert int(cycle["schedule_version"]) == 0, (
        "no schedule has been published, so schedule_version is 0"
    )
    assert cycle["schedule_published_at"] is None, "nothing has been published yet"
    assert cycle["schedule_published_by_user_id"] is None, (
        "no publishing operator has been recorded yet"
    )
    assert cycle["settled_at"] is None, "the cycle has not been settled"
    assert cycle["proration_factor"] is None, (
        "the proration factor is null until a proration run computes it"
    )
    assert int(cycle["effective_capacity_bbl"]) == 0, (
        "effective capacity stays 0 until the close sizes the line, even though "
        "the segment's linefill is fully funded"
    )
    assert float(cycle["derate_pct_applied"]) == 0, "no derate has been snapshotted"
    assert int(cycle["nominated_total_bbl"]) == 0, "no volume has been nominated"
    assert int(cycle["allocated_total_bbl"]) == 0, "no volume has been allocated"
    assert int(cycle["unallocated_capacity_bbl"]) == 0, "no capacity has been sized"
    assert int(cycle["total_transmix_bbl"]) == 0, "no interface cut has been computed"
    assert_capacity_conservation(cycle)


def test_new_nomination_starts_at_declared_defaults(api):
    """PRD 3.3: "The new nomination itself starts with `status` of `SUBMITTED`,
    `revision_count` of 0, `allocated_bbl` of 0, `history_base_bbl` of 0,
    `allocation_class` of `NEW_SHIPPER`, `pinned_tariff_id` of null and
    `rejection_reason` of null."
    PRD 2.4: "Most resources additionally carry `updated_at`, refreshed on every
    mutation of the row, and `version`, an integer that starts at 1 when the row
    is created and increments by exactly one on every mutation of that row."
    PRD 3.2: "**Pinning** is the selector that decides which tariff bills a
    nomination, and it runs once per submitted nomination when the cycle closes."

    Design: Corner/entities/nomination_computed_fields_start_at_declared_defaults
    """
    ctx = setup_open_cycle(shippers=("ALPHA",), grades=("ULSD",))
    add_canonical_alpha_history(ctx)
    refresh_cycle(ctx)

    alpha = ctx["shippers"]["ALPHA"]
    response = api.create_nomination(
        create_nomination_payload(
            ctx["cycle"]["id"],
            alpha["id"],
            ctx["grades"]["ULSD"]["id"],
            ctx["origin"]["id"],
            ctx["destination"]["id"],
            ctx["cycle"]["version"],
            nominated_bbl=30000,
        ),
        make_shipper_headers(alpha["id"]),
    )
    nomination = validate_success(response, 201)

    assert_envelope_is_object(response.json())
    assert_nomination(nomination)
    assert nomination["status"] == "SUBMITTED", "the nomination is merely collected"
    assert int(nomination["allocated_bbl"]) == 0, "nothing is allocated before proration"
    assert float(nomination["history_base_bbl"]) == 0, (
        "the shipping history base stays 0 before the close computes it, even "
        "though this shipper has two qualifying historical movements"
    )
    assert nomination["allocation_class"] == "NEW_SHIPPER", (
        "the allocation class starts at NEW_SHIPPER before the close classifies it"
    )
    assert nomination["pinned_tariff_id"] is None, (
        "no rate is pinned until the nomination window closes"
    )
    assert nomination["rejection_reason"] is None, "the nomination is not rejected"
    assert int(nomination["revision_count"]) == 0, "no revision has been requested"
    assert float(nomination["nominated_bbl"]) == 30000, "the requested volume is echoed"
    assert nomination["version"] == 1, "the nomination row is at version 1"


# ------------------------------------------------- the nomination read surface


def test_nomination_listing_pages_with_total_count_and_has_more(api):
    """PRD 2.3: "List responses carry `response_type` of `"array"` and populate four
    pagination fields inside `meta`: `limit` (the effective page size), `offset`
    (the effective starting position), `total_count` (the number of rows matching
    the filters before the page window is applied) and `has_more` (true when rows
    remain beyond the current page)."
    PRD 3.4: "`nominated_total_bbl` is the sum of `nominated_bbl` over the cycle's
    nominations whose `status` is one of `SUBMITTED`, `ACCEPTED`, `PRORATED`,
    `REVISION_REQUESTED`, `SCHEDULED` or `COMPLETED`; `allocated_total_bbl` is the
    sum of `allocated_bbl` over that same status set; `unallocated_capacity_bbl`
    is `effective_capacity_bbl` less `allocated_total_bbl`; and `proration_factor`
    is refreshed as described in §3.5."

    Design: Corner/entities/nomination_listing_paginates_with_total_count_and_has_more
    """
    ctx = setup_multi_shipper_cycle(
        [
            ("ALPHA", "ULSD", 20000),
            ("BRAVO", "ULSD", 20000),
            ("CHARLIE", "ULSD", 20000),
        ],
        grades=("ULSD",),
    )
    cycle_id = ctx["cycle"]["id"]
    expected_ids = {row["id"] for row in ctx["nominations"].values()}
    assert len(expected_ids) == 3, "three distinct nominations compete in the cycle"

    first_page, first_meta = validate_paginated(
        api.list_nominations(
            SCHEDULER, params={"cycle_id": cycle_id, "limit": 2, "offset": 0}
        )
    )
    assert len(first_page) == 2, "the first page carries the requested two rows"
    assert first_meta["total_count"] == 3, (
        "total_count counts the whole filtered set, not the page"
    )
    assert first_meta["has_more"] is True, "a third row remains beyond the first page"
    assert first_meta["limit"] == 2, "the effective page size is echoed"
    assert first_meta["offset"] == 0, "the effective starting position is echoed"

    second_page, second_meta = validate_paginated(
        api.list_nominations(
            SCHEDULER, params={"cycle_id": cycle_id, "limit": 2, "offset": 2}
        )
    )
    assert len(second_page) == 1, "the second page carries the remaining row"
    assert second_meta["total_count"] == 3, (
        "total_count is unchanged by the page window"
    )
    assert second_meta["has_more"] is False, "no row remains beyond the second page"
    assert second_meta["offset"] == 2, "the requested starting position is echoed"

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(paged_ids) == len(set(paged_ids)), "no nomination is paged twice"
    assert set(paged_ids) == expected_ids, (
        "the two pages together return exactly the cycle's three nominations"
    )

    cycle = validate_success(api.get_cycle(cycle_id, SCHEDULER), 200)
    assert int(cycle["nominated_total_bbl"]) == 60000, (
        "the cycle's nominated total is the sum of the three collected nominations"
    )


def test_owning_shipper_reads_its_own_nomination(api):
    """PRD 2.1: "Concretely, a `Shipper` may act on or read a nomination only when
    the nomination's `shipper_id` equals `X-User-ID`; may read a batch ticket only
    when the ticket's nomination belongs to that shipper; may read a settlement
    only when the settlement's `shipper_id` equals `X-User-ID`; and, when
    submitting a nomination, must supply a body `shipper_id` equal to
    `X-User-ID`."
    PRD 2.3: "Single-resource reads carry `response_type` of `"object"` and do not
    populate those four fields."

    Design: Corner/entities/nomination_retrieval_returns_stored_row_to_its_owner
    """
    ctx = setup_cycle_with_nomination(
        nominated_bbl=30000, shippers=("ALPHA",), grades=("ULSD",)
    )
    alpha = ctx["shippers"]["ALPHA"]
    nomination = ctx["nominations"]["ALPHA:ULSD"]

    response = api.get_nomination(nomination["id"], make_shipper_headers(alpha["id"]))
    read_back = validate_success(response, 200)

    assert_envelope_is_object(response.json())
    assert_nomination(read_back)
    assert read_back["id"] == nomination["id"], "the owner reads back its own row"
    assert read_back["cycle_id"] == ctx["cycle"]["id"], "the nomination names its cycle"
    assert read_back["shipper_id"] == alpha["id"], (
        "the stored shipper is the acting principal"
    )
    assert read_back["grade_id"] == ctx["grades"]["ULSD"]["id"], (
        "the nominated product grade is stored intact"
    )
    assert read_back["origin_terminal_id"] == ctx["origin"]["id"], (
        "the requested origin terminal is stored intact"
    )
    assert read_back["destination_terminal_id"] == ctx["destination"]["id"], (
        "the requested destination terminal is stored intact"
    )
    assert float(read_back["nominated_bbl"]) == 30000, (
        "the requested volume is stored intact"
    )
    assert read_back["status"] == "SUBMITTED", "the nomination is still collecting"
