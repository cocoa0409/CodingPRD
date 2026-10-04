"""Corner-queue tests: endpoint behaviors (pagination defaults, retrieval, clock)."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    create_care_program_payload,
    create_program,
    get_success_data,
    validate_paginated,
    validate_success,
)


class TestPaginationAndRetrieval:
    def test_list_care_programs_pagination_defaults(self, api):
        """PRD section 2.3: "List endpoints accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10, accepts a minimum of 1, and caps at a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. Both are optional."
        PRD section 2.3: "Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. The `meta` object of a list response always carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, regardless of whether the underlying result set spans one page or many."

        Design: Corner/endpoints/list_care_programs_pagination_defaults
        """
        for code in ("CP-1", "CP-2", "CP-3"):
            api.create_care_program(
                create_care_program_payload(
                    program_code=code, display_name=f"Program {code}",
                    service_geography_zips=["75201"],
                ),
                ADMIN,
            )
        resp = api.list_care_programs(ADMIN)
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(data) == 3

    def test_get_care_program_by_id_returns_correct_resource(self, api):
        """PRD section 4: "New resources are returned with HTTP 201; all other successful operations, including state transitions, return HTTP 200. List endpoints paginate per §2.3 and sort by `created_at` ascending."

        Design: Corner/endpoints/get_care_program_by_id_returns_correct_resource
        """
        cp1 = get_success_data(api.create_care_program(
            create_care_program_payload(program_code="CP-1", display_name="Program 1"),
            ADMIN,
        ))
        cp2 = get_success_data(api.create_care_program(
            create_care_program_payload(program_code="CP-2", display_name="Program 2"),
            ADMIN,
        ))
        fetched = validate_success(api.get_care_program(cp2["id"], ADMIN))
        assert fetched["program_code"] == "CP-2"
        assert fetched["program_code"] != cp1["program_code"]


class TestClockAdvance:
    def test_clock_advance_updates_period_index(self, api):
        """PRD section 2.4: "Time in this system is logical, not wall-clock. Each `CareProgram` carries a `current_period_index` integer that begins at 0 when the program is created and advances only via the operator-driven period-advance capability, which moves the index forward by a caller-supplied `by_days` number of days."

        Design: Corner/endpoints/clock_advance_updates_period_index
        """
        program = create_program()
        resp = api.advance_program_clock(program["id"], {"by_days": 5}, ADMIN)
        data = validate_success(resp)
        assert data["current_period_index"] == 5
