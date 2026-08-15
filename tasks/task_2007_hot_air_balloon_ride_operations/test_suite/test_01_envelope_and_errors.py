"""Response envelope shape and top-of-pipeline errors (PRD §2.1, §2.2, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_launch_site,
    create_launch_site_payload,
    set_clock,
    validate_error,
    validate_success,
)


class TestSuccessEnvelope:
    def test_response_envelope_success_shape(self, api, ops_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" — with
        `meta.api_request_id`, `meta.api_request_timestamp`, `response_type`
        ("object" for a single resource) and `data` carrying the resource.

        Design: Corner/endpoints/response_envelope_success_shape
        """
        set_clock()
        resp = api.create_launch_site(create_launch_site_payload(), ops_headers)
        body = resp.json()
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
        assert body["response_type"] == "object", (
            f"single-resource create must have response_type 'object', got "
            f"{body['response_type']!r}"
        )
        assert isinstance(body["meta"]["api_request_id"], str)
        assert isinstance(body["meta"]["api_request_timestamp"], str)
        site = validate_success(resp, expected_status=201)
        assert_launch_site(site)
        assert body["data"]["id"] == site["id"]


class TestErrorEnvelope:
    def test_response_envelope_error_shape(self, api, ops_headers):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        set_clock()
        resp = api.get_balloon(NON_EXISTENT_UUID, ops_headers)
        body = resp.json()
        assert body["response_type"] == "error", (
            f"error responses must have response_type 'error', got {body.get('response_type')!r}"
        )
        error_data = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(error_data["message"], str) and error_data["message"].strip()
        assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
            f"error meta must contain only api_request_id and api_request_timestamp, "
            f"got {sorted(body['meta'].keys())}"
        )


class TestExistenceAndAuthentication:
    def test_entity_not_found_returns_404(self, api, ops_headers):
        """PRD §2.9: "Path existence, validated left to right: for a nested path
        such as a reservation's passenger collection, the parent identifier is
        resolved first and the request is rejected with `ERR_NOT_FOUND`
        (HTTP 404) at the first identifier that does not resolve to an existing
        resource."

        Design: Corner/entities/entity_not_found_returns_404
        """
        set_clock()
        resp = api.get_flight(NON_EXISTENT_UUID, ops_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request that arrives without both headers, or whose role
        value is not one of these declared roles, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_unauthenticated
        """
        resp = api.get_flight(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
