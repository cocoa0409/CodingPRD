"""RBAC corner tests: exclusive operations do not bleed across peer roles."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_all_permits,
    create_bid_session,
    create_esa,
    create_project,
    create_warranty_claim_payload,
    get_success_data,
    setup_executed_project,
    validate_error,
)

DEV = TEST_USERS["project_developer_headers"]
SAFETY = TEST_USERS["safety_authority_headers"]
MARKET = TEST_USERS["market_operator_headers"]


def test_market_operator_cannot_execute_esa(api):
    """PRD §2.1: "If the role is valid but not permitted for the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §2.1: "`ProjectDeveloper` scopes projects, creates and executes
    equipment supply agreements, schedules milestones and permits, records
    milestone outcomes and waives liquidated damages"

    Design: Corner/roles/market_operator_cannot_execute_esa_and_developer_cannot_settle
    """
    project = create_project(api=api)
    approve_all_permits(project["id"], api=api)
    esa = create_esa(project["id"], api=api)
    version = get_success_data(api.get_project(project["id"], DEV))["version"]

    resp = api.execute_esa(esa["id"], {"expected_project_version": version}, MARKET)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    after = get_success_data(api.get_esa(esa["id"], DEV))
    assert after["status"] == "DRAFT"


def test_project_developer_cannot_settle_bid_session(api):
    """PRD §2.1: "If the role is valid but not permitted for the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §2.1: "`MarketOperator` opens, clears, settles and cancels bid
    sessions."

    Design: Corner/roles/market_operator_cannot_execute_esa_and_developer_cannot_settle
    """
    project, _ = setup_executed_project(api=api)
    session = create_bid_session(project["id"], api=api)
    resp = api.settle_bid_session(session["id"], DEV)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


def test_safety_authority_cannot_file_warranty_claim(api):
    """PRD §2.1: "If the role is valid but not permitted for the target
    endpoint, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."
    PRD §2.1: "`WarrantyAdmin` files, reviews and decides warranty claims;
    `SafetyAuthority` decides safety permits"

    Design: Corner/roles/safety_authority_cannot_decide_warranty_claim
    """
    project = create_project(api=api)
    esa = create_esa(project["id"], api=api)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(esa["id"], claimed_capacity_loss_mwh=1),
        SAFETY,
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
