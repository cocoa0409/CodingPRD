"""Authentication and role-based access control: missing headers, role
exclusivity, and the entity-backed Operator ownership chain."""
import pytest

from test_helpers import (
    validate_error,
    ApiErrorId,
    create_operator,
    create_engine,
    setup_enrolled_engine,
    setup_submitted_workscope,
    submit_report,
    create_agreement_payload,
    create_flight_hour_report_payload,
    make_operator_headers,
)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request that arrives without these headers, or whose
    `X-User-Role` value is not one of the declared roles, is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD §2.8 (tier 1): "The `X-User-Role` and `X-User-ID` headers are present
    and the role is a declared role, else `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401
    """
    res = api.list_engines({})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_operator_cannot_create_agreement(api):
    """PRD §2.1: "Access to specific operations is additionally restricted by
    role; an attempt to perform an action outside the caller's designated role
    is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "The `ContractManager` owns the commercial contract lifecycle:
    drafting, activating, renegotiating, amending agreements, enrolling
    engines, and resolving sourcing escalations with an override."

    Design: Corner/rbac/operator_cannot_create_agreement
    """
    operator = create_operator(name="Wren Air", iata_code="WA", credit_rating="B")
    res = api.create_agreement(
        create_agreement_payload(contract_ref="LTSA-R3501"),
        make_operator_headers(operator["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_shopplanner_cannot_verify_report(api, shop_planner_headers):
    """PRD §2.1: "Access to specific operations is additionally restricted by
    role; an attempt to perform an action outside the caller's designated role
    is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "The `FinanceController` verifies utilization reports, issues
    and settles billing statements, and appends contract-accounting
    snapshots."

    Design: Corner/rbac/shopplanner_cannot_verify_report
    """
    fx = setup_enrolled_engine(
        esn="ESN-W201",
        operator_overrides={"name": "Wolf Air", "iata_code": "WB"},
        agreement_overrides={"contract_ref": "LTSA-R3601"},
    )
    report = submit_report(fx["engine"], fx["operator_headers"],
                           period="2026-09", flight_hours=100, cycles=40,
                           observed_severity="BENIGN")
    res = api.verify_flight_hour_report(report["id"], shop_planner_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_operator_cannot_report_for_foreign_engine(api):
    """PRD §2.1: "When `X-User-Role` is `Operator`, `X-User-ID` is the `id` of
    the acting `Operator` entity; ownership checks on any resource traceable
    to an operator compare the resource's owning operator to `X-User-ID`."
    and "An `Operator` caller whose `X-User-ID` does not match the resolved
    owning operator is rejected with `ERR_FORBIDDEN`."
    PRD §2.8: authorization (tier 2) runs before state preconditions
    (tier 6), so the ownership failure surfaces even though the engine is
    also not enrolled.

    Design: Corner/rbac/operator_cannot_report_for_foreign_engine
    """
    operator_a = create_operator(name="Xen Air", iata_code="XA", credit_rating="B")
    operator_b = create_operator(name="Xyst Air", iata_code="XB", credit_rating="B")
    engine = create_engine(operator_a, esn="ESN-X101")

    res = api.submit_flight_hour_report(
        engine["id"],
        create_flight_hour_report_payload(period="2026-09", flight_hours=100,
                                          cycles=40, observed_severity="BENIGN"),
        make_operator_headers(operator_b["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


def test_finance_cannot_approve_workscope(api, finance_controller_headers):
    """PRD §2.1: "Access to specific operations is additionally restricted by
    role; an attempt to perform an action outside the caller's designated role
    is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "The `Operator` is the airline customer: it submits utilization
    reports, schedules shop visits, approves or rejects workscopes, and
    reserves, activates, and returns spare-engine leases."

    Design: Corner/rbac/finance_cannot_approve_workscope
    """
    fx = setup_enrolled_engine(
        esn="ESN-Y101",
        operator_overrides={"name": "Yew Air", "iata_code": "YA"},
        agreement_overrides={"contract_ref": "LTSA-R3801"},
    )
    fx = setup_submitted_workscope(fx)
    res = api.approve_workscope(fx["workscope"]["id"], finance_controller_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)
