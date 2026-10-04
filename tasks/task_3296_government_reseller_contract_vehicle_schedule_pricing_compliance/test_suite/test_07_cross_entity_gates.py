"""Cross-entity gates: posture gates order submit; manufacturer status gates authorize."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_agreement,
    create_manufacturer,
    create_order,
    create_vehicle_payload,
    drive_agreement_on_hold,
    setup_active_chain,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestOrderSubmitGatedByPosture:
    def test_submit_rejected_when_agreement_on_hold(self, api):
        """PRD §3.6: "Submission requires the vehicle to be AUTHORIZED, the
        price list to be ACTIVE, and the agreement's posture to be
        GOOD_STANDING (otherwise ERR_AGREEMENT_NOT_GOOD_STANDING)."

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_agreement_posture
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        drive_agreement_on_hold(agreement["id"], vehicle["id"], price_list["id"])
        target = create_order(vehicle["id"], price_list["id"])
        resp = api.submit_order(target["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_GOOD_STANDING)

    def test_rejected_submit_leaves_order_draft(self, api):
        """PRD §3.9: "An ON_HOLD agreement blocks vehicle authorization,
        teaming approval, and order submission."
        PRD §2.6: "otherwise, if dispute_credit_cents is strictly less than
        -100000 (that is, net debt has crossed $1,000.00), posture is ON_HOLD;
        otherwise posture is GOOD_STANDING."

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_agreement_posture
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        drive_agreement_on_hold(agreement["id"], vehicle["id"], price_list["id"])
        target = create_order(vehicle["id"], price_list["id"])
        validate_error(
            api.submit_order(target["id"], OPS),
            ApiErrorId.ERR_AGREEMENT_NOT_GOOD_STANDING,
        )
        target = validate_success(api.get_order(target["id"], OPS))
        assert target["compliance_status"] == "DRAFT"
        assert target["billing_status"] == "UNBILLED"

    def test_submit_accepted_while_good_standing(self, api):
        """PRD §3.6: "Submission requires the vehicle to be AUTHORIZED, the
        price list to be ACTIVE, and the agreement's posture to be
        GOOD_STANDING (otherwise ERR_AGREEMENT_NOT_GOOD_STANDING)."
        PRD §2.6: "a dispute_credit_cents value exactly equal to -100000
        yields ON_HOLD, while -99999 yields GOOD_STANDING."

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_agreement_posture
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        # -99999 stays GOOD_STANDING (boundary, inclusive on the debt side at -100000).
        drive_agreement_on_hold(
            agreement["id"], vehicle["id"], price_list["id"], debt_cents=-99999,
        )
        target = create_order(vehicle["id"], price_list["id"])
        resp = api.submit_order(target["id"], OPS)
        order = validate_success(resp)
        assert order["compliance_status"] == "CLEARED"


class TestVehicleAuthorizeGatedByManufacturer:
    def _pending_vehicle_on_suspended_manufacturer(self, api):
        from test_helpers import set_clock
        set_clock("2026-10-01T00:00:00Z")
        manufacturer = create_manufacturer(legal_name="M Corp")
        _, agreement = create_active_agreement(manufacturer_id=manufacturer["id"])
        resp = api.create_vehicle(create_vehicle_payload(agreement["id"]), CM)
        vehicle = validate_success(resp, expected_status=201)
        api.suspend_manufacturer(manufacturer["id"], ADMIN)
        return manufacturer, agreement, vehicle

    def test_authorize_rejected_when_manufacturer_suspended(self, api):
        """PRD §2.10: "Manufacturer liveness — the manufacturer must be
        ACTIVE for a new agreement activation or a vehicle authorization;
        failure yields ERR_MANUFACTURER_INACTIVE (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/vehicle_authorize_gated_by_manufacturer_status
        """
        _, _, vehicle = self._pending_vehicle_on_suspended_manufacturer(api)
        resp = api.authorize_vehicle(vehicle["id"], CM)
        validate_error(resp, ApiErrorId.ERR_MANUFACTURER_INACTIVE)

    def test_rejected_authorize_leaves_vehicle_pending(self, api):
        """PRD §3.1: "the administrator may later suspend it (transition to
        SUSPENDED), which blocks any new agreement activation or vehicle
        authorization referencing it without altering the posture of any
        existing agreement."

        Design: Difficulty/cross_entity_state_dependency/vehicle_authorize_gated_by_manufacturer_status
        """
        _, _, vehicle = self._pending_vehicle_on_suspended_manufacturer(api)
        validate_error(
            api.authorize_vehicle(vehicle["id"], CM),
            ApiErrorId.ERR_MANUFACTURER_INACTIVE,
        )
        vehicle = validate_success(api.get_vehicle(vehicle["id"], CM))
        assert vehicle["status"] == "PENDING"
