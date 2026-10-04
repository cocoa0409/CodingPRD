"""System-wide contracts: the optimistic-concurrency guard, the auth ladder,
role permissions, and immediate consistency."""
from test_helpers import (
    TEST_USERS,
    api_client,
    approve_application_raw,
    create_application,
    current_store,
    current_store_version,
    get_application,
    make_store_organizer_headers,
    setup_application,
    setup_release_context,
    suspend_store,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_observed_store_version_one_low_is_refused_at_approval(api):
    """PRD §2.10: "The first is the approval of an event application, which must
    be submitted with `expected_store_version`, the client's last observed
    `version` of the `Store` the event belongs to."
    PRD §2.10: "In both cases the supplied value is compared with the parent's
    current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`."

    Design: Corner/validations/stale_store_version_blocks_approval
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(store, set_release, fmt, tier="LOCAL")
    observed = current_store_version(store["id"])

    refused = approve_application_raw(application["id"], observed - 1)
    validate_error(refused, "ERR_STALE_VERSION", expected_status=412)

    row = get_application(application["id"])
    assert row["status"] == "SUBMITTED"
    assert row["prize_allocation_id"] is None


def test_the_same_approval_succeeds_at_the_observed_store_version(api):
    """PRD §2.10: "In both cases the supplied value is compared with the parent's
    current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`."
    PRD §2.10: "A reprint plan sits outside this mechanism for a subtler reason:
    its own `verdict` is computed for it by the server rather than supplied by the
    client, and no client-supplied version guard applies to reprint plans at all."

    Design: Corner/validations/stale_store_version_blocks_approval
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(store, set_release, fmt, tier="LOCAL")
    observed = current_store_version(store["id"])

    refused = approve_application_raw(application["id"], observed - 1)
    validate_error(refused, "ERR_STALE_VERSION", expected_status=412)

    approved = approve_application_raw(application["id"], observed)
    validate_success(approved, 200)
    assert current_store(store["id"])["version"] == observed + 1, (
        "the approval advanced the store's own version by one"
    )


def test_the_store_version_advances_on_approval_and_again_on_suspension(api):
    """PRD §2.7: "Every store transition advances the store's `version` by one."
    PRD §3.4: "The approval advances the application's `version` and the store's
    `version` by one each."

    Design: Corner/cross_cutting_layers/store_version_increments_on_approval_and_on_suspension
    """
    store, set_release, fmt, application, allocation = setup_application(tier="LOCAL")
    created_version = 1

    after_approval = current_store(store["id"])
    assert after_approval["version"] == created_version + 1
    assert after_approval["status"] == "ACTIVE"

    suspend_store(store["id"])
    after_suspension = current_store(store["id"])
    assert after_suspension["version"] == created_version + 2
    assert after_suspension["status"] == "SUSPENDED"


def test_a_responder_who_is_forbidden_is_refused_before_the_body_is_examined(api):
    """PRD §2.12: "A caller who is forbidden to perform an operation receives
    `ERR_UNAUTHORIZED` even if the request body is also malformed, and a correctly
    shaped request that names a non-existent resource receives `ERR_NOT_FOUND`
    before any state check is attempted."

    Design: Corner/rbac/distributor_cannot_read_reprint_plans
    """
    store, set_release, fmt = setup_release_context()

    forbidden = api_client.list_reprint_plans(
        TEST_USERS["distributor_headers"], params={"limit": 10, "offset": 0}
    )
    validate_error(forbidden, "ERR_UNAUTHORIZED", expected_status=403)

    allowed = api_client.list_reprint_plans(
        TEST_USERS["ops_admin_headers"], params={"limit": 10, "offset": 0}
    )
    data, meta = validate_paginated(allowed)
    assert isinstance(data, list)
    assert meta["total_count"] == 0


def test_the_judges_exclusive_case_filing_is_denied_to_the_store_organizer(api):
    """PRD §2.12: "Role permission comes next: an authenticated caller whose role
    is not authorized for the operation is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.10: "A judge files a rules enforcement case against a player at a
    sanctioned event"

    Design: Corner/rbac/store_organizer_cannot_file_enforcement_cases
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(store, set_release, fmt, tier="LOCAL")

    forbidden = api_client.create_enforcement_case(
        {
            "event_application_id": application["id"],
            "player_ref": "PLAYER-1",
            "judge_ref": "JUDGE-X",
            "offense_class": "MINOR",
            "rules_enforcement_level": "REGULAR",
        },
        make_store_organizer_headers(store["id"]),
    )
    validate_error(forbidden, "ERR_UNAUTHORIZED", expected_status=403)

    data, meta = validate_paginated(api_client.list_enforcement_cases(
        TEST_USERS["ops_admin_headers"],
        params={"event_application_id": application["id"], "limit": 10},
    ))
    assert meta["total_count"] == 0
    assert current_store(store["id"])["reporting_violation_points"] == 0


def test_a_request_with_no_role_header_fails_identity_not_permission(api):
    """PRD §2.12: "Identity comes first: a request without a valid `X-User-Role`,
    or naming an undeclared role, or missing `X-User-ID` for an entity-backed
    role, is rejected with `ERR_UNAUTHENTICATED`."
    PRD §2.12: "Role permission comes next: an authenticated caller whose role is
    not authorized for the operation is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/missing_role_header_is_unauthenticated_not_forbidden
    """
    store, set_release, fmt = setup_release_context()

    anonymous = api_client.list_stores(
        {"Content-Type": "application/json"}, params={"limit": 10, "offset": 0}
    )
    error = validate_error(anonymous, "ERR_UNAUTHENTICATED", expected_status=401)
    body = anonymous.json()
    assert body["response_type"] == "error"
    assert error["message"].strip(), "the error envelope carries a message"
    assert anonymous.status_code != 403, "the identity rule fires before permission"


def test_the_approval_response_carries_the_new_pool_and_the_advanced_version(api):
    """PRD §2.8: "**`version`** is a system-managed integer that starts at the
    resource's creation value and increments by one on every modification"

    Design: Corner/consistency_model/approval_pool_and_version_are_visible_in_the_same_response
    """
    store, set_release, fmt = setup_release_context()
    application = create_application(store, set_release, fmt, tier="LOCAL")
    submitted = get_application(application["id"])

    approved = approve_application_raw(
        application["id"], current_store_version(store["id"])
    )
    approved_data = validate_success(approved, 200)

    assert approved_data["status"] == "APPROVED"
    assert approved_data["prize_allocation_id"] is not None
    assert approved_data["version"] == submitted["version"] + 1

    allocation = validate_success(
        api_client.get_prize_allocation(
            approved_data["prize_allocation_id"], TEST_USERS["ops_admin_headers"]
        ),
        200,
    )
    assert allocation["status"] == "OPEN"
    assert allocation["base_tp"] == 16
    assert allocation["remaining_tp"] == 16