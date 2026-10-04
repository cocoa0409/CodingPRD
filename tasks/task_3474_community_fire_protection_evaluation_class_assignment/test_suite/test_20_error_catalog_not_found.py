"""Existence ladder: every resource type answers its own 404 error id."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    make_fire_chief_headers,
    make_water_utility_manager_headers,
    premium_quote_payload,
    validate_error,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]
ANALYST = TEST_USERS["field_analyst_headers"]
REGISTRAR = TEST_USERS["class_registrar_headers"]
INSURER = TEST_USERS["insurer_headers"]


def test_score_sheet_finalize_not_found_returns_404(api):
    """PRD §2.11: "the first identifier that matches nothing produces that
    resource type's own 404 — respectively `ERR_COMMUNITY_NOT_FOUND`,
    `ERR_CYCLE_NOT_FOUND`, `ERR_SCORE_SHEET_NOT_FOUND`".

    Design: Corner/errors/score_sheet_finalize_not_found_returns_404
    """
    resp = api.finalize_score_sheet(NON_EXISTENT_UUID, ANALYST)
    validate_error(resp, ApiErrorId.ERR_SCORE_SHEET_NOT_FOUND)


def test_classification_activate_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_CLASSIFICATION_NOT_FOUND` … before any deeper identifier is
    examined."

    Design: Corner/errors/classification_activate_not_found_returns_404
    """
    resp = api.activate_classification(
        NON_EXISTENT_UUID, {"effective_from": "2026-09-01"}, REGISTRAR
    )
    validate_error(resp, ApiErrorId.ERR_CLASSIFICATION_NOT_FOUND)


def test_department_patch_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_DEPARTMENT_NOT_FOUND`".

    Design: Corner/errors/department_patch_not_found_returns_404
    """
    resp = api.patch_fire_department(
        NON_EXISTENT_UUID, {"career_on_duty_per_shift": 2},
        make_fire_chief_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_DEPARTMENT_NOT_FOUND)


def test_apparatus_patch_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_APPARATUS_NOT_FOUND`".

    Design: Corner/errors/apparatus_patch_not_found_returns_404
    """
    resp = api.patch_apparatus(
        NON_EXISTENT_UUID, {"status": "RESERVE"}, make_fire_chief_headers("dept-x")
    )
    validate_error(resp, ApiErrorId.ERR_APPARATUS_NOT_FOUND)


def test_system_patch_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_SYSTEM_NOT_FOUND`".

    Design: Corner/errors/system_patch_not_found_returns_404
    """
    resp = api.patch_water_supply_system(
        NON_EXISTENT_UUID, {"storage_capacity_gal": 1000},
        make_water_utility_manager_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_SYSTEM_NOT_FOUND)


def test_hydrant_patch_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_HYDRANT_NOT_FOUND`".

    Design: Corner/errors/hydrant_patch_not_found_returns_404
    """
    resp = api.patch_hydrant(
        NON_EXISTENT_UUID, {"status": "OUT_OF_SERVICE"},
        make_water_utility_manager_headers("sys-x"),
    )
    validate_error(resp, ApiErrorId.ERR_HYDRANT_NOT_FOUND)


def test_flow_test_transition_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_FLOW_TEST_NOT_FOUND`".

    Design: Corner/errors/flow_test_transition_not_found_returns_404
    """
    resp = api.transition_flow_test(
        NON_EXISTENT_UUID, {"target_state": "WITNESSED"}, ANALYST
    )
    validate_error(resp, ApiErrorId.ERR_FLOW_TEST_NOT_FOUND)


def test_credit_transition_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_CREDIT_NOT_FOUND`".

    Design: Corner/errors/credit_transition_not_found_returns_404
    """
    resp = api.transition_risk_reduction_credit(
        NON_EXISTENT_UUID, {"target_state": "VERIFIED"}, ANALYST
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_NOT_FOUND)


def test_quote_create_property_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_PROPERTY_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`".

    Design: Corner/errors/quote_create_property_not_found_returns_404
    """
    resp = api.create_premium_quote(
        premium_quote_payload(NON_EXISTENT_UUID, coverage_amount_cents=1000000), INSURER
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_FOUND)


def test_request_transition_not_found_returns_404(api):
    """PRD §2.11: "produces that resource type's own 404 — respectively …
    `ERR_REQUEST_NOT_FOUND`".

    Design: Corner/errors/request_transition_not_found_returns_404
    """
    resp = api.transition_reevaluation_request(
        NON_EXISTENT_UUID, {"target_state": "DOCUMENTATION_REVIEW"}, COORD
    )
    validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_FOUND)


def test_appeal_transition_not_found_returns_404(api):
    """PRD §2.11: "the first identifier that matches nothing produces that
    resource type's own 404 — respectively … or `ERR_APPEAL_NOT_FOUND` —
    before any deeper identifier is examined."

    Design: Corner/errors/appeal_transition_not_found_returns_404
    """
    resp = api.transition_appeal(
        NON_EXISTENT_UUID, {"target_state": "DATA_VERIFICATION"}, ANALYST
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_FOUND)
