"""Corner coverage: response envelopes and error-catalog behaviors."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_active_price_list,
    create_delivered_order,
    create_dispute,
    create_manufacturer_payload,
    create_teaming_payload,
    drive_agreement_on_hold,
    setup_active_chain,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestErrorEnvelope:
    def test_error_response_shape(self, api):
        """PRD §2.2: "The meta object for error responses contains only
        api_request_id and api_request_timestamp."
        PRD §2.2: "The error_id is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The message provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_response_envelope_shape
        """
        resp = api.get_manufacturer(NON_EXISTENT_UUID, ADMIN)
        body = resp.json()
        assert resp.status_code == 404
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestSuccessEnvelope:
    def test_success_response_shape(self, api):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."
        PRD §2.2: "The response_type is either "object" for a single resource
        or "array" for a list of resources."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        Design: Corner/endpoints/success_response_envelope_shape
        """
        resp = api.create_manufacturer(
            create_manufacturer_payload(legal_name="E Corp", duns="616161616"), ADMIN,
        )
        body = resp.json()
        assert resp.status_code == 201
        assert "api_request_id" in body["meta"]
        assert body["response_type"] == "object"
        assert "id" in body["data"]


class TestActiveListSupersede:
    def test_second_activation_supersedes_first(self, api):
        """PRD §3.3: "When the activation succeeds while a sibling list on the
        same vehicle is ACTIVE, that sibling is atomically moved to SUPERSEDED
        and the vehicle's PRC accumulator is recomputed against only the newly
        active list."

        Design: Corner/errors/error_uniqueness_active_list_per_vehicle
        """
        _, _, vehicle, price_list = setup_active_chain()
        p2 = create_active_price_list(
            vehicle["id"],
            lines=[{"sku": "SW-1", "basis_price_cents": 20000,
                    "offered_price_cents": 11000, "origin_country": "US"}],
        )
        p2 = validate_success(api.get_price_list(p2["id"], CM))
        assert p2["status"] == "ACTIVE"
        p1 = validate_success(api.get_price_list(price_list["id"], CM))
        assert p1["status"] == "SUPERSEDED"


class TestTeamingApprovePostureGate:
    def test_teaming_approve_blocked_when_on_hold(self, api):
        """PRD §3.5: "Approval requires the agreement to be ACTIVE with
        posture GOOD_STANDING (otherwise ERR_AGREEMENT_NOT_GOOD_STANDING),
        every scope's vehicle to be AUTHORIZED, and every scope's SKU prefixes
        to remain contained in the agreement's product_scope."

        Design: Corner/errors/error_agreement_not_good_standing_on_teaming_approve
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        drive_agreement_on_hold(agreement["id"], vehicle["id"], price_list["id"])
        resp = api.create_teaming(
            create_teaming_payload(
                agreement["id"], vehicle["id"],
                integrator_name="Int X", small_business=True,
            ),
            CM,
        )
        teaming = validate_success(resp, expected_status=201)
        resp = api.approve_teaming(teaming["id"], CO)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_GOOD_STANDING)
