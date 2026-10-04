"""Registration, dormitory beds, client records and the bed-capacity ceiling."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_instant_equals,
    create_client,
    create_region,
    create_shelter_site,
    register_client,
    set_clock,
    setup_open_shelter,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_bed_capacity_accepts_exactly_the_last_bed(api):
    """PRD §3.2: "Capacity is checked separately from posture: if the shelter's
    `occupied_beds` plus one would exceed the site's `capacity_verified_beds`, the
    registration is refused with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bed_capacity_exact_boundary_crossing
    """
    bundle = setup_open_shelter(capacity_beds=2)
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=5)
    second = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=2)

    reg1 = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": first["id"], "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager), 201)
    assert reg1["dormitory_bed_code"] == "B-001"

    reg2 = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": second["id"], "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager), 201)
    assert reg2["dormitory_bed_code"] == "B-002"
    assert reg2["status"] == "REGISTERED"

    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert shelter["occupied_beds"] == 2


def test_bed_capacity_rejects_the_bed_past_the_boundary(api):
    """PRD §3.2: "if the shelter's `occupied_beds` plus one would exceed the site's
    `capacity_verified_beds`, the registration is refused with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/bed_capacity_exact_boundary_crossing
    """
    bundle = setup_open_shelter(capacity_beds=2)
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=5)
    second = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=2)
    third = create_client(bundle["region_id"], full_name="Cleo Marsh", household_size=1)

    register_client(bundle["shelter_id"], first["id"], manager)
    register_client(bundle["shelter_id"], second["id"], manager)

    resp = api.register_client(
        bundle["shelter_id"],
        {"client_id": third["id"], "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert shelter["occupied_beds"] == 2


def test_bed_selector_assigns_the_lowest_unused_code(api):
    """PRD §3.2: "The eligible beds are ranked by how many times each code has ever been
    assigned in this shelter — counting registrations in any status — ascending, with the bed
    code itself as the tie-breaker ascending, so the least-used bed wins and ties resolve to
    the lowest code."

    Design: Corner/entities/shelter_registration_bed_selector_lowest_code
    """
    bundle = setup_open_shelter(capacity_beds=2)
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=2)
    second = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=1)

    reg1 = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": first["id"], "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager), 201)
    assert reg1["dormitory_bed_code"] == "B-001"

    reg2 = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": second["id"], "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager), 201)
    assert reg2["dormitory_bed_code"] == "B-002"


def test_bed_turnover_buffer_rejects_an_occupancy_inside_the_window(api):
    """PRD §3.2: "A registration that specifies a `requested_bed_code` may also be refused with
    `ERR_BED_OCCUPANCY_CONFLICT` if that bed is held by a `REGISTERED` occupant or if its
    previous occupancy ended within the 120-minute turnover buffer before the requested
    `occupied_from_at`."

    Design: Difficulty/resource_temporal_overlap/dormitory_bed_turnover_buffer_rejects_adjacency
    """
    bundle = setup_open_shelter(capacity_beds=1)
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=2)
    second = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=1)

    reg1 = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": first["id"], "requested_bed_code": "B-001",
         "occupied_from_at": "2026-09-03T00:00:00Z", "functional_needs_flag": False},
        manager), 201)

    set_clock("2026-09-04T00:00:00Z")
    checked_out = validate_success(
        api.check_out_registration(reg1["id"], {}, manager))
    assert_instant_equals(checked_out["occupied_until_at"], "2026-09-04T00:00:00Z")

    resp = api.register_client(
        bundle["shelter_id"],
        {"client_id": second["id"], "requested_bed_code": "B-001",
         "occupied_from_at": "2026-09-04T00:30:00Z", "functional_needs_flag": False},
        manager)
    validate_error(resp, ApiErrorId.ERR_BED_OCCUPANCY_CONFLICT)


def test_bed_turnover_buffer_allows_an_occupancy_outside_the_window(api):
    """PRD §3.2: "its previous occupancy ended within the 120-minute turnover buffer before the
    requested `occupied_from_at`" — an occupancy starting outside that window is eligible.

    PRD §3.2: "The buffer exists so that a bed can be cleaned between clients."

    Design: Difficulty/resource_temporal_overlap/dormitory_bed_turnover_buffer_rejects_adjacency
    """
    bundle = setup_open_shelter(capacity_beds=1)
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=2)
    third = create_client(bundle["region_id"], full_name="Cleo Marsh", household_size=3)

    reg1 = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": first["id"], "requested_bed_code": "B-001",
         "occupied_from_at": "2026-09-03T00:00:00Z", "functional_needs_flag": False},
        manager), 201)

    set_clock("2026-09-04T00:00:00Z")
    validate_success(api.check_out_registration(reg1["id"], {}, manager))

    reg3 = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": third["id"], "requested_bed_code": "B-001",
         "occupied_from_at": "2026-09-04T04:00:00Z", "functional_needs_flag": False},
        manager), 201)
    assert reg3["status"] == "REGISTERED"
    assert reg3["dormitory_bed_code"] == "B-001"


def test_occupied_beds_returns_to_its_pre_registration_value(api):
    """PRD §3.2: "Both paths stamp `occupied_until_at`, recompute `occupied_beds`,
    `registered_client_count` and `reunification_pending_count`."

    PRD §3.2: "`occupied_beds` counts registrations in `REGISTERED` status that hold a non-null
    `dormitory_bed_code`."

    Design: Difficulty/compensating_invariant/shelter_occupied_beds_conserved
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]
    client = create_client(bundle["region_id"])

    before = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert before["occupied_beds"] == 0

    registration = register_client(bundle["shelter_id"], client["id"], manager)

    during = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert during["occupied_beds"] == 1

    checked_out = validate_success(
        api.check_out_registration(registration["id"], {}, manager))
    assert checked_out["status"] == "CHECKED_OUT"

    after = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert after["occupied_beds"] == 0, "the bed must be conserved back to its prior value"


