"""Single writes whose consequences travel several rows away from the write.

A registry revision reaching a placement, a reformulation reaching back up from
the bill of materials, and a supplier answer that recomputes only the rows it is
still allowed to touch.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_exposure,
    assert_instant,
    assert_load,
    assert_margin,
    assert_posture,
    assert_status,
)
from test_helpers.assertions import assert_close, assert_concentration
from test_helpers.constants import (
    ASSESSMENT_FINAL,
    ASSESSMENT_SUPERSEDED,
    ASSESSMENT_DRAFT,
    BASIS_SUPPLIER_DECLARED,
    BPA_BASIS,
    CHEMICAL_STATUS_LISTED,
    DEFAULT_CLOCK,
    DETERMINATION_APPROVED,
    DETERMINATION_REVOKED,
    DISCLOSURE_INCOMPLETE,
    DISCLOSURE_RECEIVED,
    DISCLOSURE_REQUESTED,
    LINK_STATUS_DECLARED,
    METHOD_MODELED,
    PLACEMENT_IMPLEMENTED,
    PLACEMENT_NON_COMPLIANT,
    POSTURE_EXPOSURE_UNKNOWN,
    POSTURE_WARNING_ACTIVE,
    POSTURE_WARNING_REQUIRED,
    PROJECT_VERIFICATION,
    RESULT_AT_OR_ABOVE,
    RESULT_BELOW,
    ROUTE_DERMAL,
)
from test_helpers.fixtures import (
    add_component,
    advance_disclosure,
    build_warned_product,
    finalize_assessment,
    link_chemical,
    make_assessment,
    make_bpa,
    make_material,
    make_product,
    make_reformulation_project,
    make_supplier,
    read_product,
    report_lab_result,
    revise_safe_harbor,
    set_clock,
    submit_reformulation_verification,
    verify_lab_result,
)
from test_helpers.test_users import COMPLIANCE_ANALYST


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def warned_product(api):
    """A product warning on a single LABEL channel, four rows below the registry.

    Its FINAL assessment sits at exactly 0.500 ug/day against a 0.5 ug/day
    limit, so the verdict is AT_OR_ABOVE and the posture is WARNING_ACTIVE.
    """
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    bundle = build_warned_product(
        api,
        chemical["id"],
        sku="SKU-TC1",
        route=ROUTE_DERMAL,
        product_overrides={"product_name": "Yoga Block", "annual_units": 50000},
    )
    bundle["chemical"] = chemical
    return bundle


@pytest.fixture
def reformulating_product(api):
    """The same warned product, but its link carries a VERIFIED laboratory value.

    A project targeting 4.0 ppm against the current 40.0 ppm is on file.
    """
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    bundle = build_warned_product(
        api,
        chemical["id"],
        sku="SKU-TC2",
        route=ROUTE_DERMAL,
        product_overrides={"product_name": "Bath Caddy", "annual_units": 50000},
    )
    link_id = bundle["link"]["id"]
    report_lab_result(api, link_id, 40.0, 1.0, lab_name="Cascade Analytical")
    bundle["link"] = verify_lab_result(api, link_id)
    bundle["chemical"] = chemical
    bundle["project"] = make_reformulation_project(
        api,
        bundle["product"]["id"],
        chemical["id"],
        link_id,
        4.0,
    )
    bundle["product"] = read_product(api, bundle["product"]["id"])
    return bundle


@pytest.fixture
def gapped_product(api):
    """An INCOMPLETE disclosure, one FINAL assessment taken under the gap, one DRAFT."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    link = link_chemical(api, material["id"], chemical["id"], 40.0)
    material = advance_disclosure(api, material["id"], DISCLOSURE_INCOMPLETE)
    product = make_product(
        api, "SKU-TC3", product_name="Cooler Handle", annual_units=50000
    )
    add_component(api, product["id"], material["id"], 0.25, 0.5)
    final = make_assessment(
        api, product["id"], chemical["id"], METHOD_MODELED, ROUTE_DERMAL, 1.0
    )
    final = finalize_assessment(api, final["id"])
    draft = make_assessment(
        api, product["id"], chemical["id"], METHOD_MODELED, ROUTE_DERMAL, 1.0
    )
    return {
        "chemical": chemical,
        "material": material,
        "link": link,
        "product": read_product(api, product["id"]),
        "final": final,
        "draft": draft,
    }


def _read_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, COMPLIANCE_ANALYST))


def _read_determination(api, determination_id):
    return get_success_data(
        api.get_determination(determination_id, COMPLIANCE_ANALYST)
    )


def _read_placement(api, placement_id):
    return get_success_data(api.get_placement(placement_id, COMPLIANCE_ANALYST))


