"""Segregation of duties: which role may drive which step, and which roles
are refused outright however wide their operational remit."""
from test_helpers import (
    api_client,
    build_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    ANALYST,
    APPROVER,
    OPERATOR,
    SERVICE_ENGINEER,
    get_ppa,
    setup_draft_ppa,
    setup_validated_line,
)

SERVICE_PLAN_PAYLOAD = {
    "remote_monitoring_status": "MONITORING_LINKED",
    "radius_buffer_m": 10.0,
    "window_start_iso8601": None,
    "window_end_iso8601": None,
}


def test_a_service_engineer_cannot_activate_a_contract_and_an_operator_cannot_plan_service():
    """PRD §2.1: "A `ServiceEngineer` owns remote monitoring, maintenance windows and module
    replacement staging."
    PRD §3.7: "Every live contract is maintained through a service plan created by a `ServiceEngineer`, and
    the plan carries three independent dimensions that move on their own schedules: an operational
    lifecycle, an independent hardware-replacement stage, and a monitoring health reading."
    PRD §2.1: "A request that is properly authenticated
    but whose role is not among the roles the addressed operation admits is refused with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/service_engineer_reads_service_plans_but_cannot_create_them
    """
    ctx = setup_draft_ppa()

    refused_activate = api_client.activate_ppa(ctx["ppa_id"], SERVICE_ENGINEER)
    validate_error(refused_activate, ApiErrorId.ERR_UNAUTHORIZED)
    assert refused_activate.status_code == 403, (
        "the contract itself belongs to the SiteOperator, not to the engineering role; got "
        f"{refused_activate.status_code}"
    )
    assert get_ppa(ctx["ppa_id"])["state"] == "PPA_DRAFT", (
        "a refused activation leaves the contract where it was"
    )

    refused_plan = api_client.create_service_plan(
        ctx["ppa_id"], OPERATOR, SERVICE_PLAN_PAYLOAD
    )
    validate_error(refused_plan, ApiErrorId.ERR_UNAUTHORIZED)
    assert refused_plan.status_code == 403, (
        "the widest operational role is still not the one that creates service plans; got "
        f"{refused_plan.status_code}"
    )

    activated = validate_success(api_client.activate_ppa(ctx["ppa_id"], OPERATOR))
    assert activated["state"] == "PPA_ACTIVE"

    rows, meta = validate_paginated(
        api_client.list_service_plans(ctx["ppa_id"], SERVICE_ENGINEER)
    )
    assert meta["total_count"] == 1, (
        "the engineering role reads the plan the activation cascade created; got "
        f"{meta['total_count']} plans"
    )
    assert rows[0]["id"] == activated["assigned_service_plan_id"]


def test_no_operational_role_is_a_superset_that_approves_on_its_own_authority():
    """PRD §2.1: "The seven roles are `SiteOperator`, `Customer`, `CustomerService`, `FuelCoordinator`,
    `ServiceEngineer`, `SettlementAnalyst` and `SettlementApprover`."
    PRD §2.1: "A request that is properly authenticated
    but whose role is not among the roles the addressed operation admits is refused with
    `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.4: "Approval belongs to the `SettlementApprover` and is narrower than validation."

    Design: Corner/rbac/platform_admin_role_is_not_granted_automatic_override
    """
    ctx = setup_validated_line()
    assert ctx["line"]["status"] == "SETTLEMENT_VALIDATED"

    refused = api_client.approve_settlement_line(
        ctx["ppa_id"], ctx["line_id"], OPERATOR
    )
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED)
    assert refused.status_code == 403, (
        "the role that owns the site and the contract is still refused on approval; got "
        f"{refused.status_code}"
    )
    assert (
        validate_success(
            api_client.get_settlement_line(ctx["ppa_id"], ctx["line_id"], ANALYST)
        )["status"]
        == "SETTLEMENT_VALIDATED"
    ), "a refused approval advances nothing"

    # A role string outside the declared seven is not an override either: it is
    # not even an identity.
    undeclared = api_client.approve_settlement_line(
        ctx["ppa_id"],
        ctx["line_id"],
        build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    )
    validate_error(undeclared, ApiErrorId.ERR_UNAUTHENTICATED)
    assert undeclared.status_code == 401

    approved = validate_success(
        api_client.approve_settlement_line(ctx["ppa_id"], ctx["line_id"], APPROVER)
    )
    assert approved["status"] == "SETTLEMENT_APPROVED"


def test_the_analyst_that_validated_a_line_cannot_be_the_one_that_approves_it():
    """PRD §2.1: "A `SettlementAnalyst` prepares settlement lines and accruals, issues
    allowances and reconciles the ledger, but cannot approve or apply what it prepared; a
    `SettlementApprover` approves, settles and reverses lines, and cannot create them. No single
    internal role can both prepare and apply a settlement, which is the point of the split."

    Design: Corner/rbac/settlement_analyst_cannot_approve_the_line_it_validated
    """
    ctx = setup_validated_line()
    assert ctx["line"]["status"] == "SETTLEMENT_VALIDATED"

    refused = api_client.approve_settlement_line(ctx["ppa_id"], ctx["line_id"], ANALYST)

    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED)
    assert refused.status_code == 403, (
        f"the maker is not the checker; got {refused.status_code}"
    )
    assert (
        validate_success(
            api_client.get_settlement_line(ctx["ppa_id"], ctx["line_id"], ANALYST)
        )["status"]
        == "SETTLEMENT_VALIDATED"
    ), "the line the analyst prepared stays where the analyst left it"
    assert (
        validate_success(
            api_client.get_allowance(ctx["ppa_id"], ctx["allowance"]["id"], ANALYST)
        )["lifecycle_state"]
        == "ALLOWANCE_ISSUED"
    ), "a refused approval consumes no allowance"

    approved = validate_success(
        api_client.approve_settlement_line(ctx["ppa_id"], ctx["line_id"], APPROVER)
    )
    assert approved["status"] == "SETTLEMENT_APPROVED", (
        "the same call from the checker's role moves the line forward"
    )
