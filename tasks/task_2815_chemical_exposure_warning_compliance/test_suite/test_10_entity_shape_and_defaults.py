"""What a create returns, what it defaults to, and what it refuses outright.

Derived fields on a fresh row, dormant warranty defaults, the derived bill of
materials depth, and the four shapes of refusal that guard the graph: unresolved
identifiers, missing inputs, out-of-range numbers, duplicate pairs and cycles.
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
    ERR_ENTITY_IMMUTABLE,
    ERR_INVALID_REQUEST,
    ERR_MATERIAL_CYCLE,
    ERR_NOT_FOUND,
    ERR_VALUE_OUT_OF_RANGE,
)
from test_helpers.assertions import (
    assert_concentration,
    assert_created_row,
    assert_fields_null,
    assert_lifecycle,
    assert_status,
)
from test_helpers.constants import (
    BASIS_SUPPLIER_DECLARED,
    CHEMICAL_STATUS_PROPOSED,
    DEFAULT_CLOCK,
    ENDPOINT_TYPE_REPRODUCTIVE_FEMALE,
    HARM_CLASS_REPRODUCTIVE,
    LIFECYCLE_DISCONTINUED,
    LINK_STATUS_DECLARED,
    WARRANTY_STATUS_NONE,
)
from test_helpers.fixtures import (
    discontinue_product,
    link_chemical,
    make_bpa,
    make_material,
    make_product,
    make_supplier,
    set_clock,
)
from test_helpers.test_users import COMPLIANCE_ANALYST, REGISTRY_ADMIN


# A syntactically valid UUID that no row in an empty database can carry.
MISSING_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


@pytest.fixture
def clocked(api):
    """Every entity probe starts from the same logical clock and an empty database."""
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def supplier_with_material(api, clocked):
    """One supplier and one raw material, the smallest graph a link can hang from."""
    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    return {"supplier": supplier, "material": material}


# ─────────────────────────────────────────────────────────────────────────────
# What a create returns
# ─────────────────────────────────────────────────────────────────────────────


class TestListedChemicalCreate:
    def test_the_harm_class_is_derived_from_the_endpoint_type(self, api, clocked):
        """REPRODUCTIVE_FEMALE collapses to the REPRODUCTIVE harm class, not to its own name.

        PRD: "From it the server derives `harm_class`, which is `CANCER` when `endpoint_type` is `CANCER` and `REPRODUCTIVE` for all three of the other endpoints; `harm_class` is therefore always one of `CANCER` or `REPRODUCTIVE`, and it is what later drives named-chemical grouping and harm-clause wording on labels."

        Design: Corner/entities/entity_listed_chemical_create_returns_computed_and_system_fields
        """
        chemical = make_bpa(api, list_it=False)
        assert chemical["endpoint_type"] == ENDPOINT_TYPE_REPRODUCTIVE_FEMALE
        assert chemical["harm_class"] == HARM_CLASS_REPRODUCTIVE

    def test_a_fresh_registration_is_proposed_with_no_listing_dates(self, api, clocked):
        """Registration is not listing: the row starts PROPOSED with both date fields null.

        PRD: "A newly registered chemical is created with `status` set to `PROPOSED` and `revision_count` set to 0, with `listing_effective_date` and `warning_required_from` both null."

        Design: Corner/entities/entity_listed_chemical_create_returns_computed_and_system_fields
        """
        chemical = make_bpa(api, list_it=False)
        assert_status(chemical, CHEMICAL_STATUS_PROPOSED)
        assert chemical["revision_count"] == 0
        assert_fields_null(chemical, ["listing_effective_date", "warning_required_from"])
        assert_created_row(chemical)


class TestProductListing:
    def test_the_page_envelope_counts_the_whole_matching_set(self, api, clocked):
        """total_count stays 3 across both pages while has_more flips as the window advances.

        PRD: "The `meta` object of a list response carries `limit` (the effective page size), `offset` (the effective starting index), `total_count` (the number of rows matching the filters before the page window is applied) and `has_more` (true when rows remain beyond the current window)."

        Design: Corner/entities/entity_products_list_paginates_with_total_count_and_has_more
        """
        for sku, name in (("SKU-P1", "Cleaner A"), ("SKU-P2", "Cleaner B"), ("SKU-P3", "Cleaner C")):
            make_product(api, sku, product_name=name, annual_units=1000)

        rows, meta = validate_paginated(
            api.list_products(REGISTRY_ADMIN, f.page(limit=2, offset=0))
        )
        assert len(rows) == 2
        assert meta["total_count"] == 3
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["has_more"] is True

        rows, meta = validate_paginated(
            api.list_products(REGISTRY_ADMIN, f.page(limit=2, offset=2))
        )
        assert len(rows) == 1
        assert meta["total_count"] == 3
        assert meta["offset"] == 2
        assert meta["has_more"] is False


class TestSupplierDefaults:
    def test_warranty_status_is_always_none_at_onboarding(self, api, clocked):
        """A supplier cannot be born under warranty, whatever the create body asked for.

        PRD: "Warranty terms may be supplied at onboarding but stay dormant: `warranty_scope`, `pass_through_warning_obligation`, `indemnity_cap_cents`, `warranty_effective_from` and `warranty_effective_to` are all optional at create time, and `warranty_status` is always set to `NONE` regardless of what was supplied."

        Design: Corner/entities/entity_supplier_defaults_applied_when_warranty_fields_omitted
        """
        supplier = make_supplier(api, "Bare Minimum Chemicals")
        assert supplier["warranty_status"] == WARRANTY_STATUS_NONE
        assert_created_row(supplier)

    def test_the_omitted_warranty_terms_default_to_nothing(self, api, clocked):
        """False, zero and three nulls — the defaults that contribute no warranty defence.

        PRD: "`pass_through_warning_obligation` defaults to false, `indemnity_cap_cents` defaults to 0 and must never be negative, and `warranty_scope`, `warranty_effective_from` and `warranty_effective_to` all default to null."

        Design: Corner/entities/entity_supplier_defaults_applied_when_warranty_fields_omitted
        """
        supplier = make_supplier(api, "Bare Minimum Chemicals")
        assert supplier["pass_through_warning_obligation"] is False
        assert supplier["indemnity_cap_cents"] == 0
        assert_fields_null(
            supplier,
            ["warranty_scope", "warranty_effective_from", "warranty_effective_to"],
        )


class TestBomDepth:
    def test_depth_counts_ancestors_one_level_at_a_time(self, api, clocked):
        """A three-material chain reads 0, 1 and 2, and the listing filters by parent.

        PRD: "`bom_depth` is derived, never supplied: it is 0 for a material whose `parent_material_id` is null, and otherwise one more than its parent's `bom_depth`."

        Design: Corner/entities/entity_material_bom_depth_computed_from_parent_chain
        """
        supplier = make_supplier(api, "Northgate Polymers")
        top = make_material(api, "RM-TOP", supplier["id"])
        mid = make_material(
            api,
            "RM-MID",
            supplier["id"],
            parent_material_id=top["id"],
            parent_mass_fraction=0.5,
        )
        leaf = make_material(
            api,
            "RM-LEAF",
            supplier["id"],
            parent_material_id=mid["id"],
            parent_mass_fraction=0.25,
        )
        assert top["bom_depth"] == 0
        assert top["parent_material_id"] is None
        assert mid["bom_depth"] == 1
        assert mid["parent_mass_fraction"] == pytest.approx(0.5, abs=1e-9)
        assert leaf["bom_depth"] == 2
        assert leaf["parent_mass_fraction"] == pytest.approx(0.25, abs=1e-9)

        rows, _ = validate_paginated(
            api.list_materials(
                COMPLIANCE_ANALYST, f.page(parent_material_id=top["id"])
            )
        )
        assert [row["id"] for row in rows] == [mid["id"]]


# ─────────────────────────────────────────────────────────────────────────────
# What a create refuses
# ─────────────────────────────────────────────────────────────────────────────


class TestUnresolvedIdentifiers:
    def test_an_unknown_material_path_id_is_a_not_found(self, api, clocked):
        """A well-formed UUID that names nothing is a 404, never an empty success body.

        PRD: "Any path identifier that fails to resolve produces `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/entity_get_material_with_unknown_id_returns_not_found
        """
        validate_error(
            api.get_material(MISSING_ID, COMPLIANCE_ANALYST), ERR_NOT_FOUND, 404
        )

    def test_an_unknown_body_foreign_key_is_the_same_not_found(self, api, clocked):
        """The component's material_id resolves to nothing, so no dangling row is created.

        PRD: "Foreign keys supplied in a request body are resolved with the same rule and the same error: `supplier_id`, `parent_material_id`, `material_id`, `chemical_id`, `assessment_id`, `material_chemical_id`, `product_id` and the `as_of_notice_id` query parameter all produce `ERR_NOT_FOUND` when they name nothing."

        Design: Corner/entities/entity_component_create_with_unknown_material_returns_not_found
        """
        product = make_product(
            api, "SKU-FK", product_name="Dangling Test", annual_units=1000
        )
        validate_error(
            api.create_component(
                product["id"],
                f.component_payload(MISSING_ID, 0.25, 0.5),
                COMPLIANCE_ANALYST,
            ),
            ERR_NOT_FOUND,
            404,
        )
        rows, meta = validate_paginated(
            api.list_components(COMPLIANCE_ANALYST, f.page(product_id=product["id"]))
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestRequiredAndRangedInputs:
    def test_a_product_without_annual_units_is_refused(self, api, clocked):
        """annual_units is an input with no default, so omitting it cannot become a silent 0.

        PRD: "Products are created by a `RegistryAdmin` from a `sku` of one to forty characters unique across all products, a `product_name` of one to one hundred and sixty characters, a `product_category`, a non-empty `distribution_channels` array with no duplicates, a strictly positive `label_area_sq_in` measured in square inches, and a non-negative `annual_units` count of units sold into California per year."

        Design: Corner/entities/entity_product_create_missing_required_annual_units
        """
        validate_error(
            api.create_product(
                f.product_payload(
                    "SKU-MISSING", product_name="No Units", annual_units=f.OMIT
                ),
                REGISTRY_ADMIN,
            ),
            ERR_INVALID_REQUEST,
            400,
        )
        _, meta = validate_paginated(api.list_products(REGISTRY_ADMIN))
        assert meta["total_count"] == 0

    def test_a_negative_concentration_is_refused_but_zero_is_legal(
        self, api, supplier_with_material
    ):
        """-1.0 ppm is out of range and is not clamped; 0.0 ppm stores as a declared link.

        PRD: "The numeric-domain rule at position 5 covers, specifically: a `safe_harbor_level_ug_per_day` that is zero or negative while the basis is not `NONE`; a negative `declared_concentration_ppm`; a negative `lab_result_ppm`; a `lab_loq_ppm` that is zero or negative; a `quantity_grams_per_unit` that is zero or negative; a `uses_per_day` that is zero or negative; a `label_area_sq_in` that is zero or negative; a negative `annual_units`; a negative `alleged_units`; a negative `requested_attorney_fees_cents`; a negative `indemnity_cap_cents`; and a negative `target_concentration_ppm`."

        Design: Corner/entities/entity_material_chemical_negative_concentration_rejected
        """
        chemical = make_bpa(api)
        material = supplier_with_material["material"]
        validate_error(
            api.create_material_chemical(
                material["id"],
                f.material_chemical_payload(chemical["id"], -1.0),
                COMPLIANCE_ANALYST,
            ),
            ERR_VALUE_OUT_OF_RANGE,
            422,
        )
        _, meta = validate_paginated(
            api.list_material_chemicals(
                COMPLIANCE_ANALYST, f.page(material_id=material["id"])
            )
        )
        assert meta["total_count"] == 0

        link = link_chemical(api, material["id"], chemical["id"], 0.0)
        assert_concentration(link["declared_concentration_ppm"], 0.0, "declared ppm")
        assert link["measurement_basis"] == BASIS_SUPPLIER_DECLARED
        assert_status(link, LINK_STATUS_DECLARED)


class TestUniquenessAndImmutability:
    def test_a_second_link_for_the_same_pair_is_a_duplicate(
        self, api, supplier_with_material
    ):
        """The junction is keyed on the material and chemical pair, so the second create is a 409.

        PRD: "Uniqueness constraints span five shapes and all report `ERR_DUPLICATE_RESOURCE` (HTTP 409): `chemical_name` is unique across all listed chemicals by case-sensitive exact match, `sku` is unique across all products, `legal_name` is unique across all suppliers, the pair of `material_id` and `chemical_id` is unique across all material/chemical links, and the pair of `product_id` and `material_id` is unique across product components whose status is `ACTIVE` — a component that has left `ACTIVE` no longer occupies the pair."

        Design: Corner/entities/entity_duplicate_material_chemical_pair_rejected
        """
        chemical = make_bpa(api)
        material = supplier_with_material["material"]
        first = link_chemical(api, material["id"], chemical["id"], 40.0)
        validate_error(
            api.create_material_chemical(
                material["id"],
                f.material_chemical_payload(chemical["id"], 55.0),
                COMPLIANCE_ANALYST,
            ),
            ERR_DUPLICATE_RESOURCE,
            409,
        )
        stored = get_success_data(
            api.get_material_chemical(first["id"], COMPLIANCE_ANALYST)
        )
        assert_concentration(stored["declared_concentration_ppm"], 40.0, "declared ppm")
        _, meta = validate_paginated(
            api.list_material_chemicals(
                COMPLIANCE_ANALYST, f.page(material_id=material["id"])
            )
        )
        assert meta["total_count"] == 1

    def test_a_discontinued_product_refuses_the_whole_update(self, api, clocked):
        """The terminal lifecycle state freezes the row, so the rename never lands.

        PRD: "Neither state dimension is writable: supplying `lifecycle_state` or `compliance_posture` is rejected with `ERR_FIELD_NOT_WRITABLE`, and a `DISCONTINUED` product rejects the whole update with `ERR_ENTITY_IMMUTABLE`."

        Design: Corner/entities/entity_patch_discontinued_product_rejected_as_immutable
        """
        product = make_product(
            api, "SKU-DISC", product_name="Retired Kit", annual_units=1000
        )
        discontinue_product(api, product["id"])
        validate_error(
            api.patch_product(
                product["id"], {"product_name": "Renamed Kit"}, REGISTRY_ADMIN
            ),
            ERR_ENTITY_IMMUTABLE,
            409,
        )
        stored = get_success_data(api.get_product(product["id"], REGISTRY_ADMIN))
        assert stored["product_name"] == "Retired Kit"
        assert_lifecycle(stored, LIFECYCLE_DISCONTINUED)

    def test_neither_form_of_cycle_may_be_created_by_reparenting(self, api, clocked):
        """Re-parenting under a descendant and naming itself as parent are the same refusal.

        PRD: "The same error, `ERR_MATERIAL_CYCLE`, also covers the cycle case: naming the material itself as its own parent, or naming any material that is already one of its own descendants."

        Design: Corner/entities/entity_material_parent_cycle_rejected
        """
        supplier = make_supplier(api, "Northgate Polymers")
        top = make_material(api, "RM-TOP", supplier["id"])
        mid = make_material(
            api,
            "RM-MID",
            supplier["id"],
            parent_material_id=top["id"],
            parent_mass_fraction=0.5,
        )
        for parent_id in (mid["id"], top["id"]):
            validate_error(
                api.patch_material(
                    top["id"],
                    {"parent_material_id": parent_id, "parent_mass_fraction": 0.5},
                    COMPLIANCE_ANALYST,
                ),
                ERR_MATERIAL_CYCLE,
                422,
            )

        stored_top = get_success_data(api.get_material(top["id"], COMPLIANCE_ANALYST))
        assert stored_top["parent_material_id"] is None
        assert stored_top["bom_depth"] == 0
        stored_mid = get_success_data(api.get_material(mid["id"], COMPLIANCE_ANALYST))
        assert stored_mid["bom_depth"] == 1
