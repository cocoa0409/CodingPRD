"""Security (authn/authz/RBAC), validation priority, and entity/field rules."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, ApiErrorId, NON_EXISTENT_UUID, build_user_headers,
    set_clock, make_studio, make_season, make_locked_season, make_title, approve_title,
    make_location, book_slot, make_talent, make_casting, make_license,
    create_title_payload, create_license_payload,
    setup_locked_season_with_approved_title,
)
from test_helpers.fixtures import ADMIN, PLANNER, PROD, EXEC, ADS, STREAM, LIC


class TestAuthentication:
    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a role outside
        the recognized set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_header_returns_unauthenticated
        """
        resp = api_client.create_studio(
            {"name": "No Role Studio", "ad_budget_cents": 1},
            {"X-User-ID": "test-user-1", "Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_wrong_role_returns_forbidden_not_unauthenticated(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted for the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/validations/forbidden_role_returns_forbidden_not_unauthenticated
        """
        resp = api_client.create_studio({"name": "Wrong Role", "ad_budget_cents": 1}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestExistencePriority:
    def test_unknown_path_id_returns_not_found(self, api):
        """PRD §2.7: "**Path existence** — path identifiers resolve, validated
        left to right along the URL (`ERR_NOT_FOUND`)."

        Design: Corner/validations/existence_beats_state_on_unknown_title_approve
        """
        resp = api_client.approve_title(
            NON_EXISTENT_UUID, {"expected_season_version": 1}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_unknown_body_fk_returns_not_found(self, api):
        """PRD §2.8: "A request body that references a foreign key which does not
        exist — or which exists but belongs to a different studio than the
        surrounding aggregate — is rejected with `ERR_NOT_FOUND` (HTTP 404),
        indistinguishable from a missing resource".

        Design: Corner/validations/existence_beats_state_on_unknown_title_approve
        """
        studio = make_studio(ad_budget_cents=500000)
        resp = api_client.create_season(
            {"studio_id": NON_EXISTENT_UUID, "year": 2027, "label": "Ghost",
             "required_title_count": 1, "air_window_start": "2027-11-01T00:00:00Z",
             "air_window_end": "2027-12-31T00:00:00Z",
             "delivery_deadline": "2027-10-01T00:00:00Z", "max_shoot_days": 10}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestBodyFkStudioScope:
    def test_cross_studio_talent_casting_returns_not_found(self, api):
        """PRD §2.8: "A request body that references a foreign key which does not
        exist — or which exists but belongs to a different studio than the
        surrounding aggregate — is rejected with `ERR_NOT_FOUND` (HTTP 404),
        indistinguishable from a missing resource; the API does not leak
        cross-studio existence."

        Design: Corner/validations/body_fk_out_of_scope_returns_not_found
        """
        set_clock("2027-03-01T00:00:00Z")
        studio_a = make_studio(name="Studio A", ad_budget_cents=500000)
        studio_b = make_studio(name="Studio B", ad_budget_cents=500000)
        season, sv = make_locked_season(studio_a["id"])
        t1 = make_title(season["id"], name="T1")
        approve_title(t1["id"], sv)
        talent_b, agent_b = make_talent(studio_b["id"], stage_name="Other Studio Star")
        resp = api_client.create_casting({"title_id": t1["id"], "talent_id": talent_b["id"]}, agent_b)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRbacSegregationOfDuties:
    def test_talent_agent_cannot_approve_title(self, api):
        """PRD §2.1: "`TalentAgent` — acts for a specific talent; manages talent
        records, multi-picture deals, and castings." — approve is not in this
        set, and PRD §2.1: "A request whose role is recognized but not permitted
        for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/talent_agent_cannot_approve_title
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio(ad_budget_cents=500000)
        season, sv = make_locked_season(studio["id"])
        t1 = make_title(season["id"], name="T1")
        talent, agent = make_talent(studio["id"], stage_name="Holly Star")
        resp = api_client.approve_title(t1["id"], {"expected_season_version": sv}, agent)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        title_after = get_success_data(api_client.get_title(t1["id"], PLANNER))
        assert title_after["status"] == "PITCHED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["version"] == sv

    def test_production_manager_cannot_publish_block(self, api):
        """PRD §2.1: "`ProductionManager` — owns locations and production slots and
        delivers titles." — block publish is not in this set; "A request whose
        role is recognized but not permitted for the target endpoint is rejected
        with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/production_manager_cannot_publish_block_and_programming_exec_cannot_deliver
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        loc = make_location(ctx["studio"]["id"])
        slot = book_slot(ctx["title"]["id"], loc["id"])
        validate_success(api_client.wrap_production_slot(slot["id"], PROD))
        block = get_success_data(api_client.create_program_block(
            {"season_id": ctx["season"]["id"], "name": "Friday Premieres",
             "block_start": "2027-11-05T00:00:00Z", "premiere_cadence_days": 7,
             "max_encores_per_title": 3, "min_minutes_between_airings": 1440}, EXEC))
        resp = api_client.publish_program_block(block["id"], PROD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        block_after = get_success_data(api_client.get_program_block(block["id"], EXEC))
        assert block_after["status"] == "DRAFT"

    def test_programming_exec_cannot_deliver_title(self, api):
        """PRD §2.1: "`ProgrammingExec` — owns the air schedule; locks and archives
        seasons, publishes programming blocks, and schedules air slots." —
        delivery is not in this set; "A request whose role is recognized but not
        permitted for the target endpoint is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/production_manager_cannot_publish_block_and_programming_exec_cannot_deliver
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        loc = make_location(ctx["studio"]["id"])
        slot = book_slot(ctx["title"]["id"], loc["id"])
        validate_success(api_client.wrap_production_slot(slot["id"], PROD))
        resp = api_client.deliver_title(ctx["title"]["id"], EXEC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        title_after = get_success_data(api_client.get_title(ctx["title"]["id"], PLANNER))
        assert title_after["status"] == "IN_PRODUCTION"


class TestBrandRules:
    def test_festive_tone_with_wrong_genre_rejected(self, api):
        """PRD §3.2: "a title whose `tone_rating` is `FESTIVE` must have a `genre`
        of `ROMANCE` or `FAMILY`. Either violation is rejected with
        `ERR_BRAND_VIOLATION` (HTTP 422)."

        Design: Corner/errors/brand_violation_festive_tone_wrong_genre
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio(ad_budget_cents=500000)
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        tf = make_title(season["id"], name="Festive Mystery", genre="MYSTERY",
                        tone_rating="FESTIVE")
        resp = api_client.approve_title(tf["id"], {"expected_season_version": sv}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_BRAND_VIOLATION)

    def test_festive_tone_with_romance_passes_and_version_unbumped_by_failure(self, api):
        """PRD §3.2: "a title whose `tone_rating` is `FESTIVE` must have a `genre`
        of `ROMANCE` or `FAMILY`" and "A successful approval moves the title
        `PITCHED → APPROVED`, recomputes the season's `committed_title_count`,
        and increments the season's `version` by 1".

        Design: Corner/errors/brand_violation_festive_tone_wrong_genre
        """
        set_clock("2027-03-01T00:00:00Z")
        studio = make_studio(ad_budget_cents=500000)
        season, sv = make_locked_season(studio["id"], required_title_count=2)
        tf = make_title(season["id"], name="Festive Mystery", genre="MYSTERY",
                        tone_rating="FESTIVE")
        api_client.approve_title(tf["id"], {"expected_season_version": sv}, PLANNER)
        # the failed approve must not bump the season version, so sv still authorizes
        tg = make_title(season["id"], name="Festive Romance", genre="ROMANCE",
                        tone_rating="FESTIVE")
        approved = validate_success(
            api_client.approve_title(tg["id"], {"expected_season_version": sv}, PLANNER))
        assert approved["status"] == "APPROVED"
        season_after = get_success_data(api_client.get_season(season["id"], ADMIN))
        assert season_after["committed_title_count"] == 1


class TestTitleCreationShape:
    def test_computed_status_ignores_client_input(self, api):
        """PRD §3.2: "A new title starts `PITCHED`, with `delivered_at` unset."
        and "an optional list of `content_flags` drawn from `VIOLENCE`,
        `ALCOHOL`, `GAMBLING`, and `HORROR`".

        Design: Corner/entities/title_computed_status_ignores_client_input
        """
        studio = make_studio(ad_budget_cents=500000)
        season = make_season(studio["id"], required_title_count=3)
        title = make_title(season["id"], name="Snowed Inn", content_flags=["ALCOHOL"],
                           duration_minutes=88)
        assert title["status"] == "PITCHED"
        assert title["delivered_at"] is None
        assert title["content_flags"] == ["ALCOHOL"]
        assert title["version"] == 1
        assert title.get("id") and title.get("created_at") and title.get("updated_at")

    def test_duration_below_range_rejected(self, api):
        """PRD §3.2: "a `duration_minutes` runtime in whole minutes between 60 and
        180 inclusive" — 59 violates the range; PRD §2.7: "**Input shape** —
        required fields present, enum values valid, numeric ranges respected
        (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/title_duration_out_of_range_rejected
        """
        studio = make_studio(ad_budget_cents=500000)
        season = make_season(studio["id"], required_title_count=5)
        resp = api_client.create_title(
            create_title_payload(season_id=season["id"], name="Too Short",
                                 duration_minutes=59), PLANNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duration_inclusive_bounds_accepted(self, api):
        """PRD §3.2: "a `duration_minutes` runtime in whole minutes between 60 and
        180 inclusive".

        Design: Corner/entities/title_duration_out_of_range_rejected
        """
        studio = make_studio(ad_budget_cents=500000)
        season = make_season(studio["id"], required_title_count=5)
        t60 = make_title(season["id"], name="Exactly Sixty", duration_minutes=60)
        t180 = make_title(season["id"], name="Exactly 180", duration_minutes=180)
        assert t60["duration_minutes"] == 60
        assert t180["duration_minutes"] == 180


class TestListPaginationAndFilters:
    def test_titles_paginate_and_filter(self, api):
        """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
        100; `offset` defaults to 0" and "The `meta` object of a list response
        carries the pagination fields `limit`, `offset`, `total_count`, and
        `has_more`." PRD §3.2: "The titles list endpoint supports optional
        `season_id` and `status` filters."

        Design: Corner/entities/title_list_paginates_and_filters
        """
        studio = make_studio(ad_budget_cents=500000)
        season = make_season(studio["id"], required_title_count=5)
        for name, genre, tone, dur in [("A", "ROMANCE", "WARM", 90),
                                       ("B", "FAMILY", "GENTLE", 90),
                                       ("C", "COMEDY", "GENTLE", 95)]:
            make_title(season["id"], name=name, genre=genre, tone_rating=tone,
                       duration_minutes=dur)
        page1, meta1 = validate_paginated(
            api_client.list_titles(PLANNER, params={"season_id": season["id"], "limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api_client.list_titles(PLANNER, params={"season_id": season["id"], "limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        pitched, meta_p = validate_paginated(
            api_client.list_titles(PLANNER, params={"season_id": season["id"], "status": "PITCHED"}))
        assert len(pitched) == 3
        approved, meta_a = validate_paginated(
            api_client.list_titles(PLANNER, params={"season_id": season["id"], "status": "APPROVED"}))
        assert len(approved) == 0
        default_page, meta_d = validate_paginated(
            api_client.list_titles(PLANNER, params={"season_id": season["id"]}))
        assert meta_d["limit"] == 10
        assert meta_d["offset"] == 0


class TestDealNotFound:
    def test_unknown_deal_id_returns_not_found(self, api):
        """PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`." and "The `message`
        provides a human-readable explanation of what went wrong." PRD §2.7:
        "**Path existence** — path identifiers resolve, validated left to right
        along the URL (`ERR_NOT_FOUND`)."

        Design: Corner/entities/deal_get_unknown_id_returns_not_found
        """
        make_studio(ad_budget_cents=500000)
        resp = api_client.get_deal(NON_EXISTENT_UUID, ADMIN)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert err.get("message"), "error payload must carry a message"


class TestSeasonStudioFilter:
    def test_seasons_reverse_reachable_via_studio_filter(self, api):
        """PRD §3.1: "The seasons list endpoint accepts optional `studio_id` and
        `status` filters in addition to pagination."

        Design: Corner/entities/season_fk_reverse_reachable_from_studio_filtered_list
        """
        sa = make_studio(name="Studio A", ad_budget_cents=100)
        sb = make_studio(name="Studio B", ad_budget_cents=100)
        season = make_season(sa["id"], required_title_count=1, max_shoot_days=10)
        rows_a, meta_a = validate_paginated(
            api_client.list_seasons(ADMIN, params={"studio_id": sa["id"]}))
        assert len(rows_a) == 1
        assert rows_a[0]["id"] == season["id"]
        rows_b, meta_b = validate_paginated(
            api_client.list_seasons(ADMIN, params={"studio_id": sb["id"]}))
        assert len(rows_b) == 0
        assert meta_b["total_count"] == 0


class TestLicenseInputShapeAndAuditGate:
    def test_missing_royalty_rate_returns_invalid_request(self, api):
        """PRD §2.7: "**Input shape** — required fields present, enum values
        valid, numeric ranges respected (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/license_missing_required_field_returns_invalid_request
        """
        studio = make_studio(ad_budget_cents=500000)
        season = make_season(studio["id"], required_title_count=2)
        t1 = make_title(season["id"], name="T1")
        resp = api_client.create_license(
            {"season_id": season["id"], "title_id": t1["id"], "category": "MERCHANDISE",
             "licensee": "X", "reported_revenue_cents": 100}, LIC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_audit_on_undelivered_title_rejected(self, api):
        """PRD §3.8: "Auditing trues the grant up, and requires the licensed title
        to be `DELIVERED` — otherwise `ERR_INVALID_STATE`."

        Design: Corner/errors/license_audit_on_undelivered_title_returns_invalid_state
        """
        set_clock("2027-03-01T00:00:00Z")
        ctx = setup_locked_season_with_approved_title()
        lic = make_license(ctx["season"]["id"], ctx["title"]["id"], category="PUBLISHING",
                           licensee="BookHouse", royalty_rate=0.10,
                           reported_revenue_cents=500000)
        assert lic["provisional_royalty_cents"] == 50000
        resp = api_client.audit_license(lic["id"], LIC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        lic_after = get_success_data(api_client.get_license(lic["id"], LIC))
        assert lic_after["status"] == "REPORTED"
        assert lic_after["provisional_royalty_cents"] == 50000
        assert lic_after["trued_royalty_cents"] is None
