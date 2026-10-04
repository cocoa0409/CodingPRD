"""Breadth tests: entity contracts — creation, defaults, computed fields, uniqueness."""
from test_helpers import (
    ANONYMOUS,
    ATTRACTION_HOST,
    CLUB_CARD_SPECIALIST,
    DEAL_DESK_CLERK,
    NON_EXISTENT_UUID,
    PLATFORM_ADMIN,
    ApiErrorId,
    assert_attraction,
    assert_store,
    create_attraction,
    create_boat_unit,
    create_member,
    create_open_attraction,
    create_point_event,
    create_store,
    get_success_data,
    is_valid_uuid,
    request_session,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# --- entities/store_creation_returns_all_declared_fields_and_defaults ------

def test_opening_a_store_initialises_every_computed_field_rather_than_echoing_the_request(api):
    """PRD §3.1: "The store opens with its admission posture already `OPEN`, its
    committed minutes and free minutes both zero, and its remittance ledger and
    permit-remit epoch both zero."
    PRD §2.4: "`id` is a server-minted UUID. It identifies the resource and is
    never accepted from a client on creation. No type prefix, no entity
    abbreviation and no human-readable fragment is embedded in it."

    Design: Corner/entities/store_creation_returns_all_declared_fields_and_defaults
    """
    response = api.create_store(
        {
            "name": "Ozark Flagship",
            "state_code": "MO",
            "dealer_license_no": "MO-DLR-4417",
            "dwell_capacity_minutes": 60000,
            "load_bays_total": 4,
        },
        PLATFORM_ADMIN,
    )
    store = validate_success(response, 201)
    assert_store(store)
    assert store["name"] == "Ozark Flagship"
    assert store["state_code"] == "MO"
    assert store["dwell_committed_minutes"] == 0, (
        f"a new store commits nothing; got {store['dwell_committed_minutes']}"
    )
    assert store["dwell_free_minutes"] == 60000, (
        f"free minutes equal the declared budget; got {store['dwell_free_minutes']}"
    )
    assert store["attraction_posture"] == "OPEN", (
        f"the posture is a computed default, got {store['attraction_posture']}"
    )
    assert store["remit_ledger_cents"] == 0
    assert store["permit_remit_epoch"] == 0
    assert is_valid_uuid(store["id"]), "the store id is a bare UUID with no type prefix"


# --- entities/store_retrieval_and_listing_paginate -------------------------

def test_the_store_list_reports_pagination_metadata_and_the_read_returns_the_same_row(api):
    """PRD §2.3: "The response `meta` object for a list carries `limit`,
    `offset`, `total_count`, and `has_more`."
    PRD §2.3: "`limit` caps how many records are returned and defaults to 10 when
    it is not supplied; it must be at least 1 and at most 100."
    PRD §2.3: "`total_count` is the number of records matching the filter before
    paging was applied, and `has_more` reports whether further records remain
    past the returned window."

    Design: Corner/entities/store_retrieval_and_listing_paginate
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    create_store(api)
    second = create_store(api, name="Delta Landing", state_code="AR",
                          dealer_license_no="AR-DLR-1180",
                          dwell_capacity_minutes=45000, load_bays_total=2)

    rows, meta = validate_paginated(api.list_stores(PLATFORM_ADMIN, params={"limit": 1}))
    assert len(rows) == 1, f"limit 1 returns exactly one row, got {len(rows)}"
    assert meta["total_count"] == 2, (
        f"both stores match before paging; got {meta['total_count']}"
    )
    assert meta["has_more"] is True, "further records remain past the returned window"
    assert meta["limit"] == 1 and meta["offset"] == 0

    read_back = get_success_data(api.get_store(second["id"], PLATFORM_ADMIN), 200)
    assert read_back["name"] == "Delta Landing"
    assert read_back["state_code"] == "AR"
    assert read_back["id"] == second["id"]


# --- entities/missing_store_id_returns_store_not_found ---------------------

def test_an_unknown_store_uuid_on_a_store_scoped_route_returns_store_not_found(api):
    """PRD §2.6: "A request naming a `store_id` that matches no store row fails
    with `ERR_STORE_NOT_FOUND` (HTTP 404) before any other check runs."
    PRD §2.6: "This holds for every endpoint whose path begins with the store
    segment."

    Design: Corner/entities/missing_store_id_returns_store_not_found
    """
    response = api.get_store(NON_EXISTENT_UUID, PLATFORM_ADMIN)
    validate_error(response, ApiErrorId.ERR_STORE_NOT_FOUND, 404)
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["data"]) == {"error_id", "message"}, (
        "an error envelope carries no entity fields; got " f"{sorted(body['data'])}"
    )


# --- entities/boat_unit_required_fields_and_missing_hull_id_rejected -------

def test_a_boat_unit_missing_its_hull_id_is_refused_and_leaves_no_row(api):
    """PRD §2.11: "the general request-shape rule at"

    Design: Corner/entities/boat_unit_required_fields_and_missing_hull_id_rejected
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)

    response = api.create_boat_unit(
        store["id"],
        {
            "stock_no": "BU-9001",
            "model_name": "Angler 190",
            "unit_price_cents": 9000000,
            "unit_condition": "NEW",
        },
        DEAL_DESK_CLERK,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    rows, meta = validate_paginated(
        api.list_boat_units(DEAL_DESK_CLERK, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 0, (
        f"the rejected unit left no row; got total_count {meta['total_count']}"
    )
    assert rows == []


# --- entities/boat_unit_condition_defaults_and_optional_prices -------------

def test_omitting_the_motor_and_trailer_prices_yields_zero_rather_than_null(api):
    """PRD §3.4: "optional `motor_price_cents` and `trailer_price_cents` that
    default to zero when the unit is a bare hull or is rigged without a
    trailer."
    PRD §3.4: "Units enter inventory `AVAILABLE`."

    Design: Corner/entities/boat_unit_condition_defaults_and_optional_prices
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    unit = get_success_data(
        api.create_boat_unit(
            store["id"],
            {
                "stock_no": "BU-HULL",
                "model_name": "Bare 140",
                "unit_price_cents": 1500000,
                "unit_condition": "NEW",
                "hull_id_no": "HINBARE000001",
            },
            DEAL_DESK_CLERK,
        ),
        201,
    )
    assert unit["motor_price_cents"] == 0, (
        "an omitted motor price defaults to zero rather than null; got "
        f"{unit['motor_price_cents']}"
    )
    assert unit["trailer_price_cents"] == 0, (
        "an omitted trailer price defaults to zero rather than null; got "
        f"{unit['trailer_price_cents']}"
    )
    assert unit["prior_title_no"] is None, (
        f"a new unit carries no prior title; got {unit['prior_title_no']}"
    )
    assert unit["status"] == "AVAILABLE"


# --- entities/attraction_requires_waiver_is_computed_not_client_supplied ---

def test_requires_waiver_is_derived_from_the_venue_type(api):
    """PRD §3.1: "The venue's `requires_waiver` flag is not supplied by the
    caller; the server derives it from the type. The `AQUARIUM`, `MUSEUM` and
    `TAXIDERMY_GALLERY` types never require a waiver."
    PRD §3.1: "The `FISHING_POND`, `ARCHERY_RANGE` and `SIMULATOR` types always
    do."

    Design: Corner/entities/attraction_requires_waiver_is_computed_not_client_supplied
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    aquarium = create_attraction(api, store["id"], attraction_type="AQUARIUM",
                                 capacity_units=40, dwell_cost_minutes=30)
    archery = create_attraction(api, store["id"], attraction_type="ARCHERY_RANGE",
                                capacity_units=12, dwell_cost_minutes=45)

    assert_attraction(aquarium)
    assert aquarium["requires_waiver"] is False, (
        "an aquarium never requires a waiver, because the server derives it from "
        f"the type; got {aquarium['requires_waiver']}"
    )
    assert aquarium["in_use_units"] == 0
    assert archery["requires_waiver"] is True, (
        f"an archery range always requires a waiver; got {archery['requires_waiver']}"
    )
    assert aquarium["status"] == "PLANNED"
    assert archery["status"] == "PLANNED", (
        "a venue is created PLANNED and must be opened before it accepts sessions"
    )


# --- entities/member_email_uniqueness_is_scoped_to_the_home_store ----------

def test_a_duplicate_email_is_refused_at_its_home_store_but_accepted_elsewhere(api):
    """PRD §3.8: "A member is created against a store with an `email` that must
    be unique within that store and a `full_name`."
    PRD §3.8: "A duplicate email in the same store is refused with
    `ERR_DUPLICATE_MEMBER_EMAIL` (HTTP 409)."

    Design: Corner/entities/member_email_uniqueness_is_scoped_to_the_home_store
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    first_store = create_store(api)
    second_store = create_store(api, name="Delta Landing", state_code="AR",
                                dealer_license_no="AR-DLR-1180",
                                dwell_capacity_minutes=45000, load_bays_total=2)
    original = create_member(api, first_store["id"], email="dup@x.com",
                             full_name="First Row")

    duplicate = api.create_member(
        first_store["id"],
        {"email": "dup@x.com", "full_name": "Second Row", "donation_opt_in": False},
        ANONYMOUS,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_MEMBER_EMAIL, 409)

    elsewhere = get_success_data(
        api.create_member(
            second_store["id"],
            {"email": "dup@x.com", "full_name": "Third Row", "donation_opt_in": False},
            ANONYMOUS,
        ),
        201,
    )
    assert elsewhere["email"] == "dup@x.com", (
        "uniqueness is store-scoped, so the same email is legal at a second store"
    )
    assert elsewhere["id"] != original["id"]


# --- entities/boat_unit_stock_and_hin_uniqueness_within_store --------------

def test_a_reused_stock_number_and_a_reused_hin_surface_two_distinct_errors(api):
    """PRD §3.4: "Duplicate inventory identifiers are refused: a `stock_no`
    already present in the store fails with `ERR_DUPLICATE_STOCK_NO` (HTTP 409)
    and a repeated `hull_id_no` fails with `ERR_DUPLICATE_HIN` (HTTP 409)."

    Design: Corner/entities/boat_unit_stock_and_hin_uniqueness_within_store
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    create_boat_unit(api, store["id"], stock_no="BU-9001", model_name="Angler 190",
                     unit_price_cents=9_000_000, unit_condition="NEW",
                     hull_id_no="HIN9001AA000", motor_price_cents=0,
                     trailer_price_cents=0)

    reused_stock = api.create_boat_unit(
        store["id"],
        {
            "stock_no": "BU-9001",
            "model_name": "Angler 210",
            "unit_price_cents": 11000000,
            "unit_condition": "NEW",
            "hull_id_no": "HIN9002AA000",
        },
        DEAL_DESK_CLERK,
    )
    validate_error(reused_stock, ApiErrorId.ERR_DUPLICATE_STOCK_NO, 409)

    reused_hin = api.create_boat_unit(
        store["id"],
        {
            "stock_no": "BU-9002",
            "model_name": "Angler 210",
            "unit_price_cents": 11000000,
            "unit_condition": "NEW",
            "hull_id_no": "HIN9001AA000",
        },
        DEAL_DESK_CLERK,
    )
    validate_error(reused_hin, ApiErrorId.ERR_DUPLICATE_HIN, 409)

    _, meta = validate_paginated(
        api.list_boat_units(DEAL_DESK_CLERK, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 1, (
        f"both rejections left the inventory untouched; got {meta['total_count']}"
    )


# --- entities/point_event_appended_rows_are_immutable ----------------------

def test_point_events_carry_a_monotone_server_assigned_sequence(api):
    """PRD §3.8: "Each event also carries a server-assigned `created_seq`
    monotone sequence number, which exists solely so that two events sharing a
    `created_at` can still be replayed in a deterministic order."

    Design: Corner/entities/point_event_appended_rows_are_immutable
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_im@x.com",
                           full_name="Iris Mott")
    first = create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                               points_delta=100)
    second = create_point_event(api, store["id"], member["id"], event_kind="AWARD",
                                points_delta=100)

    assert isinstance(first["created_seq"], int)
    assert second["created_seq"] > first["created_seq"], (
        "created_seq is a monotone server-assigned sequence; got "
        f"{first['created_seq']} then {second['created_seq']}"
    )
    assert first["points_delta"] == 100
    assert first["event_kind"] == "AWARD"
    assert first["id"] != second["id"]

    read_back = get_success_data(
        api.get_point_event(first["id"], CLUB_CARD_SPECIALIST), 200
    )
    assert read_back["points_delta"] == 100, (
        "the appended row keeps the delta it was written with"
    )
    assert read_back["created_seq"] == first["created_seq"]


# --- entities/attraction_session_requires_existing_attraction --------------

def test_a_session_naming_an_unknown_venue_and_a_foreign_venue_fails_two_ways(api):
    """PRD §2.6: "A reference to a missing attraction, member, waiver, boat unit,
    appraisal, title filing, boat deal, permit sale, remit batch, club card
    application, point event, service order, service intake, event offering,
    event registration, bay booking or order fulfilment fails with
    `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."
    PRD §2.6: "A session cancelled by naming a `session_id` whose `attraction_id`
    resolves to a venue belonging to a different store is rejected with
    `ERR_PARENT_MISMATCH` (HTTP 404), not with a permission error and not with a
    not-found error for the child itself."

    Design: Corner/entities/attraction_session_requires_existing_attraction
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    first_store = create_store(api)
    second_store = create_store(api, name="Delta Landing", state_code="AR",
                                dealer_license_no="AR-DLR-1180",
                                dwell_capacity_minutes=45000, load_bays_total=2)
    member = create_member(api, first_store["id"], email="m_pr@x.com",
                           full_name="Pax Rill")
    foreign_venue = create_open_attraction(api, second_store["id"],
                                           attraction_type="AQUARIUM",
                                           capacity_units=20, dwell_cost_minutes=30)

    unknown = request_session(api, first_store["id"], NON_EXISTENT_UUID,
                              member["id"], party_size=2)
    validate_error(unknown, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)

    mismatched = request_session(api, first_store["id"], foreign_venue["id"],
                                 member["id"], party_size=2)
    validate_error(mismatched, ApiErrorId.ERR_PARENT_MISMATCH, 404)

    _, meta = validate_paginated(
        api.list_sessions(ATTRACTION_HOST, params={"store_id": first_store["id"]})
    )
    assert meta["total_count"] == 0, (
        f"neither rejection created a session row; got {meta['total_count']}"
    )