"""Corner queue — entities: creation-time computed fields, uniqueness,
derived STIP window fields, the PublicComment common-fields exception,
provisional estimate computation, and 404 shape (PRD §3.1-§3.3, §2.5, §2.9)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_stip_comment,
    api_client,
    assert_apportionment,
    assert_funding_program,
    assert_project,
    assert_public_comment,
    assert_state_program,
    assert_bookkeeping_timestamp,
    create_apportionment,
    create_funding_program,
    create_project,
    create_stip,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


class TestEntityCreation:
    def test_funding_program_create_computes_base_share_from_code(self, api):
        """PRD §3.1: "The server, not the client, fixes each program's
        statutory base share: `base_federal_share_pct` is computed from the
        program code as 0.80 for `NHPP`, 0.80 for `STBG`, 0.90 for `HSIP`,
        0.80 for `CMAQ`, and 0.80 for `TAP`; any share value the client
        supplies is ignored."
        PRD §2.5: "The `version` is an integer that starts at 1 on creation
        and increments by exactly 1 on every mutation, again including
        cascaded ones."

        Design: Corner/entities/funding_program_create_computes_base_share_from_code
        """
        set_clock("2026-09-01T00:00:00Z")
        hsip_resp = api.create_funding_program(
            {
                "code": "HSIP",
                "name": "Safety",
                "eligible_activity_codes": ["SIGNAGE_LIGHTING"],
            },
            H["platform_admin"],
        )
        hsip = validate_success(hsip_resp, expected_status=201)
        assert_funding_program(hsip)
        assert hsip["base_federal_share_pct"] == 0.90
        assert hsip["version"] == 1

        tap_resp = api.create_funding_program(
            {
                "code": "TAP",
                "name": "Alternatives",
                "eligible_activity_codes": ["PEDESTRIAN_CROSSING"],
            },
            H["platform_admin"],
        )
        tap = validate_success(tap_resp, expected_status=201)
        assert_funding_program(tap)
        assert tap["base_federal_share_pct"] == 0.80
        assert tap["version"] == 1

        body = hsip_resp.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"]
        assert_bookkeeping_timestamp(
            body["meta"]["api_request_timestamp"], "api_request_timestamp"
        )

    def test_apportionment_create_initializes_available_to_apportioned(self, api):
        """PRD §3.1: "On creation `obligated_cents` is 0 and `available_cents`
        equals `apportioned_cents`".
        PRD §2.10: "One invariant holds at all times and is auditable:
        `available_cents` always equals `apportioned_cents` minus
        `obligated_cents`."

        Design: Corner/entities/apportionment_create_initializes_available_to_apportioned
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        resp = api.create_apportionment(
            {
                "funding_program_id": program["id"],
                "state_code": "OR",
                "federal_fiscal_year": 2027,
                "apportioned_cents": 750_000,
            },
            H["fhwa_division_admin"],
        )
        apportionment = validate_success(resp, expected_status=201)
        assert_apportionment(apportionment)
        assert apportionment["obligated_cents"] == 0
        assert apportionment["available_cents"] == 750_000

    def test_duplicate_apportionment_cell_rejected(self, api):
        """PRD §3.1: "A system-enforced `uniqueness` constraint permits at most
        one Apportionment per (program, state, FFY) triple: a second create for
        an existing cell is rejected with `ERR_DUPLICATE_APPORTIONMENT` (409)."

        The same program in a different fiscal year is a different cell and is
        accepted.

        Design: Corner/entities/duplicate_apportionment_cell_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="NHPP", eligible_activity_codes=["ROAD_RESURFACING"]
        )
        create_apportionment(
            program["id"], state_code="OR", federal_fiscal_year=2027,
            apportioned_cents=750_000,
        )

        dup = api.create_apportionment(
            {
                "funding_program_id": program["id"],
                "state_code": "OR",
                "federal_fiscal_year": 2027,
                "apportioned_cents": 100,
            },
            H["fhwa_division_admin"],
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_APPORTIONMENT)

        other_year = api.create_apportionment(
            {
                "funding_program_id": program["id"],
                "state_code": "OR",
                "federal_fiscal_year": 2028,
                "apportioned_cents": 100,
            },
            H["fhwa_division_admin"],
        )
        accepted = validate_success(other_year, expected_status=201)
        assert_apportionment(accepted)
        assert accepted["federal_fiscal_year"] == 2028

    def test_stip_create_derives_window_end_year_and_initial_status(self, api):
        """PRD §3.2: "A new STIP opens directly in `PUBLIC_INVOLVEMENT`, with
        `comment_period_opened_at` stamped from the logical clock and
        `amendment_count` at 0."
        PRD §3.2: "The STIP spans four federal fiscal years:
        `end_federal_fiscal_year` is computed as the start year plus three."
        PRD §2.4: "Domain timestamps whose value is copied from the logical
        clock — `comment_period_opened_at`, `advertised_on_date`,
        `findings_issued_at`, and the `closed_at` fields — render exactly as
        the logical clock reads at the moment they are stamped, for example
        `2026-09-01T00:00:00Z`."

        Design: Corner/entities/stip_create_derives_window_end_year_and_initial_status
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.create_stip(
            {
                "state_code": "AZ",
                "state_federal_land_pct": 0.42,
                "start_federal_fiscal_year": 2028,
                "description": "AZ STIP",
            },
            H["state_dot_planner"],
        )
        stip = validate_success(resp, expected_status=201)
        assert_state_program(stip)
        assert stip["status"] == "PUBLIC_INVOLVEMENT"
        assert stip["comment_period_opened_at"] == "2026-09-01T00:00:00Z", (
            "the comment window opens at the creation clock, got "
            f"{stip['comment_period_opened_at']}"
        )
        assert stip["end_federal_fiscal_year"] == 2031  # 2028 + 4 - 1
        assert stip["amendment_count"] == 0
        assert stip["total_programmed_federal_cents"] == 0

    def test_public_comment_response_has_no_version_field(self, api):
        """PRD §2.5: "The PublicComment resource is the single exception: it
        carries only `id` and `created_at`, and both `updated_at` and `version`
        are absent from it."
        PRD §3.2: "While in this status, any authenticated role may record a
        PublicComment carrying an `author_name` and free-text `comment_text`;
        the comment's `stip_id` comes from the collection it is posted under,
        and its `created_at` is taken from the logical clock."

        Design: Corner/entities/public_comment_response_has_no_version_field
        """
        set_clock("2026-09-01T00:00:00Z")
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        resp = api.create_stip_comment(
            stip["id"],
            {"author_name": "Resident", "comment_text": "Supportive."},
            H["state_dot_planner"],
        )
        comment = validate_success(resp, expected_status=201)
        assert_public_comment(comment)
        assert comment["id"]
        assert comment["created_at"]
        assert "version" not in comment, "PublicComment must not carry version"
        assert "updated_at" not in comment, "PublicComment must not carry updated_at"

        comments, meta = validate_paginated(
            api.list_stip_comments(stip["id"], H["fhwa_reviewer"])
        )
        assert meta["total_count"] == 1
        assert len(comments) == 1
        assert_public_comment(comments[0])
        assert comments[0]["id"] == comment["id"]

    def test_project_create_computes_provisional_from_program_base(self, api):
        """PRD §3.3: "`provisional_federal_share_pct` is exactly the program's
        base share — 0.80 for `NHPP`, `STBG`, `CMAQ`, and `TAP`; 0.90 for
        `HSIP` — with no interstate bump, no safety override, and no land
        adjustment; `provisional_federal_estimate_cents` is the product of
        `total_estimated_cost_cents` and that share, rounded half-up to whole
        cents."
        PRD §3.3: "The new Project starts in `NOMINATED` with
        `advertised_on_date`, `awarded_bid_id`, and
        `determined_federal_share_pct` all null."

        For CMAQ (base 0.80) at cost 5,000,001 the provisional estimate is
        round_half_up(5,000,001 x 0.80) = round_half_up(4,000,000.8) =
        4,000,001.

        Design: Corner/entities/project_create_computes_provisional_from_program_base
        """
        set_clock("2026-09-01T00:00:00Z")
        program = create_funding_program(
            code="CMAQ",
            eligible_activity_codes=["TRANSIT_EXPANSION", "ROAD_RESURFACING"],
        )
        stip = create_stip(state_code="AZ", land_pct=0.0, start_ffy=2027)
        resp = api.create_project(
            {
                "stip_id": stip["id"],
                "funding_program_id": program["id"],
                "route_name": "AZ-51",
                "description": "Transit",
                "activity_code": "TRANSIT_EXPANSION",
                "is_interstate_system": False,
                "dbe_goal_pct": 0.12,
                "total_estimated_cost_cents": 5_000_001,
            },
            H["state_dot_planner"],
        )
        project = validate_success(resp, expected_status=201)
        assert_project(project)
        assert project["provisional_federal_share_pct"] == 0.80
        assert project["provisional_federal_estimate_cents"] == 4_000_001, (
            "half-cent rounds up: round_half_up(5,000,001 x 0.80) = 4,000,001, "
            f"got {project['provisional_federal_estimate_cents']}"
        )
        assert project["status"] == "NOMINATED"
        assert project["determined_federal_share_pct"] is None

    def test_project_get_unknown_id_returns_not_found(self, api):
        """PRD §2.9: "the identifiers are validated from left to right, and the
        first one that does not resolve to an existing resource yields
        `ERR_NOT_FOUND` (404) before any further processing."
        PRD §2.7: "3. Existence: resource identifiers in the URL path must
        resolve, validated left to right; the first unresolvable identifier
        yields `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/project_get_unknown_id_returns_not_found
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.get_project(NON_EXISTENT_UUID, H["fhwa_reviewer"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404
