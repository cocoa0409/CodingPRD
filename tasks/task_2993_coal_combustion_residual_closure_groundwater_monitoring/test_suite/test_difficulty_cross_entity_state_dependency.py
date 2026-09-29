"""Writes whose admissibility is decided by a neighbouring aggregate's state."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import assertions as a
from test_helpers import factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.constants import (
    CLOSURE_STATE_CLOSURE_PLANNED,
    EVAL_VERDICT_SSL_EXCEEDANCE,
    LICENSE_ACTIVE,
    LICENSE_LAPSED,
    METHOD_CLOSURE_BY_REMOVAL,
    PARAM_ARSENIC,
    PHASE_CORRECTIVE_ACTION,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_FULLY_CERTIFIED,
    POSTURE_RESTRICTED,
    STABILITY_ADEQUATE,
    STABILITY_UNASSESSED,
)
from test_helpers.test_users import REGULATOR_HEADERS, UTILITY_ADMIN_HEADERS

ARSENIC_BACKGROUND = (0.0020, 0.0030, 0.0025, 0.0028)
ARSENIC_DETECTION = 0.0150
REMOVAL_JUSTIFICATION = (
    "Corrective action remedy requires excavation of the saturated ash to control the arsenic source"
)


def case_lapsed_geotechnical_licence(api):
    """A clean unit and a geotechnical engineer whose licence has lapsed."""
    world = fixtures.seed_unit(api, "IMP-0014")
    get_success_data(
        api.set_license_status(
            world["geotech_id"],
            factories.license_status_payload(LICENSE_LAPSED, "2026-08-01"),
            UTILITY_ADMIN_HEADERS,
        )
    )
    return world


def case_program_in_corrective_action_with_two_certified_plans(api):
    """One unit, two fully certified plans, and a program driven to corrective action.

    Arsenic is used rather than sulfate because its comparison value has to clear
    the groundwater protection standard as well as the prediction limit for the
    verdict to be an `SSL_EXCEEDANCE` that a retest can escalate twice.
    """
    world = fixtures.seed_ssi_ready(
        api,
        "IMP-0015",
        background_values=ARSENIC_BACKGROUND,
        detection_value=ARSENIC_DETECTION,
        parameter_code=PARAM_ARSENIC,
    )
    world["first_evaluation"] = fixtures.issue_evaluation(
        api, world, "EV-SSL-1", PARAM_ARSENIC, retest_confirmed=True
    )
    world["second_evaluation"] = fixtures.issue_evaluation(
        api, world, "EV-SSL-2", PARAM_ARSENIC, retest_confirmed=True
    )

    fixtures.file_stability(api, world, "2026-07-15")
    in_place = fixtures.draft_plan(api, world, "CP-IN-PLACE")
    fixtures.certify_plan_both_halves(api, world, in_place["id"], "2026-08-01")
    removal = fixtures.draft_plan(
        api,
        world,
        "CP-REMOVAL",
        selected_method=METHOD_CLOSURE_BY_REMOVAL,
        selection_justification=REMOVAL_JUSTIFICATION,
    )
    fixtures.certify_plan_both_halves(api, world, removal["id"], "2026-08-01")
    world["in_place_plan_id"] = in_place["id"]
    world["removal_plan_id"] = removal["id"]
    return world


def read_plan(api, plan_id):
    return get_success_data(api.get_closure_plan(plan_id, UTILITY_ADMIN_HEADERS))


def test_a_lapsed_licence_refuses_the_stability_filing_the_unit_itself_admits(api):
    """The blocking state lives on the signer, not on the unit or the payload.

    PRD: 14. The acting professional's licence is `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`.
    PRD: `governing_stability_verdict` starts `UNASSESSED`
    Design: Difficulty/cross_entity_state_dependency/stability_certification_gated_by_the_signing_professionals_license_state
    """
    world = case_lapsed_geotechnical_licence(api)

    response = api.create_stability_assessment(
        factories.stability_payload(world["unit_id"], "2026-07-15"), world["geotech_headers"]
    )

    validate_error(response, ApiErrorId.LICENSE_NOT_ACTIVE.value)
    filed, _ = fixtures.page(
        api.list_stability_assessments(UTILITY_ADMIN_HEADERS, {"unit_id": world["unit_id"]})
    )
    assert filed == []
    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["governing_stability_verdict"] == STABILITY_UNASSESSED


def test_restoring_the_licence_admits_the_very_same_payload(api):
    """Nothing about the request changes, only the signer's licence state.

    PRD: 14. The acting professional's licence is `ACTIVE`, else `ERR_LICENSE_NOT_ACTIVE`.
    PRD: The server records `certifying_professional_id` from the acting engineer's header identity
    Design: Difficulty/cross_entity_state_dependency/stability_certification_gated_by_the_signing_professionals_license_state
    """
    world = case_lapsed_geotechnical_licence(api)
    payload = factories.stability_payload(world["unit_id"], "2026-07-15")

    restored = get_success_data(
        api.set_license_status(
            world["geotech_id"],
            factories.license_status_payload(LICENSE_ACTIVE, "2026-08-01"),
            UTILITY_ADMIN_HEADERS,
        )
    )
    assert restored["license_status"] == LICENSE_ACTIVE
    a.assert_date(
        restored["license_status_effective_on"], "2026-08-01", "license_status_effective_on"
    )

    assessment = get_success_data(
        api.create_stability_assessment(payload, world["geotech_headers"]), 201
    )

    assert assessment["verdict"] == STABILITY_ADEQUATE
    assert assessment["certifying_professional_id"] == world["geotech_id"]
    assert assessment["deficient_criteria"] == []
    unit = fixtures.read_unit(api, world["unit_id"])
    assert unit["governing_stability_verdict"] == STABILITY_ADEQUATE
    a.assert_date(unit["stability_posting_due_date"], "2026-08-14", "stability_posting_due_date")


def test_an_in_place_plan_is_refused_while_the_sibling_program_is_in_corrective_action(api):
    """The plan is impeccable; the monitoring program next to it is not.

    PRD: it cannot be approved while the unit's monitoring program is in `CORRECTIVE_ACTION`, which is `ERR_REMEDY_REQUIRES_REMOVAL` (HTTP 409).
    PRD: An `SSL_EXCEEDANCE` verdict with `retest_confirmed` true issued while the program is already in `ASSESSMENT` drives a second escalation, `ASSESSMENT` -> `CORRECTIVE_ACTION`
    Design: Difficulty/cross_entity_state_dependency/in_place_approval_gated_by_the_monitoring_programs_corrective_action_phase
    """
    world = case_program_in_corrective_action_with_two_certified_plans(api)
    assert world["first_evaluation"]["verdict"] == EVAL_VERDICT_SSL_EXCEEDANCE
    a.assert_four_dp(
        world["first_evaluation"]["background_upper_limit"], 0.0040, "background_upper_limit"
    )
    a.assert_four_dp(world["first_evaluation"]["background_mean"], 0.0026, "background_mean")
    a.assert_six_dp(world["first_evaluation"]["background_stdev"], 0.000435, "background_stdev")
    assert world["second_evaluation"]["verdict"] == EVAL_VERDICT_SSL_EXCEEDANCE
    a.assert_four_dp(
        world["second_evaluation"]["comparison_value"], ARSENIC_DETECTION, "comparison_value"
    )
    assert fixtures.read_program(api, world["program_id"])["phase"] == PHASE_CORRECTIVE_ACTION
    # RESTRICTED and not FROZEN, so the refusal below is not the posture gate.
    assert fixtures.read_unit(api, world["unit_id"])["compliance_posture"] == POSTURE_RESTRICTED

    response = api.approve_closure_plan(
        world["in_place_plan_id"],
        factories.approve_plan_payload("2026-08-01", "PERMIT-2026-D"),
        REGULATOR_HEADERS,
    )

    validate_error(response, ApiErrorId.REMEDY_REQUIRES_REMOVAL.value)
    plan = read_plan(api, world["in_place_plan_id"])
    assert plan["status"] == PLAN_STATUS_FULLY_CERTIFIED
    assert plan["approved_on"] is None


def test_the_removal_plan_on_the_same_unit_in_the_same_phase_is_approved(api):
    """A unit in corrective action may still be closed if the ash goes away.

    PRD: A `CLOSURE_BY_REMOVAL` plan passes both gates untouched - a unit in corrective action may still be closed, provided the ash goes away.
    Design: Difficulty/cross_entity_state_dependency/in_place_approval_gated_by_the_monitoring_programs_corrective_action_phase
    """
    world = case_program_in_corrective_action_with_two_certified_plans(api)

    approved = fixtures.approve_plan(api, world["removal_plan_id"], "2026-08-01", "PERMIT-2026-E")

    assert approved["status"] == PLAN_STATUS_APPROVED
    assert approved["permit_reference"] == "PERMIT-2026-E"
    assert fixtures.read_unit(api, world["unit_id"])["closure_state"] == CLOSURE_STATE_CLOSURE_PLANNED
