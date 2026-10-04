"""Wall bins: loading, fullness ladder, restocking, rotation and element curation."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_element,
    api_client,
    assert_element,
    assert_store,
    assert_wall_bin,
    load_bin,
    open_store,
    reset_clock,
    setup_store_with_wall,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_bin_creation_derives_status_and_fill_from_declared_mass(api):
    """PRD §3.1: "Every time a bin's mass changes, its fullness is recomputed:
    `fill_pct` is the bin's mass multiplied by one hundred and divided by its
    capacity, rounded half up to one decimal place."
    PRD §3.1: "Below fifteen percent the bin is `EMPTY`; at fifteen percent or
    above but below fifty percent it is `LOW`; at fifty percent or above it is
    `OPEN`."
    PRD §3.1: "Each bin also carries a trailing observed depletion figure,
    `depletion_rate_pct_per_day`, derived from the cups settled against that bin
    over the previous seven days"

    Design: Corner/entities/wall_bin_creation_derives_status_from_declared_mass
    """
    reset_clock()
    store = open_store()
    element = add_element()

    full = validate_success(api.create_wall_bin(
        {"store_id": store["id"], "element_id": element["id"], "bin_label": "A01",
         "bin_capacity_grams": 1000, "bin_mass_grams": 1000},
        TEST_USERS["associate_headers"]), 201)
    assert_wall_bin(full)
    assert full["status"] == "OPEN", f"1000 g of 1000 g must read OPEN, got {full['status']}"
    assert full["fill_pct"] == pytest.approx(100.0), f"expected 100.0 %, got {full['fill_pct']}"

    low = validate_success(api.create_wall_bin(
        {"store_id": store["id"], "element_id": element["id"], "bin_label": "A02",
         "bin_capacity_grams": 1000, "bin_mass_grams": 400},
        TEST_USERS["associate_headers"]), 201)
    assert low["status"] == "LOW", f"400 g of 1000 g must read LOW, got {low['status']}"
    assert low["fill_pct"] == pytest.approx(40.0), f"expected 40.0 %, got {low['fill_pct']}"
    assert low["depletion_rate_pct_per_day"] == 0


def test_element_read_with_unknown_id_is_not_found(api):
    """PRD §2.4: "Third, existence: every referenced identifier must resolve,
    and where several appear in one path they are resolved from left to right so
    that only the first unresolvable one is reported, as `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/element_not_found_on_read
    """
    res = api.get_element(NON_EXISTENT_UUID, TEST_USERS["admin_headers"])
    error = validate_error(res, "ERR_NOT_FOUND")
    assert error["message"].strip(), "the not-found error must carry a message"


def test_new_element_starts_pending_catalog_under_current_production(api):
    """PRD §3.1: "A newly registered element enters `PENDING_CATALOG` under
    `CURRENT_PRODUCTION` sourcing."

    Design: Corner/entities/element_status_enum_rejects_an_unknown_value
    """
    reset_clock()
    element = add_element(element_code="4301", element_name="Tile 2x2",
                          unit_mass_grams=1.0, cost_basis_cents=4)
    assert_element(element)
    assert element["status"] == "PENDING_CATALOG", (
        f"a fresh element must read PENDING_CATALOG, got {element['status']}")
    assert element["sourcing_mode"] == "CURRENT_PRODUCTION", (
        f"a fresh element must read CURRENT_PRODUCTION, got {element['sourcing_mode']}")


def test_bin_load_against_unknown_store_is_not_found(api):
    """PRD §2.10: "The same left-to-right discipline applies to identifiers
    supplied in a request body: a payload naming several resources is resolved
    in the order they are stated, and the first unresolvable one is the one
    reported."
    PRD §2.4: "First, authentication: missing or unrecognised credentials
    produce `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/entities/wall_bin_creation_requires_an_existing_store
    """
    reset_clock()
    store = open_store()
    element = add_element()

    res = api.create_wall_bin(
        {"store_id": NON_EXISTENT_UUID, "element_id": element["id"],
         "bin_label": "B01", "bin_capacity_grams": 1000, "bin_mass_grams": 500},
        TEST_USERS["associate_headers"])
    validate_error(res, "ERR_NOT_FOUND")

    data, meta = validate_paginated(
        api.list_wall_bins(TEST_USERS["associate_headers"],
                           params={"store_id": store["id"]}))
    assert meta["total_count"] == 0, "a rejected bin load must not create a bin"
    assert data == []


def test_bin_restock_applies_capacity_ceiling(api):
    """PRD §3.1: "Restocking a single bin from the surplus drawer adds mass to
    it. The addition, given as `add_grams`, must be a positive number of grams,
    and the resulting mass may not exceed the bin's capacity — an overfill is
    refused as `ERR_CONSTRAINT_VIOLATION` rather than clamped."

    Design: Corner/calculations/bin_restock_only_accepts_what_fits_and_leaves_status_above_the_edge
    """
    store, element, _member, bin_row = setup_store_with_wall(
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 200})

    restocked = validate_success(api.restock_wall_bin(
        bin_row["id"], {"add_grams": 700}, TEST_USERS["associate_headers"]), 200)
    assert restocked["bin_mass_grams"] == 900
    assert restocked["fill_pct"] == pytest.approx(90.0)
    assert restocked["status"] == "OPEN", (
        "90 % is at or above the fifty percent floor, so the bin reads OPEN")

    overflow = api.restock_wall_bin(bin_row["id"], {"add_grams": 700},
                                    TEST_USERS["associate_headers"])
    validate_error(overflow, "ERR_CONSTRAINT_VIOLATION")

    reread = validate_success(api.get_wall_bin(bin_row["id"],
                                               TEST_USERS["associate_headers"]), 200)
    assert reread["bin_mass_grams"] == 900, "the refused overfill must not be clamped in"


def test_bin_list_intersects_store_and_status_filters(api):
    """PRD §2.3: "The pagination fields surfaced in the `meta` object of the
    envelope are `limit`, `offset`, `total_count` and `has_more`; they are
    present for list responses and absent from single-resource responses."

    Design: Corner/cross_cutting_complexity_layers/bin_list_filter_combines_store_and_status
    """
    reset_clock()
    store = open_store()
    other_store = open_store()
    element = add_element(element_code="7001")

    stocked = load_bin(store["id"], element["id"], bin_label="AD01",
                       bin_capacity_grams=1000, bin_mass_grams=600)
    empty = load_bin(store["id"], element["id"], bin_label="AD02",
                     bin_capacity_grams=1000, bin_mass_grams=0)
    foreign = load_bin(other_store["id"], element["id"], bin_label="AD03",
                       bin_capacity_grams=1000, bin_mass_grams=600)
    assert stocked["status"] == "OPEN" and empty["status"] == "EMPTY"

    data, meta = validate_paginated(api.list_wall_bins(
        TEST_USERS["associate_headers"],
        params={"store_id": store["id"], "status": "EMPTY", "limit": 10, "offset": 0}))
    assert meta["total_count"] == 1, "store and status must intersect"
    assert meta["has_more"] is False
    assert [row["id"] for row in data] == [empty["id"]]
    assert foreign["id"] not in [row["id"] for row in data]

    data, meta = validate_paginated(api.list_wall_bins(
        TEST_USERS["associate_headers"], params={"store_id": store["id"]}))
    assert meta["total_count"] == 2


def test_rotation_with_no_candidates_is_a_no_op(api):
    """PRD §3.1: "If no candidate qualifies, the call succeeds with an empty
    array and changes nothing; an empty rotation plan is not an error."

    Design: Corner/calculations/rotation_with_no_candidates_is_a_no_op_not_an_error
    """
    store, element, _member, bin_row = setup_store_with_wall(
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 800})

    res = api.rotate_wall_bins({"store_id": store["id"], "bin_ids": [bin_row["id"]]},
                               TEST_USERS["associate_headers"])
    data = validate_success(res, 200)
    assert isinstance(data, list) and data == [], (
        "a rotation with no candidate must return an empty array")

    reread = validate_success(api.get_wall_bin(bin_row["id"],
                                               TEST_USERS["associate_headers"]), 200)
    assert reread["status"] == "OPEN"
    assert reread["bin_mass_grams"] == 800, "an empty rotation plan changes nothing"
    assert reread["last_restock_index"] == 0


def test_rotation_retires_the_fullest_open_bin_and_hands_over_its_element(api):
    """PRD §3.1: "When there is a restock set, the same number of `OPEN` bins
    are retired to make room. Those are chosen from the retained bins — the
    store's `OPEN` bins — sorted with the fullest first and, among equals, the
    oldest first, and the first as many as the restock set's size become
    `RETIRED`. Each retiring bin hands its element to the corresponding position
    in the restock set, so the wall's assortment shifts along rather than
    emptying out."

    Design: Corner/cross_cutting_complexity_layers/rotation_prefers_empty_bins_and_retires_the_fullest
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element_a = add_element(element_code="7201", element_name="Brick 2x4")
    element_b = add_element(element_code="7202", element_name="Brick 2x6")

    empty_bin = load_bin(store["id"], element_a["id"], bin_label="AF01",
                         bin_capacity_grams=1000, bin_mass_grams=0)
    full_bin = load_bin(store["id"], element_b["id"], bin_label="AF02",
                        bin_capacity_grams=1000, bin_mass_grams=900)
    assert empty_bin["status"] == "EMPTY" and full_bin["status"] == "OPEN"

    res = api.rotate_wall_bins(
        {"store_id": store["id"], "bin_ids": [empty_bin["id"], full_bin["id"]]},
        TEST_USERS["associate_headers"])
    validate_success(res, 200)

    retired = validate_success(api.get_wall_bin(full_bin["id"],
                                                TEST_USERS["associate_headers"]), 200)
    assert retired["status"] == "RETIRED", (
        "the only OPEN bin in the store must be retired to make room")

    restocked = validate_success(api.get_wall_bin(empty_bin["id"],
                                                  TEST_USERS["associate_headers"]), 200)
    assert restocked["element_id"] == element_b["id"], (
        "the restocked bin takes the element released by the retired bin")
    assert restocked["element_id"] != element_a["id"]


