"""Role corners: exclusive operations refuse callers from the wrong role."""

from test_helpers import (
    account_with_contract,
    create_grant,
    get_success_data,
    read_contract,
    validate_error,
)
from test_helpers import ApiErrorId, factories
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["retailer_admin_headers"]
MANAGER = TEST_USERS["category_manager_headers"]
SCIENTIST = TEST_USERS["insights_scientist_headers"]
STEWARD = TEST_USERS["data_steward_headers"]


def test_steward_cannot_ingest_panel(api):
    """Bulk panel ingest is the platform operator's alone; the steward is refused.

    PRD: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Design: Corner/rbac/steward_cannot_ingest_panel
    """
    resp = api.ingest_households(
        [factories.household_payload("z1")], STEWARD
    )
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value, 403)


def test_scientist_cannot_approve_grant(api):
    """Grant approval is stewardship's alone; the scientist is refused.

    PRD: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Design: Corner/rbac/scientist_cannot_approve_grant
    """
    world = account_with_contract(api, name="RBAC Co")
    grant = create_grant(api, world["account"]["id"])
    resp = api.approve_grant(grant["id"], SCIENTIST)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value, 403)


def test_category_manager_cannot_suspend_contract(api):
    """Suspension is the platform operator's alone; the category manager is refused and the contract stays ACTIVE.

    PRD: "A request whose role is not permitted for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    Design: Corner/rbac/category_manager_cannot_suspend_contract
    """
    world = account_with_contract(api, name="RBAC2 Co")
    resp = api.suspend_contract(world["contract"]["id"], MANAGER)
    validate_error(resp, ApiErrorId.FORBIDDEN_ROLE.value, 403)
    contract = read_contract(api, world["contract"]["id"])
    assert contract["status"] == "ACTIVE"
