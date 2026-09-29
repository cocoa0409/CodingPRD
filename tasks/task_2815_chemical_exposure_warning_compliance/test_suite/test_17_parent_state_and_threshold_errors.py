"""Two error codes that each guard several different situations.

`ERR_PARENT_STATE_FORBIDS_WRITE` covers three parents at once: a DISCONTINUED
product refuses both component creates and assessment creates, and a WITHDRAWN
chemical refuses declaration of that chemical in a material.

`ERR_TARGET_NOT_BELOW_THRESHOLD` covers two different comparisons at two
different moments of a reformulation project's life: at create the target must be
strictly below the link's current effective concentration, and at verification the
recomputed exposure must be strictly below the chemical's safe harbour level.
"""

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_PARENT_STATE_FORBIDS_WRITE,
    ERR_TARGET_NOT_BELOW_THRESHOLD,
)
from test_helpers.assertions import (
    assert_close,
    assert_concentration,
    assert_exposure,
    assert_fields_null,
    assert_load,
    assert_margin,
    assert_posture,
    assert_status,
)
from test_helpers.constants import (
    ASSESSMENT_FINAL,
    ASSESSMENT_SUPERSEDED,
    BASIS_SUPPLIER_DECLARED,
    COMPONENT_STATUS_ACTIVE,
    DEFAULT_CLOCK,
    ENDPOINT_TYPE_DEVELOPMENTAL,
    LIFECYCLE_DISCONTINUED,
    LINK_STATUS_DECLARED,
    MATERIAL_CLASS_PACKAGING,
    METHOD_MODELED,
    POSTURE_EXPOSURE_UNKNOWN,
    PROJECT_COMPLETED,
    PROJECT_IN_PROGRESS,
    PROJECT_PLANNED,
    PROJECT_VERIFICATION,
    RESULT_AT_OR_ABOVE,
    RESULT_BELOW,
    ROUTE_ORAL,
    SAFE_HARBOR_BASIS_MADL,
)
from test_helpers.fixtures import (
    add_component,
    discontinue_product,
    make_benzene,
    make_final_assessment,
    make_listed_chemical,
    make_material,
    make_product,
    make_supplied_material,
    read_product,
    set_clock,
)
from test_helpers.test_users import (
    COMPLIANCE_ANALYST,
    REGISTRY_ADMIN,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _read_component(api, component_id):
    return get_success_data(api.get_component(component_id, COMPLIANCE_ANALYST))


def _read_link(api, link_id):
    return get_success_data(api.get_material_chemical(link_id, COMPLIANCE_ANALYST))


def _read_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, COMPLIANCE_ANALYST))


def _read_project(api, project_id):
    return get_success_data(
        api.get_reformulation_project(project_id, COMPLIANCE_ANALYST)
    )


def _project_count(api, product_id):
    _, meta = validate_paginated(
        api.list_reformulation_projects(COMPLIANCE_ANALYST, f.page(product_id=product_id))
    )
    return meta["total_count"]


def _open_project(api, bundle, target_concentration_ppm, **overrides):
    """The raw reformulation create, so a refused target can be inspected."""
    return api.create_reformulation_project(
        f.reformulation_payload(
            bundle["product"]["id"],
            bundle["chemical"]["id"],
            bundle["link"]["id"],
            target_concentration_ppm,
            "2026-08-01T00:00:00Z",
            "2026-09-01T00:00:00Z",
            **overrides,
        ),
        COMPLIANCE_ANALYST,
    )


def _move_project(api, project_id, action):
    return api.reformulation_transition(
        project_id, f.action_payload(action), COMPLIANCE_ANALYST
    )


def _started_project(api, bundle, target_concentration_ppm):
    """A project on the target, walked as far as ``IN_PROGRESS``."""
    project = get_success_data(_open_project(api, bundle, target_concentration_ppm))
    get_success_data(_move_project(api, project["id"], "START"))
    return project


# ─────────────────────────────────────────────────────────────────────────────
# Setups
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def clocked(api):
    set_clock(api, DEFAULT_CLOCK)
    return DEFAULT_CLOCK


