"""Corner queue — entities (project/voucher/clearance shapes): required
fields, enum ranges, list filtering with pagination, the clearance
conditional-field rule, non-empty voucher lines, and server-minted system
fields (PRD §2.7, §2.3, §3.3, §3.4, §3.7, §2.5)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    assert_project,
    create_funding_program,
    create_project,
    create_stip,
    determine_project_eligible,
    set_clock,
    setup_project_under_construction,
    setup_stip_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestProjectEntityRules:
    def test_project_create_missing_required_activity_code_returns_400(self, api):
        """PRD §2.7: "4. Body well-formedness: required fields present, enums
        in range, amounts positive where required, voucher `line_items`
        non-empty, `period_end_date` strictly after `period_start_date`, and
        the clearance conditional-field rule — any violation yields
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.3: "A `StateDOTPlanner` nominates a Project into a STIP with a
        payload carrying the `stip_id` and `funding_program_id` it belongs
        under, a `route_name`, a `description`, the `activity_code` (one of the
        six activity codes of §3.1), an `is_interstate_system` flag, the
        `dbe_goal_pct` contract goal as a fraction from 0 to 1 inclusive, and
        the `total_estimated_cost_cents`, which must be strictly greater than
        zero."

        Design: Corner/entities/project_create_missing_required_activity_code_returns_400
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        payload = {
            "stip_id": stip["id"],
            "funding_program_id": program["id"],
            "route_name": "AZ-51",
            "description": "No activity",
            "is_interstate_system": False,
            "dbe_goal_pct": 0.10,
            "total_estimated_cost_cents": 1_000,
        }
        resp = api.create_project(payload, H["state_dot_planner"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        projects, meta = validate_paginated(
            api.list_projects(H["fhwa_reviewer"], params={"stip_id": stip["id"]})
        )
        assert projects == [] and meta["total_count"] == 0, (
            "a rejected create must persist nothing"
        )

    def test_project_create_invalid_enum_activity_code_rejected(self, api):
        """PRD §2.7: "4. Body well-formedness: required fields present, enums
        in range, amounts positive where required, voucher `line_items`
        non-empty, `period_end_date` strictly after `period_start_date`, and
        the clearance conditional-field rule — any violation yields
        `ERR_INVALID_REQUEST` (400)."
        PRD §3.1: "Every entry in `eligible_activity_codes` must be one of the
        six recognized activity codes — `ROAD_RESURFACING`,
        `BRIDGE_REPLACEMENT`, `SIGNAGE_LIGHTING`, `GUARDRAIL_INSTALL`,
        `PEDESTRIAN_CROSSING`, or `TRANSIT_EXPANSION`".

        `SKYSCRAPER` is a well-formed string outside the six recognized codes.

        Design: Corner/entities/project_create_invalid_enum_activity_code_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        payload = {
            "stip_id": stip["id"],
            "funding_program_id": program["id"],
            "route_name": "AZ-51",
            "description": "Bad activity",
            "activity_code": "SKYSCRAPER",
            "is_interstate_system": False,
            "dbe_goal_pct": 0.10,
            "total_estimated_cost_cents": 1_000,
        }
        resp = api.create_project(payload, H["state_dot_planner"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_projects_list_filters_by_stip_and_status_with_pagination(self, api):
        """PRD §3.3: "The projects listing accepts optional `stip_id`,
        `funding_program_id`, and `status` filters."
        PRD §2.3: "Every list response is sorted by `created_at` in ascending
        order, and the `meta` object of a list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Three NOMINATED projects under one STIP: limit=2 pages 2 + 1 rows
        against total_count 3; the status filter matches all three for
        NOMINATED and none for ELIGIBLE.

        Design: Corner/entities/projects_list_filters_by_stip_and_status_with_pagination
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        for i, cost in enumerate((1_000, 2_000, 3_000), start=1):
            create_project(
                stip["id"], program["id"], route_name=f"R{i}",
                description=f"P{i}", total_estimated_cost_cents=cost,
            )

        page1, meta1 = validate_paginated(
            api.list_projects(
                H["fhwa_reviewer"],
                params={"stip_id": stip["id"], "limit": 2, "offset": 0},
            )
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2 and meta1["offset"] == 0

        page2, meta2 = validate_paginated(
            api.list_projects(
                H["fhwa_reviewer"],
                params={"stip_id": stip["id"], "limit": 2, "offset": 2},
            )
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        nominated, meta_nom = validate_paginated(
            api.list_projects(
                H["fhwa_reviewer"],
                params={"stip_id": stip["id"], "status": "NOMINATED"},
            )
        )
        assert len(nominated) == 3 and meta_nom["total_count"] == 3

        eligible, meta_eli = validate_paginated(
            api.list_projects(
                H["fhwa_reviewer"],
                params={"stip_id": stip["id"], "status": "ELIGIBLE"},
            )
        )
        assert eligible == [] and meta_eli["total_count"] == 0

    def test_clearance_create_row_kind_with_nepa_class_rejected(self, api):
        """PRD §3.4: "The conditional-field rule is strict: `nepa_class` is
        required when `kind` is `ENVIRONMENTAL` and must be null when `kind` is
        `RIGHT_OF_WAY`; either violation is a body-shape failure rejected with
        `ERR_INVALID_REQUEST`."

        Both directions fail as 400s and persist nothing.

        Design: Corner/entities/clearance_create_row_kind_with_nepa_class_rejected
        """
        pipeline = setup_stip_pipeline(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            state_code="AZ",
            project_specs=[{"total_estimated_cost_cents": 1_000}],
        )
        project = pipeline["projects"][0]
        determine_project_eligible(project["id"])

        row_with_nepa = api.create_clearance(
            {"project_id": project["id"], "kind": "RIGHT_OF_WAY", "nepa_class": "CE"},
            H["state_dot_engineer"],
        )
        validate_error(row_with_nepa, ApiErrorId.ERR_INVALID_REQUEST)

        env_without_nepa = api.create_clearance(
            {"project_id": project["id"], "kind": "ENVIRONMENTAL"},
            H["state_dot_engineer"],
        )
        validate_error(env_without_nepa, ApiErrorId.ERR_INVALID_REQUEST)

        clearances, meta = validate_paginated(
            api.list_project_clearances(project["id"], H["fhwa_reviewer"])
        )
        assert clearances == [] and meta["total_count"] == 0

    def test_voucher_create_with_empty_line_items_rejected(self, api):
        """PRD §3.7: "`line_items` must be a non-empty array whose entries each
        carry a `description` and an `eligible_amount_cents` strictly greater
        than zero."
        PRD §2.7: "4. Body well-formedness: required fields present, enums in
        range, amounts positive where required, voucher `line_items` non-empty,
        `period_end_date` strictly after `period_start_date`, and the clearance
        conditional-field rule — any violation yields `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/entities/voucher_create_with_empty_line_items_rejected
        """
        ctx = setup_project_under_construction(
            project_cost_cents=100_000,
            apportioned_cents=1_000_000,
            initial_obligated_cents=80_000,
            agreement_number="FA-VE",
        )
        resp = api.create_voucher(
            {
                "authorization_id": ctx["authorization"]["id"],
                "period_start_date": "2027-01-01T00:00:00Z",
                "period_end_date": "2027-02-01T00:00:00Z",
                "line_items": [],
                "documentation_complete": True,
                "is_final": False,
            },
            H["state_dot_engineer"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

        vouchers, meta = validate_paginated(
            api.list_authorization_vouchers(
                ctx["authorization"]["id"], H["fhwa_reviewer"]
            )
        )
        assert vouchers == [] and meta["total_count"] == 0

    def test_project_create_client_id_input_ignored(self, api):
        """PRD §2.5: "The `id` is a server-minted UUID with no type prefix;
        clients never supply it."
        PRD §2.4: "The system never consults wall-clock time."
        PRD §2.4: "System-managed bookkeeping timestamps — `created_at`,
        `updated_at`, and the envelope's `api_request_timestamp` — always
        render as ISO 8601 UTC with exactly three fractional digits, for
        example `2026-09-01T00:00:00.000Z`."

        A client-supplied id and created_at are ignored: the server mints its
        own id and stamps created_at from the logical clock.

        Design: Corner/entities/project_create_client_id_input_ignored
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        client_id = "99999999-9999-4999-8999-999999999999"
        resp = api.create_project(
            {
                "id": client_id,
                "created_at": "1999-01-01T00:00:00Z",
                "stip_id": stip["id"],
                "funding_program_id": program["id"],
                "route_name": "R1",
                "description": "P1",
                "activity_code": "ROAD_RESURFACING",
                "is_interstate_system": False,
                "dbe_goal_pct": 0.10,
                "total_estimated_cost_cents": 1_000,
            },
            H["state_dot_planner"],
        )
        project = validate_success(resp, expected_status=201)
        assert_project(project)
        assert project["id"] != client_id, (
            "the server must mint its own id, not echo the client-supplied one"
        )
        assert project["created_at"] == "2026-09-01T00:00:00.000Z", (
            "created_at is stamped from the logical clock in the bookkeeping "
            f"rendering, got {project['created_at']}"
        )
