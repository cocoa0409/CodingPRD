"""Writes that are gated by state living on a different row than the write target.

A registry status two hops away, a parent notice's status, a computed posture on
the parent product, and the state of every row in a contributing set.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CHEMICAL_NOT_LISTED,
    ERR_ENFORCEMENT_HOLD_FREEZE,
    ERR_LAB_RESULT_MISSING,
    ERR_NOTICE_NOT_NEGOTIABLE,
)
from test_helpers.assertions import (
    assert_assessment_verdict,
    assert_cents,
    assert_exposure,
    assert_instant,
    assert_load,
    assert_margin,
    assert_posture,
    assert_status,
)
from test_helpers.constants import (
    ASSESSMENT_DRAFT,
    ASSESSMENT_SUBMITTED,
    BASIS_LAB_TESTED,
    CHEMICAL_STATUS_LISTED,
    CHEMICAL_STATUS_PROPOSED,
    COMPONENT_STATUS_ACTIVE,
    DEFAULT_CLOCK,
    DISCLOSURE_VERIFIED,
    LINK_STATUS_TEST_REPORTED,
    LISTING_EFFECTIVE_DATE,
    LISTING_WARNING_REQUIRED_FROM,
    MATERIAL_CLASS_PACKAGING,
    METHOD_LAB_TESTED,
    METHOD_MODELED,
    NOTICE_DISMISSED,
    NOTICE_RECEIVED,
    NOTICE_SETTLEMENT_NEGOTIATION,
    NOTICE_UNDER_EVALUATION,
    POSTURE_ENFORCEMENT_HOLD,
    POSTURE_EXPOSURE_UNKNOWN,
    RESULT_AT_OR_ABOVE,
    ROUTE_DERMAL,
    SETTLEMENT_PROPOSED,
)
from test_helpers.fixtures import (
    add_component,
    advance_disclosure,
    dismiss_notice,
    evaluate_notice,
    link_chemical,
    make_assessment,
    make_bpa,
    make_material,
    make_notice,
    make_product,
    make_supplier,
    read_product,
    report_lab_result,
    set_clock,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    REGISTRY_ADMIN,
    REGULATORY_COUNSEL,
)


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def proposed_chemical_and_product(api):
    """Bisphenol A registered but never listed, and a bare product in DEVELOPMENT."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api, list_it=False)
    product = make_product(
        api, "SKU-CE1", product_name="Utility Bin", annual_units=50000
    )
    return {"chemical": chemical, "product": product}


@pytest.fixture
def evaluated_notice(api):
    """A notice sitting in UNDER_EVALUATION, with the clock 61 days past service."""
    set_clock(api, "2026-06-01T00:00:00Z")
    chemical = make_bpa(api)
    product = make_product(
        api, "SKU-CE2", product_name="Hose Reel", annual_units=500000
    )
    notice = make_notice(
        api,
        product["id"],
        chemical["id"],
        earliest_violation_date="2026-06-01T00:00:00Z",
        served_at="2026-06-01T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )
    notice = evaluate_notice(api, notice["id"])
    set_clock(api, DEFAULT_CLOCK)
    return {"chemical": chemical, "product": product, "notice": notice}


@pytest.fixture
def held_product_and_spare_material(api):
    """An empty product frozen by one RECEIVED notice, plus a material ready to attach."""
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")
    material = make_material(api, "RM-100", supplier["id"])
    link_chemical(api, material["id"], chemical["id"], 40.0)
    material = advance_disclosure(api, material["id"], DISCLOSURE_VERIFIED)
    product = make_product(
        api, "SKU-CE3", product_name="Planter Box", annual_units=50000
    )
    notice = make_notice(
        api,
        product["id"],
        chemical["id"],
        earliest_violation_date="2026-07-01T00:00:00Z",
        served_at="2026-07-15T00:00:00Z",
        noticing_party_name="Coastal Compliance Group",
    )
    return {
        "chemical": chemical,
        "material": material,
        "product": read_product(api, product["id"]),
        "notice": notice,
    }


@pytest.fixture
def half_lab_tested_product(api):
    """Two contributing links, one on a laboratory basis and one still DECLARED.

    RM-LAB reports 40.0 ppm against a 1.0 ppm limit of quantitation; RM-DEC
    declares 20.0 ppm and has never been tested. A LAB_TESTED DERMAL assessment
    sits in DRAFT over both of them.
    """
    set_clock(api, DEFAULT_CLOCK)
    chemical = make_bpa(api)
    supplier = make_supplier(api, "Northgate Polymers")

    lab_material = make_material(api, "RM-LAB", supplier["id"])
    lab_link = link_chemical(api, lab_material["id"], chemical["id"], 40.0)
    advance_disclosure(api, lab_material["id"], DISCLOSURE_VERIFIED)
    report_lab_result(api, lab_link["id"], 40.0, 1.0, lab_name="Cascade Analytical")

    declared_material = make_material(
        api, "RM-DEC", supplier["id"], material_class=MATERIAL_CLASS_PACKAGING
    )
    declared_link = link_chemical(
        api, declared_material["id"], chemical["id"], 20.0
    )
    advance_disclosure(api, declared_material["id"], DISCLOSURE_VERIFIED)

    product = make_product(
        api, "SKU-CE4", product_name="Lunch Kit", annual_units=50000
    )
    add_component(api, product["id"], lab_material["id"], 0.25, 0.5)
    add_component(api, product["id"], declared_material["id"], 0.25, 0.5)
    assessment = make_assessment(
        api,
        product["id"],
        chemical["id"],
        METHOD_LAB_TESTED,
        ROUTE_DERMAL,
        1.0,
    )
    return {
        "chemical": chemical,
        "lab_link": lab_link,
        "declared_link": declared_link,
        "product": product,
        "assessment": assessment,
    }


def _read_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, COMPLIANCE_ANALYST))


