"""Two calculations that read the same stored rows and answer differently.

The exposure pair diverges on a data-substitution rule; the defence-file pair
diverges on the instant it is evaluated against.
"""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_defense_components,
    assert_defense_counts,
    assert_exposure,
    assert_instant,
)
from test_helpers.constants import (
    BASIS_LAB_TESTED,
    DECISION_WARNING_REQUIRED,
    DEFAULT_CLOCK,
    DISCLOSURE_INCOMPLETE,
    DISCLOSURE_VERIFIED,
    METHOD_LAB_TESTED,
    METHOD_MODELED,
    REQUIRED_CHANNEL_LABEL,
    RESULT_AT_OR_ABOVE,
    RESULT_BELOW,
    ROUTE_DERMAL,
    VARIANT_AS_OF_SERVICE_DATE,
    VARIANT_AS_OF_TODAY,
    WARRANTY_SCOPE_ALL_MATERIALS,
)
from test_helpers.fixtures import (
    add_component,
    advance_disclosure,
    approve_determination,
    finalize_assessment,
    implement_placement,
    add_placement,
    link_chemical,
    make_assessment,
    make_bpa,
    make_determination,
    make_material,
    make_notice,
    make_product,
    make_supplier,
    make_warranted_supplier,
    report_lab_result,
    set_clock,
    verify_placement,
)
from test_helpers.test_users import COMPLIANCE_ANALYST
from prd_bench_local_runner.testing import get_success_data, validate_success

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def incomplete_disclosure_product(api):
    """RM-100 declares 40.0 ppm, its disclosure is INCOMPLETE and it is lab tested.

    The laboratory figure (40.0 ppm, limit of quantitation 1.0 ppm) and the
    disclosure gap are both on file at once, so the two exposure variants read
    identical rows and must still disagree.
    """
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    link = link_chemical(api, material["id"], chemical["id"], 40.0)
    advance_disclosure(api, material["id"], DISCLOSURE_INCOMPLETE)
    link = report_lab_result(
        api, link["id"], 40.0, 1.0, lab_name="Cascade Analytical"
    )
    product = make_product(
        api, "SKU-DV1", product_name="Grip Trainer", annual_units=50000
    )
    component = add_component(api, product["id"], material["id"], 0.25, 0.5)
    return {
        "chemical": chemical,
        "material": material,
        "link": link,
        "product": product,
        "component": component,
    }


