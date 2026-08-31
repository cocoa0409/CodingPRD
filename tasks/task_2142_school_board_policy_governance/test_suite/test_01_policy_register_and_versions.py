"""The policy register: shells, version drafting, withdrawal and the version guard."""

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_bare_uuid,
    assert_policy,
    assert_policy_version,
    add_agenda_item,
    api_client,
    draft_version,
    policy_payload,
    policy_version_payload,
    read_policy,
    read_policy_version,
    register_policy,
    schedule_meeting,
    setup_policy_with_draft,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_version,
)

ANALYST = TEST_USERS["policy_analyst_headers"]
SUPT = TEST_USERS["superintendent_headers"]
PUBLIC = TEST_USERS["public_headers"]
CLERK = TEST_USERS["board_clerk_headers"]


def test_register_policy_returns_server_minted_identity_and_initial_posture():
    """PRD 2.5: "Every resource carries a server-minted `id`: a UUID string with no
    type prefix, assigned at creation and never reused."
    PRD 3.3: "A new policy opens with `status` `UNADOPTED`, `adopted_version_no` null,
    `last_review_date` null, `version_count` 0, `open_mandate_count`,
    `overdue_mandate_count` and `active_waiver_count` all 0, and its `compliance_state`
    computed immediately by the policy-scoped three-phase recompute — which, for a
    `REQUIRED_BY_LAW` policy with no adopted version, lands on `ACTION_REQUIRED`."

    Design: Corner/entities/create_policy_returns_201_with_server_minted_identity_and_initial_posture
    """
    response = api_client.create_policy(
        policy_payload(
            code="BP-4119",
            title="Employee Conflict of Interest",
            category="PERSONNEL",
            legal_requirement_level="REQUIRED_BY_LAW",
            manual_section="4000.19",
        ),
        ANALYST,
    )
    data = validate_success(response, 201)
    assert_policy(data)
    assert_bare_uuid(data["id"], "Policy.id")
    assert data["version"] == 1, f"a new record begins at version 1, got {data['version']}"
    assert data["status"] == "UNADOPTED"
    assert data["adopted_version_no"] is None
    assert data["last_review_date"] is None
    assert data["version_count"] == 0
    assert data["open_mandate_count"] == 0
    assert data["overdue_mandate_count"] == 0
    assert data["active_waiver_count"] == 0
    assert data["compliance_state"] == "ACTION_REQUIRED"
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_local_discretion_policy_opens_compliant():
    """PRD 2.9: "Then `compliance_state` is decided by the first matching rule: if
    `overdue_mandate_count` is greater than zero, `NON_COMPLIANT`; otherwise if
    `open_mandate_count` is greater than zero, `ACTION_REQUIRED`; otherwise if the
    policy's `status` is `UNADOPTED` and its `legal_requirement_level` is
    `REQUIRED_BY_LAW`, `ACTION_REQUIRED`; otherwise if `last_review_date` is set and the
    whole number of days from `last_review_date` to the logical clock is greater than the
    three-year review cycle of 1095 days, `ACTION_REQUIRED`; otherwise `COMPLIANT`."

    Design: Corner/entities/create_local_discretion_policy_starts_compliant
    """
    response = api_client.create_policy(
        policy_payload(
            code="BP-9010",
            title="Board Retreat Guidelines",
            category="GOVERNANCE",
            legal_requirement_level="LOCAL_DISCRETION",
            manual_section="9000.10",
        ),
        ANALYST,
    )
    data = validate_success(response, 201)
    assert data["compliance_state"] == "COMPLIANT"
    assert data["open_mandate_count"] == 0
    assert data["overdue_mandate_count"] == 0
    assert data["active_waiver_count"] == 0
    assert data["last_review_date"] is None


def test_read_one_policy_echoes_every_stored_field():
    """PRD 3.3: "Registration is an analyst operation carrying the policy `code`
    (globally unique across all policies, between 3 and 20 characters, for example
    `BP-4119`), the `title` as it appears in the manual, the manual chapter `category`
    from `GOVERNANCE`, `INSTRUCTION`, `PERSONNEL`, `STUDENTS` and `BUSINESS`, the
    `legal_requirement_level` from `REQUIRED_BY_LAW`, `RECOMMENDED` and
    `LOCAL_DISCRETION`, and the `manual_section` ordering key such as `4000.19`."

    Design: Corner/entities/get_policy_by_id_returns_the_stored_row
    """
    policy = register_policy(
        code="BP-6155",
        title="Homework and Grading",
        category="INSTRUCTION",
        legal_requirement_level="RECOMMENDED",
        manual_section="6000.55",
    )
    response = api_client.get_policy(policy["id"], PUBLIC)
    data = validate_success(response, 200)
    assert data["code"] == "BP-6155"
    assert data["title"] == "Homework and Grading"
    assert data["category"] == "INSTRUCTION"
    assert data["legal_requirement_level"] == "RECOMMENDED"
    assert data["manual_section"] == "6000.55"
    assert response.json()["response_type"] == "object"