def _read_link(api, link_id):
    return get_success_data(api.get_material_chemical(link_id, COMPLIANCE_ANALYST))


def _create_assessment(api, product_id, chemical_id):
    return api.create_assessment(
        product_id,
        f.assessment_payload(chemical_id, METHOD_MODELED, ROUTE_DERMAL, 1.0),
        COMPLIANCE_ANALYST,
    )


def _create_component(api, product_id, material_id):
    return api.create_component(
        product_id,
        f.component_payload(material_id, 0.25, 0.5),
        COMPLIANCE_ANALYST,
    )


def _create_settlement(api, notice_id, fees, version):
    return api.create_settlement(
        notice_id,
        f.settlement_payload(fees, version, reformulation_commitment=False),
        REGULATORY_COUNSEL,
    )


def _submit(api, assessment_id):
    return api.assessment_transition(
        assessment_id, f.action_payload("SUBMIT"), COMPLIANCE_ANALYST
    )


# ─────────────────────────────────────────────────────────────────────────────
# The registry status, two hops from the write target
# ─────────────────────────────────────────────────────────────────────────────


class TestAssessmentNeedsAListedChemical:
    def test_a_proposed_chemical_blocks_the_assessment_create(
        self, api, proposed_chemical_and_product
    ):
        """Nothing about the product or the body is wrong; the registry row is what refuses.

        PRD: "The chemical must be in registry `status` `LISTED` at create time, otherwise the request is refused with `ERR_CHEMICAL_NOT_LISTED`, and the product must not be `DISCONTINUED`."

        Design: Difficulty/cross_entity_state_dependency/assessment_create_requires_listed_chemical_status
        """
        bundle = proposed_chemical_and_product
        assert_status(bundle["chemical"], CHEMICAL_STATUS_PROPOSED)
        assert bundle["chemical"]["listing_effective_date"] is None

        validate_error(
            _create_assessment(
                api, bundle["product"]["id"], bundle["chemical"]["id"]
            ),
            ERR_CHEMICAL_NOT_LISTED,
            409,
        )

    def test_the_refusal_leaves_no_assessment_row_behind(
        self, api, proposed_chemical_and_product
    ):
        """A refused create is not a partially created assessment.

        PRD: "A newly created assessment has `status` `DRAFT`, `submitted_by_user_id`, `reviewed_by_user_id` and `finalized_at` all null, `rejection_count` 0 and `review_note` null; its numbers are computed immediately from the product's active components."

        Design: Difficulty/cross_entity_state_dependency/assessment_create_requires_listed_chemical_status
        """
        bundle = proposed_chemical_and_product
        validate_error(
            _create_assessment(
                api, bundle["product"]["id"], bundle["chemical"]["id"]
            ),
            ERR_CHEMICAL_NOT_LISTED,
            409,
        )
        rows, _ = validate_paginated(
            api.list_assessments(
                COMPLIANCE_ANALYST, {"product_id": bundle["product"]["id"]}
            )
        )
        assert rows == []

    def test_listing_the_chemical_unblocks_the_identical_request(
        self, api, proposed_chemical_and_product
    ):
        """The registry transition computes the grace date and opens the assessment surface.

        PRD: "Listing a chemical takes it `PROPOSED → LISTED` and requires `listing_effective_date` in the payload; the server stores that date and computes `warning_required_from` as the effective date plus a one-year grace period of exactly three hundred and sixty-five days."

        Design: Difficulty/cross_entity_state_dependency/assessment_create_requires_listed_chemical_status
        """
        bundle = proposed_chemical_and_product
        validate_error(
            _create_assessment(
                api, bundle["product"]["id"], bundle["chemical"]["id"]
            ),
            ERR_CHEMICAL_NOT_LISTED,
            409,
        )
        listed = get_success_data(
            api.listed_chemical_transition(
                bundle["chemical"]["id"],
                f.list_action(LISTING_EFFECTIVE_DATE),
                REGISTRY_ADMIN,
            )
        )
        assert_status(listed, CHEMICAL_STATUS_LISTED)
        assert_instant(
            listed["warning_required_from"],
            LISTING_WARNING_REQUIRED_FROM,
            "warning_required_from",
        )

        assessment = get_success_data(
            _create_assessment(
                api, bundle["product"]["id"], bundle["chemical"]["id"]
            )
        )
        assert_status(assessment, ASSESSMENT_DRAFT)
        assert_exposure(assessment["daily_exposure_ug"], 0.0)
        assert assessment["contribution_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# The parent notice's status gates a child create
# ─────────────────────────────────────────────────────────────────────────────


class TestSettlementNeedsANegotiatingNotice:
    def test_an_evaluated_notice_cannot_open_a_settlement(self, api, evaluated_notice):
        """UNDER_EVALUATION is not negotiable, and the fresh version proves this is not layer 3.

        PRD: "The notice must be in status `SETTLEMENT_NEGOTIATION`, otherwise the create is refused with `ERR_NOTICE_NOT_NEGOTIABLE`, and the notice must not already hold a settlement in status `PROPOSED`, `COUNTERED` or `EXECUTED`, otherwise it is refused with `ERR_OPEN_SETTLEMENT_EXISTS`."

        Design: Difficulty/cross_entity_state_dependency/settlement_create_requires_notice_in_negotiation
        """
        bundle = evaluated_notice
        assert_status(bundle["notice"], NOTICE_UNDER_EVALUATION)
        version = api.notice_version(bundle["notice"]["id"], REGULATORY_COUNSEL)
        validate_error(
            _create_settlement(api, bundle["notice"]["id"], 300000, version),
            ERR_NOTICE_NOT_NEGOTIABLE,
            409,
        )

        rows, _ = validate_paginated(
            api.list_settlements(
                REGULATORY_COUNSEL, {"notice_id": bundle["notice"]["id"]}
            )
        )
        assert rows == []

    def test_the_escalation_moves_the_notice_and_its_version(
        self, api, evaluated_notice
    ):
        """Escalating both opens the negotiation and invalidates the version just read.

        PRD: "Every action on this surface is reserved to a `RegulatoryCounsel` and increments the notice's `version` by 1 and the product's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/settlement_create_requires_notice_in_negotiation
        """
        bundle = evaluated_notice
        before = api.notice_version(bundle["notice"]["id"], REGULATORY_COUNSEL)
        negotiating = get_success_data(
            api.notice_transition(
                bundle["notice"]["id"],
                f.action_payload("ESCALATE"),
                REGULATORY_COUNSEL,
            )
        )
        assert_status(negotiating, NOTICE_SETTLEMENT_NEGOTIATION)
        after = api.notice_version(bundle["notice"]["id"], REGULATORY_COUNSEL)
        assert after != before

    def test_the_same_body_succeeds_once_the_notice_is_negotiating(
        self, api, evaluated_notice
    ):
        """61 violation days, no mitigation, and the whole waterfall on the second attempt.

        PRD: "**Proposing a settlement.** A `RegulatoryCounsel` proposes a settlement under a notice by supplying a non-negative `requested_attorney_fees_cents`, an optional `reformulation_commitment` boolean defaulting to false that records whether the settlement includes a binding reformulation commitment, and the `expected_notice_version` described in Section 2.6."

        Design: Difficulty/cross_entity_state_dependency/settlement_create_requires_notice_in_negotiation
        """
        bundle = evaluated_notice
        stale_attempt_version = api.notice_version(
            bundle["notice"]["id"], REGULATORY_COUNSEL
        )
        validate_error(
            _create_settlement(
                api, bundle["notice"]["id"], 300000, stale_attempt_version
            ),
            ERR_NOTICE_NOT_NEGOTIABLE,
            409,
        )
        get_success_data(
            api.notice_transition(
                bundle["notice"]["id"],
                f.action_payload("ESCALATE"),
                REGULATORY_COUNSEL,
            )
        )
        fresh_version = api.notice_version(
            bundle["notice"]["id"], REGULATORY_COUNSEL
        )
        settlement = get_success_data(
            _create_settlement(api, bundle["notice"]["id"], 300000, fresh_version)
        )
        assert_status(settlement, SETTLEMENT_PROPOSED)
        assert settlement["violation_days"] == 61
        assert_margin(settlement["mitigation_factor"], 1.0, "mitigation_factor")
        assert_cents(
            settlement["adjusted_penalty_cents"], 2000000, "adjusted_penalty_cents"
        )
        assert_cents(settlement["allowed_fees_cents"], 300000, "allowed_fees_cents")


# ─────────────────────────────────────────────────────────────────────────────
# A computed posture on the parent product freezes the bill of materials
# ─────────────────────────────────────────────────────────────────────────────


class TestEnforcementHoldFreeze:
    def test_one_open_notice_puts_the_product_on_enforcement_hold(
        self, api, held_product_and_spare_material
    ):
        """The gate is a computed posture on a sibling's account, not a status the writer set.

        PRD: "Intake also increments the product's `open_notice_count` by 1 and, through clause 1 of the posture ladder, drives the product's `compliance_posture` to `ENFORCEMENT_HOLD` — which outranks every other clause and freezes the bill of materials — and increments the product's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/bom_write_blocked_while_product_on_enforcement_hold
        """
        bundle = held_product_and_spare_material
        assert_status(bundle["notice"], NOTICE_RECEIVED)
        assert_posture(bundle["product"], POSTURE_ENFORCEMENT_HOLD)
        assert bundle["product"]["open_notice_count"] == 1

    def test_the_component_create_is_frozen_and_leaves_the_load_alone(
        self, api, held_product_and_spare_material
    ):
        """A refused bill-of-materials write must not move the chemical load either.

        PRD: "While a product's posture is `ENFORCEMENT_HOLD`, its bill of materials is **frozen**: adding a component, updating a component and removing a component are all refused with `ERR_ENFORCEMENT_HOLD_FREEZE`."

        Design: Difficulty/cross_entity_state_dependency/bom_write_blocked_while_product_on_enforcement_hold
        """
        bundle = held_product_and_spare_material
        validate_error(
            _create_component(
                api, bundle["product"]["id"], bundle["material"]["id"]
            ),
            ERR_ENFORCEMENT_HOLD_FREEZE,
            409,
        )
        product = read_product(api, bundle["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 0.0)
        rows, _ = validate_paginated(
            api.list_components(
                COMPLIANCE_ANALYST, {"product_id": bundle["product"]["id"]}
            )
        )
        assert rows == []

    def test_dismissing_the_notice_lifts_the_hold(
        self, api, held_product_and_spare_material
    ):
        """With the open set empty the ladder falls to the no-assessment clause instead.

        PRD: "The third branch dismisses the notice, taking it `UNDER_EVALUATION → DISMISSED`; that action requires `evaluation_note` in the payload, decrements the product's `open_notice_count` by 1 and recomputes `compliance_posture`, which leaves `ENFORCEMENT_HOLD` when the count reaches 0."

        Design: Difficulty/cross_entity_state_dependency/bom_write_blocked_while_product_on_enforcement_hold
        """
        bundle = held_product_and_spare_material
        evaluate_notice(api, bundle["notice"]["id"])
        dismissed = dismiss_notice(api, bundle["notice"]["id"])
        assert_status(dismissed, NOTICE_DISMISSED)

        product = read_product(api, bundle["product"]["id"])
        assert product["open_notice_count"] == 0
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)

    def test_the_identical_component_create_then_succeeds(
        self, api, held_product_and_spare_material
    ):
        """40.0 ppm across 0.25 g of material is a 10.000 ug load once the freeze is gone.

        PRD: "Component creation, component adjustment and component removal each recompute the product's `total_listed_chemical_load_ug`, recompute `daily_exposure_ug` for every exposure assessment of that product whose status is `DRAFT`, `SUBMITTED` or `PEER_REVIEWED`, recompute `compliance_posture`, and increment both the product's `version` and the component's `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/bom_write_blocked_while_product_on_enforcement_hold
        """
        bundle = held_product_and_spare_material
        validate_error(
            _create_component(
                api, bundle["product"]["id"], bundle["material"]["id"]
            ),
            ERR_ENFORCEMENT_HOLD_FREEZE,
            409,
        )
        evaluate_notice(api, bundle["notice"]["id"])
        dismiss_notice(api, bundle["notice"]["id"])

        component = get_success_data(
            _create_component(
                api, bundle["product"]["id"], bundle["material"]["id"]
            )
        )
        assert_status(component, COMPONENT_STATUS_ACTIVE)
        product = read_product(api, bundle["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 10.0)


# ─────────────────────────────────────────────────────────────────────────────
# Every contributing link must be on a laboratory basis, not just one
# ─────────────────────────────────────────────────────────────────────────────


class TestLabTestedSubmitNeedsEveryLink:
    def test_one_declared_link_out_of_two_blocks_the_submission(
        self, api, half_lab_tested_product
    ):
        """The tested link is not enough: the untested sibling is what refuses the SUBMIT.

        PRD: "Second, if the assessment's `method` is `LAB_TESTED` and some contributing link has a `measurement_basis` other than `LAB_TESTED`, or has a null `lab_result_ppm`, or has a null `lab_loq_ppm`, the submission is refused with `ERR_LAB_RESULT_MISSING`."

        Design: Difficulty/cross_entity_state_dependency/lab_tested_submit_requires_lab_basis_on_every_link
        """
        bundle = half_lab_tested_product
        assert _read_link(api, bundle["lab_link"]["id"])["measurement_basis"] == (
            BASIS_LAB_TESTED
        )
        assert _read_link(api, bundle["declared_link"]["id"])[
            "measurement_basis"
        ] != BASIS_LAB_TESTED

        validate_error(
            _submit(api, bundle["assessment"]["id"]), ERR_LAB_RESULT_MISSING, 409
        )

    def test_the_refused_submission_leaves_the_draft_unsubmitted(
        self, api, half_lab_tested_product
    ):
        """No submitter is stamped by a submission the data-quality gate turned away.

        PRD: "A `ComplianceAnalyst` submits, taking the assessment `DRAFT → SUBMITTED`; submission recomputes `daily_exposure_ug`, `margin_ratio`, `result` and `contribution_count` from current data and stamps `submitted_by_user_id` with the acting `X-User-ID`."

        Design: Difficulty/cross_entity_state_dependency/lab_tested_submit_requires_lab_basis_on_every_link
        """
        bundle = half_lab_tested_product
        validate_error(
            _submit(api, bundle["assessment"]["id"]), ERR_LAB_RESULT_MISSING, 409
        )
        unchanged = _read_assessment(api, bundle["assessment"]["id"])
        assert_status(unchanged, ASSESSMENT_DRAFT)
        assert unchanged["submitted_by_user_id"] is None

    def test_reporting_the_missing_result_moves_the_link_onto_a_lab_basis(
        self, api, half_lab_tested_product
    ):
        """Reporting a figure is what changes the basis, and the basis is what the gate reads.

        PRD: "Reporting stores all three, stamps `lab_reported_at` with the current logical clock, and flips `measurement_basis` from `SUPPLIER_DECLARED` to `LAB_TESTED`, which is what makes this link admissible under the laboratory exposure method."

        Design: Difficulty/cross_entity_state_dependency/lab_tested_submit_requires_lab_basis_on_every_link
        """
        bundle = half_lab_tested_product
        reported = report_lab_result(
            api, bundle["declared_link"]["id"], 20.0, 1.0,
            lab_name="Cascade Analytical",
        )
        assert_status(reported, LINK_STATUS_TEST_REPORTED)
        assert reported["measurement_basis"] == BASIS_LAB_TESTED

    def test_the_identical_submission_then_succeeds_with_both_contributions(
        self, api, half_lab_tested_product
    ):
        """0.500 ug from the tested link plus 0.250 ug from the newly tested one is 0.750.

        PRD: "Otherwise the own contribution is `lab_result_ppm`."

        Design: Difficulty/cross_entity_state_dependency/lab_tested_submit_requires_lab_basis_on_every_link
        """
        bundle = half_lab_tested_product
        validate_error(
            _submit(api, bundle["assessment"]["id"]), ERR_LAB_RESULT_MISSING, 409
        )
        report_lab_result(
            api, bundle["declared_link"]["id"], 20.0, 1.0,
            lab_name="Cascade Analytical",
        )
        submitted = get_success_data(_submit(api, bundle["assessment"]["id"]))
        assert_status(submitted, ASSESSMENT_SUBMITTED)
        assert submitted["submitted_by_user_id"] is not None
        assert_assessment_verdict(submitted, 0.75, 1.5, RESULT_AT_OR_ABOVE, 2)