@pytest.fixture
def non_detect_product(api):
    """RM-200 is VERIFIED and its laboratory result 4.0 ppm sits below the 8.0 ppm limit."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Basalt Coatings")
    material = make_material(api, "RM-200", supplier["id"])
    link = link_chemical(api, material["id"], chemical["id"], 40.0)
    advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)
    link = report_lab_result(
        api, link["id"], 4.0, 8.0, lab_name="Cascade Analytical"
    )
    product = make_product(
        api, "SKU-DV3", product_name="Shelf Liner", annual_units=50000
    )
    component = add_component(api, product["id"], material["id"], 0.25, 0.5)
    return {
        "chemical": chemical,
        "material": material,
        "link": link,
        "product": product,
        "component": component,
    }


@pytest.fixture
def defense_file_product(api):
    """A complete defence file whose every artefact post-dates the notice's service.

    The warranty window opens 2026-01-01, the disclosure lands 2026-07-10, the
    assessment is finalized 2026-07-15 and the verified placement takes effect
    2026-06-01, while the notice was served 2026-05-01.
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    chemical = make_bpa(api)
    supplier = make_warranted_supplier(
        api,
        "Northgate Polymers",
        warranty_scope=WARRANTY_SCOPE_ALL_MATERIALS,
        pass_through_warning_obligation=True,
        indemnity_cap_cents=500000000,
        warranty_effective_from="2026-01-01T00:00:00Z",
    )
    material = make_material(api, "RM-100", supplier["id"])
    link = link_chemical(api, material["id"], chemical["id"], 40.0)
    get_success_data(
        api.material_disclosure(
            material["id"], f.action_payload("REQUEST"), COMPLIANCE_ANALYST
        )
    )

    set_clock(api, "2026-07-10T00:00:00Z")
    get_success_data(
        api.material_disclosure(
            material["id"], f.record_response_action("COMPLETE"), COMPLIANCE_ANALYST
        )
    )
    material = get_success_data(
        api.material_disclosure(
            material["id"], f.action_payload("VERIFY"), COMPLIANCE_ANALYST
        )
    )

    product = make_product(
        api, "SKU-DEF1", product_name="Cabinet Pull", annual_units=50000
    )
    component = add_component(api, product["id"], material["id"], 0.25, 0.5)
    assessment = make_assessment(
        api, product["id"], chemical["id"], METHOD_MODELED, ROUTE_DERMAL, 1.0
    )

    set_clock(api, "2026-07-15T00:00:00Z")
    assessment = finalize_assessment(api, assessment["id"])
    determination = make_determination(
        api, product["id"], assessment["id"], DECISION_WARNING_REQUIRED
    )
    determination = approve_determination(api, determination["id"])
    placement = add_placement(
        api,
        determination["id"],
        REQUIRED_CHANNEL_LABEL,
        "2026-06-01T00:00:00Z",
        placement_detail="Back panel warning block",
    )
    implement_placement(api, placement["id"])
    placement = verify_placement(api, placement["id"])
    notice = make_notice(
        api,
        product["id"],
        chemical["id"],
        earliest_violation_date="2026-04-01T00:00:00Z",
        served_at="2026-05-01T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )

    set_clock(api, DEFAULT_CLOCK)
    return {
        "chemical": chemical,
        "supplier": supplier,
        "material": material,
        "link": link,
        "product": product,
        "component": component,
        "assessment": assessment,
        "determination": determination,
        "placement": placement,
        "notice": notice,
    }


# ─────────────────────────────────────────────────────────────────────────────
# The exposure variants on a disclosure gap
# ─────────────────────────────────────────────────────────────────────────────


class TestDisclosureGapDivergence:
    def test_modelled_variant_substitutes_the_worst_case_default(
        self, api, incomplete_disclosure_product
    ):
        """An INCOMPLETE disclosure forces 250.0 ppm even though a laboratory figure is on file.

        PRD: "An incomplete response has a specific modelling consequence: from that point on, every modelled exposure recomputation for products holding this material substitutes the modelled default concentration for this material's own contribution."

        Design: Difficulty/dual_variant_calc/modeled_vs_lab_tested_diverge_on_incomplete_disclosure
        """
        bundle = incomplete_disclosure_product
        assessment = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_DERMAL,
            1.0,
        )
        # 250.0 ppm x 0.25 g x 0.5 contact x 0.10 dermal x 1 use = 3.125 ug/day.
        assert_assessment_verdict(assessment, 3.125, 6.25, RESULT_AT_OR_ABOVE, 1)

    def test_laboratory_variant_ignores_the_disclosure_gap(
        self, api, incomplete_disclosure_product
    ):
        """The laboratory method reads the reported 40.0 ppm and never sees the disclosure state.

        PRD: "Under the **laboratory** variant the own contribution is decided differently, and `disclosure_status` is ignored entirely on the principle that measured data supersedes supplier gaps."

        Design: Difficulty/dual_variant_calc/modeled_vs_lab_tested_diverge_on_incomplete_disclosure
        """
        bundle = incomplete_disclosure_product
        assessment = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_LAB_TESTED,
            ROUTE_DERMAL,
            1.0,
        )
        # 40.0 ppm x 0.25 g x 0.5 contact x 0.10 dermal x 1 use = 0.500 ug/day.
        assert_assessment_verdict(assessment, 0.5, 1.0, RESULT_AT_OR_ABOVE, 1)

    def test_both_variants_read_one_unchanged_pair_of_rows(
        self, api, incomplete_disclosure_product
    ):
        """A 6.25x gap opens on stored rows that neither assessment altered.

        PRD: "It is evaluated for a triple of one material, one chemical and one variant, where the variant is either modelled or laboratory-based and is inherited from the calling assessment's `method`."

        Design: Difficulty/dual_variant_calc/modeled_vs_lab_tested_diverge_on_incomplete_disclosure
        """
        bundle = incomplete_disclosure_product
        modelled = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_DERMAL,
            1.0,
        )
        laboratory = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_LAB_TESTED,
            ROUTE_DERMAL,
            1.0,
        )
        assert modelled["daily_exposure_ug"] != laboratory["daily_exposure_ug"], (
            "The two variants must diverge on this data"
        )
        assert_exposure(modelled["daily_exposure_ug"], 3.125)
        assert_exposure(laboratory["daily_exposure_ug"], 0.5)

        link = get_success_data(
            api.get_material_chemical(bundle["link"]["id"], COMPLIANCE_ANALYST)
        )
        assert link["measurement_basis"] == BASIS_LAB_TESTED
        material = get_success_data(
            api.get_material(bundle["material"]["id"], COMPLIANCE_ANALYST)
        )
        assert material["disclosure_status"] == DISCLOSURE_INCOMPLETE


# ─────────────────────────────────────────────────────────────────────────────
# The exposure variants on a non-detect
# ─────────────────────────────────────────────────────────────────────────────