@pytest.fixture
def discontinued(api, clocked):
    """SKU-E41 is DISCONTINUED straight out of DEVELOPMENT with one component.

    Benzene is LISTED and Toluene is registered and then WITHDRAWN without ever
    being listed. RM-E41 declares Benzene at 40.0 ppm with a VERIFIED disclosure
    and is the product's only component at 0.25 g/unit; RM-E41B is a second
    material of the same supplier that declares nothing at all.
    """
    benzene = make_benzene(api)
    toluene = make_listed_chemical(
        api,
        f.listed_chemical_payload(
            "Toluene",
            "108-88-3",
            ENDPOINT_TYPE_DEVELOPMENTAL,
            SAFE_HARBOR_BASIS_MADL,
            safe_harbor_level_ug_per_day=7.0,
        ),
        list_it=False,
    )
    withdrawn = get_success_data(
        api.listed_chemical_transition(
            toluene["id"], f.action_payload("WITHDRAW"), REGISTRY_ADMIN
        )
    )
    supplied = make_supplied_material(
        api, benzene["id"], 40.0, material_code="RM-E41"
    )
    spare = make_material(
        api,
        "RM-E41B",
        supplied["supplier_id"],
        material_class=MATERIAL_CLASS_PACKAGING,
    )
    product = make_product(
        api, "SKU-E41", product_name="Discontinued Widget", annual_units=500
    )
    component = add_component(api, product["id"], supplied["material"]["id"], 0.25, 0.5)
    discontinue_product(api, product["id"])
    return {
        "benzene": benzene,
        "toluene": withdrawn,
        "material": supplied["material"],
        "spare": spare,
        "product": product,
        "component": component,
    }


@pytest.fixture
def threshold(api, clocked):
    """SKU-T58 carries 800.0 ppm of Benzene and a FINAL assessment at 100.000.

    Benzene's NSRL safe harbour is 6.4 ug/day. The component is 0.25 g/unit at
    contact_factor 0.5, so a modelled ORAL assessment at one use per day evaluates
    800.0 x 0.25 x 0.5 x 1.00 x 1.0 = 100.000 ug/day and the stored load is
    800.0 x 0.25 = 200.000 ug.
    """
    benzene = make_benzene(api)
    supplied = make_supplied_material(
        api, benzene["id"], 800.0, material_code="RM-T58"
    )
    product = make_product(
        api, "SKU-T58", product_name="Threshold Widget", annual_units=500
    )
    add_component(api, product["id"], supplied["material"]["id"], 0.25, 0.5)
    assessment = make_final_assessment(
        api, product["id"], benzene["id"], METHOD_MODELED, ROUTE_ORAL, 1.0
    )
    return {
        "chemical": benzene,
        "material": supplied["material"],
        "link": supplied["link"],
        "product": product,
        "assessment": assessment,
    }


# ─────────────────────────────────────────────────────────────────────────────
# errors
# ─────────────────────────────────────────────────────────────────────────────


