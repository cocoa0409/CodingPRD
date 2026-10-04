"""Request-pipeline validation: auth presence, shape, existence, ordering."""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    NON_EXISTENT_UUID, create_supplier, create_line, get_line_version,
    supplier_payload, lot_payload, production_run_payload,
    make_quality_analyst_headers,
)


class TestRequestPipelineValidation:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request to the API must carry two headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming
        the role under which that user acts. If either header is missing, or
        if `X-User-Role` is not one of the declared role names, the request is
        rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api_client.create_supplier(
            supplier_payload(name="No Auth Co", origin_country="US"),
            headers=None)
        err = validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401
        body = resp.json()
        assert "meta" in body and "api_request_id" in body["meta"]
        assert err["message"]

    def test_lot_missing_required_spice_code_rejected(self, api):
        """PRD §2.8: "Request shape: required fields are present, types are
        valid, enum values fall within their declared sets, and unknown fields
        are rejected, else `ERR_INVALID_REQUEST` (HTTP 400)."

        Omitting the required `spice_code` yields the 400 shape error.

        Design: Corner/validations/lot_missing_required_spice_code_rejected
        """
        supplier = create_supplier()
        payload = lot_payload(supplier["id"])
        del payload["spice_code"]
        resp = api_client.create_lot(
            payload, TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_unknown_references_return_not_found(self, api):
        """PRD §2.8: "Existence: path ids and body foreign-key references ...
        must resolve to existing entities, else `ERR_NOT_FOUND` (HTTP 404)."

        An unknown path id and unknown body foreign keys on run create both
        produce 404.

        Design: Corner/validations/unknown_references_return_not_found
        """
        line = create_line(name="Line-NF")
        resp = api_client.get_lot(NON_EXISTENT_UUID,
                                  TEST_USERS["supply_planner_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        payload = production_run_payload(
            line["id"], NON_EXISTENT_UUID, NON_EXISTENT_UUID, 10,
            "2026-09-07T08:00:00Z", "2026-09-07T10:00:00Z",
            get_line_version(line["id"]))
        resp = api_client.create_production_run(
            payload, TEST_USERS["production_scheduler_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_unauthorized_role_beats_not_found(self, api):
        """PRD §2.8: "Every request is evaluated against the following checks
        in the stated order, and the first check that fails determines the
        response — later checks are not consulted." PRD §2.1: "If the role is
        valid but is not listed among the roles authorized for the target
        endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        QualityAnalyst is not authorized for disposition, so a nonexistent lot
        id still yields 403 — authorization never leaks existence.

        Design: Corner/validations/unauthorized_role_beats_not_found
        """
        resp = api_client.disposition_lot(
            NON_EXISTENT_UUID, {"action": "ACCEPT"},
            make_quality_analyst_headers("qa-1"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
