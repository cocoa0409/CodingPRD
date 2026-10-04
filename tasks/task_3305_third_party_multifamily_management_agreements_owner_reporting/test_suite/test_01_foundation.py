"""Owners, properties, envelope shape, pagination, and 404 plumbing (PRD §2, §3.1)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_owner,
    is_iso8601_timestamp,
    make_owner_rep_headers,
    setup_owner,
    setup_property,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestOwnerCreation:
    def test_owner_creation_applies_defaults_and_system_fields(self, api, pm_headers, acct_headers):
        """PRD §3.1: "Each owner carries a `distribution_day_of_month` — the
        contractual target day of each month for owner distributions, defaulting
        to 10 and constrained to the range 1 through 28".
        PRD §3.1: "A `PortfolioManager` creates an owner with a `legal_name`;
        the owner begins with `status` `ACTIVE`".

        Design: Corner/entities/owner_creation_applies_defaults_and_system_fields
        """
        created = validate_success(
            api.create_owner({"legal_name": "Default Owner LP"}, pm_headers),
            expected_status=201,
        )
        assert_owner(created)
        assert created["distribution_day_of_month"] == 10, (
            f"default distribution_day_of_month must be 10, got {created['distribution_day_of_month']}"
        )
        assert created["status"] == "ACTIVE"
        assert created["version"] == 1
        fetched = validate_success(api.get_owner(created["id"], acct_headers))
        assert fetched["distribution_day_of_month"] == 10
        assert fetched["status"] == "ACTIVE"


class TestOwnerRequiredFields:
    def test_owner_creation_rejects_missing_required_legal_name(self, api, pm_headers):
        """PRD §2.1: "An attempt to perform an operation outside the caller's
        role is rejected with `ERR_FORBIDDEN_FOR_ROLE`" — here the call is
        in-role; PRD §3.6: "malformed bodies such as negative amounts on
        charge kinds, missing required fields, or invalid enum values are
        rejected with `ERR_INVALID_REQUEST`".

        Design: Corner/entities/owner_creation_rejects_missing_required_legal_name
        """
        resp = api.create_owner({"distribution_day_of_month": 12}, pm_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestPagination:
    def test_list_endpoints_paginate_with_default_limit_and_total_count(self, api, pm_headers):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; when omitted it defaults to 10, with a minimum of 1 and a
        maximum of 100. The `offset` parameter sets the number of items
        skipped and defaults to 0."

        Design: Corner/entities/list_endpoints_paginate_with_default_limit_and_total_count
        """
        owner = setup_owner(legal_name="Page Owner LP")
        for i in range(12):
            setup_property(owner, name=f"P{i + 1:02d}", unit_count=10)

        page1, meta1 = validate_paginated(
            api.list_properties(pm_headers, params={"owner_id": owner["id"]})
        )
        assert len(page1) == 10, f"default page must hold 10 rows, got {len(page1)}"
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_properties(
                pm_headers, params={"owner_id": owner["id"], "offset": 10}
            )
        )
        assert len(page2) == 2, f"offset=10 must return the remaining 2 rows, got {len(page2)}"
        assert meta2["has_more"] is False
        assert meta2["total_count"] == 12


class TestNotFound:
    def test_get_nonexistent_property_returns_not_found(self, api, pm_headers):
        """PRD §2.6: "The request is rejected immediately with `ERR_NOT_FOUND`
        (HTTP 404) for the first identifier in the path that does not
        correspond to an existing resource, and no later identifier is
        examined."

        Design: Corner/entities/get_nonexistent_property_returns_not_found
        """
        resp = api.get_property(NON_EXISTENT_UUID, pm_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestResponseEnvelope:
    def test_response_envelope_shape_on_success_and_error(self, api, pm_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type` "error" and `data`
        carrying `error_id` and `message`; success bodies carry `meta` with
        `api_request_id` and `api_request_timestamp`, `response_type`
        "object", and the resource in `data`.

        Design: Corner/consistency/response_envelope_shape_on_success_and_error
        """
        owner = setup_owner(legal_name="Env Owner LP")

        ok_resp = api.get_owner(owner["id"], pm_headers)
        ok_data = validate_success(ok_resp)
        body = ok_resp.json()
        assert body["meta"]["api_request_id"], "api_request_id must be present"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert ok_data["id"] == owner["id"]

        err_resp = api.get_owner(NON_EXISTENT_UUID, pm_headers)
        err_body = err_resp.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == ApiErrorId.ERR_NOT_FOUND.value
        assert isinstance(err_body["data"]["message"], str) and err_body["data"]["message"]
        assert err_body["meta"]["api_request_id"]
        assert is_iso8601_timestamp(err_body["meta"]["api_request_timestamp"])
