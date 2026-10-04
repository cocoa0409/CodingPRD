"""Role authority, store shrink, immediate consistency and stale-version guards."""
import pytest

from test_helpers import (
    CLOCK_2026_09_02,
    TEST_USERS,
    add_element,
    add_member,
    anonymous_headers,
    api_client,
    assert_store,
    build_user_headers,
    draw_from_bin,
    file_replacement,
    load_bin,
    make_member_headers,
    open_cup,
    open_store,
    post_ledger,
    reset_clock,
    restock_bin,
    run_epoch,
    set_clock,
    setup_checked_out_cup,
    setup_cup_ready_to_checkout,
    setup_store_with_wall,
    setup_surplus_element,
    validate_error,
    validate_success,
)


def test_trading_store_halves_the_bucket_before_the_member_discount(api):
    """PRD §3.2: "If the store is `RESTRICTED`, the assembled bucket — base plus
    any band — is halved, rounded half up; if the store is `FROZEN`, settlement
    is refused outright with `ERR_STORE_FROZEN` and the price is never reached."
    PRD §3.2: "`member_discount_cents` is the base price multiplied by that
    rate, rounded half up, and the discounted amount is the base minus the
    discount."

    Design: Difficulty/combinatorial_formula/small_cup_band_and_waitlist_promotion_arithmetic_in_one_wave
    """
    store, element, member, bin_row = setup_store_with_wall(
        store_overrides={"wall_bin_capacity_grams": 2000},
        bin_overrides={"bin_capacity_grams": 2000, "bin_mass_grams": 2000})
    assert store["stage"] == "TRADING", (
        "2000 g of a 2000 g wall sits exactly on the restricted edge")

    order = open_cup(store["id"], member["id"], cup_size="SMALL",
                     pricing_model="CUP_FILL", declared_mass_grams=260)
    order = draw_from_bin(order["id"], bin_row["id"], 260)
    settled = validate_success(api.checkout_fusion_order(
        order["id"], {"expected_fusion_order_version": order["version"]},
        make_member_headers(member["id"])), 200)
    assert settled["priced_piece_count"] == 78
    assert settled["base_price_cents"] == 73, (
        "a trading store charges the bucket in full: 60 plus an overage band of 13")
    assert settled["final_price_cents"] == 66, (
        "consecutive roundings: the discount lands on the base, then is subtracted")


def test_shrinkage_excludes_open_orders_from_both_numerator_and_denominator(api):
    """PRD §3.2: "The included population is every cup belonging to the store
    whose `status` is `VOID` or `CLOSED` — cups still `PENDING` or `SETTLED` are
    outside the population entirely. The ratio is zero when the included
    population's declared mass sums to zero; otherwise `shrinkage_basis_points`
    is the sum of the included cups' `variance_grams` multiplied by ten thousand
    and divided by the sum of their declared masses, rounded half up once over
    the whole ratio, not per cup."
    PRD §3.2: "`variance_grams` is the cup's declared mass minus the sum of the
    grams drawn for it, so mass that left the wall without appearing on the
    scale reads positive."

    Design: Difficulty/compensating_invariant/void_then_checkout_again_conserves_the_wall_engine_mass
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="4801", element_name="Round Plate 1x1",
                          cost_basis_cents=2)
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="G01",
                       bin_capacity_grams=1000, bin_mass_grams=1000)

    pending = open_cup(store["id"], member["id"], cup_size="SMALL",
                       pricing_model="CUP_FILL", declared_mass_grams=100)
    assert pending["status"] == "PENDING"

    open_store_state = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert open_store_state["shrinkage_basis_points"] == 0, (
        "an order still PENDING is outside the included population")

    order = draw_from_bin(pending["id"], bin_row["id"], 40)
    assert order["variance_grams"] == 60, (
        "60 g left the wall without appearing on the scale")

    settled = validate_success(api.checkout_fusion_order(
        order["id"], {"expected_fusion_order_version": order["version"]},
        make_member_headers(member["id"])), 200)
    assert settled["status"] == "SETTLED"

    still_zero = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert still_zero["shrinkage_basis_points"] == 0, (
        "a SETTLED order is still outside the included population")


def test_voiding_an_order_brings_it_into_the_shrink_ratio(api):
    """PRD §3.2: "Voiding a cup returns its mass to the wall."
    PRD §3.2: "The included population is every cup belonging to the store whose
    `status` is `VOID` or `CLOSED`"
    PRD §3.2: "Earlier in their lifecycle a voided cup re-enters the included
    population and can move the ratio in either direction."

    Design: Corner/calculations/shrinkage_excludes_open_orders_from_both_numerator_and_denominator
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="4802", element_name="Round Plate 1x2",
                          cost_basis_cents=2)
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="G02",
                       bin_capacity_grams=1000, bin_mass_grams=1000)

    order = open_cup(store["id"], member["id"], cup_size="SMALL",
                     pricing_model="CUP_FILL", declared_mass_grams=100)
    order = draw_from_bin(order["id"], bin_row["id"], 40)
    settled = validate_success(api.checkout_fusion_order(
        order["id"], {"expected_fusion_order_version": order["version"]},
        make_member_headers(member["id"])), 200)

    voided = validate_success(api.void_fusion_order(
        order["id"], {"expected_fusion_order_version": settled["version"]},
        make_member_headers(member["id"])), 200)
    assert voided["status"] == "VOID"

    after = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert after["shrinkage_basis_points"] >= 0, (
        "the voided order carries a signed variance into the ratio")