def test_store_creation_returns_derived_defaults_and_starts_trading(api):
    """PRD §2.5: "A newly opened store begins in `TRADING`."
    PRD §2.5: "On opening, the store's engine mass and shrink ratio both read
    zero and its run index is unset."
    PRD §4: "Operations that create a new stand-alone resource, or that add a
    distinct new row to a collection, return `201 Created`."

    Design: Corner/entities/store_creation_returns_derived_fields_and_starts_trading
    """
    reset_clock()
    res = api.create_store(
        {"store_code": "LEGO-0201", "display_name": "Brick Yard One",
         "wall_bin_capacity_grams": 1000, "event_capacity_units": 40,
         "checklist_required": True},
        TEST_USERS["admin_headers"])
    store = validate_success(res, 201)
    assert_store(store)

    assert store["stage"] == "TRADING", f"a new store starts TRADING, got {store['stage']}"
    assert store["bin_engine_mass_grams"] == 0
    assert store["shrinkage_basis_points"] == 0
    assert store["last_event_run_index"] == 0
    assert store["id"] and store["created_at"] and store["updated_at"]


def test_element_reissue_returns_a_surplus_element_to_the_wall(api):
    """PRD §3.1: "An element that passes both tests moves to
    `RETIRED_TO_ARCHIVE` and its sourcing flips to `SURPLUS`. From the archive,
    an element may be brought forward again: naming it on a surplus restock
    requisition moves it to `CATALOG` with `SURPLUS` sourcing automatically, and
    an explicit reissue moves it back to `ACTIVE` with `CURRENT_PRODUCTION`
    sourcing."

    Design: Corner/endpoints/element_reissue_returns_an_archived_element_to_the_wall
    """
    reset_clock()
    open_store()
    element = add_element(element_code="5801", element_name="Wedge 4x2",
                          theme="Technic", cost_basis_cents=4)
    version_at_creation = element["version"]

    retired = validate_success(api.retire_element(
        element["id"], {"expected_element_version": element["version"]},
        TEST_USERS["associate_headers"]), 200)
    assert retired["status"] == "RETIRED_TO_ARCHIVE"
    assert retired["sourcing_mode"] == "SURPLUS"

    reissued = validate_success(api.reissue_element(element["id"],
                                                    TEST_USERS["associate_headers"]), 200)
    assert reissued["status"] == "ACTIVE"
    assert reissued["sourcing_mode"] == "CURRENT_PRODUCTION", (
        "reissue rewrites the sourcing mode back to current production")
    assert reissued["version"] == version_at_creation + 2, (
        "retire and reissue are two modifications, so the version moves twice")


def test_retire_is_refused_while_a_bin_holds_the_element(api):
    """PRD §3.1: "A retirement attempt must carry `expected_element_version`,
    may only target an `ACTIVE` element, and is refused with
    `ERR_ELEMENT_BIN_OCCUPIED` while any bin in any store still holds mass of
    that element; it is likewise refused while a `PENDING` cup is priced per
    piece against that element."

    Design: Corner/endpoints/retiring_a_loaded_element_is_refused_until_its_bin_is_emptied
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="5701", element_name="Brick 1x4",
                          cost_basis_cents=4)
    load_bin(store["id"], element["id"], bin_label="R01",
             bin_capacity_grams=1000, bin_mass_grams=600)

    res = api.retire_element(element["id"],
                             {"expected_element_version": element["version"]},
                             TEST_USERS["associate_headers"])
    validate_error(res, "ERR_ELEMENT_BIN_OCCUPIED")

    reread = validate_success(api.get_element(element["id"],
                                              TEST_USERS["associate_headers"]), 200)
    assert reread["status"] == "ACTIVE"
    assert reread["sourcing_mode"] == "CURRENT_PRODUCTION"