"""Role segregation, request-shape validation and list narrowing."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_BASE,
    MAX_LIMIT,
    TEST_USERS,
    create_community,
    community_version,
    founding_moderator,
    get_community,
    list_communities,
    list_moderators,
    publish_post,
    record_cluster,
    record_decision,
    record_detection,
    sanction_rows,
    set_clock,
    validate_error,
    validate_success,
    make_account_headers,
    make_moderator_headers,
)


class TestRoleSegregation:

    def test_moderator_cannot_apply_an_account_wide_sanction(self, api):
        """PRD §2.1: "A request whose role is declared but not permitted for the
        operation is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: "POST | `/api/community-administration/account-sanctions` | Apply
        an account-wide sanction through the administration route | PlatformAdmin".

        Design: Corner/RBAC/community_route_sanction_cannot_be_applied_by_a_moderator
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        response = api.apply_account_wide_sanction(
            {"account_id": "u-target", "community_id": community_id,
             "decision_outcome": "BAN_ISSUED"},
            make_moderator_headers(moderator["id"]))
        error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value

        assert sanction_rows("u-target") == []
        assert get_community(community_id)["applying_sanction_count"] == 0

    def test_account_role_cannot_reach_two_administration_routes(self, api):
        """PRD §2.1: "Role permissions are enforced before any business rule. The
        permission check is applied to every endpoint, including the read
        endpoints, and a role that is not listed for an operation cannot reach that
        operation's validation cascade at all."

        Design: Corner/RBAC/platform_admin_paths_are_closed_to_accounts
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        cluster = record_cluster(community_id, internal_link_count=10, external_link_count=10,
                                 participant_count=40, legitimate_participant_count=4,
                                 actor_moderator_id=moderator["id"])
        item = record_detection(community_id, source_id="src-role",
                                subject_account_id="u-target", signal_severity_band=5,
                                detection_confidence=0.90, overlap_ratio=0.20,
                                published_at_utc="2026-09-12T00:00:00Z",
                                actor_moderator_id=moderator["id"])
        decision = record_decision(community_id, item["id"], decision_outcome="BAN_ISSUED",
                                   decision_confidence=0.90, dissection_band=0,
                                   precedent_approval_count=0,
                                   actor_moderator_id=moderator["id"])

        account_headers = make_account_headers("user-x")
        escalate = api.escalate_brigade_cluster(
            {"cluster_id": cluster["id"], "sanction_ladder": "BAN"}, account_headers)
        revise = api.revise_decision({"decision_id": decision["id"]}, account_headers)

        validate_error(escalate, ApiErrorId.ERR_FORBIDDEN_ROLE)
        validate_error(revise, ApiErrorId.ERR_FORBIDDEN_ROLE)

        assert api.get_brigade_cluster(community_id, cluster["id"],
                                       TEST_USERS["platform_admin_headers"]).json()["data"]["status"] == "DETECTED"
        assert decision["status"] == "RECORDED"

    def test_moderator_identity_resolves_through_the_team_rows(self, api):
        """PRD §2.1: "When `X-User-Role` is `Moderator`, `X-User-ID` is the `id`
        of the acting `Moderator` row."
        PRD §2.1: "Ownership checks on any resource that references a moderator —
        a protest approval's `moderator_id`, the `blocked_by_moderator_id` recorded
        on a succession — compare that field to `X-User-ID`."

        Design: Corner/RBAC/entity_backed_moderator_identity_is_read_from_the_team_rows
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        mod_alpha = founding_moderator(community_id)
        mod_beta = appoint_moderator_row(community_id, "mod-beta", "Mod Beta", mod_alpha["id"])

        response = api.list_moderators(community_id, make_moderator_headers(mod_beta["id"]),
                                       params={"status": "ACTIVE"})
        rows, _meta = validate_paginated_rows(response)
        assert len(rows) == 2

        beta_row = [row for row in rows if row["id"] == mod_beta["id"]][0]
        assert beta_row["moderator_account_id"] == "mod-beta"
        assert beta_row["status"] == "ACTIVE"
        assert beta_row["moderator_role"] == "REGULAR_MODERATOR"

        founder_row = [row for row in rows if row["moderator_account_id"] == "mod-alpha"][0]
        assert founder_row["is_top_moderator"] is True
        assert founder_row["top_rank"] == 1