def test_every_departure_gives_its_bed_back(api):
    """PRD §3.2: "`occupied_beds` counts registrations in `REGISTERED` status that hold a
    non-null `dormitory_bed_code`."

    PRD §3.2: "Both paths stamp `occupied_until_at`, recompute `occupied_beds`,
    `registered_client_count` and `reunification_pending_count`."

    Design: Difficulty/compensating_invariant/shelter_occupied_beds_conserved
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=2)
    second = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=1)
    reg1 = register_client(bundle["shelter_id"], first["id"], manager)
    reg2 = register_client(bundle["shelter_id"], second["id"], manager)

    both = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert both["occupied_beds"] == 2
    assert both["occupied_beds"] <= both["registered_client_count"]

    validate_success(api.check_out_registration(reg1["id"], {}, manager))
    one = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert one["occupied_beds"] == 1

    validate_success(api.check_out_registration(reg2["id"], {}, manager))
    none = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert none["occupied_beds"] == 0, "every bed is returned when its occupant leaves"


def test_checked_out_registration_leaves_the_occupancy_aggregate(api):
    """PRD §3.2: "`occupied_beds` counts registrations in `REGISTERED` status that hold a
    non-null `dormitory_bed_code`."

    Design: Corner/calculations/occupied_beds_excludes_checked_out_registrations
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    first = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=2)
    second = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=1)

    reg1 = register_client(bundle["shelter_id"], first["id"], manager)
    register_client(bundle["shelter_id"], second["id"], manager)

    two = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert two["occupied_beds"] == 2
    assert two["registered_client_count"] == 2

    validate_success(api.check_out_registration(reg1["id"], {}, manager))

    one = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert one["occupied_beds"] == 1

    retained = validate_success(api.get_registration(reg1["id"], manager))
    assert retained["status"] == "CHECKED_OUT", "the row itself is retained"


