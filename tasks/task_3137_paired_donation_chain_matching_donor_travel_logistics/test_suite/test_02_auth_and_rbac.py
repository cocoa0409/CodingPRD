"""Authentication, authorization, and error-envelope tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_center,
    create_center_payload,
    create_donor,
    create_donor_payload,
    get_success_data,
    make_center_coordinator_headers,
    reset_clock,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["registry_admin_headers"]
OPERATOR = TEST_USERS["match_operator_headers"]
LOGISTICS = TEST_USERS["logistics_headers"]


class TestAuthentication:
    def test_unauthenticated_request_missing_role_header(self, api):
        """PRD §2.1: "If `X-User-Role` is missing or not one of the recognized
        values, the server rejects the request with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/validations/unauthenticated_request_missing_role_header
        """
        reset_clock()
        center = create_center()
        resp = api.get_center(center["id"], headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestAuthorization:
    def test_unauthorized_role_for_center_create(self, api):
        """PRD §4: "POST | `/nkr/centers` | Create a TransplantCenter |
        RegistryAdmin".
        PRD §2.1: "If the role is recognized but is not authorized for the
        endpoint per the access rules below, the server rejects with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/validations/unauthorized_role_for_center_create
        """
        reset_clock()
        center = create_center()
        resp = api.create_center(
            create_center_payload(), make_center_coordinator_headers(center["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_match_operator_cannot_register_donor(self, api):
        """PRD §4: "POST | `/nkr/donors` | Register a Donor | CenterCoordinator".
        PRD §2.1: "If the role is recognized but is not authorized for the
        endpoint per the access rules below, the server rejects with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/match_operator_cannot_register_donor
        """
        reset_clock()
        center = create_center()
        resp = api.create_donor(create_donor_payload(center["id"]), OPERATOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_center_coordinator_cannot_run_chain(self, api):
        """PRD §4: "POST | `/nkr/chain-runs` | Create a ChainRun |
        MatchOperator".
        PRD §2.1: "If the role is recognized but is not authorized for the
        endpoint per the access rules below, the server rejects with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/center_coordinator_cannot_run_chain
        """
        reset_clock()
        center = create_center()
        resp = api.create_chain_run(
            {"run_label": "test"}, make_center_coordinator_headers(center["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_logistics_cannot_run_chain(self, api):
        """PRD §4: "POST | `/nkr/chain-runs` | Create a ChainRun |
        MatchOperator".
        PRD §2.1: "If the role is recognized but is not authorized for the
        endpoint per the access rules below, the server rejects with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/logistics_cannot_run_chain
        """
        reset_clock()
        resp = api.create_chain_run({"run_label": "test"}, LOGISTICS)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_registry_admin_cannot_complete_nephrectomy(self, api):
        """PRD §4: "POST | `/nkr/donors/{donor_id}/complete-nephrectomy` | Mark
        donor nephrectomy done; mints DonorProtectionPolicy | CenterCoordinator".
        PRD §2.1: "If the role is recognized but is not authorized for the
        endpoint per the access rules below, the server rejects with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/registry_admin_cannot_complete_nephrectomy
        """
        reset_clock()
        center = create_center()
        donor = create_donor(center)
        resp = api.complete_nephrectomy(donor["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    def test_center_coordinator_cannot_release_slot(self, api):
        """PRD §4: "POST | `/nkr/slots/{slot_id}/release` | Release a RESERVED
        slot | MatchOperator".
        PRD §2.1: "If the role is recognized but is not authorized for the
        endpoint per the access rules below, the server rejects with
        `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/center_coordinator_cannot_release_slot
        """
        reset_clock()
        center = create_center()
        # No reserved slot exists yet; role authorization precedes existence,
        # so a CenterCoordinator calling release is rejected with
        # ERR_UNAUTHORIZED regardless of the slot id.
        resp = api.release_slot(
            "00000000-0000-0000-0000-000000000000",
            make_center_coordinator_headers(center["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


class TestCenterOwnership:
    def test_center_mismatch_on_nephrectomy(self, api):
        """PRD §2.1: "A mismatch between the acting coordinator's center and the
        center owning the targeted resource is rejected with
        `ERR_CENTER_MISMATCH` (HTTP 403)."
        PRD §3.6: "A `CenterCoordinator` at the donor's `home_center_id` —
        verified by `ERR_CENTER_MISMATCH` — marks the donor's nephrectomy done,
        requiring that `surgery_state` is `SURGERY_SCHEDULED` (otherwise
        `ERR_INVALID_STATE`) and that the donor's `medical_status` is `CLEARED`
        (otherwise `ERR_DONOR_NOT_CLEARED`)."

        Design: Corner/validations/center_mismatch_on_nephrectomy
        """
        reset_clock()
        center_a = create_center()
        center_b = create_center()
        donor = create_donor(center_a)
        resp = api.complete_nephrectomy(
            donor["id"], make_center_coordinator_headers(center_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_CENTER_MISMATCH.value)


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with "`response_type`: "error"" and a data
        object carrying "`error_id`" and "`message`".
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape
        """
        reset_clock()
        center = create_center()
        payload = create_donor_payload(center["id"], abo_type="INVALID_ENUM")
        resp = api.create_donor(payload, make_center_coordinator_headers(center["id"]))
        body = resp.json()
        assert resp.status_code == 400
        assert body.get("response_type") == "error"
        assert isinstance(body["data"].get("error_id"), str)
        assert body["data"]["error_id"] == "ERR_INVALID_REQUEST"
        assert isinstance(body["data"].get("message"), str)
        assert len(body["data"]["message"].strip()) > 0
        meta = body.get("meta", {})
        assert isinstance(meta.get("api_request_id"), str)
        assert isinstance(meta.get("api_request_timestamp"), str)