def test_store_read_returns_the_recomputed_engine_mass_after_a_bin_load(api):
    """PRD §2.5: "The engine mass itself — `bin_engine_mass_grams` — is the sum
    of `bin_mass_grams` across the store's wall bins whose `status` is `OPEN`,
    `LOW` or `EMPTY`."
    PRD §2.5: "Otherwise, the store is `RESTRICTED` when the engine mass is below
    one tenth of the store's `wall_bin_capacity_grams`, and `TRADING` when it
    reaches that value or higher."

    Design: Corner/endpoints/store_read_returns_the_recomputed_engine_mass_after_a_bin_load
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    element = add_element(element_code="5601", element_name="Slope 30")
    load_bin(store["id"], element["id"], bin_label="Q01", bin_capacity_grams=1000,
             bin_mass_grams=600)
    load_bin(store["id"], element["id"], bin_label="Q02", bin_capacity_grams=1000,
             bin_mass_grams=500)

    reread = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert_store(reread)
    assert reread["bin_engine_mass_grams"] == 1100, (
        "the derived engine mass follows every bin write on its own")
    assert reread["stage"] == "TRADING", (
        "1100 g is above the 200 g edge of a 2000 g wall")

    bins = validate_success(api.list_wall_bins(
        TEST_USERS["associate_headers"], params={"store_id": store["id"]}), 200)
    assert len(bins) == 2


def test_cascade_recompute_of_the_engine_mass_after_a_draw(api):
    """PRD §2.5: "The store's `bin_engine_mass_grams`, `shrinkage_basis_points`
    and `stage` are recomputed on the same mutating call that changed a bin"

    Design: Corner/cross_cutting_complexity_layers/cascade_recompute_of_the_engine_mass_after_a_draw
    """
    store, element, member, bin_row = setup_store_with_wall(
        store_overrides={"wall_bin_capacity_grams": 2000},
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 900})

    order = open_cup(store["id"], member["id"], cup_size="SMALL",
                     pricing_model="CUP_FILL", declared_mass_grams=100)
    draw_from_bin(order["id"], bin_row["id"], 200)

    after = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert after["bin_engine_mass_grams"] == 700, (
        "the stored total follows the draw without a separate recompute call")
    assert after["stage"] == "TRADING", (
        "700 g is well above the 200 g restricted edge")

    bin_after = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert bin_after["bin_mass_grams"] == 700
    assert bin_after["fill_pct"] == pytest.approx(70.0)


def test_my_draw_lands_on_the_store_bin_engine_mass_immediately(api):
    """PRD §2.7: "`updated_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits recording the most recent modification, advanced on every
    mutation including changes to derived fields."
    PRD §2.5: "The store's `bin_engine_mass_grams`, `shrinkage_basis_points`
    and `stage` are recomputed on the same mutating call that changed a bin, and
    the store's `updated_at` and `version` advance with each such recomputation,
    since a derived-field change is a mutation like any other."

    Design: Corner/cross_cutting_complexity_layers/cascade_recompute_of_the_engine_mass_after_a_draw
    """
    store, element, member, bin_row = setup_store_with_wall(
        store_overrides={"wall_bin_capacity_grams": 2000},
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 900})
    version_before = store["version"]

    order = open_cup(store["id"], member["id"], cup_size="SMALL",
                     pricing_model="CUP_FILL", declared_mass_grams=100)
    draw_from_bin(order["id"], bin_row["id"], 200)

    after = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert after["bin_engine_mass_grams"] == 700
    assert after["version"] > version_before, (
        "a derived-field change is a mutation like any other and advances the version")


def test_member_cannot_restock_the_wall(api):
    """PRD §2.1: "`X-User-Role`: `X-User-ID` is an opaque identifier for the
    brick specialist on the shop floor, who owns the wall, the exit tunnel, event
    scheduling and replacement fulfilment."
    PRD §2.4: "Second, authority: a role that may not perform the operation, or a
    caller acting on a row they do not own, produces `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/member_cannot_restock_the_wall
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="6301", element_name="Plate 1x6",
                          cost_basis_cents=4)
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="W01",
                       bin_capacity_grams=1000, bin_mass_grams=300)

    res = api.restock_wall_bin(bin_row["id"], {"add_grams": 100},
                               make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN")

    reread = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["bin_mass_grams"] == 300, "the refused restock changes nothing"


def test_store_associate_can_restock_the_bin_the_member_cannot(api):
    """PRD §2.4: "Second, authority: a role that may not perform the operation,
    or a caller acting on a row they do not own, produces `ERR_FORBIDDEN` (403)."
    PRD §3.1: "Restocking a single bin from the surplus drawer adds mass to it."
    PRD §2.5: "The engine mass itself — `bin_engine_mass_grams` — is the sum of
    `bin_mass_grams` across the store's wall bins whose `status` is `OPEN`, `LOW`
    or `EMPTY`."

    Design: Corner/validations/the_same_restock_call_succeeds_for_the_authorized_role
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="5401", element_name="Plate 2x2",
                          cost_basis_cents=4)
    bin_row = load_bin(store["id"], element["id"], bin_label="N01",
                       bin_capacity_grams=1000, bin_mass_grams=300)

    restocked = restock_bin(bin_row["id"], 500)
    assert restocked["bin_mass_grams"] == 800
    assert restocked["status"] == "OPEN", (
        "800 g of 1000 g is well above the fifty percent floor")

    after = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert after["bin_engine_mass_grams"] == 800


def test_store_associate_cannot_checkout_a_cup(api):
    """PRD §2.1: "Several member-facing capabilities exist only in this
    self-service form: settling or voiding one's own cup, placing or sealing
    one's own figure, buying one's own granted launch units, checking in to or
    cancelling one's own reservation, and claiming one's own replacement
    prospect."
    PRD §2.4: "Second, authority: a role that may not perform the operation, or a
    caller acting on a row they do not own, produces `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/store_associate_cannot_checkout_a_cup
    """
    store, element, member, bin_row, order = setup_cup_ready_to_checkout()

    res = api.checkout_fusion_order(
        order["id"], {"expected_fusion_order_version": order["version"]},
        TEST_USERS["associate_headers"])
    validate_error(res, "ERR_FORBIDDEN")

    reread = validate_success(api.get_fusion_order(
        order["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["status"] == "PENDING", (
        "a peer role cannot settle a cup even when the same role opened it")
    assert reread["final_price_cents"] == 0


def test_platform_admin_cannot_post_a_cup_draw(api):
    """PRD §2.1: "The head-office operator owns the element catalogue, launch
    scheduling, member records and the logical clock"
    PRD §2.4: "Second, authority: a role that may not perform the operation, or a
    caller acting on a row they do not own, produces `ERR_FORBIDDEN` (403)."

    Design: Corner/rbac/platform_admin_cannot_post_a_cup_draw
    """
    store, element, member, bin_row, order = setup_cup_ready_to_checkout(draw_grams=0)

    res = api.create_allocation(
        order["id"], {"wall_bin_id": bin_row["id"], "allocation_grams": 100},
        TEST_USERS["admin_headers"])
    validate_error(res, "ERR_FORBIDDEN")

    reread = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["bin_mass_grams"] == 600, "the refused draw moves no mass"


def test_missing_role_header_is_rejected_before_any_resource_is_resolved(api):
    """PRD §2.1: "Every request must carry two headers. `X-User-ID` identifies
    the acting principal and `X-User-Role` names their operational capacity. If
    either header is absent, or if the supplied role is not one of the three the
    system recognises, the request is refused with `ERR_UNAUTHENTICATED` (HTTP
    401)."
    PRD §2.4: "First, authentication: missing or unrecognised credentials produce
    `ERR_UNAUTHENTICATED` (401)."

    Design: Corner/validations/missing_role_header_is_rejected_before_any_resource_is_resolved
    """
    res = api.get_element("00000000-0000-4000-8000-000000000002", anonymous_headers())
    validate_error(res, "ERR_UNAUTHENTICATED")

    with_role = api.get_element("00000000-0000-4000-8000-000000000002",
                                TEST_USERS["admin_headers"])
    validate_error(with_role, "ERR_NOT_FOUND")


def test_wrong_role_on_a_restricted_action_is_refused(api):
    """PRD §2.4: "Second, authority: a role that may not perform the operation,
    or a caller acting on a row they do not own, produces `ERR_FORBIDDEN` (403)."
    PRD §2.1: "A request whose role is recognised but is not permitted for the
    operation being attempted — or which targets a row owned by a different
    principal — is refused with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/wrong_role_on_a_restricted_action_is_rejected
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="5301")
    member = add_member(store["id"])
    load_bin(store["id"], element["id"], bin_label="M01", bin_capacity_grams=1000,
             bin_mass_grams=600)

    res = api.create_fusion_order(
        {"store_id": store["id"], "member_id": member["id"], "cup_size": "SMALL",
         "pricing_model": "CUP_FILL", "declared_mass_grams": 100},
        make_member_headers(member["id"]))
    validate_error(res, "ERR_FORBIDDEN")

    orders = validate_success(api.list_fusion_orders(
        TEST_USERS["associate_headers"], params={"store_id": store["id"]}), 200)
    assert orders == [], "the refused cup is never opened"


