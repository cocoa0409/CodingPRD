"""Delegated administration: RBAC denial, scope enforcement, self-approval."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    make_account,
    make_account_admin_headers,
    make_delegation,
    make_partner_manager_headers,
    make_partner_org,
    make_pool,
    make_transfer_request,
    make_va,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
LOGISTICS = TEST_USERS["logistics_agent_headers"]


class TestRoleDenial:
    def test_logistics_agent_cannot_create_pool(self, api):
        """PRD §2.1: "the logistics agent performs the physical RMA
        transitions (ship, deliver, receive, close) and reads devices,
        contracts, coverages, and RMA cases, but cannot create or mutate
        licensing resources. Any role attempting an endpoint outside its
        permission set is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/logistics_agent_cannot_create_pool
        """
        account = make_account()
        va = make_va(account["id"])

        resp = api.create_license_pool({
            "virtual_account_id": va["id"],
            "sku": "X",
            "license_model": "PERPETUAL",
            "purchased_quantity": 5,
        }, LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_account_admin_cannot_execute_transfer(self, api):
        """PRD §3.8: "Execution is the platform admin's exclusive act and
        applies only to an `APPROVED` request whose target virtual account and
        target smart account are both `ACTIVE`".

        Design: Corner/rbac/account_admin_cannot_execute_transfer
        """
        account = make_account()
        va1 = make_va(account["id"])
        va2 = make_va(account["id"])
        pool = make_pool(va1["id"], purchased_quantity=10)
        transfer = make_transfer_request(pool["id"], va2["id"], quantity=3)
        account_admin = make_account_admin_headers(account["id"])
        approved = validate_success(api.approve_license_transfer_request(
            transfer["id"], {"expected_transfer_version": transfer["version"]}, account_admin))
        assert approved["status"] == "APPROVED"

        resp = api.execute_license_transfer_request(transfer["id"], account_admin)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestPartnerDelegation:
    def test_partner_without_delegation_forbidden(self, api):
        """PRD §2.1: "A revoked or missing delegation, or an operation outside
        the granted scope, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/partner_without_delegation_forbidden
        """
        partner = make_partner_org()
        account = make_account()
        va = make_va(account["id"])

        resp = api.create_license_pool({
            "virtual_account_id": va["id"],
            "sku": "X",
            "license_model": "PERPETUAL",
            "purchased_quantity": 5,
        }, make_partner_manager_headers(partner["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_licensing_scope_allows_pool_forbids_contract(self, api):
        """PRD §2.1: "`LICENSING` scope covers license, pool, device, and
        assignment operations; `SERVICE_CONTRACTS` scope covers contract,
        coverage, and RMA operations; `FULL` scope covers both. A revoked or
        missing delegation, or an operation outside the granted scope, is
        rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/cross_cutting_layers/delegated_scope_enforcement_licensing_vs_contracts
        """
        partner = make_partner_org()
        account = make_account(managing_partner_id=partner["id"])
        make_delegation(partner["id"], account["id"], scope="LICENSING")
        va = make_va(account["id"])
        partner_headers = make_partner_manager_headers(partner["id"])

        pool = validate_success(api.create_license_pool({
            "virtual_account_id": va["id"],
            "sku": "LIC-SCOPED",
            "license_model": "PERPETUAL",
            "purchased_quantity": 5,
        }, partner_headers), expected_status=201)
        assert pool["sku"] == "LIC-SCOPED", "LICENSING scope must allow pool creation"

        resp = api.create_service_contract({
            "smart_account_id": account["id"],
            "contract_number": "C-SCOPED",
            "service_level": "ADVANCE_NBD",
            "support_tier": "FULL",
            "start_date": "2026-09-01T00:00:00Z",
            "end_date": "2027-09-01T00:00:00Z",
        }, partner_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_partner_self_approval_forbidden(self, api):
        """PRD §3.8: "Approval and rejection belong to the customer's
        `AccountAdmin` or the `PlatformAdmin`, never to the partner side: when
        `requested_by_partner_org_id` is set, the approver must be the
        `AccountAdmin` of the source pool's smart account (or the
        `PlatformAdmin`); an attempt by the partner side to approve its own
        request is rejected with `ERR_SELF_APPROVAL_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/partner_self_approval_blocked
        """
        partner = make_partner_org()
        account = make_account(managing_partner_id=partner["id"])
        make_delegation(partner["id"], account["id"], scope="FULL")
        va1 = make_va(account["id"])
        va2 = make_va(account["id"])
        pool = make_pool(va1["id"], purchased_quantity=10)
        partner_headers = make_partner_manager_headers(partner["id"])

        transfer = make_transfer_request(
            pool["id"], va2["id"], quantity=3, reason="PARTNER_EXIT", headers=partner_headers)
        assert transfer["requested_by_partner_org_id"] == partner["id"]

        resp = api.approve_license_transfer_request(
            transfer["id"], {"expected_transfer_version": transfer["version"]}, partner_headers)
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)

    def test_account_admin_approves_partner_request(self, api):
        """PRD §3.8: "when `requested_by_partner_org_id` is set, the approver
        must be the `AccountAdmin` of the source pool's smart account (or the
        `PlatformAdmin`)". PRD §3.8: "Approval moves the request from
        `PENDING_APPROVAL` to `APPROVED` and records the approver in
        `decided_by`".

        Design: Corner/rbac/partner_self_approval_blocked
        """
        partner = make_partner_org()
        account = make_account(managing_partner_id=partner["id"])
        make_delegation(partner["id"], account["id"], scope="FULL")
        va1 = make_va(account["id"])
        va2 = make_va(account["id"])
        pool = make_pool(va1["id"], purchased_quantity=10)
        partner_headers = make_partner_manager_headers(partner["id"])

        transfer = make_transfer_request(
            pool["id"], va2["id"], quantity=3, reason="PARTNER_EXIT", headers=partner_headers)

        approved = validate_success(api.approve_license_transfer_request(
            transfer["id"], {"expected_transfer_version": transfer["version"]},
            make_account_admin_headers(account["id"])))
        assert approved["status"] == "APPROVED"
