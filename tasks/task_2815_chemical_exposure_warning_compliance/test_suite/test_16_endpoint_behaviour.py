"""Endpoint surfaces: the conditional component create, the re-parenting PATCH,
the product listing filters, the computed compliance summary and the junction
listings of the material/chemical many-to-many.

These cases probe what each endpoint owns beyond its happy path: one optional
field that flips a create between a duplicate refusal and a supersede, a PATCH
whose effects land two hops away, filters that must narrow conjunctively and
compose with the page window, a read that synthesises every counter on demand,
and a junction collection that has to be reachable from either side.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DUPLICATE_RESOURCE,
    ERR_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_close,
    assert_concentration,
    assert_defense_components,
    assert_defense_counts,
    assert_instant,
    assert_load,
    assert_posture,
    assert_status,
)
from test_helpers.constants import (
    BASIS_LAB_TESTED,
    BASIS_SUPPLIER_DECLARED,
    CADMIUM_CAS,
    CADMIUM_NAME,
    CATEGORY_CONSUMER_GOOD,
    CATEGORY_FOOD,
    CATEGORY_FURNITURE,
    COMPONENT_STATUS_ACTIVE,
    COMPONENT_STATUS_REMOVED,
    COMPONENT_STATUS_SUPERSEDED,
    DEFAULT_CLOCK,
    DISCLOSURE_VERIFIED,
    ENDPOINT_TYPE_CANCER,
    LIFECYCLE_DEVELOPMENT,
    LIFECYCLE_DISCONTINUED,
    LIFECYCLE_MARKETED,
    MATERIAL_CLASS_MANUFACTURING_AID,
    MATERIAL_CLASS_PACKAGING,
    POSTURE_EXPOSURE_UNKNOWN,
    SAFE_HARBOR_BASIS_NONE,
    VARIANT_AS_OF_TODAY,
)
from test_helpers.fixtures import (
    add_component,
    advance_disclosure,
    discontinue_product,
    link_chemical,
    make_bpa,
    make_listed_chemical,
    make_material,
    make_product,
    make_supplied_material,
    make_supplier,
    read_product,
    remove_component,
    report_lab_result,
    set_clock,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    REGULATORY_COUNSEL,
)


UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"
OTHER_UNKNOWN_ID = "00000000-0000-0000-0000-0000000000fe"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _add_component_raw(api, product_id, material_id, **overrides):
    """The raw component create, so a duplicate refusal can be inspected."""
    return api.create_component(
        product_id, f.component_payload(material_id, **overrides), COMPLIANCE_ANALYST
    )


def _read_component(api, component_id):
    return get_success_data(api.get_component(component_id, COMPLIANCE_ANALYST))


def _read_material(api, material_id):
    return get_success_data(api.get_material(material_id, COMPLIANCE_ANALYST))


def _read_link(api, link_id):
    return get_success_data(api.get_material_chemical(link_id, COMPLIANCE_ANALYST))


def _components(api, **filters):
    return validate_paginated(
        api.list_components(COMPLIANCE_ANALYST, f.page(**filters))
    )


def _materials(api, **filters):
    return validate_paginated(api.list_materials(COMPLIANCE_ANALYST, f.page(**filters)))


def _links(api, **filters):
    return validate_paginated(
        api.list_material_chemicals(COMPLIANCE_ANALYST, f.page(**filters))
    )


def _products(api, **filters):
    return validate_paginated(api.list_products(COMPLIANCE_ANALYST, f.page(**filters)))


def _ids(rows):
    return [row["id"] for row in rows]


def _summary(api, product_id, **params):
    return api.compliance_summary(product_id, REGULATORY_COUNSEL, f.page(**params))


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def clocked(api):
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def one_component(api, clocked):
    """SKU-EP1 holds one ACTIVE component of RM-EP1, which declares 20.0 ppm.

    The component is 0.5 g/unit at contact_factor 1.0, so the product's load is
    20.0 x 0.5 = 10.000 ug per finished unit.
    """
    chemical = make_bpa(api)
    supplied = make_supplied_material(
        api, chemical["id"], 20.0, material_code="RM-EP1"
    )
    product = make_product(
        api, "SKU-EP1", product_name="Endpoint Widget One", annual_units=1000
    )
    component = get_success_data(
        _add_component_raw(
            api,
            product["id"],
            supplied["material"]["id"],
            quantity_grams_per_unit=0.5,
            contact_factor=1.0,
        )
    )
    return {
        "chemical": chemical,
        "material": supplied["material"],
        "product": product,
        "component": component,
    }


@pytest.fixture
def bom_tree(api, clocked):
    """Two roots: RA -> C -> G declaring 100.0, 40.0 and 8.0 ppm, and RB -> RB1.

    RA, C and G all have a VERIFIED disclosure, so no worst-case substitution
    enters the roll-up. SKU-EP2 holds one ACTIVE component of RA at 0.1 g/unit.
    """
    chemical = make_bpa(api)
    supplier_id = make_supplier(api, "Northgate Polymers")["id"]

    ra = make_material(api, "RA", supplier_id)
    c = make_material(
        api, "C", supplier_id, parent_material_id=ra["id"], parent_mass_fraction=0.5
    )
    g = make_material(
        api, "G", supplier_id, parent_material_id=c["id"], parent_mass_fraction=0.5
    )
    rb = make_material(
        api, "RB", supplier_id, material_class=MATERIAL_CLASS_PACKAGING
    )
    rb1 = make_material(
        api,
        "RB1",
        supplier_id,
        material_class=MATERIAL_CLASS_PACKAGING,
        parent_material_id=rb["id"],
        parent_mass_fraction=0.5,
    )

    link_chemical(api, ra["id"], chemical["id"], 100.0)
    link_chemical(api, c["id"], chemical["id"], 40.0)
    link_chemical(api, g["id"], chemical["id"], 8.0)
    for material in (ra, c, g):
        advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)

    product = make_product(
        api, "SKU-EP2", product_name="Endpoint Widget Two", annual_units=1000
    )
    add_component(api, product["id"], ra["id"], 0.1, 1.0)
    return {
        "chemical": chemical,
        "ra": ra,
        "c": c,
        "g": g,
        "rb": rb,
        "rb1": rb1,
        "product": product,
    }


@pytest.fixture
def catalogue(api, clocked):
    """Four component-less products spanning three categories and two lifecycles.

    The clock is advanced one day between creates so that the ``created_at``
    ascending order of the collection is SKU-F1, SKU-F2, SKU-F3, SKU-F4 with no
    ties, which is what makes an offset assertion meaningful.
    """
    set_clock(api, "2026-08-01T00:00:00Z")
    p1 = make_product(
        api, "SKU-F1", product_name="Filter One", product_category=CATEGORY_CONSUMER_GOOD
    )
    set_clock(api, "2026-08-02T00:00:00Z")
    p2 = make_product(
        api, "SKU-F2", product_name="Filter Two", product_category=CATEGORY_FOOD
    )
    set_clock(api, "2026-08-03T00:00:00Z")
    p3 = make_product(
        api,
        "SKU-F3",
        product_name="Filter Three",
        product_category=CATEGORY_CONSUMER_GOOD,
    )
    set_clock(api, "2026-08-04T00:00:00Z")
    p4 = make_product(
        api, "SKU-F4", product_name="Filter Four", product_category=CATEGORY_FURNITURE
    )
    discontinue_product(api, p3["id"])
    discontinue_product(api, p4["id"])
    return {"p1": p1, "p2": p2, "p3": p3, "p4": p4}


@pytest.fixture
def bare_product(api, clocked):
    """SKU-EP4 has no components, no assessments, no determinations, no notices."""
    return make_product(
        api, "SKU-EP4", product_name="Endpoint Widget Four", annual_units=1000
    )


@pytest.fixture
def junction(api, clocked):
    """RM-X declares Bisphenol A and Cadmium; RM-Y declares Bisphenol A alone."""
    bpa = make_bpa(api)
    cadmium = make_listed_chemical(
        api,
        f.listed_chemical_payload(
            CADMIUM_NAME, CADMIUM_CAS, ENDPOINT_TYPE_CANCER, SAFE_HARBOR_BASIS_NONE
        ),
    )
    supplier_id = make_supplier(api, "Northgate Polymers")["id"]
    material_x = make_material(api, "RM-X", supplier_id)
    material_y = make_material(
        api, "RM-Y", supplier_id, material_class=MATERIAL_CLASS_MANUFACTURING_AID
    )
    link_x_bpa = link_chemical(api, material_x["id"], bpa["id"], 20.0)
    link_x_cd = link_chemical(api, material_x["id"], cadmium["id"], 5.0)
    link_y_bpa = link_chemical(api, material_y["id"], bpa["id"], 3.0)
    return {
        "bpa": bpa,
        "cadmium": cadmium,
        "supplier_id": supplier_id,
        "material_x": material_x,
        "material_y": material_y,
        "link_x_bpa": link_x_bpa,
        "link_x_cd": link_x_cd,
        "link_y_bpa": link_y_bpa,
    }


# ─────────────────────────────────────────────────────────────────────────────
# endpoints
# ─────────────────────────────────────────────────────────────────────────────


class TestComponentSupersedeIsConditional:
    """POST /products/{id}/components behaves in two ways on one optional field.

    Without ``supersedes_component_id`` a second component for the same material
    collides with the ACTIVE-scoped pair; with it, the named row leaves ACTIVE
    before the uniqueness check runs, so the same request succeeds.
    """

    def test_second_component_for_the_same_material_is_a_duplicate(
        self, api, one_component
    ):
        """Repeating the material without naming a predecessor is refused.

        PRD: "Uniqueness constraints span five shapes and all report `ERR_DUPLICATE_RESOURCE` (HTTP 409): `chemical_name` is unique across all listed chemicals by case-sensitive exact match, `sku` is unique across all products, `legal_name` is unique across all suppliers, the pair of `material_id` and `chemical_id` is unique across all material/chemical links, and the pair of `product_id` and `material_id` is unique across product components whose status is `ACTIVE` — a component that has left `ACTIVE` no longer occupies the pair."
        PRD: "Rules are evaluated in ascending priority order; the first rule whose condition holds short-circuits the request and returns its error, and no later rule is evaluated."

        The product already holds an ACTIVE component of RM-EP1, so the pair of
        `product_id` and `material_id` is occupied and the create is refused with
        ERR_DUPLICATE_RESOURCE. The refusal short-circuits, so the stored load
        stays at the 10.000 ug the surviving component produces.

        Design: Corner/endpoints/ep_component_create_supersede_is_conditional_on_supersedes_component_id
        """
        response = _add_component_raw(
            api,
            one_component["product"]["id"],
            one_component["material"]["id"],
            quantity_grams_per_unit=0.75,
            contact_factor=1.0,
        )
        validate_error(response, ERR_DUPLICATE_RESOURCE, 409)

        product = read_product(api, one_component["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 10.000)
        assert_status(
            _read_component(api, one_component["component"]["id"]),
            COMPONENT_STATUS_ACTIVE,
        )

    def test_naming_the_predecessor_supersedes_it_and_the_create_lands(
        self, api, one_component
    ):
        """The same body plus supersedes_component_id is accepted.

        PRD: "Because the active pair of `product_id` and `material_id` is unique, replacing a component that uses the same material requires the optional `supersedes_component_id` field: supplying it moves the named component `ACTIVE → SUPERSEDED` **before** the uniqueness check runs, so the check only ever sees the replacement, and the replacement is created `ACTIVE` in the same request. The superseded row's `version` increments by 1, the product's chemical load is recomputed from the replacement's quantity, and `compliance_posture` is recomputed. The named component must currently be `ACTIVE` and must belong to the same product."

        The predecessor is moved ACTIVE to SUPERSEDED before the uniqueness check
        sees anything, and the replacement is created ACTIVE in the same request.

        Design: Corner/endpoints/ep_component_create_supersede_is_conditional_on_supersedes_component_id
        """
        replacement = get_success_data(
            _add_component_raw(
                api,
                one_component["product"]["id"],
                one_component["material"]["id"],
                quantity_grams_per_unit=0.25,
                contact_factor=1.0,
                supersedes_component_id=one_component["component"]["id"],
            )
        )
        assert_status(replacement, COMPONENT_STATUS_ACTIVE)
        assert_status(
            _read_component(api, one_component["component"]["id"]),
            COMPONENT_STATUS_SUPERSEDED,
        )

    def test_load_is_recomputed_from_the_replacement_quantity_alone(
        self, api, one_component
    ):
        """The SUPERSEDED row contributes nothing to the recomputed load.

        PRD: "For each such chemical-and-component pair the server evaluates the modelled effective concentration of that chemical in that component's material — the roll-up described in Section 3.5, always under the modelled variant regardless of any assessment — multiplies it by that component's `quantity_grams_per_unit`, and rounds the product half up to three decimal places."

        20.0 ppm at 0.25 g per unit is 5.000 ug, not 5.000 added to the 10.000 the
        superseded row used to carry.

        Design: Corner/endpoints/ep_component_create_supersede_is_conditional_on_supersedes_component_id
        """
        get_success_data(
            _add_component_raw(
                api,
                one_component["product"]["id"],
                one_component["material"]["id"],
                quantity_grams_per_unit=0.25,
                contact_factor=1.0,
                supersedes_component_id=one_component["component"]["id"],
            )
        )
        product = read_product(api, one_component["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 5.000)

    def test_component_listing_counts_the_superseded_row_but_the_status_filter_does_not(
        self, api, one_component
    ):
        """Both rows are listable; only one of them is ACTIVE.

        PRD: "/product-components` | Paginated component list, optionally filtered by `product_id`, `material_id` or `status`."
        PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."

        Design: Corner/endpoints/ep_component_create_supersede_is_conditional_on_supersedes_component_id
        """
        replacement = get_success_data(
            _add_component_raw(
                api,
                one_component["product"]["id"],
                one_component["material"]["id"],
                quantity_grams_per_unit=0.25,
                contact_factor=1.0,
                supersedes_component_id=one_component["component"]["id"],
            )
        )
        rows, meta = _components(api, product_id=one_component["product"]["id"])
        assert meta["total_count"] == 2, f"Expected both rows, got {meta}"
        assert set(_ids(rows)) == {
            one_component["component"]["id"],
            replacement["id"],
        }, f"Unexpected component ids: {_ids(rows)}"

        active_rows, active_meta = _components(
            api,
            product_id=one_component["product"]["id"],
            status=COMPONENT_STATUS_ACTIVE,
        )
        assert active_meta["total_count"] == 1, (
            f"Expected one ACTIVE component, got {active_meta}"
        )
        assert _ids(active_rows) == [replacement["id"]], (
            f"Expected only the replacement to be ACTIVE, got {_ids(active_rows)}"
        )

    def test_removing_the_last_active_component_empties_the_load_and_the_posture(
        self, api, one_component
    ):
        """REMOVE drops the load to zero and the posture back to EXPOSURE_UNKNOWN.

        PRD: "Removing a component takes it `ACTIVE → REMOVED` and excludes it from every exposure and load calculation from that instant on; a product whose last `ACTIVE` component is removed falls back to `EXPOSURE_UNKNOWN` through clause 2 of the posture ladder."

        Design: Corner/endpoints/ep_component_create_supersede_is_conditional_on_supersedes_component_id
        """
        replacement = get_success_data(
            _add_component_raw(
                api,
                one_component["product"]["id"],
                one_component["material"]["id"],
                quantity_grams_per_unit=0.25,
                contact_factor=1.0,
                supersedes_component_id=one_component["component"]["id"],
            )
        )
        removed = remove_component(api, replacement["id"])
        assert_status(removed, COMPONENT_STATUS_REMOVED)

        product = read_product(api, one_component["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 0.000)
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)

    def test_only_the_two_accepted_writes_bump_the_product_version(
        self, api, one_component
    ):
        """The refused create leaves the product's version alone.

        PRD: "Component creation, component adjustment and component removal each recompute the product's `total_listed_chemical_load_ug`, recompute `daily_exposure_ug` for every exposure assessment of that product whose status is `DRAFT`, `SUBMITTED` or `PEER_REVIEWED`, recompute `compliance_posture`, and increment both the product's `version` and the component's `version` by 1."
        PRD: "Rules are evaluated in ascending priority order; the first rule whose condition holds short-circuits the request and returns its error, and no later rule is evaluated."

        Three writes are attempted: a duplicate create, a supersede create and a
        removal. Only the last two are accepted, so the product's version moves by
        exactly 2.

        Design: Corner/endpoints/ep_component_create_supersede_is_conditional_on_supersedes_component_id
        """
        before = api.product_version(one_component["product"]["id"], COMPLIANCE_ANALYST)

        validate_error(
            _add_component_raw(
                api,
                one_component["product"]["id"],
                one_component["material"]["id"],
                quantity_grams_per_unit=0.75,
                contact_factor=1.0,
            ),
            ERR_DUPLICATE_RESOURCE,
            409,
        )
        replacement = get_success_data(
            _add_component_raw(
                api,
                one_component["product"]["id"],
                one_component["material"]["id"],
                quantity_grams_per_unit=0.25,
                contact_factor=1.0,
                supersedes_component_id=one_component["component"]["id"],
            )
        )
        remove_component(api, replacement["id"])

        after = api.product_version(one_component["product"]["id"], COMPLIANCE_ANALYST)
        assert after == before + 2, (
            f"Expected the product version to move from {before} to {before + 2}, "
            f"got {after}"
        )


class TestMaterialReparentRecomputesDepthAndLoad:
    """PATCH /materials/{id} moves one node and repairs everything it touches.

    The moved material's own descendant is re-depthed, and the product that
    reaches the *old* parent loses the whole moved subtree from its roll-up.
    """

    def test_the_starting_tree_has_the_depths_and_the_load_the_walk_implies(
        self, api, bom_tree
    ):
        """RA/C/G sit at depths 0/1/2 and the product carries 12.200 ug.

        PRD: "`bom_depth` is derived, never supplied: it is 0 for a material whose `parent_material_id` is null, and otherwise one more than its parent's `bom_depth`."
        PRD: "For each child, the child's own effective concentration is computed by the same rules under the same variant and multiplied by that child's `parent_mass_fraction`, and the products are added to the running total. The total for the level is then rounded half up to four decimal places, and that rounded value is what the level returns to its parent."

        C rolls up to 40.0 + 0.5 x 8.0 = 44.0000 and RA to 100.0 + 0.5 x 44.0 =
        122.0000, so 0.1 g of RA per finished unit is a 12.200 ug load.

        Design: Corner/endpoints/ep_material_reparent_recomputes_descendant_depth_and_product_load
        """
        assert _read_material(api, bom_tree["ra"]["id"])["bom_depth"] == 0
        assert _read_material(api, bom_tree["c"]["id"])["bom_depth"] == 1
        assert _read_material(api, bom_tree["g"]["id"])["bom_depth"] == 2
        assert _read_material(api, bom_tree["rb1"]["id"])["bom_depth"] == 1

        product = read_product(api, bom_tree["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 12.200)

    def test_the_patch_re_depths_the_moved_material_and_its_descendant(
        self, api, bom_tree
    ):
        """Moving C under RB1 pushes C to depth 2 and G, unnamed, to depth 3.

        PRD: "Re-parenting an existing material is the only other way to disturb the tree; that update accepts `parent_material_id`, `parent_mass_fraction` and `naturally_occurring_claim`, recomputes `bom_depth` for the material and every one of its descendants, and rejects the whole request when any descendant would end up deeper than 4."

        Design: Corner/endpoints/ep_material_reparent_recomputes_descendant_depth_and_product_load
        """
        moved = get_success_data(
            api.patch_material(
                bom_tree["c"]["id"],
                {
                    "parent_material_id": bom_tree["rb1"]["id"],
                    "parent_mass_fraction": 0.25,
                },
                COMPLIANCE_ANALYST,
            )
        )
        assert moved["parent_material_id"] == bom_tree["rb1"]["id"], (
            f"Expected C to hang off RB1, got {moved['parent_material_id']!r}"
        )
        assert_close(moved["parent_mass_fraction"], 0.25, 4, "parent_mass_fraction")
        assert moved["bom_depth"] == 2, f"Expected C at depth 2, got {moved}"
        assert _read_material(api, bom_tree["g"]["id"])["bom_depth"] == 3, (
            "The descendant must be re-depthed even though it was not named"
        )

    def test_the_old_parent_is_left_alone_by_the_patch(self, api, bom_tree):
        """RA keeps depth 0 and is not itself versioned by its child's move.

        PRD: "Both material creation and material re-parenting recompute the chemical mass load of every product whose active components reach the affected material through the parent chain, and re-parenting increments the material's `version` by 1."

        The version bump belongs to the re-parented material, so the material that
        merely lost a child sees no bump.

        Design: Corner/endpoints/ep_material_reparent_recomputes_descendant_depth_and_product_load
        """
        before = _read_material(api, bom_tree["ra"]["id"])["version"]
        get_success_data(
            api.patch_material(
                bom_tree["c"]["id"],
                {
                    "parent_material_id": bom_tree["rb1"]["id"],
                    "parent_mass_fraction": 0.25,
                },
                COMPLIANCE_ANALYST,
            )
        )
        after = _read_material(api, bom_tree["ra"]["id"])
        assert after["bom_depth"] == 0, f"Expected RA still at depth 0, got {after}"
        assert after["version"] == before, (
            f"Expected RA's version to stay at {before}, got {after['version']}"
        )

    def test_the_product_load_drops_to_the_roots_own_contribution(self, api, bom_tree):
        """The product loses the whole moved subtree: 12.200 becomes 10.000.

        PRD: "Both material creation and material re-parenting recompute the chemical mass load of every product whose active components reach the affected material through the parent chain, and re-parenting increments the material's `version` by 1."
        PRD: "For each such chemical-and-component pair the server evaluates the modelled effective concentration of that chemical in that component's material — the roll-up described in Section 3.5, always under the modelled variant regardless of any assessment — multiplies it by that component's `quantity_grams_per_unit`, and rounds the product half up to three decimal places."

        RA now rolls up to its own 100.0000 alone, so 0.1 g per unit is 10.000 ug.

        Design: Corner/endpoints/ep_material_reparent_recomputes_descendant_depth_and_product_load
        """
        get_success_data(
            api.patch_material(
                bom_tree["c"]["id"],
                {
                    "parent_material_id": bom_tree["rb1"]["id"],
                    "parent_mass_fraction": 0.25,
                },
                COMPLIANCE_ANALYST,
            )
        )
        product = read_product(api, bom_tree["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 10.000)

    def test_the_child_listing_follows_the_material_to_its_new_parent(
        self, api, bom_tree
    ):
        """RA has no children left and RB1 has exactly one.

        PRD: "Materials are the inventory layer, and they form a tree rather than a flat list."
        PRD: "/materials` | Paginated material list, optionally filtered by `supplier_id`, `parent_material_id`, `material_class` or `disclosure_status`."

        Design: Corner/endpoints/ep_material_reparent_recomputes_descendant_depth_and_product_load
        """
        get_success_data(
            api.patch_material(
                bom_tree["c"]["id"],
                {
                    "parent_material_id": bom_tree["rb1"]["id"],
                    "parent_mass_fraction": 0.25,
                },
                COMPLIANCE_ANALYST,
            )
        )
        _, old_meta = _materials(api, parent_material_id=bom_tree["ra"]["id"])
        assert old_meta["total_count"] == 0, (
            f"Expected RA to have no children left, got {old_meta}"
        )

        new_rows, new_meta = _materials(api, parent_material_id=bom_tree["rb1"]["id"])
        assert new_meta["total_count"] == 1, (
            f"Expected RB1 to have exactly one child, got {new_meta}"
        )
        assert _ids(new_rows) == [bom_tree["c"]["id"]], (
            f"Expected C under RB1, got {_ids(new_rows)}"
        )


class TestProductListingFiltersCombineConjunctively:
    """GET /products narrows on every supplied filter and then pages the result.

    The catalogue holds SKU-F1 (CONSUMER_GOOD, DEVELOPMENT), SKU-F2 (FOOD,
    DEVELOPMENT), SKU-F3 (CONSUMER_GOOD, DISCONTINUED) and SKU-F4 (FURNITURE,
    DISCONTINUED), created one day apart in that order.
    """

    def test_the_category_filter_alone_matches_two_products(self, api, catalogue):
        """CONSUMER_GOOD returns SKU-F1 and SKU-F3 in created_at order.

        PRD: "/products` | Paginated product list, optionally filtered on `lifecycle_state`, `compliance_posture` or `product_category`."
        PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."

        Design: Corner/endpoints/ep_product_listing_filters_combine_conjunctively_with_pagination
        """
        rows, meta = _products(api, product_category=CATEGORY_CONSUMER_GOOD)
        assert meta["total_count"] == 2, f"Expected two CONSUMER_GOOD rows, got {meta}"
        assert _ids(rows) == [catalogue["p1"]["id"], catalogue["p3"]["id"]], (
            f"Expected SKU-F1 then SKU-F3, got {_ids(rows)}"
        )

    def test_adding_a_lifecycle_filter_narrows_rather_than_widens(self, api, catalogue):
        """CONSUMER_GOOD and DEVELOPMENT together leave only SKU-F1.

        PRD: "/products` | Paginated product list, optionally filtered on `lifecycle_state`, `compliance_posture` or `product_category`."
        PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."

        A union of the two filters would have returned three rows; the intersection
        returns one.

        Design: Corner/endpoints/ep_product_listing_filters_combine_conjunctively_with_pagination
        """
        rows, meta = _products(
            api,
            product_category=CATEGORY_CONSUMER_GOOD,
            lifecycle_state=LIFECYCLE_DEVELOPMENT,
        )
        assert meta["total_count"] == 1, f"Expected exactly one row, got {meta}"
        assert _ids(rows) == [catalogue["p1"]["id"]], (
            f"Expected only SKU-F1, got {_ids(rows)}"
        )

    def test_lifecycle_and_posture_filters_also_intersect(self, api, catalogue):
        """DISCONTINUED and EXPOSURE_UNKNOWN return the two discontinued rows.

        PRD: "A newly created product has `lifecycle_state` set to `DEVELOPMENT`, `compliance_posture` set to `EXPOSURE_UNKNOWN`, and every derived counter — `open_notice_count`, `accrued_penalty_cents` and `total_listed_chemical_load_ug` — set to 0."
        PRD: "The commercial dimension is a short line. Marketing a product takes `lifecycle_state` from `DEVELOPMENT` to `MARKETED`; discontinuing it takes `lifecycle_state` from either `DEVELOPMENT` or `MARKETED` to `DISCONTINUED`, which is terminal."

        Neither product has components, so both are still on the posture they were
        created with while their lifecycle has moved on independently.

        Design: Corner/endpoints/ep_product_listing_filters_combine_conjunctively_with_pagination
        """
        rows, meta = _products(
            api,
            lifecycle_state=LIFECYCLE_DISCONTINUED,
            compliance_posture=POSTURE_EXPOSURE_UNKNOWN,
        )
        assert meta["total_count"] == 2, f"Expected two discontinued rows, got {meta}"
        assert _ids(rows) == [catalogue["p3"]["id"], catalogue["p4"]["id"]], (
            f"Expected SKU-F3 then SKU-F4, got {_ids(rows)}"
        )

    def test_a_filter_matching_nothing_is_an_empty_page_not_a_not_found(
        self, api, catalogue
    ):
        """No product is MARKETED, so the collection read returns zero rows.

        PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."
        PRD: "/products` | Paginated product list, optionally filtered on `lifecycle_state`, `compliance_posture` or `product_category`."

        Design: Corner/endpoints/ep_product_listing_filters_combine_conjunctively_with_pagination
        """
        rows, meta = _products(api, lifecycle_state=LIFECYCLE_MARKETED)
        assert rows == [], f"Expected an empty data array, got {rows}"
        assert meta["total_count"] == 0, f"Expected total_count 0, got {meta}"
        assert meta["has_more"] is False, f"Expected has_more false, got {meta}"

    def test_the_page_window_reports_the_whole_unfiltered_total(self, api, catalogue):
        """limit=3 and offset=3 leaves one of the four rows and nothing beyond it.

        PRD: "Every collection read accepts two optional query parameters. `limit` defaults to 10 when omitted, has a minimum accepted value of 1 and a maximum accepted value of 200. `offset` defaults to 0 when omitted and has a minimum accepted value of 0 with no upper bound. A `limit` below 1, a `limit` above 200, or a negative `offset` is refused with `ERR_INVALID_PAGINATION` (HTTP 400)."
        PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."

        Design: Corner/endpoints/ep_product_listing_filters_combine_conjunctively_with_pagination
        """
        rows, meta = _products(api, limit=3, offset=3)
        assert meta["total_count"] == 4, f"Expected all four rows counted, got {meta}"
        assert len(rows) == 1, f"Expected one row in the window, got {_ids(rows)}"
        assert _ids(rows) == [catalogue["p4"]["id"]], (
            f"Expected the last row SKU-F4, got {_ids(rows)}"
        )
        assert meta["has_more"] is False, f"Expected has_more false, got {meta}"

    def test_the_offset_is_applied_after_filtering_not_before(self, api, catalogue):
        """Within the CONSUMER_GOOD pair, offset=1 lands on SKU-F3.

        PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending. The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."
        PRD: "/products` | Paginated product list, optionally filtered on `lifecycle_state`, `compliance_posture` or `product_category`."

        total_count is the size of the filtered set, so an offset taken over the
        whole table would have skipped past SKU-F3 entirely.

        Design: Corner/endpoints/ep_product_listing_filters_combine_conjunctively_with_pagination
        """
        rows, meta = _products(
            api, product_category=CATEGORY_CONSUMER_GOOD, limit=1, offset=1
        )
        assert meta["total_count"] == 2, f"Expected the filtered total 2, got {meta}"
        assert _ids(rows) == [catalogue["p3"]["id"]], (
            f"Expected SKU-F3 at offset 1 of the filtered set, got {_ids(rows)}"
        )
        assert meta["has_more"] is False, f"Expected has_more false, got {meta}"


class TestComplianceSummaryComputedRead:
    """GET /products/{id}/compliance-summary synthesises the defence file.

    SKU-EP4 has no components, no assessments, no determinations and no notices,
    which is the case that separates "no evidence" from "vacuously perfect".
    """

    def test_the_read_echoes_the_variant_and_the_current_logical_clock(
        self, api, bare_product
    ):
        """Without as_of_notice_id the AS_OF_TODAY variant is evaluated.

        PRD: "The compliance summary is a computed read that scores how well a product's records would hold up as a defence. It reports a `product_id`, the `variant` it evaluated, the `as_of` instant it evaluated against, an integer `defense_strength_score` from 0 to 100, the four evidence components `warning_evidence`, `assessment_evidence`, `warranty_evidence` and `recordkeeping_evidence`, and the six counts they were derived from: `required_channel_count`, `covered_channel_count`, `verified_channel_count`, `final_assessment_count`, `verified_material_count` and `active_component_count`."
        PRD: "The `AS_OF_TODAY` variant applies when the summary is requested without `as_of_notice_id`, and `as_of` is the current logical clock; every `FINAL` assessment counts regardless of its `finalized_at`, and recordkeeping evidence reads the current `disclosure_status` with no `data_received_at` cut-off."

        Design: Corner/endpoints/ep_compliance_summary_computed_read_reports_zero_evidence_and_unknown_notice_not_found
        """
        summary = get_success_data(_summary(api, bare_product["id"]))
        assert summary["product_id"] == bare_product["id"], (
            f"Expected the summary to name its product, got {summary['product_id']!r}"
        )
        assert summary["variant"] == VARIANT_AS_OF_TODAY, (
            f"Expected the AS_OF_TODAY variant, got {summary['variant']!r}"
        )
        assert_instant(summary["as_of"], DEFAULT_CLOCK, "as_of")

    def test_every_evidence_component_of_a_bare_product_is_zero(
        self, api, bare_product
    ):
        """Zero ACTIVE components forces warranty and recordkeeping to 0.0, not 1.0.

        PRD: "Each of the four components is exactly 0.0, 0.5 or 1.0. Warning evidence looks at the product's single determination in status `APPROVED`, of which at most one can exist; when there is none, or when its `required_channels` list is empty, warning evidence is 0.0. Otherwise the covered set is those entries of `required_channels` having a placement of that determination whose `status` is `IMPLEMENTED` or `VERIFIED` and whose window contains `as_of`, meaning `effective_from` is at or before `as_of` and either `effective_to` is null or `as_of` is at or before `effective_to`; the verified set is the same restricted to `status` `VERIFIED`. Warning evidence is 1.0 when the verified set covers every required channel, 0.5 when the covered set covers every required channel, and 0.0 otherwise."

        There is no APPROVED determination, so warning evidence is 0.0; there is no
        assessment at all, so assessment evidence is 0.0; and the two component-scoped
        measures are pinned at 0.0 rather than at the vacuous-truth value.

        Design: Corner/endpoints/ep_compliance_summary_computed_read_reports_zero_evidence_and_unknown_notice_not_found
        """
        summary = get_success_data(_summary(api, bare_product["id"]))
        assert_defense_components(summary, 0.0, 0.0, 0.0, 0.0)

    def test_the_weighted_score_of_a_bare_product_is_zero(self, api, bare_product):
        """Four components at 0.0 weight to an integer score of 0.

        PRD: "The four components are then weighted and summed: warning evidence carries a weight of 40, assessment evidence 25, warranty evidence 20 and recordkeeping evidence 15, for a maximum of 100. The weighted sum is rounded half up to zero decimal places, so `defense_strength_score` is always an integer between 0 and 100."

        Design: Corner/endpoints/ep_compliance_summary_computed_read_reports_zero_evidence_and_unknown_notice_not_found
        """
        summary = get_success_data(_summary(api, bare_product["id"]))
        assert summary["defense_strength_score"] == 0, (
            f"Expected score 0, got {summary['defense_strength_score']!r}"
        )

    def test_all_six_derived_counts_are_zero(self, api, bare_product):
        """The counts the components derive from are reported and all empty.

        PRD: "The compliance summary is a computed read that scores how well a product's records would hold up as a defence. It reports a `product_id`, the `variant` it evaluated, the `as_of` instant it evaluated against, an integer `defense_strength_score` from 0 to 100, the four evidence components `warning_evidence`, `assessment_evidence`, `warranty_evidence` and `recordkeeping_evidence`, and the six counts they were derived from: `required_channel_count`, `covered_channel_count`, `verified_channel_count`, `final_assessment_count`, `verified_material_count` and `active_component_count`."
        PRD: "Each of the four components is exactly 0.0, 0.5 or 1.0. Warning evidence looks at the product's single determination in status `APPROVED`, of which at most one can exist; when there is none, or when its `required_channels` list is empty, warning evidence is 0.0. Otherwise the covered set is those entries of `required_channels` having a placement of that determination whose `status` is `IMPLEMENTED` or `VERIFIED` and whose window contains `as_of`, meaning `effective_from` is at or before `as_of` and either `effective_to` is null or `as_of` is at or before `effective_to`; the verified set is the same restricted to `status` `VERIFIED`. Warning evidence is 1.0 when the verified set covers every required channel, 0.5 when the covered set covers every required channel, and 0.0 otherwise."

        Design: Corner/endpoints/ep_compliance_summary_computed_read_reports_zero_evidence_and_unknown_notice_not_found
        """
        summary = get_success_data(_summary(api, bare_product["id"]))
        assert_defense_counts(summary, 0, 0, 0, 0, 0, 0)

    def test_an_unresolvable_as_of_notice_id_is_not_found(self, api, bare_product):
        """The query-parameter foreign key is resolved, not ignored.

        PRD: "Foreign keys supplied in a request body are resolved with the same rule and the same error: `supplier_id`, `parent_material_id`, `material_id`, `chemical_id`, `assessment_id`, `material_chemical_id`, `product_id` and the `as_of_notice_id` query parameter all produce `ERR_NOT_FOUND` when they name nothing. The compliance-summary read applies an additional ownership test to `as_of_notice_id`: a notice that exists but belongs to a different product is treated as not found."
        PRD: "/products/{product_id}/compliance-summary` | Computed defence-file read returning `defense_strength_score` with its four evidence components and the counts they derive from; without `as_of_notice_id` the AS_OF_TODAY variant is evaluated against the current logical clock, and with `as_of_notice_id` the AS_OF_SERVICE_DATE variant is evaluated against that notice's `served_at` (the notice must belong to this product, otherwise `ERR_NOT_FOUND`)."

        A silent fall back to AS_OF_TODAY would have returned HTTP 200.

        Design: Corner/endpoints/ep_compliance_summary_computed_read_reports_zero_evidence_and_unknown_notice_not_found
        """
        validate_error(
            _summary(api, bare_product["id"], as_of_notice_id=UNKNOWN_ID),
            ERR_NOT_FOUND,
            404,
        )

    def test_an_unknown_product_is_not_found_and_no_read_mutates_anything(
        self, api, bare_product
    ):
        """The path identifier is resolved first, and no read bumps the version.

        PRD: "URL path parameters are resolved left to right, and each segment must resolve to a stored row of the entity that segment names before the next segment is considered. Any path identifier that fails to resolve produces `ERR_NOT_FOUND` (HTTP 404)."
        PRD: "Rules are evaluated in ascending priority order; the first rule whose condition holds short-circuits the request and returns its error, and no later rule is evaluated."

        Design: Corner/endpoints/ep_compliance_summary_computed_read_reports_zero_evidence_and_unknown_notice_not_found
        """
        before = api.product_version(bare_product["id"], COMPLIANCE_ANALYST)

        get_success_data(_summary(api, bare_product["id"]))
        validate_error(
            _summary(api, bare_product["id"], as_of_notice_id=UNKNOWN_ID),
            ERR_NOT_FOUND,
            404,
        )
        validate_error(_summary(api, OTHER_UNKNOWN_ID), ERR_NOT_FOUND, 404)

        after = api.product_version(bare_product["id"], COMPLIANCE_ANALYST)
        assert after == before, (
            f"Expected the product version to stay at {before}, got {after}"
        )


class TestMaterialChemicalLinkListings:
    """GET /material-chemicals is reachable from either side of the junction.

    RM-X declares Bisphenol A at 20.0 ppm and Cadmium at 5.0 ppm; RM-Y, a
    MANUFACTURING_AID from the same supplier, declares Bisphenol A at 3.0 ppm.
    """

    def test_the_material_side_filter_returns_both_links_of_that_material(
        self, api, junction
    ):
        """material_id collects every chemical declared in RM-X.

        PRD: "/material-chemicals` | Paginated link list, optionally filtered by `material_id`, `chemical_id`, `status` or `measurement_basis`."

        Design: Corner/endpoints/ep_material_chemical_link_listings_filter_from_both_sides
        """
        rows, meta = _links(api, material_id=junction["material_x"]["id"])
        assert meta["total_count"] == 2, f"Expected both links of RM-X, got {meta}"
        assert set(_ids(rows)) == {
            junction["link_x_bpa"]["id"],
            junction["link_x_cd"]["id"],
        }, f"Unexpected link ids: {_ids(rows)}"

    def test_the_chemical_side_filter_returns_every_material_declaring_it(
        self, api, junction
    ):
        """chemical_id collects both materials that declare Bisphenol A.

        PRD: "/material-chemicals` | Paginated link list, optionally filtered by `material_id`, `chemical_id`, `status` or `measurement_basis`."
        PRD: "The pair of `material_id` and `chemical_id` is unique, so a chemical can be declared at most once per material; a second declaration is refused with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/endpoints/ep_material_chemical_link_listings_filter_from_both_sides
        """
        rows, meta = _links(api, chemical_id=junction["bpa"]["id"])
        assert meta["total_count"] == 2, (
            f"Expected both Bisphenol A declarations, got {meta}"
        )
        assert set(_ids(rows)) == {
            junction["link_x_bpa"]["id"],
            junction["link_y_bpa"]["id"],
        }, f"Unexpected link ids: {_ids(rows)}"

    def test_filtering_by_the_pair_returns_the_one_row_that_can_exist(
        self, api, junction
    ):
        """The pair is unique, so both filters together select a single link.

        PRD: "Uniqueness constraints span five shapes and all report `ERR_DUPLICATE_RESOURCE` (HTTP 409): `chemical_name` is unique across all listed chemicals by case-sensitive exact match, `sku` is unique across all products, `legal_name` is unique across all suppliers, the pair of `material_id` and `chemical_id` is unique across all material/chemical links, and the pair of `product_id` and `material_id` is unique across product components whose status is `ACTIVE` — a component that has left `ACTIVE` no longer occupies the pair."
        PRD: "/material-chemicals` | Paginated link list, optionally filtered by `material_id`, `chemical_id`, `status` or `measurement_basis`."

        Design: Corner/endpoints/ep_material_chemical_link_listings_filter_from_both_sides
        """
        rows, meta = _links(
            api,
            material_id=junction["material_x"]["id"],
            chemical_id=junction["bpa"]["id"],
        )
        assert meta["total_count"] == 1, f"Expected exactly one link, got {meta}"
        assert _ids(rows) == [junction["link_x_bpa"]["id"]], (
            f"Expected the RM-X/Bisphenol A link, got {_ids(rows)}"
        )
        assert_concentration(rows[0]["declared_concentration_ppm"], 20.0)

    def test_no_link_is_lab_tested_before_a_result_is_reported(self, api, junction):
        """Declarations land as SUPPLIER_DECLARED, so the basis filter is empty.

        PRD: "A newly declared link starts with `measurement_basis` set to `SUPPLIER_DECLARED` and `status` set to `DECLARED`, with `lab_name`, `lab_result_ppm`, `lab_loq_ppm`, `lab_reported_at` and `dispute_note` all null."
        PRD: "/material-chemicals` | Paginated link list, optionally filtered by `material_id`, `chemical_id`, `status` or `measurement_basis`."

        Design: Corner/endpoints/ep_material_chemical_link_listings_filter_from_both_sides
        """
        rows, meta = _links(api, measurement_basis=BASIS_LAB_TESTED)
        assert rows == [], f"Expected no lab-tested links yet, got {_ids(rows)}"
        assert meta["total_count"] == 0, f"Expected total_count 0, got {meta}"
        assert (
            _read_link(api, junction["link_x_bpa"]["id"])["measurement_basis"]
            == BASIS_SUPPLIER_DECLARED
        )

    def test_the_basis_filter_follows_the_report_result_flip(self, api, junction):
        """Reporting a result moves exactly one link into the LAB_TESTED set.

        PRD: "When the laboratory answers, the same analyst reports the result, taking the link `TEST_REQUESTED → TEST_REPORTED`; that action requires all three of `lab_name`, `lab_result_ppm` and `lab_loq_ppm` in the payload, where `lab_name` identifies the analytical laboratory, `lab_result_ppm` is the reported concentration in parts per million and must not be negative, and `lab_loq_ppm` is the laboratory's limit of quantitation in parts per million and must be strictly positive. Reporting stores all three, stamps `lab_reported_at` with the current logical clock, and flips `measurement_basis` from `SUPPLIER_DECLARED` to `LAB_TESTED`, which is what makes this link admissible under the laboratory exposure method."
        PRD: "/material-chemicals` | Paginated link list, optionally filtered by `material_id`, `chemical_id`, `status` or `measurement_basis`."

        The filter has to read the flipped value rather than the one the link was
        created with, and the sibling Cadmium link must not be dragged along.

        Design: Corner/endpoints/ep_material_chemical_link_listings_filter_from_both_sides
        """
        report_lab_result(
            api, junction["link_x_bpa"]["id"], 18.0, 1.0, lab_name="Harbor Analytical"
        )

        rows, meta = _links(api, measurement_basis=BASIS_LAB_TESTED)
        assert meta["total_count"] == 1, f"Expected one lab-tested link, got {meta}"
        assert _ids(rows) == [junction["link_x_bpa"]["id"]], (
            f"Expected only the reported link, got {_ids(rows)}"
        )
        assert rows[0]["measurement_basis"] == BASIS_LAB_TESTED, (
            f"Expected LAB_TESTED, got {rows[0]['measurement_basis']!r}"
        )
        assert_instant(rows[0]["lab_reported_at"], DEFAULT_CLOCK, "lab_reported_at")
        assert (
            _read_link(api, junction["link_x_cd"]["id"])["measurement_basis"]
            == BASIS_SUPPLIER_DECLARED
        )

    def test_the_two_material_filters_are_also_conjunctive(self, api, junction):
        """supplier_id and material_class together select RM-Y alone.

        PRD: "/materials` | Paginated material list, optionally filtered by `supplier_id`, `parent_material_id`, `material_class` or `disclosure_status`."

        Both materials belong to the same supplier, so only the class narrows the
        pair down to one row.

        Design: Corner/endpoints/ep_material_chemical_link_listings_filter_from_both_sides
        """
        rows, meta = _materials(
            api,
            supplier_id=junction["supplier_id"],
            material_class=MATERIAL_CLASS_MANUFACTURING_AID,
        )
        assert meta["total_count"] == 1, f"Expected exactly RM-Y, got {meta}"
        assert _ids(rows) == [junction["material_y"]["id"]], (
            f"Expected RM-Y, got {_ids(rows)}"
        )