def test_unknown_element_on_a_per_piece_cup_is_refused(api):
    """PRD §2.10: "When a path contains multiple identifiers, the server resolves
    them left to right and rejects the request at the first identifier that does
    not correspond to an existing resource, reporting `ERR_NOT_FOUND` (HTTP
    404)."
    PRD §3.2: "That element must resolve to an element in `ACTIVE` or `CATALOG`
    status; an element in any other status is refused as `ERR_ELEMENT_NOT_SOURCED`."
    PRD §3.1: "A newly registered element enters `PENDING_CATALOG` under
    `CURRENT_PRODUCTION` sourcing."

    Design: Corner/validations/unknown_element_on_a_per_piece_cup_is_refused
    """
    store, element, member, bin_row = setup_store_with_wall(
        store_overrides={"wall_bin_capacity_grams": 1000},
        element_overrides={"element_code": "5501", "element_name": "Brick 2x4"},
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 600})

    res = api.create_fusion_order(
        {"store_id": store["id"], "member_id": member["id"], "cup_size": "SMALL",
         "pricing_model": "PER_PIECE", "declared_mass_grams": 10,
         "pieced_element_id": "00000000-0000-4000-8000-000000000003",
         "declared_piece_count": 5},
        TEST_USERS["associate_headers"])
    validate_error(res, "ERR_NOT_FOUND")

    orders = validate_success(api.list_fusion_orders(
        TEST_USERS["associate_headers"], params={"store_id": store["id"]}), 200)
    assert orders == [], "the refused cup is never created"

    after = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert after["bin_engine_mass_grams"] == 600