class TestParentStateForbidsWrite:
    """One error code, three different forbidding parents."""

    def test_the_lifecycle_move_left_the_posture_and_the_load_alone(
        self, api, discontinued
    ):
        """SKU-E41 is DISCONTINUED and still EXPOSURE_UNKNOWN carrying 10.000 ug.

        PRD: "Both actions are reserved to a `RegistryAdmin`, both increment the product's `version` by 1, and neither touches `compliance_posture` — the two dimensions are genuinely independent."
        PRD: "clause 1 does not apply, and either the product has zero components in status `ACTIVE`, or some active component's material (or any material anywhere in that material's subtree) has a `disclosure_status` of `NOT_REQUESTED`, `REQUESTED`, `INCOMPLETE` or `REFUSED`, or some listed chemical reachable from the active components has no exposure assessment for this product in status `FINAL`."

        Benzene is reachable from the one active component and has no FINAL
        assessment, so clause 2 of the posture ladder holds.

        Design: Corner/errors/err_parent_state_forbids_write_on_discontinued_product_and_withdrawn_chemical
        """
        product = read_product(api, discontinued["product"]["id"])
        assert product["lifecycle_state"] == LIFECYCLE_DISCONTINUED, (
            f"Expected DISCONTINUED, got {product['lifecycle_state']!r}"
        )
        assert_posture(product, POSTURE_EXPOSURE_UNKNOWN)
        assert_load(product["total_listed_chemical_load_ug"], 10.000)

    def test_a_component_create_under_a_discontinued_product_is_refused(
        self, api, discontinued
    ):
        """The product is the forbidding parent of a bill-of-materials create.

        PRD: "Once a product is `DISCONTINUED`, creating a component on it, creating an exposure assessment for it and creating a placement under one of its determinations are all refused with `ERR_PARENT_STATE_FORBIDS_WRITE`, while posture recomputation continues normally, so a discontinued product can still enter and later leave an enforcement hold."

        Design: Corner/errors/err_parent_state_forbids_write_on_discontinued_product_and_withdrawn_chemical
        """
        response = api.create_component(
            discontinued["product"]["id"],
            f.component_payload(
                discontinued["spare"]["id"],
                quantity_grams_per_unit=0.10,
                contact_factor=1.0,
            ),
            COMPLIANCE_ANALYST,
        )
        validate_error(response, ERR_PARENT_STATE_FORBIDS_WRITE, 409)

    def test_an_assessment_create_under_a_discontinued_product_is_refused(
        self, api, discontinued
    ):
        """The same parent forbids opening an exposure assessment.

        PRD: "Once a product is `DISCONTINUED`, creating a component on it, creating an exposure assessment for it and creating a placement under one of its determinations are all refused with `ERR_PARENT_STATE_FORBIDS_WRITE`, while posture recomputation continues normally, so a discontinued product can still enter and later leave an enforcement hold."

        The chemical is LISTED, so nothing else about this request is wrong.

        Design: Corner/errors/err_parent_state_forbids_write_on_discontinued_product_and_withdrawn_chemical
        """
        response = api.create_assessment(
            discontinued["product"]["id"],
            f.assessment_payload(
                discontinued["benzene"]["id"], METHOD_MODELED, ROUTE_ORAL, 1.0
            ),
            COMPLIANCE_ANALYST,
        )
        validate_error(response, ERR_PARENT_STATE_FORBIDS_WRITE, 409)

    def test_a_declaration_against_a_withdrawn_chemical_is_refused(
        self, api, discontinued
    ):
        """Here the chemical, not the product, is the forbidding parent.

        PRD: "A link may not be created against a chemical whose registry `status` is `WITHDRAWN`, which is refused with `ERR_PARENT_STATE_FORBIDS_WRITE`."

        RM-E41B is not attached to the discontinued product at all, so the product
        cannot be what refuses this write.

        Design: Corner/errors/err_parent_state_forbids_write_on_discontinued_product_and_withdrawn_chemical
        """
        response = api.create_material_chemical(
            discontinued["spare"]["id"],
            f.material_chemical_payload(discontinued["toluene"]["id"], 12.0),
            COMPLIANCE_ANALYST,
        )
        validate_error(response, ERR_PARENT_STATE_FORBIDS_WRITE, 409)

    def test_removing_a_component_of_a_discontinued_product_is_refused(
        self, api, discontinued
    ):
        """Removal is blocked by the same code and the component survives ACTIVE.

        PRD: "Removal is also blocked while the parent product is `DISCONTINUED`, with `ERR_PARENT_STATE_FORBIDS_WRITE`."

        Design: Corner/errors/err_parent_state_forbids_write_on_discontinued_product_and_withdrawn_chemical
        """
        response = api.component_transition(
            discontinued["component"]["id"],
            f.action_payload("REMOVE"),
            COMPLIANCE_ANALYST,
        )
        validate_error(response, ERR_PARENT_STATE_FORBIDS_WRITE, 409)
        assert_status(
            _read_component(api, discontinued["component"]["id"]),
            COMPONENT_STATUS_ACTIVE,
        )

    def test_the_same_endpoint_succeeds_for_a_listed_chemical(self, api, discontinued):
        """Declaring the LISTED Benzene in RM-E41B is accepted.

        PRD: "A newly declared link starts with `measurement_basis` set to `SUPPLIER_DECLARED` and `status` set to `DECLARED`, with `lab_name`, `lab_result_ppm`, `lab_loq_ppm`, `lab_reported_at` and `dispute_note` all null."

        The refusal is a property of the WITHDRAWN parent, not of the endpoint.

        Design: Corner/errors/err_parent_state_forbids_write_on_discontinued_product_and_withdrawn_chemical
        """
        link = get_success_data(
            api.create_material_chemical(
                discontinued["spare"]["id"],
                f.material_chemical_payload(discontinued["benzene"]["id"], 12.0),
                COMPLIANCE_ANALYST,
            )
        )
        assert_status(link, LINK_STATUS_DECLARED)
        assert link["measurement_basis"] == BASIS_SUPPLIER_DECLARED, (
            f"Expected SUPPLIER_DECLARED, got {link['measurement_basis']!r}"
        )
        assert_fields_null(
            link, ["lab_name", "lab_result_ppm", "lab_loq_ppm", "lab_reported_at"]
        )

    def test_none_of_the_refused_writes_moved_the_stored_load(self, api, discontinued):
        """Four refusals in a row leave the product exactly as it was.

        PRD: "Rules are evaluated in ascending priority order; the first rule whose condition holds short-circuits the request and returns its error, and no later rule is evaluated."
        PRD: "For each such chemical-and-component pair the server evaluates the modelled effective concentration of that chemical in that component's material — the roll-up described in Section 3.5, always under the modelled variant regardless of any assessment — multiplies it by that component's `quantity_grams_per_unit`, and rounds the product half up to three decimal places."

        Design: Corner/errors/err_parent_state_forbids_write_on_discontinued_product_and_withdrawn_chemical
        """
        before = api.product_version(discontinued["product"]["id"], COMPLIANCE_ANALYST)

        validate_error(
            api.create_component(
                discontinued["product"]["id"],
                f.component_payload(
                    discontinued["spare"]["id"],
                    quantity_grams_per_unit=0.10,
                    contact_factor=1.0,
                ),
                COMPLIANCE_ANALYST,
            ),
            ERR_PARENT_STATE_FORBIDS_WRITE,
            409,
        )
        validate_error(
            api.create_assessment(
                discontinued["product"]["id"],
                f.assessment_payload(
                    discontinued["benzene"]["id"], METHOD_MODELED, ROUTE_ORAL, 1.0
                ),
                COMPLIANCE_ANALYST,
            ),
            ERR_PARENT_STATE_FORBIDS_WRITE,
            409,
        )
        validate_error(
            api.create_material_chemical(
                discontinued["spare"]["id"],
                f.material_chemical_payload(discontinued["toluene"]["id"], 12.0),
                COMPLIANCE_ANALYST,
            ),
            ERR_PARENT_STATE_FORBIDS_WRITE,
            409,
        )
        validate_error(
            api.component_transition(
                discontinued["component"]["id"],
                f.action_payload("REMOVE"),
                COMPLIANCE_ANALYST,
            ),
            ERR_PARENT_STATE_FORBIDS_WRITE,
            409,
        )

        product = read_product(api, discontinued["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 10.000)
        assert product["version"] == before, (
            f"Expected the version to stay at {before}, got {product['version']}"
        )


class TestReformulationTargetThreshold:
    """One error code guarding two comparisons at two moments.

    At create the target is measured against the link's current concentration; at
    verification the resulting exposure is measured against the safe harbour level,
    and both boundaries are strict.
    """

    def test_a_target_equal_to_the_current_concentration_is_refused(
        self, api, threshold
    ):
        """800.0 is not strictly below the link's current 800.0.

        PRD: "Create-time validation also requires the target to be a genuine improvement: `target_concentration_ppm` must be strictly less than the linked material-chemical's current effective concentration, and a target equal to or above the current concentration is refused with `ERR_TARGET_NOT_BELOW_THRESHOLD`."
        PRD: "Otherwise the server multiplies together five factors — the effective concentration, the component's `quantity_grams_per_unit`, the component's `contact_factor`, the absorption factor for the assessment's `route`, and the assessment's `uses_per_day` — and rounds that product half up to three decimal places, giving one per-component contribution."
        PRD: "Otherwise `margin_ratio` is `daily_exposure_ug` divided by `safe_harbor_level_ug_per_day`, rounded half up to four decimal places, and `result` is `AT_OR_ABOVE_SAFE_HARBOR` when `daily_exposure_ug` is greater than or equal to the level and `BELOW_SAFE_HARBOR` when it is strictly less."

        The setup it is measured against is pinned: 800.0 ppm at 0.25 g/unit and
        contact_factor 0.5 gives a 100.000 ug/day modelled ORAL exposure, a
        margin_ratio of 15.6250 against the 6.4 ug/day NSRL, and a 200.000 ug load.

        Design: Corner/errors/err_reformulation_target_not_below_threshold_at_create_and_at_complete
        """
        product = read_product(api, threshold["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 200.000)
        assessment = _read_assessment(api, threshold["assessment"]["id"])
        assert_exposure(assessment["daily_exposure_ug"], 100.000)
        assert_margin(assessment["margin_ratio"], 15.6250)
        assert assessment["result"] == RESULT_AT_OR_ABOVE, (
            f"Expected AT_OR_ABOVE_SAFE_HARBOR, got {assessment['result']!r}"
        )

        validate_error(
            _open_project(api, threshold, 800.0), ERR_TARGET_NOT_BELOW_THRESHOLD, 422
        )
        assert _project_count(api, threshold["product"]["id"]) == 0, (
            "The refused create must not have stored a project"
        )

    def test_a_genuine_improvement_is_accepted_and_captures_its_baseline(
        self, api, threshold
    ):
        """A target of 51.2 is stored PLANNED with the FINAL exposure as baseline.

        PRD: "`baseline_daily_exposure_ug` is the `daily_exposure_ug` of the newest assessment in status `FINAL` for the same product and chemical pair, where "newest" means ranked by `finalized_at` descending and then by `created_at` descending as the tie-break; when the product has no `FINAL` assessment for that chemical the baseline is 0."
        PRD: "`verified_daily_exposure_ug` and `reduction_pct` both start null and `status` starts `PLANNED`."

        Design: Corner/errors/err_reformulation_target_not_below_threshold_at_create_and_at_complete
        """
        project = get_success_data(_open_project(api, threshold, 51.2))
        assert_status(project, PROJECT_PLANNED)
        assert_exposure(
            project["baseline_daily_exposure_ug"], 100.000, "baseline_daily_exposure_ug"
        )
        assert_fields_null(project, ["verified_daily_exposure_ug", "reduction_pct"])

    def test_verification_is_refused_when_the_new_exposure_only_equals_the_level(
        self, api, threshold
    ):
        """51.2 ppm lands exactly on the safe harbour, and equality is refused.

        PRD: "Submission is refused with `ERR_TARGET_NOT_BELOW_THRESHOLD` when the resulting `verified_daily_exposure_ug` is not strictly less than the chemical's `safe_harbor_level_ug_per_day`."
        PRD: "Otherwise the server multiplies together five factors — the effective concentration, the component's `quantity_grams_per_unit`, the component's `contact_factor`, the absorption factor for the assessment's `route`, and the assessment's `uses_per_day` — and rounds that product half up to three decimal places, giving one per-component contribution."

        51.2 x 0.25 x 0.5 x 1.00 x 1.0 is 6.400, and the NSRL is 6.4, so an
        implementation comparing with <= would wrongly accept this submission. The
        refusal leaves the formulation, the FINAL assessment and the load untouched.

        Design: Corner/errors/err_reformulation_target_not_below_threshold_at_create_and_at_complete
        """
        project = _started_project(api, threshold, 51.2)

        validate_error(
            _move_project(api, project["id"], "SUBMIT_VERIFICATION"),
            ERR_TARGET_NOT_BELOW_THRESHOLD,
            422,
        )

        assert_status(_read_project(api, project["id"]), PROJECT_IN_PROGRESS)
        assert_concentration(
            _read_link(api, threshold["link"]["id"])["declared_concentration_ppm"],
            800.0,
        )
        assessment = _read_assessment(api, threshold["assessment"]["id"])
        assert_status(assessment, ASSESSMENT_FINAL)
        assert_exposure(assessment["daily_exposure_ug"], 100.000)
        product = read_product(api, threshold["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 200.000)

    def test_a_target_that_clears_the_level_rewrites_the_formulation(
        self, api, threshold
    ):
        """8.0 ppm verifies at 1.000 ug/day and tears down the old numbers.

        PRD: "At level one the linked material-chemical's `declared_concentration_ppm` is overwritten with the project's `target_concentration_ppm`, its `status` resets to `DECLARED`, its `measurement_basis` resets to `SUPPLIER_DECLARED`, and `lab_name`, `lab_result_ppm`, `lab_loq_ppm` and `lab_reported_at` are all cleared — the old laboratory evidence describes a formulation that no longer exists."
        PRD: "Submitting for verification also stamps `verified_daily_exposure_ug` with the recomputed modelled exposure for the project's product and chemical pair and computes `reduction_pct` as one hundred times the difference between `baseline_daily_exposure_ug` and `verified_daily_exposure_ug` divided by `baseline_daily_exposure_ug`, rounded half up to two decimal places; when `baseline_daily_exposure_ug` is 0 the percentage is undefined and `reduction_pct` is null."

        8.0 x 0.25 x 0.5 gives 1.000 ug/day, so the reduction from the 100.000
        baseline is 99.00 per cent; the FINAL assessment is recomputed against the
        new concentration and then superseded, and the load falls to 2.000.

        Design: Corner/errors/err_reformulation_target_not_below_threshold_at_create_and_at_complete
        """
        project = _started_project(api, threshold, 8.0)
        verified = get_success_data(
            _move_project(api, project["id"], "SUBMIT_VERIFICATION")
        )
        assert_status(verified, PROJECT_VERIFICATION)
        assert_exposure(
            verified["verified_daily_exposure_ug"], 1.000, "verified_daily_exposure_ug"
        )
        assert_close(verified["reduction_pct"], 99.00, 2, "reduction_pct")

        link = _read_link(api, threshold["link"]["id"])
        assert_concentration(link["declared_concentration_ppm"], 8.0)
        assert_status(link, LINK_STATUS_DECLARED)
        assert link["measurement_basis"] == BASIS_SUPPLIER_DECLARED, (
            f"Expected SUPPLIER_DECLARED, got {link['measurement_basis']!r}"
        )

        assessment = _read_assessment(api, threshold["assessment"]["id"])
        assert_status(assessment, ASSESSMENT_SUPERSEDED)
        assert_exposure(assessment["daily_exposure_ug"], 1.000)
        assert_margin(assessment["margin_ratio"], 0.1563)
        assert assessment["result"] == RESULT_BELOW, (
            f"Expected BELOW_SAFE_HARBOR, got {assessment['result']!r}"
        )

        product = read_product(api, threshold["product"]["id"])
        assert_load(product["total_listed_chemical_load_ug"], 2.000)

    def test_completion_accepts_a_strictly_lower_exposure_and_keeps_the_rewrite(
        self, api, threshold
    ):
        """1.000 is strictly below 6.4, so COMPLETE lands and 8.0 ppm stays.

        PRD: "Completing takes the project `VERIFICATION → COMPLETED` and requires `verified_daily_exposure_ug` to be **strictly** below the chemical's `safe_harbor_level_ug_per_day`; exposure exactly equal to the safe harbour level fails with `ERR_TARGET_NOT_BELOW_THRESHOLD`, which is the mirror image of the assessment verdict rule, where exposure exactly at the level is treated as `BELOW_SAFE_HARBOR`."

        Design: Corner/errors/err_reformulation_target_not_below_threshold_at_create_and_at_complete
        """
        project = _started_project(api, threshold, 8.0)
        get_success_data(_move_project(api, project["id"], "SUBMIT_VERIFICATION"))

        completed = get_success_data(_move_project(api, project["id"], "COMPLETE"))
        assert_status(completed, PROJECT_COMPLETED)
        assert_exposure(
            completed["verified_daily_exposure_ug"],
            1.000,
            "verified_daily_exposure_ug",
        )
        assert_concentration(
            _read_link(api, threshold["link"]["id"])["declared_concentration_ppm"], 8.0
        )