class TestNonDetectDivergence:
    def test_modelled_variant_substitutes_half_the_limit_of_quantitation(
        self, api, non_detect_product
    ):
        """A result below the limit of quantitation becomes half that limit and still counts.

        PRD: "The two variants are the system's first deliberate dual-variant calculation: for identical stored rows, the laboratory variant yields a strictly smaller or equal concentration than the modelled variant whenever a contributing link is a non-detect (0.0 rather than half the limit of quantitation) or a contributing material has an incomplete or refused disclosure (its measured value rather than the modelled default of 250.0)."

        Design: Difficulty/dual_variant_calc/modeled_half_loq_vs_lab_tested_zero_on_non_detect
        """
        bundle = non_detect_product
        assessment = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_DERMAL,
            1.0,
        )
        # 8.0 / 2 = 4.0 ppm x 0.25 g x 0.5 contact x 0.10 dermal = 0.050 ug/day.
        assert_assessment_verdict(assessment, 0.05, 0.1, RESULT_BELOW, 1)

    def test_laboratory_variant_treats_a_non_detect_as_a_true_zero(
        self, api, non_detect_product
    ):
        """The component contributes 0.0 and therefore drops out of the contribution count.

        PRD: "If `lab_result_ppm` is strictly below `lab_loq_ppm`, the own contribution is 0.0 — under this variant a non-detect is treated as a true zero rather than as half the limit."

        Design: Difficulty/dual_variant_calc/modeled_half_loq_vs_lab_tested_zero_on_non_detect
        """
        bundle = non_detect_product
        assessment = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_LAB_TESTED,
            ROUTE_DERMAL,
            1.0,
        )
        assert_assessment_verdict(assessment, 0.0, 0.0, RESULT_BELOW, 0)

    def test_the_observable_difference_is_the_contribution_count(
        self, api, non_detect_product
    ):
        """One variant counts the component, the other skips it entirely.

        PRD: "A component whose effective concentration comes out as exactly 0.0 is skipped entirely and does not count toward `contribution_count`."

        Design: Difficulty/dual_variant_calc/modeled_half_loq_vs_lab_tested_zero_on_non_detect
        """
        bundle = non_detect_product
        modelled = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_MODELED,
            ROUTE_DERMAL,
            1.0,
        )
        laboratory = make_assessment(
            api,
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            METHOD_LAB_TESTED,
            ROUTE_DERMAL,
            1.0,
        )
        assert modelled["contribution_count"] == 1
        assert laboratory["contribution_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# The defence file variants
# ─────────────────────────────────────────────────────────────────────────────


class TestDefenseFileVariants:
    def test_as_of_today_counts_every_stored_row(self, api, defense_file_product):
        """Read without a notice, the defence file scores a perfect 100.

        PRD: "The `AS_OF_TODAY` variant applies when the summary is requested without `as_of_notice_id`, and `as_of` is the current logical clock; every `FINAL` assessment counts regardless of its `finalized_at`, and recordkeeping evidence reads the current `disclosure_status` with no `data_received_at` cut-off."

        Design: Difficulty/dual_variant_calc/defense_score_as_of_today_vs_as_of_service_date
        """
        bundle = defense_file_product
        summary = validate_success(
            api.compliance_summary(bundle["product"]["id"], COMPLIANCE_ANALYST)
        )
        assert summary["variant"] == VARIANT_AS_OF_TODAY
        assert_instant(summary["as_of"], DEFAULT_CLOCK, "as_of")
        assert summary["defense_strength_score"] == 100
        assert_defense_components(summary, 1.0, 1.0, 1.0, 1.0)
        assert_defense_counts(summary, 1, 1, 1, 1, 1, 1)

    def test_as_of_service_date_excludes_evidence_dated_after_service(
        self, api, defense_file_product
    ):
        """Read as of the 2026-05-01 service date, only the warranty survives: 20 of 100.

        PRD: "In that variant, placements must have been in force at `served_at`, `FINAL` assessments count only when their `finalized_at` is at or before `served_at`, warranty coverage is tested against `served_at`, and disclosure responses count only when `data_received_at` is at or before `served_at`."

        Design: Difficulty/dual_variant_calc/defense_score_as_of_today_vs_as_of_service_date
        """
        bundle = defense_file_product
        summary = validate_success(
            api.compliance_summary(
                bundle["product"]["id"],
                COMPLIANCE_ANALYST,
                {"as_of_notice_id": bundle["notice"]["id"]},
            )
        )
        assert summary["variant"] == VARIANT_AS_OF_SERVICE_DATE
        assert_instant(summary["as_of"], "2026-05-01T00:00:00Z", "as_of")
        # 40 x 0.0 + 25 x 0.0 + 20 x 1.0 + 15 x 0.0 = 20.
        assert summary["defense_strength_score"] == 20
        assert_defense_components(summary, 0.0, 0.0, 1.0, 0.0)
        assert summary["required_channel_count"] == 1
        assert summary["covered_channel_count"] == 0
        assert summary["verified_channel_count"] == 0
        assert summary["final_assessment_count"] == 0
        assert summary["active_component_count"] == 1

    def test_the_service_date_score_never_exceeds_todays_score(
        self, api, defense_file_product
    ):
        """The same stored rows, two instants, and the earlier instant can only score lower.

        PRD: "Because each of those restrictions can only remove evidence, the `AS_OF_SERVICE_DATE` score is always lower than or equal to the `AS_OF_TODAY` score for the same product."

        Design: Difficulty/dual_variant_calc/defense_score_as_of_today_vs_as_of_service_date
        """
        bundle = defense_file_product
        today = validate_success(
            api.compliance_summary(bundle["product"]["id"], COMPLIANCE_ANALYST)
        )
        service = validate_success(
            api.compliance_summary(
                bundle["product"]["id"],
                COMPLIANCE_ANALYST,
                {"as_of_notice_id": bundle["notice"]["id"]},
            )
        )
        assert service["defense_strength_score"] <= today["defense_strength_score"]
        assert today["defense_strength_score"] == 100
        assert service["defense_strength_score"] == 20
