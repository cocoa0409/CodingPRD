"""Role-based access control (PRD 2.1 and the PRD 4 endpoint table).

Exclusive operations reject every other role with 403
ERR_INSUFFICIENT_PERMISSIONS; the read surface is shared across all roles.
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers.api_errors import ERR_INSUFFICIENT_PERMISSIONS
from test_helpers.assertions import (
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    active_contract,
    add_housing_unit,
    bookable_inventory,
    create_contract,
    hire_employee,
    housing_scenario,
    reset_clock,
    submit_filing,
    vouchers_for_hire,
)
from test_helpers.test_users import (
    ACCOUNTANT,
    FRONT_DESK,
    HR_MANAGER,
    OFFICER,
)


class TestExclusiveFilingAdjudication:
    def test_front_desk_cannot_approve_a_filing(self, client):
        """PRD 4 (endpoint table): `POST /contracts/{id}/rate-filings/{filingId}/approve`
        is authorized for the AgencyRateAnalyst, and "any other role
        attempting the operation receives `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/front_desk_cannot_approve_rate_filing
        """
        scenario = bookable_inventory(client, clock=None)
        contract_id = scenario["contract"]["id"]
        filing = submit_filing(
            client, contract_id,
            scenario["season"]["id"], scenario["room_class"]["id"],
            scenario["study"]["id"],
            submitted_rates=f.band_rates_payload(18000, 22000, 25000),
        )
        from test_helpers.test_users import RATE_ANALYST
        client.start_review_filing(contract_id, filing["id"], headers=RATE_ANALYST)
        response = client.approve_filing(
            contract_id, filing["id"], headers=FRONT_DESK
        )
        validate_error(response, ERR_INSUFFICIENT_PERMISSIONS)
        reread = get_success_data(client.get_filing(
            contract_id, filing["id"], headers=RATE_ANALYST
        ))
        assert reread["status"] == C.FILING_UNDER_REVIEW


class TestPeerRoleIsolation:
    def _hire_with_voucher(self, client):
        scenario = housing_scenario(client, bed_count=4)
        contract_id = scenario["contract"]["id"]
        hire = hire_employee(
            client, contract_id,
            scenario["season"]["id"],
            scenario["lines"][C.LINE_LODGING]["id"],
            scenario["unit"]["id"],
            needs_transport=True, transport_origin="Denver",
        )
        voucher = vouchers_for_hire(client, contract_id, hire["id"])[0]
        return contract_id, voucher

    def test_the_accountant_cannot_create_housing_units(self, client):
        """PRD 4 (endpoint table): `POST /contracts/{id}/housing-units` is
        authorized for the ConcessionerHRManager, and "any other role
        attempting the operation receives `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/accountant_cannot_manage_housing_or_vouchers
        """
        contract_id, _voucher = self._hire_with_voucher(client)
        response = client.create_housing_unit(
            contract_id, f.housing_unit_payload(unit_code="DORM-G2"),
            headers=ACCOUNTANT,
        )
        validate_error(response, ERR_INSUFFICIENT_PERMISSIONS)

    def test_the_accountant_cannot_void_a_voucher(self, client):
        """PRD 4 (endpoint table): `POST /contracts/{id}/transport-vouchers/{voucherId}/void`
        is authorized for the ConcessionerHRManager, and "any other role
        attempting the operation receives `ERR_INSUFFICIENT_PERMISSIONS`."

        Design: Corner/rbac/accountant_cannot_manage_housing_or_vouchers
        """
        contract_id, voucher = self._hire_with_voucher(client)
        response = client.void_voucher(
            contract_id, voucher["id"], headers=ACCOUNTANT
        )
        validate_error(response, ERR_INSUFFICIENT_PERMISSIONS)
        reread = get_success_data(client.get_voucher_flat(
            voucher["id"], headers=HR_MANAGER
        ))
        assert reread["status"] == C.VOUCHER_BOOKED


class TestSharedReadSurface:
    def test_two_unrelated_roles_read_the_same_contract(self, client):
        """PRD 3.10: "Every child resource carries a `contract_id` identifying
        its owning contract ... All roles may read every resource."

        Design: Corner/rbac/shared_get_endpoints_work_for_every_role
        """
        reset_clock(client)
        contract = create_contract(client)
        by_officer = validate_success(client.get_contract(
            contract["id"], headers=OFFICER
        ))
        by_hr = validate_success(client.get_contract(
            contract["id"], headers=HR_MANAGER
        ))
        assert by_officer == by_hr
        assert by_officer["id"] == contract["id"]
