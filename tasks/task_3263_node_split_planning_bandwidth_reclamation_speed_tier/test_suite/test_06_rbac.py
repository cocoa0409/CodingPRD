"""RBAC tests (Corner/rbac instances)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_block,
    create_franchise_area,
    create_node,
    create_service_group,
    get_success_data,
    setup_proposed_action,
    setup_project_in_permit_review,
    validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["network_planner_headers"]
ENGINEER = TEST_USERS["capacity_engineer_headers"]
PROVISIONING = TEST_USERS["provisioning_agent_headers"]
CARE = TEST_USERS["customer_care_headers"]


def test_customer_care_cannot_approve_capacity_action_forbidden():
    """PRD §2.1: "When a request's role is not among the endpoint's declared
    roles, the server rejects it with `ERR_FORBIDDEN_ROLE` (HTTP 403)." — the
    approve endpoint's declared role is `CapacityEngineer` only (PRD §4).

    Design: Corner/rbac/customer_care_cannot_approve_capacity_action_forbidden
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-RB", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-RB", homes_passed=100)
    action = setup_proposed_action(sg, action_type="NODE_SPLIT")

    resp = api_client.approve_capacity_action(action["id"], CARE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    current = get_success_data(api_client.get_capacity_action(action["id"], ADMIN))
    assert current["status"] == "PROPOSED"


def test_provisioning_agent_cannot_adjudicate_permit_forbidden():
    """PRD §3.4: "Permitting belongs to the `FranchiseAdmin`." and §2.1: "When
    a request's role is not among the endpoint's declared roles, the server
    rejects it with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/provisioning_agent_cannot_adjudicate_permit_forbidden
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-RB2", homes_passed=600, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-RB2", homes_passed=600)
    _, project = setup_project_in_permit_review(sg)

    resp = api_client.adjudicate_permit(project["id"], {"decision": "GRANTED"}, PROVISIONING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    current = get_success_data(api_client.get_node_split_project(project["id"], ADMIN))
    assert current["status"] == "PERMIT_REVIEW"


def test_network_planner_cannot_install_equipment_forbidden():
    """PRD §2.1: "`ProvisioningAgent` (owns customer premises, customer premises
    equipment, provisioning requests, and refresh campaigns)" and "When a
    request's role is not among the endpoint's declared roles, the server
    rejects it with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/network_planner_cannot_install_equipment_forbidden
    """
    fa = create_franchise_area()
    node = create_node(fa["id"], node_code="NE-RB3", homes_passed=100, downstream_spectrum_mhz=48)
    create_block(node["id"], block_type="DATA", mhz=48)
    sg = create_service_group(node["id"], sg_code="SG-RB3", homes_passed=100)
    cp = get_success_data(
        api_client.create_customer_premise(sg["id"], {"premise_ref": "P-RB3", "address": "3 Role Rd"}, PROVISIONING)
    )

    resp = api_client.create_equipment(
        cp["id"],
        {"model": "XB8", "docsis_version": "4.0", "capability_class": "D40",
         "max_downstream_mbps": 1000, "video_legacy": False},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_missing_auth_headers_rejected_on_business_endpoint():
    """PRD §2.1: "A request missing either header is rejected with
    `ERR_MISSING_AUTH_CONTEXT` (HTTP 400)."

    Design: Corner/rbac/missing_auth_headers_rejected_on_business_endpoint
    """
    resp = api_client.create_franchise_area(
        {
            "name": "No Auth",
            "region_code": "NA",
            "obligation_homes_required": 1,
            "obligation_deadline": "2027-01-01T00:00:00Z",
        },
        headers={"Content-Type": "application/json"},
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT)