class TestAuthenticationBand:

    def test_request_without_a_declared_role_is_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or that presents a role
        string outside the declared set, is rejected with
        `ERR_UNAUTHENTICATED`."
        PRD §2.6: "The authentication band comes first: a missing or unrecognised
        `X-User-Role`, or a missing `X-User-ID`, yields `ERR_UNAUTHENTICATED`".

        Design: Corner/errors/unauthenticated_request_without_role_header
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]

        response = api.list_moderators(community_id, {"X-User-ID": "someone"})
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)
        assert get_community(community_id)["active_moderator_count"] == 1

    def test_account_cannot_read_the_moderation_queue(self, api):
        """PRD §2.1: "A request whose role is declared but not permitted for the
        operation is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §3.10: "A moderator and a platform administrator read the community's
        content reports and its content decisions as the working queue".

        Design: Corner/errors/anonymous_role_is_denied_on_a_moderator_only_route
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        publish_post(community_id, author_account_id="user-ap")

        response = api.list_content_reports(community_id, make_account_headers("user-ap"))
        error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value

        allowed = api.list_content_reports(community_id, TEST_USERS["platform_admin_headers"])
        rows, _meta = validate_paginated_rows(allowed)
        assert rows == []


class TestRequestShapeValidation:

    def test_missing_description_is_invalid_request(self, api):
        """PRD §3.1: "A new community comes into being when an account, a
        moderator or a platform administrator creates it with a `name`, a
        `description`, an optional `is_over_18` declaration and an optional
        `founding_moderator_account_id`."
        PRD §2.6: "a required field that is missing, an enum member outside its
        declared set, or a numeric field outside its declared range is refused with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/community_create_missing_description_returns_invalid_request
        """
        set_clock(CLOCK_BASE)
        response = api.create_community({"name": "r/Alpha"},
                                        make_account_headers("mod-alpha"))
        error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
        assert error["error_id"] != ApiErrorId.ERR_DUPLICATE_COMMUNITY_NAME.value

        rows, _meta = validate_paginated_rows(
            api.list_communities(TEST_USERS["platform_admin_headers"]))
        assert rows == []

    def test_rule_band_outside_the_declared_set_is_invalid_request(self, api):
        """PRD §3.1: "The `rule_band` declares the permitted-content band the rule
        governs, as an integer: 1 means all ages, 2 means mature, and 3 means
        adult-only."
        PRD §2.6: "a required field that is missing, an enum member outside its
        declared set, or a numeric field outside its declared range is refused with
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/community_rule_band_out_of_range_is_invalid_request
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)

        response = api.create_rule(
            community_id,
            {"rule_code": "R-9", "rule_text": "Too high", "rule_band": 4,
             "is_sitewide_floor": False, "expected_community_version": community["version"]},
            make_moderator_headers(moderator["id"]))
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

        assert api.list_rules(community_id, TEST_USERS["platform_admin_headers"]).json()["data"] == []
        assert get_community(community_id)["active_rule_count"] == 0

    def test_pagination_bounds_are_rejected_not_clamped(self, api):
        """PRD §2.3: "`limit` is the maximum number of items returned; when it is
        omitted it defaults to 10, its minimum accepted value is 1 and its maximum
        accepted value is 100. ... A `limit` below 1 or above 100, or a negative
        `offset`, is rejected with `ERR_PAGINATION_INVALID`."

        Design: Corner/validations/pagination_bounds_are_rejected_not_clamped
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        admin = TEST_USERS["platform_admin_headers"]

        zero = api.list_moderators(community_id, admin, params={"limit": 0})
        validate_error(zero, ApiErrorId.ERR_PAGINATION_INVALID)

        high = api.list_moderators(community_id, admin, params={"limit": 101})
        validate_error(high, ApiErrorId.ERR_PAGINATION_INVALID)

        at_max = api.list_moderators(community_id, admin,
                                     params={"limit": MAX_LIMIT, "offset": 0})
        rows, meta = validate_paginated_rows(at_max)
        assert len(rows) == 1
        assert meta["has_more"] is False
        assert meta["total_count"] == 1

    def test_out_of_range_limit_is_rejected_on_the_community_list(self, api):
        """PRD §2.6: "Pagination arguments are the one exception to that catch-all,
        since they carry their own dedicated code `ERR_PAGINATION_INVALID` as §2.3
        states."
        PRD §2.3: "A `limit` below 1 or above 100, or a negative `offset`, is
        rejected with `ERR_PAGINATION_INVALID`."

        Design: Corner/validations/every_error_code_in_the_catalogue_is_reachable
        """
        set_clock(CLOCK_BASE)
        response = api.list_communities(TEST_USERS["account_headers"], params={"limit": 0})
        validate_error(response, ApiErrorId.ERR_PAGINATION_INVALID)


class TestListingAndPagination:

    def test_communities_list_filters_and_paginates(self, api):
        """PRD §3.10: "Communities narrow by `state` and by `enforcement_tier`;
        rules narrow by `status` and by `rule_band`; the moderator team narrows by
        `status` and by `moderator_role`".
        PRD §2.3: "Every list endpoint returns its resources ordered by creation
        timestamp ascending ... List responses carry `limit`, `offset`,
        `total_count` and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/communities_list_filters_and_paginates
        """
        set_clock(CLOCK_BASE)
        create_community("r/Alpha", founder_account_id="mod-a")
        create_community("r/Beta", founder_account_id="mod-b")
        create_community("r/Gamma", founder_account_id="mod-g")
        admin = TEST_USERS["platform_admin_headers"]

        page_one = api.list_communities(admin, params={"limit": 2, "offset": 0})
        rows_one, meta_one = validate_paginated_rows(page_one)
        assert len(rows_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True

        page_two = api.list_communities(admin, params={"limit": 2, "offset": 2})
        rows_two, meta_two = validate_paginated_rows(page_two)
        assert len(rows_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False

        active = api.list_communities(admin, params={"state": "ACTIVE"})
        rows_active, _meta = validate_paginated_rows(active)
        assert len(rows_active) == 3


class TestNotFoundResolution:

    def test_unknown_community_id_reports_the_entity_specific_code(self, api):
        """PRD §2.6: "For every route of the form
        `/api/communities/{communityId}/...`, a community identifier that does not
        resolve is reported as `ERR_COMMUNITY_NOT_FOUND`".
        PRD §4: "GET | `/api/communities/{id}` | Get a community with all computed
        posture fields | Account, Moderator, PlatformAdmin, Anonymous,
        ContentReviewer, SuccessionAuditor".

        Design: Corner/entities/community_get_with_an_unknown_id_returns_community_not_found
        """
        set_clock(CLOCK_BASE)
        response = api.get_community("00000000-0000-4000-8000-000000000000",
                                     TEST_USERS["anonymous_headers"])
        error = validate_error(response, ApiErrorId.ERR_COMMUNITY_NOT_FOUND)
        assert error["error_id"] != ApiErrorId.ERR_NOT_FOUND.value
        assert error.get("message")


class TestRuleConflicts:

    def test_floor_flag_with_a_low_band_is_refused(self, api):
        """PRD §3.1: "Setting `is_sitewide_floor` true while declaring a `rule_band`
        below the sitewide floor band is a conflict and is refused with
        `ERR_RULE_CONFLICT`."
        PRD §3.1: "The `is_sitewide_floor` flag defaults to false and, when true,
        marks the rule as a restatement of a sitewide policy floor that local
        moderators may not lower."

        Design: Corner/entities/community_rule_below_sitewide_floor_is_refused
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        admin = TEST_USERS["platform_admin_headers"]

        floor_payload = {"rule_code": "R-FLOOR", "rule_text": "Sitewide floor restated",
                         "rule_band": 1, "is_sitewide_floor": True,
                         "expected_community_version": community["version"]}
        response = api.create_rule(community_id, floor_payload,
                                   make_moderator_headers(moderator["id"]))
        validate_error(response, ApiErrorId.ERR_RULE_CONFLICT)

        accepted_payload = {"rule_code": "R-FLOOR", "rule_text": "Same rule without the floor flag",
                            "rule_band": 1, "is_sitewide_floor": False,
                            "expected_community_version": community["version"]}
        accepted = validate_success(
            api.create_rule(community_id, accepted_payload,
                            make_moderator_headers(moderator["id"])), 201)
        assert accepted["is_sitewide_floor"] is False
        assert accepted["rule_band"] == 1
        assert accepted["status"] == "ACTIVE"
        assert len(api.list_rules(community_id, admin).json()["data"]) == 1

    def test_rule_code_is_unique_among_active_rules(self, api):
        """PRD §3.1: "The `rule_code` is a stable local identifier and must be
        unique among the community's `ACTIVE` rules; a duplicate is refused with
        `ERR_DUPLICATE_RULE_CODE`."

        Design: Corner/entities/community_rule_code_uniqueness_among_active_rules
        """
        set_clock(CLOCK_BASE)
        community = create_community("r/Alpha", description="Alpha community")
        community_id = community["id"]
        moderator = founding_moderator(community_id)
        admin = TEST_USERS["platform_admin_headers"]
        version = community["version"]

        first = validate_success(api.create_rule(
            community_id,
            {"rule_code": "R-1", "rule_text": "Be civil", "rule_band": 1,
             "is_sitewide_floor": False, "expected_community_version": version},
            make_moderator_headers(moderator["id"])), 201)

        # §3.1: "every rule mutation carries the community's
        # `expected_community_version`" — so the duplicate write must carry the
        # version the first write advanced the *community* to, not the rule's own
        # `version`. Otherwise the OCC band (which §2.6 ranks ahead of the
        # business constraints) reports staleness instead of the duplicate code.
        assert first["version"] == 1
        assert community_version(community_id) == version + 1

        second = api.create_rule(
            community_id,
            {"rule_code": "R-1", "rule_text": "Duplicate code", "rule_band": 2,
             "is_sitewide_floor": False, "expected_community_version": community_version(community_id)},
            make_moderator_headers(moderator["id"]))
        error = validate_error(second, ApiErrorId.ERR_DUPLICATE_RULE_CODE)
        assert error["error_id"] != ApiErrorId.ERR_STALE_VERSION.value

        rows = api.list_rules(community_id, admin).json()["data"]
        assert len(rows) == 1


# --- local helpers -----------------------------------------------------------

def validate_paginated_rows(response):
    from test_helpers import validate_paginated
    return validate_paginated(response)


def appoint_moderator_row(community_id, account_id, display_name, actor_moderator_id):
    from test_helpers import appoint_moderator
    return appoint_moderator(community_id, account_id, display_name=display_name,
                             actor_moderator_id=actor_moderator_id)