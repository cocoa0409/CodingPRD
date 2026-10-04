"""Account registration, computed fields, auth context, role authorization,
and list pagination (PRD §2.1, §2.3, §2.5, §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_parental_controls,
    assert_user,
    create_experience_payload,
    create_parental_controls_payload,
    create_user,
    get_user,
    make_creator_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUserCreationAndComputedFields:
    def test_user_create_returns_full_envelope_and_initial_state(self, api):
        """PRD §3.1: "Registration produces a `User` in `ACTIVE` status and immediately
        computes the account's `age_band`: a user younger than thirteen years is `CHILD`,
        a user at least thirteen but younger than eighteen is `TEEN`, and a user eighteen
        or older is `ADULT`."

        Design: Corner/entities/user_create_returns_full_envelope_and_initial_state
        """
        set_clock()
        resp = api.create_user(
            {"username": "u_1", "email": "u1@x.com", "date_of_birth": "1990-06-15"},
            TEST_USERS["anonymous_headers"],
        )
        user = validate_success(resp, 201)
        assert_user(user)
        assert user["status"] == "ACTIVE"
        assert user["age_band"] == "ADULT", (
            f"DOB 1990-06-15 at 2026-09-01 must be ADULT, got {user['age_band']}"
        )
        assert user["chat_filter_level"] == "ADULT"
        assert user["robux_balance"] == 0
        assert user["earned_robux_lifetime"] == 0
        assert user["is_devex_eligible"] is False

    def test_user_create_child_computes_safe_chat_filter(self, api):
        """PRD §3.1: "The `chat_filter_level` itself is a computed field with three
        values: `SAFE` when the user's `age_band` is `CHILD` or when parental controls
        set `chat_mode` to `RESTRICTED`; `STANDARD` for a `TEEN`; and `ADULT` for an
        `ADULT` with no parental override."

        Design: Corner/entities/user_create_child_computes_safe_chat_filter
        """
        set_clock()
        resp = api.create_user(
            {"username": "kid1", "email": "kid1@x.com", "date_of_birth": "2020-05-15"},
            TEST_USERS["anonymous_headers"],
        )
        user = validate_success(resp, 201)
        assert_user(user)
        assert user["age_band"] == "CHILD", (
            f"DOB 2020-05-15 at 2026-09-01 must be CHILD, got {user['age_band']}"
        )
        assert user["chat_filter_level"] == "SAFE"

    def test_user_get_unknown_id_returns_user_not_found(self, api, platform_admin_headers):
        """PRD §2.5: "every id appearing in a nested URL is checked for existence in
        strict left-to-right order, and the first missing segment produces the
        corresponding 404 — `ERR_USER_NOT_FOUND`, `ERR_EXPERIENCE_NOT_FOUND`,
        `ERR_ITEM_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
        `ERR_SUBMISSION_NOT_FOUND`, `ERR_APPEAL_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, or
        `ERR_TERMINATION_NOT_FOUND` — before any later segment is even consulted."

        Design: Corner/entities/user_get_unknown_id_returns_user_not_found
        """
        set_clock()
        resp = api.get_user(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_USER_NOT_FOUND)

    def test_user_create_missing_email_returns_invalid_request(self, api, anonymous_headers):
        """PRD §3.1: "A new account is registered by an `Anonymous` caller supplying a
        `username` (a unique handle of three to twenty characters drawn from letters,
        digits, and underscore), an `email` used for identity-verification
        correspondence, a `date_of_birth` in ISO 8601 date form, and an optional
        `parent_user_id`."
        PRD §2.5: "Sixth come structural business constraints such as the resale price
        floor, limited-supply exhaustion, segregation of duties, and idempotency
        conflicts, surfacing `ERR_RESALE_FLOOR_VIOLATION`,
        `ERR_LIMITED_SUPPLY_EXHAUSTED`, `ERR_SEGREGATION_OF_DUTIES`,
        `ERR_DUPLICATE_IDEMPOTENCY_KEY`, or `ERR_INVALID_REQUEST`."

        Design: Corner/entities/user_create_missing_email_returns_invalid_request
        """
        set_clock()
        resp = api.create_user(
            {"username": "noemail", "date_of_birth": "1990-01-01"}, anonymous_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestParentalControlsDefaults:
    def test_parental_controls_default_chat_mode_is_filtered(self, api):
        """PRD §3.1: "`chat_mode` defaults to `FILTERED` and may be `RESTRICTED` (no
        free-text chat at all), `FILTERED` (server-side lexical filtering), or `OPEN`
        (no restriction beyond the child's `age_band`)."
        PRD §3.1: "A null `monthly_spend_limit_robux` — the default — means no cap;
        when set, it is a hard cap on the total of the child's completed purchase
        debits per calendar month."
        PRD §3.1: "`allowed_age_ratings` is a whitelist of experience rating levels the
        child may join — a subset of `ALL`, `NINE_PLUS`, `THIRTEEN_PLUS`, and
        `SEVENTEEN_PLUS` — and defaults to an empty array, which means the child simply
        inherits the defaults implied by their `age_band`."

        Design: Corner/entities/parental_controls_default_chat_mode_is_filtered
        """
        set_clock()
        parent = create_user(
            username="par_pc", email="par_pc@x.com", date_of_birth="1985-01-01"
        )
        child = create_user(
            username="kid_pc", email="kid_pc@x.com",
            date_of_birth="2020-01-01", parent_user_id=parent["id"],
        )
        parent_fresh = get_user(parent["id"])
        payload = create_parental_controls_payload(child["id"], parent_fresh["version"])
        resp = api.set_parental_controls(
            parent["id"], payload, make_creator_headers(parent["id"])
        )
        controls = validate_success(resp, 200)
        assert_parental_controls(controls)
        assert controls["chat_mode"] == "FILTERED"
        assert controls["monthly_spend_limit_robux"] is None
        assert controls["allowed_age_ratings"] == []


class TestPagination:
    def test_experiences_list_paginates(self, api, platform_admin_headers):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10 when omitted, accepts a minimum of 1, and rejects values above
        100. The `offset` parameter controls how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/entities/experiences_list_paginates
        """
        set_clock()
        creator = create_user(
            username="cr_pg", email="cr_pg@x.com", date_of_birth="1990-01-01"
        )
        headers = make_creator_headers(creator["id"])
        for title in ("AAA", "BBB", "CCC"):
            resp = api.create_experience(
                {"title": title, "description": f"desc {title}"}, headers
            )
            validate_success(resp, 201)

        resp = api.list_experiences(
            platform_admin_headers,
            params={"creator_user_id": creator["id"], "limit": 2, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"limit=2 must return 2 rows, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        resp = api.list_experiences(
            platform_admin_headers,
            params={"creator_user_id": creator["id"], "limit": 2, "offset": 2},
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"offset=2 with 3 rows must return 1 row, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestAuthAndRoleValidation:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "Every request to the API carries two mandatory HTTP headers:
        `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the
        operational capacity in which they act. A request missing either header, or
        carrying a malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        set_clock()
        resp = api.get_user(NON_EXISTENT_UUID, None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_wrong_role_cannot_approve_devex(self, api, moderator_headers):
        """PRD §2.1: "When a caller attempts an operation their role does not permit,
        the request is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §2.5: "Second comes role authorization against the operation, yielding
        `ERR_UNAUTHORIZED_ROLE`. Third, path-segment identifiers are resolved: every id
        appearing in a nested URL is checked for existence in strict left-to-right order"

        Design: Corner/validations/wrong_role_cannot_approve_devex
        """
        set_clock()
        resp = api.approve_devex_request(NON_EXISTENT_UUID, moderator_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_anonymous_cannot_create_experience(self, api, anonymous_headers):
        """PRD §2.1: "When a caller attempts an operation their role does not permit,
        the request is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: "POST | `/ugc/experiences` | Create experience (DRAFT) | Creator"

        Design: Corner/rbac/anonymous_cannot_create_experience
        """
        set_clock()
        resp = api.create_experience(
            create_experience_payload(title="Anon World"), anonymous_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_safety_agent_cannot_decide_moderation_submission(self, api, safety_agent_headers):
        """PRD §2.1: "When a caller attempts an operation their role does not permit,
        the request is rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: "POST | `/ugc/moderation-submissions/{id}/decide` | Human decision on a
        submission | Moderator"

        Design: Corner/rbac/safety_agent_cannot_decide_moderation_submission
        """
        set_clock()
        resp = api.decide_moderation_submission(
            NON_EXISTENT_UUID, {"decision": "APPROVE"}, safety_agent_headers
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
