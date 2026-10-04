"""Error catalogue corners: 404 on nested paths and the error envelope shape."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID, validate_error

from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import ADMIN


class TestNotFoundOnSubresourceList:
    def test_missing_parent_returns_404(self, client):
        """PRD 2.8: "When an endpoint path contains multiple resource
        identifiers, the server validates the identifiers in left-to-right
        order. The request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the
        first path identifier that does not resolve to an existing resource;
        deeper identifiers are not examined once an earlier one fails."

        Design: Corner/errors/corner_not_found_on_subresource_list
        """
        resp = client.list_patient_encounters(NON_EXISTENT_UUID, headers=ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


class TestErrorEnvelopeShape:
    def test_error_envelope_fields(self, client):
        """PRD 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD 2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD 2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/corner_error_envelope_shape
        """
        resp = client.get_physician(NON_EXISTENT_UUID, headers=ADMIN)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        data = body["data"]
        assert data["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
        assert isinstance(data["message"], str) and data["message"].strip()
