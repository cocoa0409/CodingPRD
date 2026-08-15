"""Listing defaults and filters, soft-delete retrieval, and same-response
consistency."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_bin_range_payload,
    create_program_payload,
    create_program_with_bin_and_publish,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["program_manager_headers"]


class TestPaginationAndFilters:
    def test_pagination_default_limit_offset(self, api):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum
        of 100. `offset` defaults to 0. List responses carry the pagination
        fields `limit`, `offset`, `total_count`, and `has_more` in the `meta`
        object."

        Design: Corner/endpoints/pagination_default_limit_offset
        """
        set_clock("2026-08-01T00:00:00Z")
        for i in range(1, 13):
            get_success_data(
                api.create_program(
                    create_program_payload(program_code=f"P-PG-{i}"), PM,
                ),
            )
        data, meta = validate_paginated(api.list_programs(PM))
        assert meta["total_count"] == 12, (
            f"12 programs created; total_count must be 12, got {meta['total_count']}"
        )
        assert meta["limit"] == 10, f"Default limit is 10; got {meta['limit']}"
        assert meta["offset"] == 0, f"Default offset is 0; got {meta['offset']}"
        assert meta["has_more"] is True, (
            "With 12 rows and a default limit of 10, has_more must be true"
        )
        assert len(data) == 10

    def test_list_programs_filtered_by_posture(self, api):
        """PRD §3.1: "Programs can be listed with filters on `posture`,
        `network`, and `product_class`."

        Design: Corner/endpoints/list_programs_filtered_by_posture
        """
        set_clock("2026-08-01T00:00:00Z")
        get_success_data(
            api.create_program(create_program_payload(program_code="P-F-D"), PM),
        )
        prog_live = get_success_data(
            api.create_program(create_program_payload(program_code="P-F-L"), PM),
        )
        get_success_data(
            api.create_bin_range(prog_live["id"], create_bin_range_payload(), PM),
        )
        get_success_data(api.publish_program(prog_live["id"], PM))
        data, meta = validate_paginated(api.list_programs(PM, params={"posture": "LIVE"}))
        assert meta["total_count"] == 1, (
            f"Exactly one LIVE program exists; got total_count={meta['total_count']}"
        )
        assert all(p["posture"] == "LIVE" for p in data)
        assert data[0]["program_code"] == "P-F-L"


class TestSoftDelete:
    def test_get_terminated_program_still_queryable(self, api):
        """PRD §2.4: "A terminated card program remains fully queryable after
        termination (soft-delete semantics): reads against it and its
        historical sub-resources continue to succeed." and PRD §3.2: "A
        successful termination stamps `terminated_at`."

        Design: Corner/endpoints/get_terminated_program_still_queryable
        """
        set_clock("2026-08-01T00:00:00Z")
        prog, _bin = create_program_with_bin_and_publish("P-TERM")
        get_success_data(api.sunset_program(prog["id"], PM))
        get_success_data(api.terminate_program(prog["id"], "VOLUNTARY", PM))
        resp = api.get_program(prog["id"], PM)
        data = validate_success(resp)
        assert data["posture"] == "TERMINATED"
        assert data.get("terminated_at"), (
            "terminated_at must be stamped on the terminated program"
        )


class TestImmediateConsistency:
    def test_immediate_consistency_after_state_change(self, api):
        """PRD §3.2: "A successful publish flips `posture` to `LIVE` and
        increments the program's `version`." and PRD §2.2: "Unless otherwise
        noted, operations that create or modify a resource will return the
        created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_consistency_after_state_change
        """
        set_clock("2026-08-01T00:00:00Z")
        prog = get_success_data(
            api.create_program(create_program_payload(program_code="P-IC"), PM),
        )
        get_success_data(
            api.create_bin_range(prog["id"], create_bin_range_payload(), PM),
        )
        resp = api.publish_program(prog["id"], PM)
        data = validate_success(resp)
        assert data["posture"] == "LIVE", (
            f"The publish response itself must carry posture=LIVE; got "
            f"{data['posture']}"
        )