def test_policy_listing_reports_total_count_and_has_more():
    """PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of records matching
    the filters before pagination is applied and `has_more` is true exactly when records
    remain beyond the current page."

    Design: Corner/entities/list_policies_paginates_with_total_count_and_has_more
    """
    register_policy("BP-1000", "Policy One", "GOVERNANCE", "LOCAL_DISCRETION", "1000.10")
    register_policy("BP-2000", "Policy Two", "INSTRUCTION", "RECOMMENDED", "2000.10")
    register_policy("BP-3000", "Policy Three", "STUDENTS", "RECOMMENDED", "3000.10")

    first_page, first_meta = validate_paginated(
        api_client.list_policies(PUBLIC, {"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2, f"limit 2 must return two rows, got {len(first_page)}"
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert api_client.list_policies(PUBLIC, {"limit": 2, "offset": 0}).json()["response_type"] == "array"

    second_page, second_meta = validate_paginated(
        api_client.list_policies(PUBLIC, {"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False


def test_unknown_policy_id_returns_policy_not_found():
    """PRD 2.7: "Each family has its own not-found code: `ERR_BOARD_MEMBER_NOT_FOUND`,
    `ERR_COMMITTEE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_DISCLOSURE_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_POLICY_VERSION_NOT_FOUND`, `ERR_MANDATE_NOT_FOUND`,
    `ERR_MEETING_NOT_FOUND`, `ERR_AGENDA_ITEM_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`,
    `ERR_EVALUATION_NOT_FOUND` and `ERR_PUBLICATION_NOT_FOUND`, all returned with HTTP 404."

    Design: Corner/entities/get_policy_with_unknown_uuid_returns_not_found
    """
    response = api_client.get_policy("00000000-0000-4000-8000-000000000000", PUBLIC)
    validate_error(response, ApiErrorId.ERR_POLICY_NOT_FOUND.value)
    assert response.status_code == 404
    assert response.json()["response_type"] == "error"


def test_policy_missing_legal_requirement_level_is_malformed():
    """PRD 2.7: "Request-body shape — required fields present, types correct, enum
    members valid, numbers in range, datetimes well formed, conditionally-required
    combinations satisfied (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_policy_missing_required_field_returns_invalid_request
    """
    response = api_client.create_policy(
        {
            "code": "BP-4119",
            "title": "Employee Conflict of Interest",
            "category": "PERSONNEL",
            "manual_section": "4000.19",
        },
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400
    _rows, meta = validate_paginated(api_client.list_policies(PUBLIC))
    assert meta["total_count"] == 0, "a malformed registration must create nothing"


def test_policy_category_outside_the_declared_chapters_is_malformed():
    """PRD 3.3: "Registration is an analyst operation carrying the policy `code`
    (globally unique across all policies, between 3 and 20 characters, for example
    `BP-4119`), the `title` as it appears in the manual, the manual chapter `category`
    from `GOVERNANCE`, `INSTRUCTION`, `PERSONNEL`, `STUDENTS` and `BUSINESS`, the
    `legal_requirement_level` from `REQUIRED_BY_LAW`, `RECOMMENDED` and
    `LOCAL_DISCRETION`, and the `manual_section` ordering key such as `4000.19`."
    PRD 2.7: "Request-body shape — required fields present, types correct, enum members
    valid, numbers in range, datetimes well formed, conditionally-required combinations
    satisfied (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_policy_with_unknown_category_returns_invalid_enum
    """
    response = api_client.create_policy(
        policy_payload(category="FACILITIES", legal_requirement_level="RECOMMENDED"), ANALYST
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400


def test_duplicate_policy_code_is_refused():
    """PRD 3.3: "A code already in use is refused with `ERR_DUPLICATE_POLICY_CODE`."

    Design: Corner/validations/duplicate_policy_code_returns_conflict
    """
    register_policy()
    response = api_client.create_policy(
        policy_payload(
            code="BP-4119",
            title="Duplicate Code Attempt",
            category="BUSINESS",
            legal_requirement_level="RECOMMENDED",
            manual_section="3000.19",
        ),
        ANALYST,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_POLICY_CODE.value)
    assert response.status_code == 409
    _rows, meta = validate_paginated(api_client.list_policies(PUBLIC))
    assert meta["total_count"] == 1, "the duplicate registration must not create a second row"


def test_drafting_a_version_under_an_unknown_policy_is_a_path_failure():
    """PRD 2.7: "Resource identifiers embedded in a URL path are resolved **left to
    right**, and the first segment that fails to resolve decides the error."
    PRD 2.7: "3. Path existence — every id in the URL resolves, left to right (the twelve
    not-found codes)."

    Design: Corner/entities/create_policy_version_under_unknown_policy_returns_not_found
    """
    policy = register_policy(
        code="BP-6155",
        title="Homework and Grading",
        category="INSTRUCTION",
        legal_requirement_level="RECOMMENDED",
        manual_section="6000.55",
    )
    response = api_client.create_policy_version(
        "00000000-0000-4000-8000-000000000000",
        policy_version_payload(
            policy["version"], body_text="Orphan draft.", summary_of_change="Orphan"
        ),
        ANALYST,
    )
    error = validate_error(response, ApiErrorId.ERR_POLICY_NOT_FOUND.value)
    assert response.status_code == 404
    assert error["error_id"] != ApiErrorId.ERR_STALE_VERSION.value


def test_new_policy_version_opens_in_draft_and_echoes_the_parent_version():
    """PRD 3.3: "On creation the server assigns `version_no` sequentially per policy
    starting at 1, in creation order, never reusing a number even when a version is later
    withdrawn. The new row opens with `status` `DRAFT`, `reading_count` 0,
    `first_reading_meeting_id`, `adopting_meeting_id`, `adopted_at`, `effective_date`,
    `superseded_at` and `withdrawn_reason` all null. Creating the version increments the
    parent policy's `version` by 1, echoes that new value back as `policy_version_after`,
    and recomputes the policy's `version_count` as the number of version rows on that
    policy in any status."

    Design: Corner/state_machines/new_policy_version_starts_in_draft_with_reading_count_zero
    """
    policy = register_policy(
        code="BP-6155",
        title="Homework and Grading",
        category="INSTRUCTION",
        legal_requirement_level="RECOMMENDED",
        manual_section="6000.55",
    )
    response = api_client.create_policy_version(
        policy["id"],
        policy_version_payload(
            policy["version"], body_text="Draft one.", summary_of_change="Initial draft"
        ),
        ANALYST,
    )
    data = validate_success(response, 201)
    assert_policy_version(data)
    assert data["status"] == "DRAFT"
    assert data["version_no"] == 1
    assert data["reading_count"] == 0
    assert data["first_reading_meeting_id"] is None
    assert data["adopted_at"] is None
    assert data["effective_date"] is None
    assert data["policy_version_after"] == 2
    assert read_policy(policy["id"])["version_count"] == 1


def test_analyst_and_superintendent_share_the_version_drafting_write():
    """PRD 3.3: "Drafting a version is the one write shared by the analyst and the
    superintendent."
    PRD 3.3: "On creation the server assigns `version_no` sequentially per policy starting
    at 1, in creation order, never reusing a number even when a version is later withdrawn."

    Design: Corner/rbac/superintendent_and_policy_analyst_share_the_version_drafting_operation
    """
    policy = register_policy(
        code="BP-6155",
        title="Homework and Grading",
        category="INSTRUCTION",
        legal_requirement_level="RECOMMENDED",
        manual_section="6000.55",
    )
    first = validate_success(
        api_client.create_policy_version(
            policy["id"],
            policy_version_payload(
                policy["version"], body_text="Analyst draft.", summary_of_change="Analyst revision"
            ),
            ANALYST,
        ),
        201,
    )
    second = validate_success(
        api_client.create_policy_version(
            policy["id"],
            policy_version_payload(
                first["policy_version_after"],
                body_text="Superintendent draft.",
                summary_of_change="Executive revision",
            ),
            SUPT,
        ),
        201,
    )
    assert first["version_no"] == 1
    assert second["version_no"] == 2
    assert first["status"] == "DRAFT" and second["status"] == "DRAFT"
    assert read_policy(policy["id"])["version_count"] == 2


def test_stale_expected_policy_version_is_refused_with_precondition_failed():
    """PRD 2.6: "Drafting a new version of a policy requires a non-optional
    `expected_policy_version` field in the request body, carrying the client's last
    observed `version` of the target policy. If that value does not equal the policy's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_policy_version_returns_precondition_failed
    """
    policy = register_policy(
        code="BP-6155",
        title="Homework and Grading",
        category="INSTRUCTION",
        legal_requirement_level="RECOMMENDED",
        manual_section="6000.55",
    )
    first = validate_success(
        api_client.create_policy_version(
            policy["id"],
            policy_version_payload(
                policy["version"], body_text="First draft.", summary_of_change="First"
            ),
            ANALYST,
        ),
        201,
    )
    assert first["policy_version_after"] == 2

    stale = api_client.create_policy_version(
        policy["id"],
        policy_version_payload(
            policy["version"],
            body_text="Second draft from a stale view.",
            summary_of_change="Second",
        ),
        ANALYST,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value)
    assert stale.status_code == 412

    refreshed = read_policy(policy["id"])
    assert refreshed["version"] == 2
    assert refreshed["version_count"] == 1
    _rows, meta = validate_paginated(
        api_client.list_policy_versions(PUBLIC, {"policy_id": policy["id"]})
    )
    assert meta["total_count"] == 1


def test_policy_version_counter_advances_once_per_mutation():
    """PRD 2.5: "All fourteen resource families in this system additionally carry an
    `updated_at` timestamp — same format as `created_at`, refreshed on every mutation of
    that record — and a `version`, an integer that begins at 1 when the record is created
    and increments by exactly 1 on every mutation of that record."
    PRD 3.3: "Either way the policy's `version_count` is recomputed and the policy's
    `version` rises by 1."

    Design: Corner/cross_cutting_complexity_layers/parent_version_increments_on_every_mutation_including_cascades
    """
    policy = register_policy(
        code="BP-6155",
        title="Homework and Grading",
        category="INSTRUCTION",
        legal_requirement_level="RECOMMENDED",
        manual_section="6000.55",
    )
    assert policy["version"] == 1
    created = draft_version(
        policy["id"], policy["version"], body_text="First draft.", summary_of_change="First"
    )
    assert created["policy_version_after"] == 2
    withdraw_version(created["id"], "Replaced by counsel language.")

    after_withdraw = read_policy(policy["id"])
    assert after_withdraw["version"] == 3
    assert after_withdraw["version_count"] == 1
    version_row = read_policy_version(created["id"])
    assert version_row["status"] == "WITHDRAWN"
    assert version_row["withdrawn_reason"] == "Replaced by counsel language."


def test_withdrawal_is_blocked_while_a_proposed_item_still_lists_the_version():
    """PRD 3.3: "Withdrawal is refused with `ERR_VERSION_ON_LIVE_AGENDA` while any agenda
    item in `PROPOSED` or `POSTED` status still references the version, and with
    `ERR_POLICY_VERSION_NOT_ELIGIBLE` when the version is already `ADOPTED`, `SUPERSEDED`
    or `WITHDRAWN`."

    Design: Corner/validations/withdrawing_a_version_that_is_still_on_a_live_agenda_is_rejected
    """
    policy, version = setup_policy_with_draft()
    meeting = schedule_meeting()
    item = add_agenda_item(
        meeting["id"],
        meeting["version"],
        item_type="POLICY_FIRST_READING",
        title="First reading BP-4119",
        policy_version_id=version["id"],
    )

    response = api_client.withdraw_policy_version(
        version["id"], {"withdrawn_reason": "Counsel asked for a rewrite."}, ANALYST
    )
    validate_error(response, ApiErrorId.ERR_VERSION_ON_LIVE_AGENDA.value)
    assert response.status_code == 409

    row = read_policy_version(version["id"])
    assert row["status"] == "DRAFT"
    assert row["withdrawn_reason"] is None
    from test_helpers import read_agenda_item

    assert read_agenda_item(item["id"])["status"] == "PROPOSED"


def test_first_reading_item_cannot_list_a_withdrawn_version():
    """PRD 3.4: "For a `POLICY_FIRST_READING` item the linked version's `status` must be
    `DRAFT`."
    PRD 3.4: "In both cases a version that is `WITHDRAWN`, `ADOPTED` or `SUPERSEDED` is
    refused with `ERR_POLICY_VERSION_NOT_ELIGIBLE`."

    Design: Corner/errors/first_reading_item_on_an_already_read_version_returns_not_eligible
    """
    policy, version = setup_policy_with_draft()
    withdraw_version(version["id"], "Counsel asked for a rewrite.")
    meeting = schedule_meeting()

    response = api_client.create_agenda_item(
        {
            "meeting_id": meeting["id"],
            "item_type": "POLICY_FIRST_READING",
            "title": "First reading of a withdrawn draft",
            "expected_meeting_version": meeting["version"],
            "policy_version_id": version["id"],
        },
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_POLICY_VERSION_NOT_ELIGIBLE.value)
    assert read_policy_version(version["id"])["status"] == "WITHDRAWN"
    _rows, meta = validate_paginated(
        api_client.list_agenda_items(PUBLIC, {"meeting_id": meeting["id"]})
    )
    assert meta["total_count"] == 0


def test_pagination_limit_above_one_hundred_is_malformed():
    """PRD 2.3: "`limit` controls page size: it defaults to 10, has a minimum of 1 and a
    maximum of 100."
    PRD 2.3: "A `limit` below 1 or above 100, or a negative `offset`, is a malformed
    request and is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/pagination_limit_above_the_maximum_returns_invalid_request
    """
    register_policy("BP-9010", "Board Retreat Guidelines", "GOVERNANCE", "LOCAL_DISCRETION", "9000.10")
    response = api_client.list_policies(PUBLIC, {"limit": 101})
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    assert response.status_code == 400