def _read_link(api, link_id):
    return get_success_data(api.get_material_chemical(link_id, COMPLIANCE_ANALYST))


def _read_material(api, material_id):
    return get_success_data(api.get_material(material_id, COMPLIANCE_ANALYST))


def _disclosure(api, material_id, payload):
    return get_success_data(
        api.material_disclosure(material_id, payload, COMPLIANCE_ANALYST)
    )


# ─────────────────────────────────────────────────────────────────────────────
# The registry revision, four levels down
# ─────────────────────────────────────────────────────────────────────────────


class TestRegistryRevisionCascade:
    def test_the_revision_recomputes_the_verdict_and_supersedes_the_assessment(
        self, api, warned_product
    ):
        """A tenfold looser limit keeps the exposure at 0.500 but drops the margin to 0.1000.

        PRD: "At level one, every exposure assessment naming this chemical whose status is `FINAL` keeps the `daily_exposure_ug` it was finalized with but has its `margin_ratio` and `result` recomputed against the new level, and then transitions `FINAL → SUPERSEDED`."

        Design: Difficulty/transitive_cascade/revise_safe_harbor_cascades_four_levels
        """
        bundle = warned_product
        assert_posture(bundle["product"], POSTURE_WARNING_ACTIVE)
        assert_assessment_verdict(
            bundle["assessment"], 0.5, 1.0, RESULT_AT_OR_ABOVE, 1
        )

        revised = revise_safe_harbor(api, bundle["chemical"]["id"], BPA_BASIS, 5.0)
        assert_status(revised, CHEMICAL_STATUS_LISTED)
        assert revised["revision_count"] == 1
        assert_close(revised["safe_harbor_level_ug_per_day"], 5.0, 4, "level")

        assessment = _read_assessment(api, bundle["assessment"]["id"])
        assert_status(assessment, ASSESSMENT_SUPERSEDED)
        assert_exposure(assessment["daily_exposure_ug"], 0.5)
        assert_margin(assessment["margin_ratio"], 0.1)
        assert assessment["result"] == RESULT_BELOW

    def test_the_supersede_revokes_the_determination_that_cited_it(
        self, api, warned_product
    ):
        """Level two only fires because level one moved the assessment out of FINAL.

        PRD: "At level two, because those assessments have left `FINAL`, every warning determination that cites one of them and whose status is `APPROVED` transitions `APPROVED → REVOKED`."

        Design: Difficulty/transitive_cascade/revise_safe_harbor_cascades_four_levels
        """
        bundle = warned_product
        assert_status(bundle["determination"], DETERMINATION_APPROVED)
        revise_safe_harbor(api, bundle["chemical"]["id"], BPA_BASIS, 5.0)
        determination = _read_determination(api, bundle["determination"]["id"])
        assert_status(determination, DETERMINATION_REVOKED)

    def test_the_revocation_reaches_the_placement_the_registry_cannot_see(
        self, api, warned_product
    ):
        """No edge runs from a chemical to a placement; level three is reached through level two.

        PRD: "At level three, because those determinations have left `APPROVED`, every placement of each revoked determination whose status is `IMPLEMENTED` or `VERIFIED` transitions to `NON_COMPLIANT`."

        Design: Difficulty/transitive_cascade/revise_safe_harbor_cascades_four_levels
        """
        bundle = warned_product
        assert_status(bundle["placement"], PLACEMENT_IMPLEMENTED)
        revise_safe_harbor(api, bundle["chemical"]["id"], BPA_BASIS, 5.0)
        placement = _read_placement(api, bundle["placement"]["id"])
        assert_status(placement, PLACEMENT_NON_COMPLIANT)

    def test_coverage_and_posture_are_recomputed_last(self, api, warned_product):
        """The warning that was up on every channel is gone, so the ladder falls to clause 2.

        PRD: "At level four, `covered_channel_count` on each revoked determination is recomputed and each affected product's `compliance_posture` is recomputed through the posture ladder."

        Design: Difficulty/transitive_cascade/revise_safe_harbor_cascades_four_levels
        """
        bundle = warned_product
        assert _read_determination(api, bundle["determination"]["id"])[
            "covered_channel_count"
        ] == 1
        revise_safe_harbor(api, bundle["chemical"]["id"], BPA_BASIS, 5.0)

        determination = _read_determination(api, bundle["determination"]["id"])
        assert determination["covered_channel_count"] == 0
        product = read_product(api, bundle["product"]["id"])
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)


# ─────────────────────────────────────────────────────────────────────────────
# The reformulation, three levels up from the bill of materials
# ─────────────────────────────────────────────────────────────────────────────


