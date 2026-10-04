"""Build-a-Minifigure: component availability, sealing and exit inspections."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_element,
    add_member,
    api_client,
    assert_exit_inspection,
    assert_minifigure_build,
    create_exit_inspection_payload,
    draw_from_bin,
    load_bin,
    make_member_headers,
    open_build,
    open_cup,
    open_store,
    reset_clock,
    seal_build,
    set_components,
    setup_four_component_bins,
    validate_error,
    validate_success,
)


def test_build_seals_when_every_component_element_sits_in_a_stocked_bin(api):
    """PRD §3.5: "An associate or the member then places or replaces components
    by naming any subset of the four slots; each named element must be loaded in
    at least one bin of that store holding mass above zero"
    PRD §3.5: "A figure may only be sealed when `components_missing` is zero —
    an attempt at sealing an incomplete figure is refused with
    `ERR_COMPONENTS_INCOMPLETE` — and when the platform has been populated at
    least once, which is to say `platform_gen` has reached one."
    PRD §3.5: "Sealing requires `expected_build_version`, moves the figure to
    `SEALED`, and awards the sealing member a fixed good-will credit"

    Design: Difficulty/cross_entity_state_dependency/build_seal_depends_on_every_component_bin_state
    """
    store, member, elements, bins = setup_four_component_bins()

    build = open_build(store["id"], member["id"])
    assert_minifigure_build(build)
    build = set_components(
        build["id"], member["id"],
        torso_element_id=elements["torso"]["id"],
        head_element_id=elements["head"]["id"],
        legs_element_id=elements["legs"]["id"],
        accessory_element_id=elements["accessory"]["id"],
    )
    assert build["components_missing"] == 0, (
        "all four named elements sit in stocked bins of this store")

    sealed = seal_build(build["id"], build["version"], member["id"])
    assert sealed["status"] == "SEALED"
    assert sealed["platform_gen"] == 1, (
        "the assembly platform was populated exactly once")

    refreshed = validate_success(api.get_minifigure_build(
        build["id"], TEST_USERS["associate_headers"]), 200)
    assert refreshed["status"] == "SEALED"


def test_a_component_whose_bin_was_drawn_empty_is_not_stocked(api):
    """PRD §3.5: "A `RETIRED` bin does not count as on the wall even if it still
    holds mass of the element."
    PRD §2.4: "Fifth, sibling readiness: resources named in the payload must
    already carry the status the operation depends on. This rung covers four
    distinct refusals, and it is evaluated before any fiscal or capacity
    arithmetic: ... `ERR_COMPONENT_NOT_STOCKED` when a build component is not on
    the wall"

    Design: Difficulty/cross_entity_state_dependency/build_seal_depends_on_every_component_bin_state
    """
    store, member, elements, bins = setup_four_component_bins()

    # Draw the legs bin completely dry through a cup.
    drain = open_cup(store["id"], member["id"], cup_size="SMALL",
                     pricing_model="CUP_FILL", declared_mass_grams=600,
                     measured_volume_ml=0)
    draw_from_bin(drain["id"], bins["legs"]["id"], 600)
    drained = validate_success(api.get_wall_bin(
        bins["legs"]["id"], TEST_USERS["associate_headers"]), 200)
    assert drained["bin_mass_grams"] == 0
    assert drained["status"] == "EMPTY"

    build = open_build(store["id"], member["id"])
    res = api.set_build_components(
        build["id"],
        {"torso_element_id": elements["torso"]["id"],
         "head_element_id": elements["head"]["id"],
         "legs_element_id": elements["legs"]["id"],
         "accessory_element_id": elements["accessory"]["id"]},
        make_member_headers(member["id"]))
    validate_error(res, "ERR_COMPONENT_NOT_STOCKED")


def test_sealing_an_unpopulated_figure_is_refused(api):
    """PRD §3.5: "A figure may only be sealed when `components_missing` is zero —
    an attempt at sealing an incomplete figure is refused with
    `ERR_COMPONENTS_INCOMPLETE`"
    PRD §3.5: "begins in `BUILDING`, with `platform_gen` at zero and
    `components_missing` reporting all four component slots as missing"

    Design: Corner/state_machines/a_returned_build_is_terminal_and_refuses_further_mutations
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="4701", element_name="Legs Blue",
                          cost_basis_cents=12)
    member = add_member(store["id"])
    load_bin(store["id"], element["id"], bin_label="F01", bin_capacity_grams=1000,
             bin_mass_grams=1000)

    build = open_build(store["id"], member["id"])
    assert build["components_missing"] == 4, (
        "a fresh figure reports all four component slots as missing")
    assert build["platform_gen"] == 0

    res = api.seal_build(build["id"], {"expected_build_version": build["version"]},
                         make_member_headers(member["id"]))
    validate_error(res, "ERR_COMPONENTS_INCOMPLETE")

    reread = validate_success(api.get_minifigure_build(
        build["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["status"] == "BUILDING", (
        "the refused seal leaves the figure on the platform")


def test_sealing_twice_is_rejected_and_leaves_the_first_seal_intact(api):
    """PRD §2.9: "the same expected-version pattern, with the same stale-version
    discipline, guards the other version-bearing writes ... sealing a figure
    carries `expected_build_version`"
    PRD §2.7: "`updated_at` (string): an ISO 8601 UTC timestamp with three
    fractional digits recording the most recent modification, advanced on every
    mutation including changes to derived fields."

    Design: Corner/state_machines/sealing_twice_is_rejected_and_leaves_the_first_seal_intact
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=2000)
    torso = add_element(element_code="4601", element_name="Torso Plain",
                        cost_basis_cents=20)
    head = add_element(element_code="4602", element_name="Head Smile",
                       cost_basis_cents=10)
    member = add_member(store["id"])
    load_bin(store["id"], torso["id"], bin_label="E01", bin_capacity_grams=1000,
             bin_mass_grams=1000)
    load_bin(store["id"], head["id"], bin_label="E02", bin_capacity_grams=1000,
             bin_mass_grams=1000)

    build = open_build(store["id"], member["id"])
    build = set_components(build["id"], member["id"],
                           torso_element_id=torso["id"],
                           head_element_id=head["id"])

    sealed = seal_build(build["id"], build["version"], member["id"])
    assert sealed["status"] == "SEALED"

    res = api.seal_build(sealed["id"],
                         {"expected_build_version": sealed["version"]},
                         make_member_headers(member["id"]))
    validate_error(res, "ERR_INVALID_STATE")

    reread = validate_success(api.get_minifigure_build(
        build["id"], TEST_USERS["associate_headers"]), 200)
    assert reread["platform_gen"] == 1, (
        "the refused second seal does not advance the platform generation")
    assert reread["status"] == "SEALED", (
        "the first seal stands")


def test_a_cup_is_born_pending_and_its_inspection_born_scheduled(api):
    """PRD §3.2: "A new cup starts `PENDING`."
    PRD §3.2: "The inspection's `variance_bps` is the absolute value of the
    cup's `variance_grams` multiplied by ten thousand and divided by the cup's
    declared mass, rounded half up; it is therefore a magnitude, and the
    direction of the discrepancy lives on the cup's `variance_grams`, which is
    signed."

    Design: Corner/state_machines/fusion_order_starts_pending_and_inspection_starts_scheduled
    """
    reset_clock()
    store = open_store(wall_bin_capacity_grams=1000)
    element = add_element(element_code="4501", element_name="Brick 2x6",
                          cost_basis_cents=7)
    member = add_member(store["id"])
    bin_row = load_bin(store["id"], element["id"], bin_label="D01",
                       bin_capacity_grams=1000, bin_mass_grams=1000)

    order = open_cup(store["id"], member["id"], cup_size="JUMBO",
                     pricing_model="CUP_FILL", declared_mass_grams=300)
    assert order["status"] == "PENDING", f"a new cup starts PENDING, got {order['status']}"
    assert order["base_price_cents"] == 0, (
        "priced fields are unset before settlement")
    assert order["final_price_cents"] == 0

    order = draw_from_bin(order["id"], bin_row["id"], 300)

    res = api.create_exit_inspection(
        create_exit_inspection_payload(order["id"], order["version"]),
        TEST_USERS["associate_headers"])
    inspection = validate_success(res, 201)
    assert_exit_inspection(inspection)
    assert inspection["stage"] == "COMPLETED"
    assert inspection["variance_bps"] == 0, (
        "the draw matches the declared mass, so the variance is zero")

    refreshed = validate_success(api.get_fusion_order(
        order["id"], TEST_USERS["associate_headers"]), 200)
    assert refreshed["status"] == "PENDING", (
        "recording an inspection alone does not settle the cup")