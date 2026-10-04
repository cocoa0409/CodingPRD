"""Corner queue — endpoints (response envelopes, pagination defaults) and
consistency_model (immediate read-after-create) (PRD §2.2, §2.3, §2.5, §3.2)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    assert_bookkeeping_timestamp,
    assert_state_program,
    create_stip,
    set_clock,
    validate_paginated,
    validate_success,
)

H = TEST_USERS


class TestEnvelopeAndConsistency:
    def test_error_envelope_shape_on_failure(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."
        PRD §2.4: "System-managed bookkeeping timestamps — `created_at`,
        `updated_at`, and the envelope's `api_request_timestamp` — always
        render as ISO 8601 UTC with exactly three fractional digits, for
        example `2026-09-01T00:00:00.000Z`."

        Verified on a 404 for an unallocated STIP id.

        Design: Corner/endpoints/error_envelope_shape_on_failure
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_stip(NON_EXISTENT_UUID, H["state_dot_planner"])
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error", (
            f"error responses carry response_type error, got {body.get('response_type')!r}"
        )
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "error responses carry a human-readable message"
        )
        assert body["meta"]["api_request_id"]
        assert_bookkeeping_timestamp(
            body["meta"]["api_request_timestamp"], "api_request_timestamp"
        )

    def test_success_envelope_carries_meta_and_object_type(self, api):
        """PRD §2.2: "The `response_type` is either \"object\" for a single
        resource or \"array\" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.4: "System-managed bookkeeping timestamps — `created_at`,
        `updated_at`, and the envelope's `api_request_timestamp` — always
        render as ISO 8601 UTC with exactly three fractional digits, for
        example `2026-09-01T00:00:00.000Z`."

        Design: Corner/endpoints/success_envelope_carries_meta_and_object_type
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)

        resp = api.get_stip(stip["id"], H["state_dot_engineer"])
        data = validate_success(resp)
        assert data["id"] == stip["id"]
        assert data["status"] == "PUBLIC_INVOLVEMENT"

        body = resp.json()
        assert body["response_type"] == "object", (
            f"a single-resource GET carries response_type object, got {body.get('response_type')!r}"
        )
        assert body["meta"]["api_request_id"]
        assert_bookkeeping_timestamp(
            body["meta"]["api_request_timestamp"], "api_request_timestamp"
        )

    def test_list_endpoint_defaults_paginate_at_ten(self, api):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items
        returned; it defaults to 10 when omitted, accepts a minimum of 1, and
        is capped at a maximum of 100. The `offset` parameter sets how many
        items to skip and defaults to 0."
        PRD §2.3: "Every list response is sorted by `created_at` in ascending
        order, and the `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Twelve recorded comments paginate 10 + 2 under the defaults.

        Design: Corner/endpoints/list_endpoint_defaults_paginate_at_ten
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        for i in range(1, 13):
            resp = api.create_stip_comment(
                stip["id"],
                {"author_name": f"C{i}", "comment_text": f"Comment {i}."},
                H["state_dot_planner"],
            )
            assert resp.status_code == 201, f"comment {i} setup failed"

        page1, meta1 = validate_paginated(
            api.list_stip_comments(stip["id"], H["fhwa_reviewer"])
        )
        assert len(page1) == 10, (
            f"the default page size is 10, got {len(page1)}"
        )
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_stip_comments(stip["id"], H["fhwa_reviewer"], params={"offset": 10})
        )
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
        assert meta2["offset"] == 10

    def test_read_after_create_reflects_immediately(self, api):
        """PRD §3.2: "A new STIP opens directly in `PUBLIC_INVOLVEMENT`, with
        `comment_period_opened_at` stamped from the logical clock and
        `amendment_count` at 0."
        PRD §3.2: "The STIP spans four federal fiscal years:
        `end_federal_fiscal_year` is computed as the start year plus three."
        PRD §2.5: "The `version` is an integer that starts at 1 on creation and
        increments by exactly 1 on every mutation, again including cascaded
        ones."

        A separate GET issued right after creation returns every stored field
        exactly as created.

        Design: Corner/consistency_model/read_after_create_reflects_immediately
        """
        set_clock("2026-09-01T00:00:00Z")
        created = create_stip(
            state_code="NM", land_pct=0.33, start_ffy=2027, description="NM STIP"
        )

        resp = api.get_stip(created["id"], H["fhwa_reviewer"])
        stip = validate_success(resp)
        assert_state_program(stip)
        assert stip["state_code"] == "NM"
        assert stip["state_federal_land_pct"] == 0.33
        assert stip["start_federal_fiscal_year"] == 2027
        assert stip["end_federal_fiscal_year"] == 2030
        assert stip["status"] == "PUBLIC_INVOLVEMENT"
        assert stip["amendment_count"] == 0
        assert stip["version"] == 1
        assert stip["comment_period_opened_at"] == "2026-09-01T00:00:00Z"
        assert stip["description"] == "NM STIP"