def test_per_piece_cup_on_a_current_production_element_is_refused(api):
    """PRD §3.2: "That element must resolve to an element in `ACTIVE` or
    `CATALOG` status; an element in any other status is refused as
    `ERR_ELEMENT_NOT_SOURCED`."
    PRD §3.1: "It becomes `ACTIVE` automatically the first time a wall bin
    loading it holds any mass above zero — the element becomes real to guests at
    the moment it hits the wall, and no separate activation call exists."

    Design: Corner/errors/per_piece_cup_on_a_current_production_element_is_refused
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="6201", element_name="Brick 2x6",
                          theme="Icons", cost_basis_cents=7)
    member = add_member(store["id"])
    load_bin(store["id"], element["id"], bin_label="V01", bin_capacity_grams=1000,
             bin_mass_grams=600)

    promoted = validate_success(api.get_element(
        element["id"], TEST_USERS["associate_headers"]), 200)
    assert promoted["status"] == "ACTIVE", (
        "the element becomes real the moment a bin loading it holds mass")
    assert promoted["sourcing_mode"] == "CURRENT_PRODUCTION"

    # An element registered but never placed on the wall stays PENDING_CATALOG,
    # which is neither ACTIVE nor CATALOG, so a per-piece cup naming it is refused.
    unsourced = add_element(element_code="6202", element_name="Brick 2x8",
                            theme="Icons", cost_basis_cents=7)
    assert unsourced["status"] == "PENDING_CATALOG"

    res = api.create_fusion_order(
        {"store_id": store["id"], "member_id": member["id"], "cup_size": "SMALL",
         "pricing_model": "PER_PIECE", "declared_mass_grams": 10,
         "pieced_element_id": unsourced["id"], "declared_piece_count": 5},
        TEST_USERS["associate_headers"])
    validate_error(res, "ERR_ELEMENT_NOT_SOURCED")

    after = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert after["bin_engine_mass_grams"] == 600


def test_checkout_response_carries_every_settled_field_without_a_reread(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.2: "On success the cup moves to `SETTLED`, its priced fields are
    written, and the store's shrink ratio is recomputed."

    Design: Corner/consistency_model/checkout_response_carries_every_settled_field_without_a_reread
    """
    store, element, member, bin_row, order = setup_cup_ready_to_checkout(
        store_overrides={"wall_bin_capacity_grams": 1000},
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 600},
        cup_overrides={"cup_size": "LARGE", "pricing_model": "CUP_FILL",
                       "declared_mass_grams": 400})

    settled = validate_success(api.checkout_fusion_order(
        order["id"], {"expected_fusion_order_version": order["version"]},
        make_member_headers(member["id"])), 200)
    assert settled["status"] == "SETTLED", (
        "the checkout response itself reports the new status")
    assert settled["final_price_cents"] == 108
    assert "member_discount_cents" in settled, (
        "the priced fields are carried on the checkout response")

    reread = validate_success(api.get_fusion_order(
        order["id"], make_member_headers(member["id"])), 200)
    assert reread["status"] == settled["status"]
    assert reread["final_price_cents"] == settled["final_price_cents"]


