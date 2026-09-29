"""Three pinned computations: a nested roll-up, a label string and a score.

The effective-concentration walk is post-order and rounds at every level, so a
grandchild is scaled twice; the label names one chemical per harm class and
assembles a byte-exact sentence; and the defence score must resolve 62.5 upwards.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_close,
    assert_defense_components,
    assert_defense_counts,
    assert_instant,
    assert_load,
    assert_status,
    assert_warning_content,
)
from test_helpers.constants import (
    BENZENE_NAME,
    BPA_NAME,
    CADMIUM_CAS,
    CADMIUM_NAME,
    CHANNEL_CATALOG,
    CHANNEL_RETAIL,
    DEFAULT_CLOCK,
    DETERMINATION_DRAFT,
    DISCLOSURE_RECEIVED,
    DISCLOSURE_VERIFIED,
    ENDPOINT_TYPE_CANCER,
    METHOD_MODELED,
    REQUIRED_CHANNEL_CATALOG,
    REQUIRED_CHANNEL_LABEL,
    RESULT_AT_OR_ABOVE,
    RESULT_BELOW,
    RESULT_NO_SAFE_HARBOR,
    ROUTE_DERMAL,
    SAFE_HARBOR_BASIS_NONE,
    VARIANT_AS_OF_TODAY,
    WARNING_TYPE_LONG,
    WARNING_WEBSITE_BASE,
    WARRANTY_STATUS_ACTIVE,
)
from test_helpers.fixtures import (
    add_component,
    add_placement,
    advance_disclosure,
    approve_determination,
    implement_placement,
    link_chemical,
    make_assessment,
    make_benzene,
    make_bpa,
    make_determination,
    make_final_assessment,
    make_listed_chemical,
    make_material,
    make_product,
    make_supplier,
    make_warranted_supplier,
    read_product,
    set_clock,
    submit_assessment,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    LABELING_SPECIALIST,
    LS_1,
)


# The one string the long-form template must produce for two named chemicals
# spanning both harm classes, trailing period included.
LONG_FORM_TEXT = (
    "WARNING: This product can expose you to chemicals including "
    "Cadmium, Bisphenol A, which are known to the State of California "
    "to cause cancer and birth defects or other reproductive harm. "
    "For more information go to https://www.P65Warnings.ca.gov."
)


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def nested_tree(api):
    """RM-PARENT 10.0 / RM-CHILD 12.5 at 0.3 / RM-GRAND 8.0 at 0.5, all VERIFIED.

    One single-component probe product per level makes each level's rolled-up
    concentration observable through ``total_listed_chemical_load_ug``.
    """
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")

    parent = make_material(api, "RM-PARENT", supplier["id"])
    child = make_material(
        api,
        "RM-CHILD",
        supplier["id"],
        parent_material_id=parent["id"],
        parent_mass_fraction=0.3,
    )
    grand = make_material(
        api,
        "RM-GRAND",
        supplier["id"],
        parent_material_id=child["id"],
        parent_mass_fraction=0.5,
    )
    for material, ppm in ((parent, 10.0), (child, 12.5), (grand, 8.0)):
        link_chemical(api, material["id"], chemical["id"], ppm)
        advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)

    probes = {}
    for key, sku, name, material in (
        ("parent", "SKU-TREE", "Nested Tree Widget", parent),
        ("child", "SKU-TREE-C", "Child Probe", child),
        ("grand", "SKU-TREE-G", "Grandchild Probe", grand),
    ):
        product = make_product(api, sku, product_name=name, annual_units=1000)
        add_component(api, product["id"], material["id"], 0.25, 0.5)
        probes[key] = product

    return {
        "chemical": chemical,
        "parent": parent,
        "child": child,
        "grand": grand,
        "probes": probes,
    }


@pytest.fixture
def label_product(api):
    """SKU-LBL with three FINAL assessments spanning both harm classes.

    Cadmium has no safe harbour at all, Benzene has a finite margin above its
    NSRL, and Bisphenol A is above its MADL — three qualifying assessments.
    """
    set_clock(api, DEFAULT_CLOCK)
    cadmium = make_listed_chemical(
        api,
        f.listed_chemical_payload(
            CADMIUM_NAME, CADMIUM_CAS, ENDPOINT_TYPE_CANCER, SAFE_HARBOR_BASIS_NONE
        ),
    )
    benzene = make_benzene(api)
    bpa = make_bpa(api)

    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    for chemical, ppm in ((cadmium, 100.0), (benzene, 800.0), (bpa, 60.0)):
        link_chemical(api, material["id"], chemical["id"], ppm)
    advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)

    product = make_product(
        api,
        "SKU-LBL",
        product_name="Label Text Widget",
        distribution_channels=f.channels(CHANNEL_RETAIL, CHANNEL_CATALOG),
        label_area_sq_in=10.0,
        annual_units=1000,
    )
    add_component(api, product["id"], material["id"], 0.25, 0.5)

    assessments = {
        key: make_final_assessment(
            api,
            product["id"],
            chemical["id"],
            method=METHOD_MODELED,
            route=ROUTE_DERMAL,
            uses_per_day=1.0,
        )
        for key, chemical in (
            ("cadmium", cadmium),
            ("benzene", benzene),
            ("bpa", bpa),
        )
    }
    return {
        "cadmium": cadmium,
        "benzene": benzene,
        "bpa": bpa,
        "material": material,
        "product": product,
        "assessments": assessments,
    }


@pytest.fixture
def partial_evidence_product(api):
    """SKU-SCORE: half credit on warning, warranty and recordkeeping, full on assessment.

    The placement is IMPLEMENTED but never VERIFIED, the warranty is active but
    passes no obligation through, and the disclosure stopped at RECEIVED.
    """
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_warranted_supplier(
        api,
        "Northgate Polymers",
        pass_through_warning_obligation=False,
        indemnity_cap_cents=5000000,
    )
    material = make_material(api, "RM-100", supplier["id"])
    link_chemical(api, material["id"], chemical["id"], 60.0)
    material = advance_disclosure(api, material["id"], DISCLOSURE_RECEIVED)

    product = make_product(
        api,
        "SKU-SCORE",
        product_name="Defense Score Widget",
        distribution_channels=f.channels(CHANNEL_RETAIL),
        annual_units=1000,
    )
    add_component(api, product["id"], material["id"], 0.25, 0.5)
    assessment = make_final_assessment(
        api,
        product["id"],
        chemical["id"],
        method=METHOD_MODELED,
        route=ROUTE_DERMAL,
        uses_per_day=1.0,
    )
    determination = make_determination(api, product["id"], assessment["id"])
    determination = approve_determination(api, determination["id"])
    placement = add_placement(
        api,
        determination["id"],
        channel=REQUIRED_CHANNEL_LABEL,
        effective_from="2026-07-01T00:00:00Z",
        placement_detail="Back panel, 6 pt bold, adjacent to net contents",
    )
    placement = implement_placement(api, placement["id"])

    return {
        "chemical": chemical,
        "supplier": supplier,
        "material": material,
        "product": product,
        "assessment": assessment,
        "determination": determination,
        "placement": placement,
    }


def _summary(api, product_id):
    return get_success_data(api.compliance_summary(product_id, COMPLIANCE_ANALYST))


def _load_of(api, product_id):
    return read_product(api, product_id)["total_listed_chemical_load_ug"]


# ─────────────────────────────────────────────────────────────────────────────
# The post-order roll-up, one level at a time
# ─────────────────────────────────────────────────────────────────────────────


class TestNestedMaterialTreeRollup:
    def test_the_leaf_level_returns_only_its_own_declared_value(self, api, nested_tree):
        """RM-GRAND has no children, so its 8.0 ppm surfaces as a load of 8.0 x 0.25 = 2.000.

        PRD: "For each such chemical-and-component pair the server evaluates the modelled effective concentration of that chemical in that component's material — the roll-up described in Section 3.5, always under the modelled variant regardless of any assessment — multiplies it by that component's `quantity_grams_per_unit`, and rounds the product half up to three decimal places."

        Design: Corner/calculations/calc_effective_concentration_rolls_up_nested_material_tree
        """
        probe = nested_tree["probes"]["grand"]
        assert_load(_load_of(api, probe["id"]), 2.000)

    def test_a_child_adds_its_own_value_to_the_scaled_grandchild(
        self, api, nested_tree
    ):
        """12.5 + 0.5 x 8.0000 = 16.5000, so the child probe reads 16.5 x 0.25 = 4.125.

        PRD: "For each child, the child's own effective concentration is computed by the same rules under the same variant and multiplied by that child's `parent_mass_fraction`, and the products are added to the running total."

        Design: Corner/calculations/calc_effective_concentration_rolls_up_nested_material_tree
        """
        probe = nested_tree["probes"]["child"]
        assert_load(_load_of(api, probe["id"]), 4.125)

    def test_the_root_scales_the_already_rolled_up_child_total(self, api, nested_tree):
        """10.0 + 0.3 x 16.5000 = 14.9500 and 14.9500 x 0.25 = 3.7375, which lands on 3.738.

        A flat roll-up that ignored RM-GRAND would give 3.438 and one that
        multiplied the two mass fractions together would give 2.800.

        PRD: "The total for the level is then rounded half up to four decimal places, and that rounded value is what the level returns to its parent."

        Design: Corner/calculations/calc_effective_concentration_rolls_up_nested_material_tree
        """
        probe = nested_tree["probes"]["parent"]
        load = _load_of(api, probe["id"])
        assert_load(load, 3.738)
        assert load != pytest.approx(3.438, abs=1e-6), (
            "3.438 means the grandchild level was never walked"
        )
        assert load != pytest.approx(2.800, abs=1e-6), (
            "2.800 means the mass fractions were multiplied instead of nested"
        )

    def test_the_three_levels_agree_with_the_depths_that_produced_them(
        self, api, nested_tree
    ):
        """The chain reads depth 0, 1, 2 and the probes read 3.738, 4.125, 2.000 together.

        PRD: "Rounding is therefore applied once per tree level, in post-order — not once at the end of the whole walk."

        Design: Corner/calculations/calc_effective_concentration_rolls_up_nested_material_tree
        """
        assert nested_tree["parent"]["bom_depth"] == 0
        assert nested_tree["child"]["bom_depth"] == 1
        assert nested_tree["grand"]["bom_depth"] == 2
        assert_load(_load_of(api, nested_tree["probes"]["parent"]["id"]), 3.738)
        assert_load(_load_of(api, nested_tree["probes"]["child"]["id"]), 4.125)
        assert_load(_load_of(api, nested_tree["probes"]["grand"]["id"]), 2.000)

    def test_the_rolled_up_root_drives_one_dermal_contribution(self, api, nested_tree):
        """14.9500 x 0.25 x 0.5 x 0.10 x 1.0 = 0.186875, so exposure is 0.187 from one component.

        PRD: "Otherwise the server multiplies together five factors — the effective concentration, the component's `quantity_grams_per_unit`, the component's `contact_factor`, the absorption factor for the assessment's `route`, and the assessment's `uses_per_day` — and rounds that product half up to three decimal places, giving one per-component contribution."

        Design: Corner/calculations/calc_effective_concentration_rolls_up_nested_material_tree
        """
        probe = nested_tree["probes"]["parent"]
        assessment = make_assessment(
            api,
            probe["id"],
            nested_tree["chemical"]["id"],
            method=METHOD_MODELED,
            route=ROUTE_DERMAL,
            uses_per_day=1.0,
        )
        submitted = submit_assessment(api, assessment["id"])
        assert_assessment_verdict(submitted, 0.187, 0.3740, RESULT_BELOW, 1)


# ─────────────────────────────────────────────────────────────────────────────
# One chemical per harm class, and a byte-exact sentence
# ─────────────────────────────────────────────────────────────────────────────


class TestLongFormWarningContent:
    def test_the_three_qualifying_assessments_carry_three_verdicts(
        self, api, label_product
    ):
        """Cadmium has no level to compare against, so its margin is null and its verdict adverse.

        PRD: "When the chemical's `safe_harbor_basis` is `NONE` there is no level to compare against: `margin_ratio` is set to null and `result` is set to `NO_SAFE_HARBOR`, which is the most adverse of the three verdicts because it means no exposure is presumptively safe."

        Design: Corner/calculations/calc_warning_text_long_form_names_one_chemical_per_harm_class
        """
        assessments = label_product["assessments"]
        assert_assessment_verdict(
            assessments["cadmium"], 1.250, None, RESULT_NO_SAFE_HARBOR, 1
        )
        assert_assessment_verdict(
            assessments["benzene"], 10.000, 1.5625, RESULT_AT_OR_ABOVE, 1
        )
        assert_assessment_verdict(
            assessments["bpa"], 0.750, 1.5000, RESULT_AT_OR_ABOVE, 1
        )

    def test_one_chemical_is_named_per_harm_class_with_cancer_first(
        self, api, label_product
    ):
        """Cadmium outranks Benzene on the no-safe-harbour key, and the cancer name leads.

        PRD: "The ranking is: assessments whose `result` is `NO_SAFE_HARBOR` outrank every assessment with a finite `margin_ratio`; among the remainder, a larger `margin_ratio` outranks a smaller one; the first tie-break is the chemical's `safe_harbor_level_ug_per_day` ascending, with a null level sorting ahead of every numeric level; the second tie-break is the chemical's `chemical_name` ascending."

        Design: Corner/calculations/calc_warning_text_long_form_names_one_chemical_per_harm_class
        """
        determination = make_determination(
            api,
            label_product["product"]["id"],
            label_product["assessments"]["benzene"]["id"],
        )
        assert determination["named_chemicals"] == [CADMIUM_NAME, BPA_NAME]
        assert BENZENE_NAME not in determination["named_chemicals"]

    def test_the_assembled_long_form_string_is_byte_exact(self, api, label_product):
        """Ten square inches and no occupancy take the long form, plural verb and closing period.

        PRD: "The sixth step assembles `warning_text`, and the assembly is byte-exact — including the trailing period on the long and occupancy formats, which the short format does not carry."

        Design: Corner/calculations/calc_warning_text_long_form_names_one_chemical_per_harm_class
        """
        determination = make_determination(
            api,
            label_product["product"]["id"],
            label_product["assessments"]["benzene"]["id"],
        )
        assert_warning_content(
            determination,
            WARNING_TYPE_LONG,
            True,
            [CADMIUM_NAME, BPA_NAME],
            WARNING_WEBSITE_BASE,
            LONG_FORM_TEXT,
            [REQUIRED_CHANNEL_LABEL, REQUIRED_CHANNEL_CATALOG],
        )

    def test_the_required_channels_follow_the_pinned_order(self, api, label_product):
        """RETAIL and CATALOG map to LABEL then CATALOG, and nothing else is required.

        PRD: "The seventh step fills `required_channels`, the placement channels this determination must cover, in the pinned order `LABEL`, `CATALOG`, `INTERNET_POS`, `POSTED_SIGN`. `LABEL` is included when the product's `distribution_channels` contains `RETAIL`; `CATALOG` when it contains `CATALOG`; `INTERNET_POS` when it contains `INTERNET`; and `POSTED_SIGN` is appended when the product's `occupancy_type` is anything other than `NONE`."

        Design: Corner/calculations/calc_warning_text_long_form_names_one_chemical_per_harm_class
        """
        determination = make_determination(
            api,
            label_product["product"]["id"],
            label_product["assessments"]["benzene"]["id"],
        )
        assert determination["required_channels"] == [
            REQUIRED_CHANNEL_LABEL,
            REQUIRED_CHANNEL_CATALOG,
        ]

    def test_the_fresh_determination_is_a_draft_prepared_by_its_author(
        self, api, label_product
    ):
        """Content selection runs at create time, on a row that is still only a DRAFT.

        PRD: "The computation runs at create time and again on approval, against the data current at that moment, and it proceeds in seven steps."

        Design: Corner/calculations/calc_warning_text_long_form_names_one_chemical_per_harm_class
        """
        determination = make_determination(
            api,
            label_product["product"]["id"],
            label_product["assessments"]["benzene"]["id"],
            headers=LABELING_SPECIALIST,
        )
        assert_status(determination, DETERMINATION_DRAFT)
        assert determination["prepared_by_user_id"] == LS_1
        assert determination["warning_text"] == LONG_FORM_TEXT


# ─────────────────────────────────────────────────────────────────────────────
# 62.5 must resolve upwards
# ─────────────────────────────────────────────────────────────────────────────


class TestDefenseScoreHalfUp:
    def test_the_summary_reads_the_today_variant_at_the_current_clock(
        self, api, partial_evidence_product
    ):
        """No as_of_notice_id was supplied, so the evaluation instant is the logical clock.

        PRD: "The `AS_OF_TODAY` variant applies when the summary is requested without `as_of_notice_id`, and `as_of` is the current logical clock; every `FINAL` assessment counts regardless of its `finalized_at`, and recordkeeping evidence reads the current `disclosure_status` with no `data_received_at` cut-off."

        Design: Corner/calculations/calc_defense_score_rounds_half_up_partial_evidence_to_63
        """
        product_id = partial_evidence_product["product"]["id"]
        summary = _summary(api, product_id)
        assert summary["product_id"] == product_id
        assert summary["variant"] == VARIANT_AS_OF_TODAY
        assert_instant(summary["as_of"], DEFAULT_CLOCK, "as_of")

    def test_an_implemented_but_unverified_channel_is_half_credit(
        self, api, partial_evidence_product
    ):
        """LABEL is covered but not verified, so warning evidence stops at 0.5 while assessment is full.

        PRD: "Warning evidence is 1.0 when the verified set covers every required channel, 0.5 when the covered set covers every required channel, and 0.0 otherwise."

        Design: Corner/calculations/calc_defense_score_rounds_half_up_partial_evidence_to_63
        """
        summary = _summary(api, partial_evidence_product["product"]["id"])
        assert_close(summary["warning_evidence"], 0.5, 2, "warning_evidence")
        assert_close(summary["assessment_evidence"], 1.0, 2, "assessment_evidence")

    def test_the_warranty_half_credit_turns_on_the_pass_through_alone(
        self, api, partial_evidence_product
    ):
        """The warranty is ACTIVE, in window and covers RAW_MATERIAL, and still only earns 0.5.

        PRD: "Warranty evidence looks at the materials of the product's `ACTIVE` components: with zero such components it is 0.0; it is 1.0 when every one of those materials has a supplier whose `warranty_status` is `ACTIVE`, whose half-open warranty window covers `as_of`, whose `warranty_scope` covers the material's `material_class`, and whose `pass_through_warning_obligation` is true; it is 0.5 when all of those hold except the pass-through obligation; and 0.0 otherwise."

        Design: Corner/calculations/calc_defense_score_rounds_half_up_partial_evidence_to_63
        """
        supplier = partial_evidence_product["supplier"]
        assert supplier["warranty_status"] == WARRANTY_STATUS_ACTIVE
        assert supplier["pass_through_warning_obligation"] is False
        summary = _summary(api, partial_evidence_product["product"]["id"])
        assert_close(summary["warranty_evidence"], 0.5, 2, "warranty_evidence")

    def test_a_received_disclosure_is_the_lower_recordkeeping_tier(
        self, api, partial_evidence_product
    ):
        """RECEIVED clears the 0.5 tier but not the VERIFIED tier the full credit needs.

        PRD: "Recordkeeping evidence is 0.0 when there are no `ACTIVE` components; under `AS_OF_TODAY` it is 1.0 when every one of those materials has `disclosure_status` `VERIFIED`, 0.5 when every one is `RECEIVED` or `VERIFIED`, and 0.0 otherwise; under `AS_OF_SERVICE_DATE` the same two tiers apply but each material must additionally have a non-null `data_received_at` at or before `as_of`, and 0.0 otherwise."

        Design: Corner/calculations/calc_defense_score_rounds_half_up_partial_evidence_to_63
        """
        assert (
            partial_evidence_product["material"]["disclosure_status"]
            == DISCLOSURE_RECEIVED
        )
        summary = _summary(api, partial_evidence_product["product"]["id"])
        assert_close(summary["recordkeeping_evidence"], 0.5, 2, "recordkeeping_evidence")
        assert_defense_components(summary, 0.5, 1.0, 0.5, 0.5)

    def test_the_weighted_sum_of_sixty_two_and_a_half_becomes_sixty_three(
        self, api, partial_evidence_product
    ):
        """40x0.5 + 25x1.0 + 20x0.5 + 15x0.5 = 62.5, and half up makes that an integer 63.

        PRD: "The weighted sum is rounded half up to zero decimal places, so `defense_strength_score` is always an integer between 0 and 100."

        Design: Corner/calculations/calc_defense_score_rounds_half_up_partial_evidence_to_63
        """
        summary = _summary(api, partial_evidence_product["product"]["id"])
        score = summary["defense_strength_score"]
        assert isinstance(score, int) and not isinstance(score, bool), (
            f"defense_strength_score must be an integer, got {score!r}"
        )
        assert score == 63, f"Expected 62.5 to round half up to 63, got {score}"

    def test_the_six_counts_the_score_was_derived_from(
        self, api, partial_evidence_product
    ):
        """One required channel covered but unverified, one final assessment, no verified material.

        PRD: "It reports a `product_id`, the `variant` it evaluated, the `as_of` instant it evaluated against, an integer `defense_strength_score` from 0 to 100, the four evidence components `warning_evidence`, `assessment_evidence`, `warranty_evidence` and `recordkeeping_evidence`, and the six counts they were derived from: `required_channel_count`, `covered_channel_count`, `verified_channel_count`, `final_assessment_count`, `verified_material_count` and `active_component_count`."

        Design: Corner/calculations/calc_defense_score_rounds_half_up_partial_evidence_to_63
        """
        summary = _summary(api, partial_evidence_product["product"]["id"])
        assert_defense_counts(summary, 1, 1, 0, 1, 0, 1)
