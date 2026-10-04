"""Response envelope shape and role/validation precedence (PRD §2.2, §2.6)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_ID,
    SHIPPER_ADA,
    api_client,
    assert_carrier,
    create_carrier_payload,
    create_rate_complaint_payload,
    is_iso8601_timestamp,
    make_shipper_headers,
    register_carrier,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
BOARD = TEST_USERS["board_adjudicator_headers"]


class TestResponseEnvelope:
    def test_error_envelope_shape_on_failure(self):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        resp = api_client.get_carrier(NON_EXISTENT_ID, BOARD)
        validate_error(resp, ApiErrorId.ERR_CARRIER_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
        assert isinstance(body["data"].get("message"), str)
        assert len(body["data"]["message"].strip()) > 0

    def test_success_envelope_on_create(self):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `data` field contains the resource object or an array
        of resource objects. For 2xx responses with no data, it contains an
        empty object. Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."

        Design: Corner/endpoints/success_envelope_on_create
        """
        resp = api_client.create_carrier(create_carrier_payload(), ADMIN)
        carrier = validate_success(resp, 201)
        assert_carrier(carrier)
        body = resp.json()
        assert body["response_type"] == "object"
        assert body["data"]["id"] == carrier["id"]
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


class TestValidationPrecedence:
    def test_role_error_precedes_existence(self):
        """PRD §2.6: "Every request is validated against the following
        seventeen checks in strict priority order. The first check that fails
        determines the response; no later check is evaluated." (role
        authorization, check 2, precedes path existence, check 4).

        Design: Corner/validations/role_error_precedes_existence
        """
        # Shipper is not authorized for the decide endpoint; the unknown path
        # id must not surface a 404 first.
        resp = api_client.decide_rate_complaint(
            NON_EXISTENT_ID, {"outcome": "UPHELD"},
            make_shipper_headers(SHIPPER_ADA))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_shipper_cannot_create_carrier_rejected(self):
        """PRD §2.1: "A caller whose role is syntactically valid but not
        listed among the roles authorized for the invoked endpoint is rejected
        with `ERR_FORBIDDEN_ROLE` (HTTP 403)." PRD §4 lists POST
        /stb/carriers under authorized role PlatformAdmin only.

        Design: Corner/rbac/shipper_cannot_create_carrier_rejected
        """
        resp = api_client.create_carrier(
            create_carrier_payload(
                carrier_code="SHPX", legal_name="Shipper-Run Railroad",
                carrier_class="III", base_route_miles=10),
            make_shipper_headers(SHIPPER_ADA))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