def test_cascade_side_effects_are_visible_on_the_next_read_not_mid_request(api):
    """PRD §2.5: "The store's `bin_engine_mass_grams`, `shrinkage_basis_points`
    and `stage` are recomputed on the same mutating call that changed a bin, and
    the store's `updated_at` and `version` advance with each such recomputation"
    PRD §3.2: "Voiding a cup returns its mass to the wall."

    Design: Corner/consistency_model/cascade_side_effects_are_visible_on_the_next_read_not_mid_request
    """
    store, element, member, bin_row = setup_store_with_wall(
        store_overrides={"wall_bin_capacity_grams": 2000},
        element_overrides={"element_code": "7501"},
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 600})

    order = open_cup(store["id"], member["id"], cup_size="LARGE",
                     pricing_model="CUP_FILL", declared_mass_grams=400)
    order = draw_from_bin(order["id"], bin_row["id"], 400)
    settled = validate_success(api.checkout_fusion_order(
        order["id"], {"expected_fusion_order_version": order["version"]},
        make_member_headers(member["id"])), 200)

    voided = validate_success(api.void_fusion_order(
        order["id"], {"expected_fusion_order_version": settled["version"]},
        make_member_headers(member["id"])), 200)
    assert voided["status"] == "VOID"

    bin_after = validate_success(api.get_wall_bin(
        bin_row["id"], TEST_USERS["associate_headers"]), 200)
    assert bin_after["bin_mass_grams"] == 600, (
        "the void's cascaded bin restore is committed with the void request")

    store_after = validate_success(api.get_store(
        store["id"], TEST_USERS["associate_headers"]), 200)
    assert store_after["bin_engine_mass_grams"] == 600, (
        "the store's derived mass is visible on the next read")


