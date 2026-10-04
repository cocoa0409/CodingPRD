"""Resource identity: creation defaults, listing and append-only resources."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_element,
    add_member,
    api_client,
    assert_fusion_allocation,
    assert_member,
    draw_from_bin,
    load_bin,
    open_cup,
    open_store,
    reset_clock,
    setup_store_with_wall,
    stored_instant,
    validate_paginated,
    validate_success,
)


def test_member_creation_applies_tier_and_balance_defaults(api):
    """PRD §3.3: "A new member begins `ACTIVE`, at the `STANDARD` tier, with a
    zero `points_balance` and no event passes to their name."
    PRD §2.7: "`version` (integer): a system-managed counter that increases by
    one on every modification"

    Design: Corner/entities/member_creation_applies_tier_and_balance_defaults
    """
    reset_clock()
    store = open_store()
    res = api.create_member(
        {"email": "m_default@example.com", "display_name": "Default Member",
         "home_store_id": store["id"]},
        TEST_USERS["admin_headers"])
    member = validate_success(res, 201)
    assert_member(member)

    assert member["tier"] == "STANDARD", f"expected STANDARD, got {member['tier']}"
    assert member["stage"] == "ACTIVE", f"expected ACTIVE, got {member['stage']}"
    assert member["points_balance"] == 0
    assert member["passed_mb_reservations"] == 0
    assert member["version"] == 1, "the first version of a resource is 1"


def test_element_listing_paginates_with_total_count(api):
    """PRD §2.3: "List endpoints accept two query parameters. `limit` caps how
    many items are returned: it defaults to 10, must be at least 1 and at most
    100. `offset` states how many items to skip and defaults to 0."
    PRD §2.3: "The pagination fields surfaced in the `meta` object of the
    envelope are `limit`, `offset`, `total_count` and `has_more`"

    Design: Corner/entities/element_listing_paginates_with_total_count
    """
    reset_clock()
    for code, name, theme in (("4101", "Brick 1x1", "Town"),
                              ("4102", "Brick 1x2", "Town"),
                              ("4103", "Brick 1x3", "Icons")):
        add_element(element_code=code, element_name=name, theme=theme)

    data, meta = validate_paginated(api.list_elements(
        TEST_USERS["admin_headers"], params={"limit": 2, "offset": 0}))
    assert len(data) == 2, f"limit 2 must return 2 rows, got {len(data)}"
    assert meta["total_count"] == 3, (
        "total_count reports the whole filtered set, not the returned page")
    assert meta["has_more"] is True
    first_page_first_id = data[0]["id"]

    data, meta = validate_paginated(api.list_elements(
        TEST_USERS["admin_headers"], params={"limit": 2, "offset": 2}))
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert data[0]["id"] != first_page_first_id, "offset 2 must skip the first page"


def test_missing_element_required_field_is_rejected(api):
    """PRD §3.1: "Elements are registered by head office with an `element_code`
    that is unique across the catalogue, an `element_name`, an owning `theme`,
    the `unit_mass_grams` of one piece and a wholesale `cost_basis_cents`; the
    mass of a single element must be greater than zero and the cost basis may be
    zero but never negative."
    PRD §2.2: "All error API responses (4xx status codes) follow this standard
    envelope format in their JSON body"

    Design: Corner/entities/missing_element_required_field_is_rejected
    """
    reset_clock()
    res = api.create_element(
        {"element_code": "4201", "element_name": "Brick 2x2", "theme": "Town",
         "unit_mass_grams": 1.8},
        TEST_USERS["admin_headers"])

    if res.status_code < 400:
        raise AssertionError(
            "a registration missing cost_basis_cents must be refused, but it "
            f"succeeded: HTTP {res.status_code} {res.text}")
    body = res.json()
    assert body.get("response_type") == "error", "the refusal must use the error envelope"
    assert isinstance(body["data"]["error_id"], str) and body["data"]["error_id"]

    _data, meta = validate_paginated(api.list_elements(
        TEST_USERS["admin_headers"], params={"theme": "Town"}))
    assert meta["total_count"] == 0, "the refused registration must not create an element"


def test_bin_draws_are_append_only_and_visible_from_the_cup(api):
    """PRD §2.7: "A `FusionAllocation` — one bin draw recorded against a cup —
    and a `LoyaltyLedger` entry — one signed points movement recorded against a
    member — carry only `id` and `created_at`. Neither has an `updated_at` and
    neither has a `version`, because neither is ever modified after it is
    written. Callers must not expect either field on those two resources, and no
    endpoint takes a version field for them."
    PRD §3.2: "A successful draw subtracts from the bin, recomputes the bin's
    status from its new fullness, and re-derives the store's engine mass and
    posture."

    Design: Corner/entities/fusion_allocation_is_immutable
    """
    store, element, member, bin_row = setup_store_with_wall(
        store_overrides={"wall_bin_capacity_grams": 1000},
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 1000},
    )
    order = open_cup(store["id"], member["id"], cup_size="LARGE",
                     pricing_model="CUP_FILL", declared_mass_grams=400)
    draw_from_bin(order["id"], bin_row["id"], 400)

    data, _meta = validate_paginated(api.list_order_allocations(
        order["id"], TEST_USERS["associate_headers"]))
    assert len(data) == 1, f"exactly one draw was recorded, got {len(data)}"
    assert data[0]["allocation_grams"] == 400
    assert data[0]["fusion_order_id"] == order["id"]
    assert data[0]["wall_bin_id"] == bin_row["id"]
    assert "version" not in data[0], "a bin draw must not carry a version"
    assert "updated_at" not in data[0], "a bin draw must not carry an updated_at"

    reread = validate_success(api.get_wall_bin(bin_row["id"],
                                               TEST_USERS["associate_headers"]), 200)
    assert reread["bin_mass_grams"] == 600, (
        "the draw must have subtracted 400 g from a 1000 g bin")


def test_member_and_bin_reads_resolve_children_from_a_parent_id(api):
    """PRD §2.3: "Unless a subsection below says otherwise, list results are
    ordered by creation timestamp ascending."
    PRD §2.10: "Several paths address a resource through more than one
    identifier — a bin's draws read through the bin, a cup's draws read through
    the cup, a member's ledger read through the member."

    Design: Corner/endpoints/the_member_sub_resource_read_finds_bins_by_store
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="5901")
    first = add_member(store["id"], email="m_x1@example.com",
                       display_name="Cross One")
    add_member(store["id"], email="m_x2@example.com", display_name="Cross Two")
    bin_row = load_bin(store["id"], element["id"], bin_label="S01",
                       bin_capacity_grams=1000, bin_mass_grams=600)

    data, meta = validate_paginated(api.list_members(
        TEST_USERS["associate_headers"], params={"home_store_id": store["id"]}))
    assert meta["total_count"] == 2, "both members belong to this home store"
    ordered = [stored_instant(row["created_at"]) for row in data]
    assert ordered == sorted(ordered), (
        "results are ordered by creation timestamp ascending")

    _data, meta = validate_paginated(api.list_wall_bins(
        TEST_USERS["associate_headers"], params={"store_id": store["id"]}))
    assert meta["total_count"] == 1
    _data, meta = validate_paginated(api.list_wall_bins(
        TEST_USERS["associate_headers"], params={"element_id": element["id"]}))
    assert meta["total_count"] == 1
    _data, meta = validate_paginated(api.list_wall_bins(
        TEST_USERS["associate_headers"],
        params={"store_id": store["id"], "status": "OPEN"}))
    assert meta["total_count"] == 1
    assert bin_row["status"] == "OPEN"