class TestReformulationVerificationCascade:
    def test_verification_rewrites_the_link_and_discards_the_lab_evidence(
        self, api, reformulating_product
    ):
        """40.0 ppm of verified laboratory data becomes a 4.0 ppm supplier declaration.

        PRD: "At level one the linked material-chemical's `declared_concentration_ppm` is overwritten with the project's `target_concentration_ppm`, its `status` resets to `DECLARED`, its `measurement_basis` resets to `SUPPLIER_DECLARED`, and `lab_name`, `lab_result_ppm`, `lab_loq_ppm` and `lab_reported_at` are all cleared — the old laboratory evidence describes a formulation that no longer exists."

        Design: Difficulty/transitive_cascade/reformulation_verification_cascades_three_levels
        """
        bundle = reformulating_product
        assert_load(bundle["product"]["total_listed_chemical_load_ug"], 10.0)
        submit_reformulation_verification(api, bundle["project"]["id"])

        link = _read_link(api, bundle["link"]["id"])
        assert_concentration(link["declared_concentration_ppm"], 4.0, "declared ppm")
        assert_status(link, LINK_STATUS_DECLARED)
        assert link["measurement_basis"] == BASIS_SUPPLIER_DECLARED
        assert link["lab_result_ppm"] is None
        assert link["lab_loq_ppm"] is None
        assert link["lab_name"] is None
        assert link["lab_reported_at"] is None

    def test_the_rewrite_drops_the_load_and_supersedes_the_final_assessment(
        self, api, reformulating_product
    ):
        """A tenfold cut in concentration cuts the conserved load from 10.000 to 1.000 ug.

        PRD: "At level two, because that concentration changed, every assessment in status `FINAL` belonging to a product that holds the affected material has its `daily_exposure_ug`, `margin_ratio` and `result` recomputed and then transitions `FINAL → SUPERSEDED`, and each affected product's `total_listed_chemical_load_ug` is recomputed."

        Design: Difficulty/transitive_cascade/reformulation_verification_cascades_three_levels
        """
        bundle = reformulating_product
        submit_reformulation_verification(api, bundle["project"]["id"])

        product = read_product(api, bundle["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 1.0)
        assessment = _read_assessment(api, bundle["assessment"]["id"])
        assert_status(assessment, ASSESSMENT_SUPERSEDED)

    def test_the_supersede_tears_down_the_warning_and_the_posture(
        self, api, reformulating_product
    ):
        """Level three revokes the determination, flags the placement and empties the coverage.

        PRD: "At level three, because those assessments left `FINAL`, every determination in status `APPROVED` citing one of them transitions `APPROVED → REVOKED` — the basis-assessment-left-`FINAL` edge, distinct from the `SUPERSEDED` edge reserved for a newer approved determination on the same product — so that determination's `IMPLEMENTED` and `VERIFIED` placements go to `NON_COMPLIANT`, its `covered_channel_count` falls to 0, and the product's `compliance_posture` is recomputed."

        Design: Difficulty/transitive_cascade/reformulation_verification_cascades_three_levels
        """
        bundle = reformulating_product
        assert_posture(bundle["product"], POSTURE_WARNING_ACTIVE)
        submit_reformulation_verification(api, bundle["project"]["id"])

        determination = _read_determination(api, bundle["determination"]["id"])
        assert_status(determination, DETERMINATION_REVOKED)
        assert determination["covered_channel_count"] == 0
        placement = _read_placement(api, bundle["placement"]["id"])
        assert_status(placement, PLACEMENT_NON_COMPLIANT)
        product = read_product(api, bundle["product"]["id"])
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)

    def test_the_project_records_the_reduction_it_achieved(
        self, api, reformulating_product
    ):
        """0.500 ug/day down to 0.050 ug/day is a 90.00 per cent reduction.

        PRD: "Submitting for verification also stamps `verified_daily_exposure_ug` with the recomputed modelled exposure for the project's product and chemical pair and computes `reduction_pct` as one hundred times the difference between `baseline_daily_exposure_ug` and `verified_daily_exposure_ug` divided by `baseline_daily_exposure_ug`, rounded half up to two decimal places; when `baseline_daily_exposure_ug` is 0 the percentage is undefined and `reduction_pct` is null."

        Design: Difficulty/transitive_cascade/reformulation_verification_cascades_three_levels
        """
        bundle = reformulating_product
        assert_exposure(bundle["project"]["baseline_daily_exposure_ug"], 0.5)
        project = submit_reformulation_verification(api, bundle["project"]["id"])
        assert_status(project, PROJECT_VERIFICATION)
        assert_exposure(project["verified_daily_exposure_ug"], 0.05)
        assert_close(project["reduction_pct"], 90.0, 2, "reduction_pct")
        assert_exposure(project["baseline_daily_exposure_ug"], 0.5)


# ─────────────────────────────────────────────────────────────────────────────
# The supplier answer that closes a modelling gap
# ─────────────────────────────────────────────────────────────────────────────


class TestDisclosureResponseCascade:
    def test_the_open_gap_prices_every_recomputation_at_the_worst_case(
        self, api, gapped_product
    ):
        """250.0 ppm drives both assessments to 3.125 ug/day and the load to 62.500 ug.

        PRD: "An incomplete response has a specific modelling consequence: from that point on, every modelled exposure recomputation for products holding this material substitutes the modelled default concentration for this material's own contribution."

        Design: Difficulty/transitive_cascade/disclosure_response_cascades_modeled_exposure_and_load
        """
        bundle = gapped_product
        assert _read_material(api, bundle["material"]["id"])["disclosure_status"] == (
            DISCLOSURE_INCOMPLETE
        )
        assert_load(bundle["product"]["total_listed_chemical_load_ug"], 62.5)
        assert_posture(bundle["product"], POSTURE_EXPOSURE_UNKNOWN)
        assert_exposure(bundle["final"]["daily_exposure_ug"], 3.125)
        assert_exposure(bundle["draft"]["daily_exposure_ug"], 3.125)

    def test_a_bare_re_request_does_not_improve_the_exposure_picture(
        self, api, gapped_product
    ):
        """REQUESTED still carries the worst-case substitution, so nothing downstream moves.

        PRD: "Note that a `RECEIVED` or `VERIFIED` disclosure carries no worst-case substitution, while `NOT_REQUESTED`, `REQUESTED`, `INCOMPLETE` and `REFUSED` all do; this is why simply requesting data does not improve a product's exposure picture, and why clause 2 of the posture ladder holds a product in `EXPOSURE_UNKNOWN` until every material in every active component's subtree has reached `RECEIVED` or `VERIFIED`."

        Design: Difficulty/transitive_cascade/disclosure_response_cascades_modeled_exposure_and_load
        """
        bundle = gapped_product
        requested = _disclosure(
            api, bundle["material"]["id"], f.action_payload("REQUEST")
        )
        assert requested["disclosure_status"] == DISCLOSURE_REQUESTED

        product = read_product(api, bundle["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 62.5)
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)
        assert_exposure(
            _read_assessment(api, bundle["draft"]["id"])["daily_exposure_ug"], 3.125
        )

    def test_a_complete_response_recomputes_the_open_rows_and_the_load(
        self, api, gapped_product
    ):
        """Closing the gap recomputes the DRAFT row to 0.500 ug/day and the load to 10.000 ug.

        PRD: "Beyond that, any change to `disclosure_status` recomputes every modelled exposure assessment in status `DRAFT`, `SUBMITTED` or `PEER_REVIEWED` belonging to every product that reaches this material, and recomputes those products' `total_listed_chemical_load_ug` and `compliance_posture`."

        Design: Difficulty/transitive_cascade/disclosure_response_cascades_modeled_exposure_and_load
        """
        bundle = gapped_product
        _disclosure(api, bundle["material"]["id"], f.action_payload("REQUEST"))
        received = _disclosure(
            api, bundle["material"]["id"], f.record_response_action("COMPLETE")
        )
        assert received["disclosure_status"] == DISCLOSURE_RECEIVED
        assert_instant(received["data_received_at"], DEFAULT_CLOCK, "data_received_at")

        draft = _read_assessment(api, bundle["draft"]["id"])
        assert_assessment_verdict(draft, 0.5, 1.0, RESULT_AT_OR_ABOVE, 1)
        assert_status(draft, ASSESSMENT_DRAFT)

        product = read_product(api, bundle["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 10.0)
        assert_posture(product, POSTURE_WARNING_REQUIRED)

    def test_the_final_row_keeps_the_numbers_it_was_finalized_with(
        self, api, gapped_product
    ):
        """A data-level recomputation may not touch a FINAL assessment.

        PRD: "Assessments already in `FINAL` keep the numbers they were finalized with — only the four explicit supersede cascades may touch a `FINAL` row."

        Design: Difficulty/transitive_cascade/disclosure_response_cascades_modeled_exposure_and_load
        """
        bundle = gapped_product
        _disclosure(api, bundle["material"]["id"], f.action_payload("REQUEST"))
        _disclosure(
            api, bundle["material"]["id"], f.record_response_action("COMPLETE")
        )

        final = _read_assessment(api, bundle["final"]["id"])
        assert_status(final, ASSESSMENT_FINAL)
        assert_exposure(final["daily_exposure_ug"], 3.125)
        assert_margin(final["margin_ratio"], 6.25)