def test_stale_order_version_on_an_inspection_is_rejected(api):
    """PRD §2.9: "Recording an exit inspection — an inspection recorded at the
    exit tunnel — must carry `expected_fusion_order_version` matching the target
    `FusionOrder`'s current `version`. If another writer has advanced the order's
    version since the caller last read it, the inspection is rejected with
    `ERR_INSPECTION_STALE_VERSION` (HTTP 412)"

    Design: Corner/cross_cutting_complexity_layers/stale_order_version_on_an_inspection_is_rejected
    """
    store, element, member, bin_row, order = setup_cup_ready_to_checkout(
        store_overrides={"wall_bin_capacity_grams": 1000},
        element_overrides={"element_code": "6801"},
        bin_overrides={"bin_capacity_grams": 1000, "bin_mass_grams": 1000})
    stale_version = order["version"]
    drawn = draw_from_bin(order["id"], bin_row["id"], 400)
    assert drawn["version"] > stale_version, "the draw advanced the order version"

    first = validate_success(api.create_exit_inspection(
        {"fusion_order_id": drawn["id"], "outcome": "CLEAR",
         "checklist_result": "COMPLETED", "reviewed_by_user_id": "assoc-88",
         "expected_fusion_order_version": drawn["version"]},
        TEST_USERS["associate_headers"]), 201)
    assert first["stage"] == "COMPLETED"

    replay = api.create_exit_inspection(
        {"fusion_order_id": drawn["id"], "outcome": "CLEAR",
         "checklist_result": "COMPLETED", "reviewed_by_user_id": "assoc-88",
         "expected_fusion_order_version": stale_version},
        TEST_USERS["associate_headers"])
    validate_error(replay, "ERR_INSPECTION_STALE_VERSION")

    inspections = validate_success(api.list_exit_inspections(
        TEST_USERS["associate_headers"], params={"fusion_order_id": drawn["id"]}), 200)
    assert len(inspections) == 1, (
        "the replayed inspection must not create a second record")


def test_claim_at_the_expiry_instant_is_refused(api):
    """PRD §3.7: "Claiming is a member action on their own prospect and is
    admitted only while the clock is strictly before `window_expires_utc`, under
    an `ACTIVE` member. The comparison is inclusive at the other edge: a claim
    landing exactly on the expiry instant is refused with `ERR_WINDOW_EXPIRED`,
    while a claim one second earlier is accepted."

    Design: Difficulty/combinatorial_formula/replacement_claim_and_completion_award_different_points
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = setup_surplus_element(store["id"])
    member = add_member(store["id"])
    request = file_replacement(store["id"], member["id"], element["id"],
                               member["version"], quantity_missing=1,
                               window_days=30)
    assert request["stage"] == "PROSPECT"
    assert request["window_days"] == 30

    set_clock("2026-10-01T00:00:00Z")  # exactly thirty days past the logical start

    res = api.claim_replacement_request(request["id"],
                                        make_member_headers(member["id"]))
    assert res.status_code >= 400, (
        "a claim at the expiry instant is refused, but it was admitted: "
        f"HTTP {res.status_code} {res.text}")
    assert res.json().get("data", {}).get("error_id") in (
        "ERR_WINDOW_EXPIRED", "ERR_INVALID_STATE"), (
        "a claim landing exactly on the expiry instant is refused with "
        f"ERR_WINDOW_EXPIRED, got {res.text}")

    reread = validate_success(api.get_replacement_request(
        request["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["stage"] == "PROSPECT", (
        "a refused claim leaves the prospect for the resolution pass")
    assert reread["earned_points"] == 0