def test_registration_requires_a_known_client(api):
    """PRD §2.11: "The catalogue of existence failures is `ERR_REGION_NOT_FOUND`,
    `ERR_OPERATION_NOT_FOUND`, `ERR_SHELTER_SITE_NOT_FOUND`, `ERR_SHELTER_OPERATION_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_FUND_POOL_NOT_FOUND` and
    `ERR_BLOOD_DRIVE_NOT_FOUND`, all at HTTP status 404."

    Design: Corner/entities/shelter_registration_requires_known_client
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    resp = api.register_client(
        bundle["shelter_id"],
        {"client_id": NON_EXISTENT_UUID, "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager)
    validate_error(resp, ApiErrorId.ERR_CLIENT_NOT_FOUND)

    shelter = validate_success(api.get_shelter_operation(bundle["shelter_id"], manager))
    assert shelter["occupied_beds"] == 0


def test_registration_requires_a_known_shelter_operation(api):
    """PRD §2.11: "When a request path names more than one resource, the identifiers are
    resolved from left to right along the path, and the first one that does not correspond to
    an existing resource determines the response."

    Design: Corner/entities/registration_requires_known_shelter_operation
    """
    bundle = setup_open_shelter()
    manager = bundle["manager_headers"]

    resp = api.register_client(
        NON_EXISTENT_UUID,
        {"client_id": NON_EXISTENT_UUID, "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager)
    validate_error(resp, ApiErrorId.ERR_SHELTER_OPERATION_NOT_FOUND)


def test_functional_needs_registration_requires_a_supporting_site(api):
    """PRD §2.5: "A registration whose `functional_needs_flag` is true may only target a site
    whose `functional_needs_support` is true; when it does not, the registration is refused
    with `ERR_FUNCTIONAL_NEEDS_UNSUPPORTED` at HTTP status 409."

    Design: Corner/validations/functional_needs_registration_requires_supporting_site
    """
    bundle = setup_open_shelter(functional_needs_support=False)
    manager = bundle["manager_headers"]

    plain = create_client(bundle["region_id"], full_name="Ana Lopez", household_size=2)
    needs = create_client(bundle["region_id"], full_name="Ben Okafor", household_size=2)

    accepted = validate_success(api.register_client(
        bundle["shelter_id"],
        {"client_id": plain["id"], "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": False},
        manager), 201)
    assert accepted["status"] == "REGISTERED"

    resp = api.register_client(
        bundle["shelter_id"],
        {"client_id": needs["id"], "occupied_from_at": "2026-09-03T20:00:00Z",
         "functional_needs_flag": True},
        manager)
    validate_error(resp, ApiErrorId.ERR_FUNCTIONAL_NEEDS_UNSUPPORTED)


def test_client_without_a_head_of_household_has_no_primary_client(api):
    """PRD §3.2: "The linkage is optional: an unaccompanied client is a valid record with no
    `primary_client_id`."

    Design: Corner/entities/client_defaults_primary_client_null
    """
    bundle = setup_open_shelter()
    created = validate_success(api.create_client(
        {"full_name": "Ana Lopez", "household_size": 4, "region_id": bundle["region_id"]},
        bundle["caseworker_headers"]), 201)
    assert created.get("primary_client_id") is None
    assert created["household_size"] == 4

    read = validate_success(
        api.get_client(created["id"], bundle["caseworker_headers"]))
    assert read.get("primary_client_id") is None
    assert read["household_size"] == 4


def test_household_members_are_reachable_in_reverse(api):
    """PRD §3.2: "an optional `primary_client_id` pointing at the head-of-household record this
    one is attached to, which is how a family group is expressed."

    PRD §4: "List clients filtered by region or head-of-household link"

    Design: Corner/entities/client_household_members_reverse_lookup
    """
    bundle = setup_open_shelter()
    caseworker = bundle["caseworker_headers"]
    region_id = bundle["region_id"]

    head = validate_success(api.create_client(
        {"full_name": "Ana Lopez", "household_size": 4, "region_id": region_id}, caseworker), 201)
    member1 = validate_success(api.create_client(
        {"full_name": "Luis Lopez", "household_size": 1, "region_id": region_id,
         "primary_client_id": head["id"]}, caseworker), 201)
    member2 = validate_success(api.create_client(
        {"full_name": "Mia Lopez", "household_size": 1, "region_id": region_id,
         "primary_client_id": head["id"]}, caseworker), 201)

    resp = api.list_clients(caseworker, params={"primary_client_id": head["id"]})
    data, _meta = validate_paginated(resp)
    ids = [row["id"] for row in data]
    assert sorted(ids) == sorted([member1["id"], member2["id"]])
    assert head["id"] not in ids, "the head of household is not a member of itself"


def test_region_read_of_an_unknown_id_is_not_found(api, admin_headers):
    """PRD §2.11: "The catalogue of existence failures is `ERR_REGION_NOT_FOUND`,
    `ERR_OPERATION_NOT_FOUND`, `ERR_SHELTER_SITE_NOT_FOUND`, `ERR_SHELTER_OPERATION_NOT_FOUND`,
    `ERR_VOLUNTEER_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_CLIENT_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`, `ERR_FUND_POOL_NOT_FOUND` and
    `ERR_BLOOD_DRIVE_NOT_FOUND`, all at HTTP status 404."

    Design: Corner/entities/region_not_found_returns_404
    """
    resp = api.get_region(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_REGION_NOT_FOUND)


def test_shelter_site_listing_honours_offset_paging(api, coordinator_headers):
    """PRD §2.3: "The `offset` query parameter states how many items to skip and defaults to 0
    when omitted."

    PRD §2.3: "Paged responses carry four additional fields inside the `meta` object of the
    response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/shelter_site_pagination_second_page
    """
    headers = coordinator_headers
    region = create_region()
    site_a = create_shelter_site(region["id"], facility_name="Lincoln High")
    site_b = create_shelter_site(
        region["id"], facility_name="Roosevelt Gym", address_line="2 Oak St",
        capacity_beds=12, accessibility_rating="PARTIAL", functional_needs_support=False)

    page0, meta0 = validate_paginated(
        api.list_region_shelter_sites(region["id"], headers, params={"limit": 1, "offset": 0}))
    page1, meta1 = validate_paginated(
        api.list_region_shelter_sites(region["id"], headers, params={"limit": 1, "offset": 1}))

    assert len(page0) == 1 and len(page1) == 1
    assert page0[0]["id"] != page1[0]["id"]
    assert {page0[0]["id"], page1[0]["id"]} == {site_a["id"], site_b["id"]}
    assert meta0["total_count"] == 2
    assert meta0["has_more"] is True
